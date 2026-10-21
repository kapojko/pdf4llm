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
import json
import math
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# Deterministic pre-passes (no LLM involved).
# ---------------------------------------------------------------------------

_HR_LINE_RE = re.compile(r"(?m)^\s*(?:-{3,}|\*{3,}|_{3,})\s*\n")


def _is_hr_line(line: str) -> bool:
    """True for standalone horizontal-rule lines ('---', '***', '___').

    A '|' anywhere means it is a table row (e.g. a single-cell delimiter
    '| --- |'), which must never be stripped.
    """
    return "|" not in line and bool(re.fullmatch(r"\s*(?:-{3,}|\*{3,}|_{3,})\s*", line))


def strip_horizontal_rules(text: str) -> tuple[str, int]:
    """Remove standalone horizontal-rule lines (PDF page-break artifacts).

    Must run BEFORE the LLM pass: models reliably try to delete them, which
    is a content change and would poison whole chunks. Stripping first means
    the model never sees them. Only lines consisting solely of dashes/
    asterisks/underscores are removed; nothing inside tables or text.
    Returns (text, removed_count).
    """
    out, n = _HR_LINE_RE.subn("", text)
    return out, n


_BULLET_LEAD_RE = re.compile(r"(?m)^(\s*[-*+])\s+[•\u2022]\s+")
_BULLET_TRAIL_RE = re.compile(r"(?m)^(\s*[-*+].*?)\s+[•\u2022]\s*$")


def dedupe_bullets(text: str) -> str:
    """Remove '•' glyphs that duplicate a Markdown list marker."""
    text = _BULLET_LEAD_RE.sub(r"\1 ", text)
    text = _BULLET_TRAIL_RE.sub(r"\1", text)
    return text


# ---------------------------------------------------------------------------
# Deterministic pre-pass: subscript normalisation (no LLM involved).
# PDF extraction flattens V_CC to 'V CC', T_amb to 'T amb', t_pd to 't pd'.
# Normalised forms: established uppercase terms are joined ('V CC' -> 'VCC',
# 'V IH' -> 'VIH', 't PLH' -> 'tPLH'); everything else gets an underscore
# ('T amb' -> 'T_amb', 'C L' -> 'C_L', 'I IK' -> 'I_IK', 'Q n+1' -> 'Q_n+1').
# Deterministic + guarded: prefix/suffix whitelists, English-stopword filter,
# so prose like 'I do' or 'a few' can never be rewritten.
# ---------------------------------------------------------------------------

_SUB_PAIR_RE = re.compile(r"(?<![A-Za-z_\-])([A-Za-z]) ([A-Za-z][A-Za-z0-9+]{0,3}(?:\+\d+)?)\b")

# prefixes that are established quantity symbols in datasheets (never English
# words on their own). 'I' (current) and 'V' (voltage) collide with the
# pronoun/numeral readings, so 'I' is restricted below and handled via
# underscore form only.
_SUB_PREFIXES = set("VTPCRQtfLNM")

# English words a subscript suffix must never collide with (lowercase form).
_SUB_STOPWORDS = {
    "a", "an", "am", "and", "any", "are", "as", "at", "be", "but", "by",
    "can", "do", "due", "few", "for", "from", "had", "has", "he", "her",
    "him", "his", "how", "if", "in", "is", "it", "its", "may", "me",
    "my", "no", "not", "now", "of", "on", "one", "only", "or", "our",
    "out", "per", "so", "sub", "such", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "to", "two", "up",
    "us", "use", "was", "way", "we", "were", "what", "when", "which",
    "who", "why", "will", "with", "you", "your",
}


def _sub_form(prefix: str, suffix: str) -> str | None:
    """Return the normalised 'prefix_suffix' token, or None if not safe."""
    if prefix not in _SUB_PREFIXES and prefix != "I":
        return None  # prefix is not a known quantity symbol -> leave alone
    if prefix in {"A", "a", "i"}:
        return None  # article/pronoun readings dominate
    if suffix.lower() in _SUB_STOPWORDS:
        return None
    if prefix == "I":
        # current symbol; joining I+IK -> 'IIK' is unreadable, and 'I' is the
        # English pronoun -> underscore form only
        return f"{prefix}_{suffix}"
    if suffix.isupper() and len(suffix) >= 2:
        # established compact terms: V CC -> VCC, V IH -> VIH, t PLH -> tPLH
        return f"{prefix}{suffix}"
    # mixed/lowercase or single-letter suffixes: T amb -> T_amb, C L -> C_L
    return f"{prefix}_{suffix}"


def fix_subscripts(text: str) -> tuple[str, int]:
    """Normalise flattened subscripts. Returns (text, replacement_count)."""
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        form = _sub_form(m.group(1), m.group(2))
        if form is None:
            return m.group(0)
        count += 1
        return form

    return _SUB_PAIR_RE.sub(repl, text), count


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
- removing or altering horizontal rule lines ('---' on its own line) — keep
  them byte-identical;
- changing the spacing around em/en dashes ('—', '–') — keep it as-is;
- translating, rephrasing, summarising, "improving" grammar or spelling;
- changing the number of lines that start with '|' (table rows) or the number
  of '|' characters in them;
- altering any digit, number, hex token (0x1A2B), unit or value;
- adding comments, notes, headings, code fences or explanations.
Return ONLY the corrected Markdown, nothing else."""

TECHNICAL_SYSTEM_PROMPT = (
    "The text comes from an electronic component datasheet or microcontroller "
    "reference manual. PDF extraction left false spaces inside words.\n"
    "Typical fixes in this domain: 'D-t yp e' -> 'D-type', 'fli p -flo p' -> "
    "'flip-flop', 'Orderin g' -> 'Ordering'. Subscripts like 'VCC', 'T_amb', "
    "'C_L' are already normalised — never change or move underscores ('_').\n"
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
    if left in "\u2014\u2013" or right in "\u2014\u2013":  # around em/en dashes
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

def _fmt_duration(seconds: float) -> str:
    """Human-readable duration: 42s, 6m05s, 1h02m."""
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m{sec:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


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


def _pair_by_similarity(o_blk: list[str], c_blk: list[str],
                        min_ratio: float = 0.55) -> dict[int, int]:
    """Greedy 1:1 pairing of orig lines to candidate lines by similarity.

    Used when line counts differ (model deleted/merged a line, e.g. a '---'
    horizontal rule): the shift must not cost us every following row.
    Returns {orig_index_within_block: cand_index_within_block}.
    """
    scored: list[tuple[float, int, int]] = []
    for i, ol in enumerate(o_blk):
        for j, cl in enumerate(c_blk):
            if ol == cl:
                r = 1.0
            elif not ol.strip() or not cl.strip():
                continue
            else:
                r = difflib.SequenceMatcher(None, ol, cl).ratio()
            if r >= min_ratio:
                scored.append((r, i, j))
    scored.sort(reverse=True)
    pairs: dict[int, int] = {}
    used_o: set[int] = set()
    used_c: set[int] = set()
    for r, i, j in scored:
        if i in used_o or j in used_c:
            continue
        pairs[i] = j
        used_o.add(i)
        used_c.add(j)
    return pairs


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
            # unequal line counts: first try the block as a whole (this handles
            # legitimate false-line-break joins); if that fails, pair rows by
            # similarity so one deleted line does not poison the whole block
            o_text = "\n".join(o_blk)
            c_text = "\n".join(c_blk)
            if c_text.strip() and _verify_chunk(o_text, c_text) is None:
                out_lines.extend(c_blk)
                fixed += 1
                total += 1
                continue
            pairs = _pair_by_similarity(o_blk, c_blk)
            for k, o_line in enumerate(o_blk):
                j = pairs.get(k)
                c_line = c_blk[j] if j is not None else None
                if c_line is None or o_line == c_line:
                    out_lines.append(o_line)
                    continue
                total += 1
                if not c_line.strip():
                    out_lines.append(o_line)
                    continue
                abs_idx = i1 + k
                if o_line.lstrip().startswith("|") or c_line.lstrip().startswith("|"):
                    reason = _verify_chunk(o_line, c_line)
                else:
                    reason = _verify_line_in_context(o_lines, abs_idx, c_line)
                if reason is None:
                    out_lines.append(c_line)
                    fixed += 1
                else:
                    reasons.append(reason)
                    out_lines.append(o_line)
    return "\n".join(out_lines), fixed, total, reasons


def _run_chunk(
    idx: int,
    total: int,
    chunk: str,
    sep: str,
    system_prompt: str,
    model: str,
    endpoint: str,
    api_key: str,
    max_tokens: int,
    sampling: dict | None,
    retries: int,
) -> tuple[str, dict]:
    """Process ONE chunk: call -> verify -> accept / salvage -> bounded retries.

    This is the whole per-chunk logic, shared by the sequential and the
    parallel path — the safety architecture (per-chunk verification with
    invariants A/B/C, then salvage, then hinted retries) is identical no
    matter how many workers run. Chunks are independent: the result text is
    ``verified_chunk + sep`` so reassembly is exact concatenation.

    Returns (result_text, per-chunk stats delta).
    """
    print(f"  llm: chunk {idx}/{total} ({len(chunk)} chars) ...", flush=True)
    chunk_start = time.monotonic()
    best: str | None = None      # verified-safe version of this chunk
    best_fixed = -1
    chunk_rejections: list[str] = []
    n_calls = 0

    for attempt in range(1 + max(0, retries)):
        hint = chunk_rejections[-1] if (attempt and chunk_rejections) else None
        try:
            candidate = _call_llm(
                system_prompt, chunk, model, endpoint, api_key,
                max_tokens=max_tokens, sampling=sampling, retry_hint=hint,
            )
            n_calls += 1
        except Exception as e:  # network/model error -> keep original
            chunk_rejections.append(f"llm error: {type(e).__name__}: {e}"[:200])
            continue
        if _verify_chunk(chunk, candidate) is None:
            best, best_fixed = candidate, 1 << 30  # whole chunk verified
            break
        salvaged, fixed, n_total, reasons = _salvage(chunk, candidate)
        chunk_rejections.extend(reasons[:3])
        if fixed > best_fixed:
            best, best_fixed = salvaged, fixed
        if fixed >= n_total:  # every differing block verified -> done
            break

    if best is None or best_fixed <= 0:
        result = chunk + sep
        delta = {
            "index": idx,
            "rejected": True,
            "blocks_fixed": 0,
            "rejection": {
                "chunk": idx,
                "reason": "; ".join(chunk_rejections[:3]) or "no usable output",
                "preview": chunk[:120],
            },
        }
    elif best_fixed >= (1 << 30):
        result = best + sep
        delta = {"index": idx, "accepted": True, "blocks_fixed": 0, "rejection": None}
    else:
        result = best + sep
        delta = {"index": idx, "salvaged": True, "blocks_fixed": best_fixed,
                 "rejection": None}
    delta["retries_used"] = max(0, n_calls - 1)
    delta["duration"] = time.monotonic() - chunk_start
    return result, delta


def _apply_chunk_delta(stats: dict, delta: dict) -> None:
    """Merge one chunk's stats delta into the global stats dict."""
    if delta.get("accepted"):
        stats["chunks_accepted"] += 1
    elif delta.get("salvaged"):
        stats["chunks_salvaged"] += 1
        stats["blocks_fixed"] += delta["blocks_fixed"]
    elif delta.get("rejected"):
        stats["chunks_rejected"] += 1
        stats["rejections"].append(delta["rejection"])
    stats["retries_used"] += delta["retries_used"]


# ---------------------------------------------------------------------------
# llama-swappy self-description probe (workers auto-set + context check)
# ---------------------------------------------------------------------------

# Rough chars-per-token for technical English datasheet/manual prose. Used
# ONLY for the coarse "does the chunk fit the context" estimate — never for
# anything safety-relevant (the verifier is the safety mechanism).
_CHARS_PER_TOKEN = 3.5
# Slack for the system prompt, retry hint, code-fence wrapping and estimator
# error, added on top of the estimated input+output tokens.
_CTX_MARGIN_TOKENS = 512
# Cap on auto-selected workers: beyond 4 slots the GPU (bandwidth-limited)
# spends its throughput on more concurrent streams without shortening the
# critical path.
_MAX_AUTO_WORKERS = 4


class LlmContextError(RuntimeError):
    """The server context provably cannot hold a chunk's input + output."""


def probe_swappy(endpoint: str, api_key: str, timeout: float = 3.0) -> dict | None:
    """Fetch the llama-swappy self-description endpoint, if present.

    Tries ``<base>/llama-swappy/info`` where <base> is the endpoint with a
    trailing ``/v1`` stripped first, then the endpoint as given. Returns the
    parsed JSON dict, or None when the endpoint does not exist or does not
    answer (any ordinary OpenAI-compatible server, network issue, bad JSON).
    Never raises.
    """
    base = endpoint.rstrip("/")
    urls = [b + "/llama-swappy/info" for b in dict.fromkeys(
        [re.sub(r"/v1/?$", "", base), base])]
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            if isinstance(data, dict) and isinstance(data.get("models"), list):
                return data
        except Exception:
            continue
    return None


def estimate_chunk_tokens(max_chunk_chars: int) -> int:
    """Rough token estimate for the largest chunk: input + output + slack.

    The correction pass is whitespace-only, so the output has roughly the
    same size as the input — hence 2x the input estimate plus a margin for
    the system prompt, retry hint and estimator error.
    """
    in_tokens = math.ceil(max_chunk_chars / _CHARS_PER_TOKEN)
    return 2 * in_tokens + _CTX_MARGIN_TOKENS


def resolve_workers(
    endpoint: str,
    api_key: str,
    model: str,
    max_chunk_chars: int,
    workers: int | None,
    note=None,
) -> tuple[int, dict | None]:
    """Probe llama-swappy; auto-set workers and check the context fit.

    Worker priority: explicit ``workers`` argument > ``min(slots, 4)`` from
    the info endpoint > 1 (unknown server). The context check compares a
    rough input+output estimate for the largest chunk against the per-request
    contextSize reported by llama-swappy (v1.3 semantics: total -c divided
    by slots) and raises LlmContextError when it does not fit. Missing data
    (no info endpoint, model key not listed, contextSize absent) degrades
    with a warning — never aborts.

    Returns (workers, swappy_model_entry_or_None).
    """
    if note is None:  # pragma: no cover
        def note(msg: str) -> None:
            print(msg, flush=True)

    info = probe_swappy(endpoint, api_key)
    if info is None:
        return (max(1, workers) if workers is not None else 1), None

    models = info.get("models") or []
    entry = next((m for m in models if m.get("key") == model), None)
    if entry is None and len(models) == 1:
        entry = models[0]
    if entry is None:
        note(f"  llm: note: llama-swappy info has no entry for model {model!r} "
             "— skipping context check")
        return (max(1, workers) if workers is not None else 1), None

    ctx = entry.get("contextSize")
    if ctx:
        need = estimate_chunk_tokens(max_chunk_chars)
        if need > ctx:
            raise LlmContextError(
                f"server context too small: {ctx} tokens/request available "
                f"(llama-swappy, model {entry.get('key')!r}), but the largest "
                f"chunk needs ~{need} tokens (in+out, rough estimate; "
                f"{max_chunk_chars} chars). Reduce the chunk size or increase "
                "the server context (-c, divided by -np)."
            )

    slots = entry.get("slots")
    if workers is not None:
        n_workers = max(1, workers)
        how = "explicit"
    elif slots:
        n_workers = min(int(slots), _MAX_AUTO_WORKERS)
        how = "from llama-swappy slots"
    else:
        n_workers = 1
        how = "default (slots unknown)"
    note(f"  llm: llama-swappy: slots={slots}, context={ctx} tok/request "
         f"-> workers={n_workers} ({how})")
    return n_workers, entry


def correct_with_llm(
    text: str,
    model: str,
    endpoint: str,
    api_key: str,
    verbose: bool = True,
    max_chars: int = 6000,
    classify: bool = True,
    sampling: dict | None = None,
    retries: int = 2,
    workers: int | None = None,
) -> tuple[str, dict]:
    """Run the guarded LLM correction pass.

    Returns (corrected_text, stats). Every model output is verified
    algorithmically: fully valid chunks are accepted as-is; rejected ones go
    through block-level salvage (only independently verified blocks are
    applied); ``retries`` bounded regeneration attempts may follow, keeping
    the attempt that fixes the most blocks. Whatever fails verification is
    kept as the original — rejection is always safe, never silent.

    ``workers`` > 1 processes chunks concurrently (ThreadPoolExecutor,
    litellm calls are thread-safe). Safety is unaffected: every chunk still
    goes through the same verify/salvage/retry pipeline, chunks are
    independent and the output is reassembled strictly in original order.

    ``workers`` None (default) auto-selects from the llama-swappy info
    endpoint: min(slots, 4), falling back to 1 when the server does not
    self-describe. When the server reports its per-request context, a rough
    input+output estimate for the largest chunk is checked against it and
    the pass is aborted (LlmContextError) when a chunk provably cannot fit.
    """
    text = dedupe_bullets(text)
    text, hr_removed = strip_horizontal_rules(text)

    is_technical, source = (True, "heuristic")
    if classify:
        is_technical, source = classify_with_llm(
            text, model, endpoint, api_key, sampling=sampling
        )
    system_prompt = TECHNICAL_SYSTEM_PROMPT if is_technical else GENERAL_SYSTEM_PROMPT
    sub_count = 0
    if is_technical:
        text, sub_count = fix_subscripts(text)
    if verbose:
        print(
            f"  llm: document classified {'technical' if is_technical else 'general'} "
            f"({source})"
            + (f"; {sub_count} subscripts normalised" if sub_count else "")
        )

    chunks = chunk_markdown(text, max_chars)

    # llama-swappy probe: auto workers + rough context-sufficiency check.
    # Runs on the ACTUAL largest chunk (an oversized single line can exceed
    # max_chars), before any LLM call so an abort costs nothing.
    swappy_entry: dict | None = None
    if chunks:
        biggest = max(len(chunk) for chunk, _sep in chunks)
        workers, swappy_entry = resolve_workers(
            endpoint, api_key, model, biggest, workers,
            note=lambda msg: print(msg, flush=True),
        )
    elif workers is None:
        workers = 1

    stats: dict = {
        "model": model,
        "sampling": sampling or DEFAULT_SAMPLING,
        "classification": {
            "technical": is_technical,
            "source": source,
        },
        "subscripts_normalised": sub_count,
        "horizontal_rules_removed": hr_removed,
        "chunks_total": len(chunks),
        "chunks_accepted": 0,
        "chunks_salvaged": 0,
        "chunks_rejected": 0,
        "blocks_fixed": 0,
        "retries_used": 0,
        "rejections": [],
    }
    if swappy_entry is not None:
        stats["swappy"] = {
            "key": swappy_entry.get("key"),
            "slots": swappy_entry.get("slots"),
            "context_per_request": swappy_entry.get("contextSize"),
            "workers": workers,
        }

    out_parts: list[str | None] = [None] * len(chunks)
    t0 = time.monotonic()

    if workers <= 1:
        # Sequential path: exactly the original behaviour, including prints.
        chunk_durations: list[float] = []
        for i, (chunk, sep) in enumerate(chunks, 1):
            result, delta = _run_chunk(
                i, len(chunks), chunk, sep, system_prompt, model, endpoint,
                api_key, max_chars * 2, sampling, retries,
            )
            out_parts[i - 1] = result
            _apply_chunk_delta(stats, delta)
            chunk_durations.append(delta["duration"])
            # unconditional progress: the LLM pass is slow and the user must
            # see that it is alive, with an ETA based on the avg chunk so far
            if i < len(chunks):
                eta = (sum(chunk_durations) / len(chunk_durations)) * (len(chunks) - i)
                print(
                    f"  llm: chunk {i}/{len(chunks)} done in "
                    f"{_fmt_duration(delta['duration'])}  |  elapsed "
                    f"{_fmt_duration(time.monotonic() - t0)}  |  "
                    f"eta ~{_fmt_duration(eta)}",
                    flush=True,
                )
    else:
        # Parallel path: ThreadPoolExecutor (litellm calls are thread-safe).
        # The executor caps in-flight requests at max_workers, so a huge doc
        # cannot queue unbounded. Each worker merges its own stats delta under
        # a lock; reassembly below is strictly in original chunk order.
        workers = min(workers, len(chunks))
        lock = threading.Lock()
        done_count = [0]

        def _worker(idx: int, chunk: str, sep: str) -> None:
            result, delta = _run_chunk(
                idx, len(chunks), chunk, sep, system_prompt, model, endpoint,
                api_key, max_chars * 2, sampling, retries,
            )
            out_parts[idx - 1] = result
            with lock:
                _apply_chunk_delta(stats, delta)
                done_count[0] += 1
                n_done = done_count[0]
            # unconditional progress (not gated on -v): completed-chunk count
            # with elapsed time and an ETA from the parallel throughput so far
            elapsed = time.monotonic() - t0
            eta = elapsed / n_done * (len(chunks) - n_done)
            print(
                f"  llm: {n_done}/{len(chunks)} done, elapsed "
                f"{_fmt_duration(elapsed)}, eta ~{_fmt_duration(eta)}",
                flush=True,
            )

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [
                ex.submit(_worker, i, chunk, sep)
                for i, (chunk, sep) in enumerate(chunks, 1)
            ]
            for fut in futures:
                fut.result()  # propagate worker exceptions

    # deterministic meta.json regardless of completion order
    stats["rejections"].sort(key=lambda r: r["chunk"])
    return "".join(out_parts), stats
