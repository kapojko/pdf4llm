"""Optional local-LLM broken-text correction pass, with algorithmic safety gate.

Design (safety-first):

1. Classification (technical vs general) picks only the *prompt* — never the
   safety rules. LLM classifier on the document head; keyword heuristic
   fallback; any ambiguity/error defaults to the strict technical prompt.
2. The model may only perform whitespace-level edits (join split words,
   ``V CC`` -> ``VCC``, ``SOT108 - 1`` -> ``SOT108-1``, false line breaks).
3. Every chunk is verified algorithmically before it is accepted:
   - Invariant A: whitespace-stripped input and output are byte-identical
     (catches ANY inserted/deleted/reordered content character — rephrasing,
     translation, "helpful" fixes).
   - Invariant B: table rows keep their cell count; edits are checked
     per cell (90% of datasheet data lives in cells).
   - Invariant C: a deleted whitespace run is only allowed where its
     neighbours cannot make a numeric join dangerous (digit-digit and
     value-symbol joins are structurally forbidden, e.g. ``2 0`` -> ``20``,
     ``0x30 08`` -> ``0x3008``, ``V CC + 0.5`` -> ``VCC+ 0.5``).
   - Non-passing chunk is rejected as a whole and the original kept;
     the rejection is logged into meta.json.
"""
from __future__ import annotations

import difflib
import re

# ---------------------------------------------------------------------------
# Deterministic pre-pass: bullet deduplication (no LLM involved).
# PDF extraction often emits BOTH a Markdown '-' marker and the original
# '•' glyph. Removing a duplicated bullet is structural, not content, so it
# is done deterministically instead of being trusted to the model.
# ---------------------------------------------------------------------------

_BULLET_LEAD_RE = re.compile(r"(?m)^(\s*[-*+])\s+[•\u2022]\s+")
_BULLET_TRAIL_RE = re.compile(r"(?m)^(\s*[-*+].*?)\s+[•\u2022]\s*$")


def dedupe_bullets(text: str) -> str:
    """Remove '•' glyphs that duplicate a Markdown list marker."""
    text = _BULLET_LEAD_RE.sub(r"\1 ", text)
    text = _BULLET_TRAIL_RE.sub(r"\1", text)
    return text


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# Keyword heuristic — cheap fallback / sanity check for the LLM classifier.
_TECH_KEYWORDS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"(?i)\bdatasheet\b|\bdata\s+sheet\b"), 4),
    (re.compile(r"(?i)\breference\s+manual\b"), 4),
    (re.compile(r"(?i)\bpin\s+(description|definition|out)\b"), 3),
    (re.compile(r"(?i)\brevision\s+history\b"), 3),
    (re.compile(r"(?i)\bregister\b"), 3),
    (re.compile(r"(?i)\b(peripheral|timer|GPIO|UART|USART|SPI|I2C|I2S|DMA|ADC|DAC|CRC)\b"), 2),
    (re.compile(r"(?i)\b(electrical|static|dynamic)\s+characteristics\b"), 3),
    (re.compile(r"(?i)\babsolute\s+maximum\s+ratings?\b"), 3),
    (re.compile(r"\b0x[0-9A-Fa-f]{2,}\b"), 3),
    (re.compile(r"(?i)\b(VCC|VDD|VSS|GND|VIO)\b"), 2),
    (re.compile(r"\bSOT\s?-?\s?\d+\b|\bLQFP\b|\bTSSOP\b|\bQFN\b|\bSOIC\b|\bBGA\b"), 3),
    (re.compile(r"(?i)\b(firmware|flash|SRAM|EEPROM|interrupt|clock tree|bootloader)\b"), 2),
    (re.compile(r"(?i)\b(typ|typ\.|min|max)\s*\.?\b"), 1),
    (re.compile(r"(?i)\bpackage\s+(outline|information)\b"), 3),
    (re.compile(r"(?i)\bbit\b.*\bfield\b|\breset\s+value\b"), 3),
]

TECH_SCORE_THRESHOLD = 8


def classify_heuristic(text: str, head_chars: int = 8000) -> tuple[bool, int]:
    """Keyword-based datasheet/manual detector. Returns (is_technical, score)."""
    head = text[:head_chars]
    score = sum(weight for pattern, weight in _TECH_KEYWORDS if pattern.search(head))
    return score >= TECH_SCORE_THRESHOLD, score


CLASSIFY_SYSTEM_PROMPT = (
    "You classify documents. Decide whether the given beginning of a document "
    "is from a TECHNICAL hardware document (electronic component datasheet, "
    "microcontroller reference manual, register specification) or GENERAL text. "
    "Answer with exactly one word: TECHNICAL or GENERAL. No other output."
)


def classify_with_llm(
    text: str,
    model: str,
    endpoint: str,
    api_key: str,
    head_chars: int = 4000,
    max_tokens: int = 1024,
    sampling: dict | None = None,
) -> tuple[bool, str]:
    """Classify the document head via LLM.

    Returns (is_technical, source) where source is 'llm' or 'heuristic-fallback'.
    Fails safe: any error or ambiguous answer falls back to the keyword
    heuristic, which itself defaults to strict/technical on a high score.
    """
    head = text[:head_chars]
    try:
        import litellm  # lazy import

        litellm.suppress_debug_info = True
        std, extra = _split_sampling(sampling or DEFAULT_SAMPLING)
        resp = litellm.completion(
            model=f"openai/{model}",
            messages=[
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": head},
            ],
            api_base=endpoint,
            api_key=api_key,
            max_tokens=max_tokens,
            # Disable thinking: a reasoning model wastes its token budget on
            # deliberation for a one-word answer. Verified to be honoured by
            # llama-server for this model (passes through the llama-swappy
            # proxy untouched).
            extra_body={**extra, "chat_template_kwargs": {"enable_thinking": False}},
            **std,
        )
        answer = (resp.choices[0].message.content or "").strip().upper()
    except Exception:
        return (*classify_heuristic(text), "heuristic-fallback")

    if "TECHNICAL" in answer and "GENERAL" not in answer:
        return True, "llm"
    if "GENERAL" in answer and "TECHNICAL" not in answer:
        return False, "llm"
    # Ambiguous (refusal, rambling, both words, empty) -> heuristic fallback.
    return (*classify_heuristic(text), "heuristic-fallback")


# ---------------------------------------------------------------------------
# Chunking (line-based, structure-preserving)
# ---------------------------------------------------------------------------

def chunk_markdown(text: str, max_chars: int = 6000) -> list[tuple[str, str]]:
    """Split Markdown into LLM-sized chunks WITHOUT destroying structure.

    Returns a list of (chunk, separator) pairs whose concatenation reproduces
    ``text`` exactly:  text == "".join(chunk + sep for chunk, sep in chunks)
    (the last separator is ""). Chunks break only at line boundaries, tables
    are never mixed with prose in a chunk, an oversized table is split at row
    boundaries only, and an oversized single line is sent as-is (the verifier
    gates whatever the model returns).
    """
    lines = text.split("\n")
    n = len(lines)
    chunks: list[tuple[str, str]] = []
    i = 0
    while i < n:
        j = i  # exclusive end of the chunk
        size = 0
        sep_extra = 0  # blank lines folded into the separator after this chunk
        while j < n:
            line_len = len(lines[j]) + 1
            if size + line_len > max_chars and j > i:
                break
            size += line_len
            j += 1
            # never cut inside a table block: swallow consecutive '|'-rows
            if lines[j - 1].lstrip().startswith("|"):
                while (
                    j < n
                    and lines[j].lstrip().startswith("|")
                    and size + len(lines[j]) + 1 <= max_chars
                ):
                    size += len(lines[j]) + 1
                    j += 1
                break
            # prefer a paragraph boundary: fold the blank-line run into the sep
            if size >= max_chars * 0.6 and j < n and lines[j].strip() == "":
                while j < n and lines[j].strip() == "":
                    sep_extra += 1
                    j += 1
                break
        end = j - sep_extra  # chunk lines are i..end-1; blanks live in the sep
        chunk = "\n".join(lines[i:end])
        if j >= n:
            sep = "\n" * (n - end)
        else:
            sep = "\n" * (j - end + 1)
        chunks.append((chunk, sep))
        i = j
    return chunks


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_COMMON_RULES = """You fix whitespace defects in extracted PDF-to-Markdown text.
ALLOWED ONLY:
(a) remove stray spaces inside and between words so falsely split words join
    correctly (deleting false line breaks so split words join is included);
(b) collapse runs of spaces;
(c) delete a false line break inside a paragraph, replacing it with one space
    (or with nothing where two word halves join).
FORBIDDEN:
- adding, deleting, reordering or changing ANY non-whitespace character;
- translating, rephrasing, summarising, "improving" grammar or spelling;
- changing the number of lines that start with '|' (table rows) or the number
  of '|' characters in them;
- altering any digit, number, hex token (0x1A2B), unit or value;
- adding comments, notes, headings, code fences or explanations.
Return ONLY the corrected Markdown, nothing else."""

TECHNICAL_SYSTEM_PROMPT = (
    "The text comes from an electronic component datasheet or microcontroller "
    "reference manual. PDF extraction left false spaces inside words and "
    "subscripts.\n"
    "Typical fixes in this domain: 'D-t yp e' -> 'D-type', 'fli p -flo p' -> "
    "'flip-flop', 'V CC' -> 'VCC', 'T amb' -> 'Tamb', 'Q n+1' -> 'Qn+1', "
    "'SOT108 - 1' -> 'SOT108-1', 'Orderin g' -> 'Ordering'.\n"
    "Register values, pin numbers, voltages, timings and part numbers are "
    "sacrosanct: never let two numbers or a number and a symbol merge "
    "('2 0' must NOT become '20', '0.5 V' must stay '0.5 V').\n"
    + _COMMON_RULES
)

GENERAL_SYSTEM_PROMPT = (
    "The text is general document prose converted from PDF. PDF extraction "
    "left false spaces inside words and false line breaks.\n"
    "Typical fixes: 'examp le' -> 'example', 'wo rd' -> 'word'.\n"
    + _COMMON_RULES
)

# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

# Defaults follow the Ornith-1.5-9B model card's "precise coding" set (the
# correction pass is a precision task, not free-form generation). Sampling is
# a *yield* parameter here, not a safety one — the algorithmic verifier is the
# safety mechanism and is independent of sampling. Override via config.json:
#   "llm_sampling": {"temperature": 1.0, "top_p": 0.95, ...}
DEFAULT_SAMPLING: dict = {
    "temperature": 0.6,
    "top_p": 0.95,
    "top_k": 20,
    "min_p": 0.0,
    "presence_penalty": 0.0,
}

# Keys litellm accepts as standard completion kwargs; everything else in the
# sampling dict is forwarded via extra_body (OpenAI-compatible extensions
# like top_k / min_p).
_STANDARD_SAMPLING_KEYS = {"temperature", "top_p", "presence_penalty", "frequency_penalty"}

# ---------------------------------------------------------------------------
# Algorithmic verification
# ---------------------------------------------------------------------------

def _join_allowed(left: str, right: str) -> bool:
    """Whitelist: may the whitespace between `left` and `right` be removed?

    This is what makes the VCC fix safe: joins are allowed exactly where no
    numeric value can be corrupted. Any pair not listed here is rejected.
    """
    if left.isalpha() and right.isalpha():          # V CC, T amb, fli p
        return True
    if left == "-" and right.isalnum():             # SOT108 - 1
        return True
    if right == "-" and left.isalnum():             # SOT108 - 1
        return True
    if left == "." and right.isalnum():             # 2 . 5 -> 2.5, '# 3.  Ordering'
        return True
    if right == "." and left.isalnum():             # 2 . 5 -> 2.5
        return True
    if left.isalpha() and right in ".,;:!?)":        # 'V CC .' -> 'VCC.'
        return True
    if left in "([{" and right.isalnum():            # '( nD)' -> '(nD)'
        return True
    return False


def _is_ws(s: str) -> bool:
    return all(c.isspace() for c in s)


def _check_whitespace_edit(orig: str, out: str) -> str | None:
    """Char-level diff check: only whitespace may change, and only safely.

    Returns None if the edit is acceptable, otherwise a rejection reason.
    """
    sm = difflib.SequenceMatcher(None, orig, out, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        removed = orig[i1:i2]
        inserted = out[j1:j2]
        if not _is_ws(removed) or not _is_ws(inserted):
            return f"non-whitespace change: {removed!r} -> {inserted!r}"
        if tag == "delete" or (tag == "replace" and removed):
            # Expand to the full whitespace run in the original so neighbour
            # checks see real content characters on both sides.
            a, b = i1, i2
            while a > 0 and orig[a - 1].isspace():
                a -= 1
            while b < len(orig) and orig[b].isspace():
                b += 1
            if not _is_ws(orig[a:b]) or len(orig[a:b]) != b - a:  # defensive
                return "internal: malformed whitespace run"
            left = orig[a - 1] if a > 0 else ""
            right = orig[b] if b < len(orig) else ""
            if left and right and not _join_allowed(left, right):
                return (
                    f"unsafe whitespace join ({left!r} | {right!r}): "
                    f"...{orig[max(0, a - 12):b + 12]!r}..."
                )
    return None


def _verify_chunk(orig: str, out: str) -> str | None:
    """Verify a whole chunk. Returns None if accepted, else a reason."""
    if not out.strip():
        return "empty model output"
    # Model may wrap output in a code fence — strip exactly one.
    m = re.match(r"^\s*```[^\n]*\n(.*)\n```\s*$", out, re.DOTALL)
    if m:
        out = m.group(1)

    # Invariant A (whole chunk): whitespace-stripped sequences identical.
    if "".join(out.split()) != "".join(orig.split()):
        return "invariant A violated: content characters changed"

    # Invariant C (neighbour rules) on the chunk as a whole.
    reason = _check_whitespace_edit(orig, out)
    if reason:
        return reason

    orig_lines = orig.split("\n")
    out_lines = out.split("\n")

    # Invariant B: table rows must keep their cell count and '|' positions.
    orig_rows = [l for l in orig_lines if l.lstrip().startswith("|")]
    out_rows = [l for l in out_lines if l.lstrip().startswith("|")]
    if len(orig_rows) != len(out_rows):
        return "table row added or removed"
    for orow, orow_out in zip(orig_rows, out_rows):
        if orow.count("|") != orow_out.count("|"):
            return f"table cell count changed: {orow_out[:60]!r}"
        # per-cell whitespace-only edit check
        ocells = orow.split("|")
        ncells = orow_out.split("|")
        for oc, nc in zip(ocells, ncells):
            if "".join(oc.split()) != "".join(nc.split()):
                return f"cell content changed: {nc.strip()[:60]!r}"
            reason = _check_whitespace_edit(oc, nc)
            if reason:
                return f"cell edit rejected ({reason})"
    return None


# ---------------------------------------------------------------------------
# Correction pass
# ---------------------------------------------------------------------------

def _split_sampling(sampling: dict) -> tuple[dict, dict]:
    """Split sampling config into litellm standard kwargs vs extra_body."""
    std = {k: v for k, v in sampling.items() if k in _STANDARD_SAMPLING_KEYS}
    extra = {k: v for k, v in sampling.items() if k not in _STANDARD_SAMPLING_KEYS}
    return std, extra


def _call_llm(prompt_system: str, chunk: str, model: str, endpoint: str,
              api_key: str, max_tokens: int, sampling: dict | None = None,
              retry_hint: str | None = None) -> str:
    import litellm  # lazy import

    litellm.suppress_debug_info = True
    std, extra = _split_sampling(sampling or DEFAULT_SAMPLING)
    user_content = chunk
    if retry_hint:
        user_content += (
            "\n\nNOTE: your previous output for this text was REJECTED because "
            f"it changed non-whitespace content ({retry_hint}). Only whitespace-"
            "level fixes are allowed; everything else must stay byte-identical."
        )
    resp = litellm.completion(
        model=f"openai/{model}",
        messages=[
            {"role": "system", "content": prompt_system},
            {"role": "user", "content": user_content},
        ],
        api_base=endpoint,
        api_key=api_key,
        max_tokens=max_tokens,
        timeout=300,
        extra_body={**extra, "chat_template_kwargs": {"enable_thinking": False}},
        **std,
    )
    return (resp.choices[0].message.content or "").strip()


def _verify_line_in_context(o_lines: list[str], idx: int, c_line: str) -> str | None:
    """Verify a single-line replacement with neighbouring lines as context."""
    prev = o_lines[idx - 1] if idx > 0 else ""
    nxt = o_lines[idx + 1] if idx + 1 < len(o_lines) else ""
    ctx_o = prev + "\n" + o_lines[idx] + "\n" + nxt
    ctx_c = prev + "\n" + c_line + "\n" + nxt
    if "".join(ctx_c.split()) != "".join(ctx_o.split()):
        return "invariant A violated: content characters changed"
    return _check_whitespace_edit(ctx_o, ctx_c)


def _salvage(orig: str, cand: str) -> tuple[str, int, int, list[str]]:
    """Line/block-level salvage from a rejected candidate.

    Line-diff original vs candidate. Every differing piece that independently
    passes verification is applied (single lines are verified in the context
    of their neighbours; unequal-count regions are verified as whole blocks);
    everything else reverts to the original. The result is therefore always
    safe by construction, even when the candidate was hallucinated.
    Returns (salvaged_text, pieces_fixed, pieces_total, reasons_of_failed).
    """
    o_lines = orig.split("\n")
    c_lines = cand.split("\n")
    sm = difflib.SequenceMatcher(None, o_lines, c_lines, autojunk=False)
    out_lines: list[str] = []
    reasons: list[str] = []
    fixed = 0
    total = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out_lines.extend(o_lines[i1:i2])
            continue
        o_blk = o_lines[i1:i2]
        c_blk = c_lines[j1:j2]
        if len(o_blk) == len(c_blk):
            for k, (o_line, c_line) in enumerate(zip(o_blk, c_blk)):
                if o_line == c_line:
                    out_lines.append(o_line)
                    continue
                total += 1
                if not c_line.strip():
                    out_lines.append(o_line)
                    continue
                if o_line.lstrip().startswith("|") or c_line.lstrip().startswith("|"):
                    reason = _verify_chunk(o_line, c_line)
                else:
                    reason = _verify_line_in_context(o_lines, i1 + k, c_line)
                if reason is None:
                    out_lines.append(c_line)
                    fixed += 1
                else:
                    reasons.append(reason)
                    out_lines.append(o_line)
        else:
            total += 1
            o_text = "\n".join(o_blk)
            c_text = "\n".join(c_blk)
            reason = _verify_chunk(o_text, c_text) if c_text.strip() else "empty"
            if c_text.strip() and reason is None:
                out_lines.extend(c_blk)
                fixed += 1
            else:
                if reason and reason != "empty":
                    reasons.append(reason)
                out_lines.extend(o_blk)
    return "\n".join(out_lines), fixed, total, reasons


def correct_with_llm(
    text: str,
    model: str,
    endpoint: str,
    api_key: str,
    verbose: bool = True,
    max_chars: int = 6000,
    classify: bool = True,
    sampling: dict | None = None,
    retries: int = 1,
) -> tuple[str, dict]:
    """Run the guarded LLM correction pass.

    Returns (corrected_text, stats). Every model output is verified
    algorithmically: fully valid chunks are accepted as-is; rejected ones go
    through block-level salvage (only independently verified blocks are
    applied); ``retries`` bounded regeneration attempts may follow, keeping
    the attempt that fixes the most blocks. Whatever fails verification is
    kept as the original — rejection is always safe, never silent.
    """
    text = dedupe_bullets(text)

    is_technical, source = (True, "heuristic")
    if classify:
        is_technical, source = classify_with_llm(
            text, model, endpoint, api_key, sampling=sampling
        )
    system_prompt = TECHNICAL_SYSTEM_PROMPT if is_technical else GENERAL_SYSTEM_PROMPT
    if verbose:
        print(
            f"  llm: document classified {'technical' if is_technical else 'general'} "
            f"({source})"
        )

    chunks = chunk_markdown(text, max_chars)
    stats: dict = {
        "model": model,
        "sampling": sampling or DEFAULT_SAMPLING,
        "classification": {
            "technical": is_technical,
            "source": source,
        },
        "chunks_total": len(chunks),
        "chunks_accepted": 0,
        "chunks_salvaged": 0,
        "chunks_rejected": 0,
        "blocks_fixed": 0,
        "retries_used": 0,
        "rejections": [],
    }

    out_parts: list[str] = []
    for i, (chunk, sep) in enumerate(chunks, 1):
        if verbose:
            print(f"  llm: chunk {i}/{len(chunks)} ({len(chunk)} chars) ...")
        best: str | None = None      # verified-safe version of this chunk
        best_fixed = -1
        chunk_rejections: list[str] = []
        n_calls = 0

        for attempt in range(1 + max(0, retries)):
            hint = chunk_rejections[-1] if (attempt and chunk_rejections) else None
            try:
                candidate = _call_llm(
                    system_prompt, chunk, model, endpoint, api_key,
                    max_tokens=max_chars * 2, sampling=sampling, retry_hint=hint,
                )
                n_calls += 1
            except Exception as e:  # network/model error -> keep original
                chunk_rejections.append(f"llm error: {type(e).__name__}: {e}"[:200])
                continue
            if _verify_chunk(chunk, candidate) is None:
                best, best_fixed = candidate, 1 << 30  # whole chunk verified
                break
            salvaged, fixed, total, reasons = _salvage(chunk, candidate)
            chunk_rejections.extend(reasons[:3])
            if fixed > best_fixed:
                best, best_fixed = salvaged, fixed
            if fixed >= total:  # every differing block verified -> done
                break

        if best is None or best_fixed <= 0:
            stats["chunks_rejected"] += 1
            stats["rejections"].append(
                {"chunk": i,
                 "reason": "; ".join(chunk_rejections[:3]) or "no usable output",
                 "preview": chunk[:120]}
            )
            out_parts.append(chunk + sep)
        elif best_fixed >= (1 << 30):
            stats["chunks_accepted"] += 1
            out_parts.append(best + sep)
        else:
            stats["chunks_salvaged"] += 1
            stats["blocks_fixed"] += best_fixed
            out_parts.append(best + sep)
        stats["retries_used"] += max(0, n_calls - 1)

    return "".join(out_parts), stats
