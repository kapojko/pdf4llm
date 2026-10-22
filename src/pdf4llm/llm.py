"""Optional local-LLM broken-text correction pass (single strict mode).

Design (safety-first):

1. Classification (technical vs general) picks only the *prompt* — never the
   safety rules. LLM classifier on the document head; keyword heuristic
   fallback; any ambiguity/error defaults to the strict technical prompt.
2. Deterministic pre-passes (no LLM involved) remove known extraction noise
   the models reliably try to "fix" and thereby poison chunks with:
   horizontal rules, TOC dot leaders, duplicate bullet glyphs; plus guarded
   subscript normalisation ('V CC' -> 'VCC', 'T amb' -> 'T_amb').
3. Structure never passes through the model:
   - table chunks are processed at cell level: only cells whose content looks
     defect-suspect are sent (deterministic pre-filter; ~90% of cells are
     skipped), each batch with its row as context; the row skeleton (pipes,
     padding, separator rows) is spliced back untouched;
   - TOC-like chunks (every row duplicates a long cell) are skipped
     deterministically: no model output can ever verify against them;
   - prose chunks get ONE whole-chunk attempt (the only unit that can join
     falsely split lines), then a deterministic line-level salvage of the
     candidate, then batched re-asks of the disputed lines (only the
     failed subset, up to llm_retries rounds, with a hint).
   All unit-level requests use an indexed echo protocol ('N| text');
   measured on a 9B/A1.3B model, they produced zero content
   violations where whole-table chunks were rejected ~70% of the time.
   Sampling is never overridden: server-side defaults apply unless the user
   configures llm_sampling, and failed units are re-requested up to
   llm_retries times with a rejection-reason hint.
4. Every model output is verified algorithmically before any part of it is
   accepted: canonical/whitespace-level edits only (typographic punctuation
   classes — dashes, quotes, bullets, ellipsis — accepted in either direction
   via a closed canonical map), numeric-token protection, table structure
   checks. Words and numbers are physically immutable. Whatever fails
   verification is kept as the original — rejection is always safe, never
   silent; per-chunk outcomes are logged into meta.json.
"""
from __future__ import annotations

import difflib
import json
import math
import queue
import re
import threading
import time
import urllib.request

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


# ---------------------------------------------------------------------------
# Deterministic pre-pass: TOC dot leaders (no LLM involved).
# Extraction leaves dotted leaders in tables of contents ('Glossary
# . . . . . . . . 71', 'Overview ...... 12'). Models treat the dot runs as
# noise and trim or pad them — a non-whitespace change, so the whole chunk
# fails invariant A and every retry is burned on a hopeless chunk (TOC pages
# can be a large share of a reference manual). Collapsing runs of 4+ dots
# (spaces allowed between the dots) to a single space removes the temptation
# deterministically; titles and page numbers survive byte-identical. Runs of
# exactly 3 dots (ellipsis in prose) are deliberately left alone.
# ---------------------------------------------------------------------------

_DOT_LEADER_RE = re.compile(r"(?:\.[ \t]*){4,}")


def collapse_dot_leaders(text: str) -> tuple[str, int]:
    """Collapse dotted TOC leaders (4+ dots, optionally space-separated).

    Returns (text, collapsed_run_count).
    """
    return _DOT_LEADER_RE.subn(" ", text)


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
        std, extra = _split_sampling(sampling or {})
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
# Unit-level protocol prompts (line / cell echo requests)
#
# The echo format is the discipline: measured on ling-3.0-tiny, per-line and
# per-cell requests produced ZERO content violations (vs ~70% rejections for
# whole-table chunks), because a short numbered unit leaves no room for the
# model's editorial instincts. Sampling is never overridden for these
# requests — the server-side defaults apply unless llm_sampling is set.
# ---------------------------------------------------------------------------

_LINE_RULES = """You fix whitespace defects in text extracted from a PDF.
Input: numbered lines 'N| text'.
Fix ONLY false spaces inside words ('examp le' -> 'example', 'D-t yp e' ->
'D-type', 'fli p -flo p' -> 'flip-flop').
HARD RULES:
- return EXACTLY the same numbered lines: same indices, same order, one line
  of output per line of input, no extra text, no code fences;
- never add, delete or reorder words; never change any letter, digit,
  number, hex token (0x1A2B), unit or value; never merge or split numbers
  ('2 0' must stay '2 0');
- never DELETE punctuation. Dash-like characters may be rewritten as '-'
  but never removed; bullet glyphs may be rewritten as '*';
- if a line has no defects, return it unchanged.
"""

TECHNICAL_LINE_PROMPT = (
    "The lines come from an electronic component datasheet or microcontroller "
    "reference manual. Subscripts like 'VCC' and 'T_amb' are already "
    "normalised — never change or move underscores ('_').\n" + _LINE_RULES
)
GENERAL_LINE_PROMPT = _LINE_RULES

_CELL_RULES = """You fix false spaces in words inside table cells extracted from a PDF.
Input: numbered cells 'N| text', then the original table row as CONTEXT.
Fix ONLY false spaces inside words ('R es .' -> 'Res.', 'D-t yp e' ->
'D-type'); collapse double spaces inside a cell.
HARD RULES:
- return EXACTLY the numbered cell lines: same indices, same order, one line
  per cell, no extra text, no code fences; never return the context row;
- never change any letter, digit, number, hex token, unit or value; never
  merge or split numbers ('2 0' must stay '2 0');
- never add or remove cell boundaries ('|');
- if a cell has no defects, return it unchanged.
"""

TECHNICAL_CELL_PROMPT = (
    "The cells come from an electronic component datasheet or microcontroller "
    "reference manual (register maps, pin tables, electrical "
    "characteristics).\n" + _CELL_RULES
)
GENERAL_CELL_PROMPT = _CELL_RULES

# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

# Sampling is NOT forced by the tool. When the user configures llm_sampling,
# it is forwarded verbatim on every request; otherwise NO sampling parameters
# are sent and the server-side defaults apply. The set below is only a
# suggested example (from a 9B model card's 'precise coding' preset) for the
# llm_sampling config key — never sent automatically.
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

# Output token cap. The task is nearly echo-like, but measured rewrites —
# cell re-alignment, whitespace padding — can reach ~2x the input length,
# and the previous 1x cap truncated 419/2936 calls on rm0410 (about half of
# them completable at 4x). 2x keeps a looping (or secretly reasoning) model
# on a short leash while letting legitimate rewrites finish; the truncated
# output then fails verification (invariant A) and the usual salvage
# machinery takes over. This is what terminates false loops cheaply.
_OUT_MARGIN_TOKENS = 256  # code fence + retry hint + estimator error


def output_token_cap(n_chars: int) -> int:
    """max_tokens for one request: 2x input tokens (3.5 chars/token) + margin."""
    return 2 * math.ceil(max(1, n_chars) / _CHARS_PER_TOKEN) + _OUT_MARGIN_TOKENS


# Belt-and-braces against reasoning output: the request already sends
# chat_template_kwargs {enable_thinking: false}, but some servers/templates
# ignore it. A leading <think>...</think> block is stripped before
# verification; an unclosed <think> means the output is all thinking.
_THINK_BLOCK_RE = re.compile(r"^(?:\s*<think>.*?</think>)+\s*", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """Remove a leading <think>...</think> block (or an all-thinking output)."""
    text = _THINK_BLOCK_RE.sub("", text)
    if text.lstrip().startswith("<think>"):
        return ""
    return text

# ---------------------------------------------------------------------------
# Algorithmic verification (single strict mode)
#
# Invariant A: input and output are identical after whitespace-stripping and
#   canonicalisation — i.e. whitespace edits plus a CLOSED set of
#   bidirectional typographic normalisations, nothing else.
# Canonical map: dash/quote/bullet/ellipsis glyph variants map to one
#   canonical form in BOTH directions, so the model may freely swap
#   '–' <-> '-' while a deleted dash or a changed letter stays rejected.
#   The map never touches [0-9A-Za-z_], so register names, constants and
#   words are physically immutable.
# Numeric-token check: digit runs with their internal separators (0.5,
#   1:0, 1,000, 2026-03-23) and a leading sign (±, -, +, –) must survive
#   as an ordered sequence — this is what blocks dangerous whitespace
#   joins like '2 0' -> '20', '0x30 08' -> '0x3008', '-40' -> '40'.
# Invariant B: table rows keep their cell count; edits checked per cell.
# ---------------------------------------------------------------------------

# Bidirectional canonical glyph map. Every class is meaning-preserving in
# technical documents and never maps to or from a letter or digit:
#   dashes (en/em/figure/minus/hyphen variants) -> '-';
#   curly/typographic quotes and primes -> straight ' and ";
#   ellipsis character -> '...';
#   bullet glyphs -> '*'.
_CANON_SUBS = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2015": "-", "\u2043": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201b": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201f": '"', "\u2033": '"',
    "\u2026": "...",
    "\u2022": "*", "\u25cf": "*", "\u25e6": "*", "\u25aa": "*",
    "\u2023": "*",
}
_CANON_RE = re.compile("|".join(re.escape(c) for c in _CANON_SUBS))

# escaped pipes are a markdown-table artifact ('\|' renders as '|'); models
# reliably unescape them, which must not count as a content change
_ESCAPED_PIPE_RE = re.compile(r"\\\|")


def canonicalize(text: str) -> str:
    """Map typographic glyph variants to one canonical form (see above)."""
    return _ESCAPED_PIPE_RE.sub("|", _CANON_RE.sub(lambda m: _CANON_SUBS[m.group(0)], text))


def _ws_canon(text: str) -> str:
    """Whitespace-stripped canonical form (the invariant-A projection)."""
    return canonicalize("".join(text.split()))


# Numeric token: optional sign, digits, internal separators; whitespace may
# surround the separators (extraction often spaces them out: '0 . 5').
# '.' ',' ':' '/' only — multiplication ('x', '×', '*') is deliberately NOT
# a separator, so '2×3' -> '23' is rejected. Signs '+-–—±' attach to the
# token so '-40' -> '40' (temperature!) is rejected.
_NUM_TOKEN_RE = re.compile(r"[+\-\u2013\u2014\u00b1]?\s*[0-9]+(?:\s*[.,:/]\s*[0-9]+)*")


def _num_tokens(text: str) -> list[str]:
    """Numeric tokens, whitespace inside each token normalised away.

    Runs on the canonicalized text so a dash swap ('—2' -> '-2') is not
    mistaken for a sign change.
    """
    return [re.sub(r"\s+", "", tok) for tok in _NUM_TOKEN_RE.findall(canonicalize(text))]


def _num_check(orig: str, out: str) -> str | None:
    """Ordered numeric-token comparison. Returns a reason or None."""
    o_toks = _num_tokens(orig)
    c_toks = _num_tokens(out)
    if o_toks == c_toks:
        return None
    for a, b in zip(o_toks, c_toks):
        if a != b:
            return f"numeric token changed: {a!r} -> {b!r}"
    if len(o_toks) > len(c_toks):
        return f"numeric token dropped: {o_toks[len(c_toks)]!r}"
    return f"numeric token inserted: {c_toks[len(o_toks)]!r}"


def _verify_pair(orig: str, out: str) -> str | None:
    """Verify one text unit (chunk, line or cell) at the canonical level.

    Returns None if acceptable, else a reason. Accepts whitespace edits and
    canonical glyph swaps; rejects any other content change.
    """
    if not out.strip():
        return "empty model output"
    # Model may wrap output in a code fence — strip exactly one.
    m = re.match(r"^\s*```[^\n]*\n(.*)\n```\s*$", out, re.DOTALL)
    if m:
        out = m.group(1)
    # Invariant A (canonical): whitespace-stripped sequences identical.
    if _ws_canon(out) != _ws_canon(orig):
        return "invariant A violated: content characters changed"
    # Numeric-token protection: blocks whitespace merges that corrupt values
    # ('2 0' -> '20', '0x30 08' -> '0x3008', '-40' -> '40').
    return _num_check(orig, out)


# ---------------------------------------------------------------------------
# Structure helpers: table rows, TOC-like chunks, cell surgery, and the
# 'N| text' echo protocol used for all line- and cell-level model requests.
# ---------------------------------------------------------------------------

def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_separator_row(line: str) -> bool:
    """A delimiter row like '| --- | --- |' (never sent to the model)."""
    return _is_table_row(line) and set(line) <= {"|", "-", " ", "\t"}


def _split_row_cells(row: str) -> list[tuple[str, str, str]] | None:
    """Split a table row into (lead_ws, core, trail_ws) per cell.

    Splits on unescaped pipes only ('\\|' is an escaped literal pipe inside
    a cell, e.g. in WCH datasheets). The parts outside the outer pipes are
    not cells and are not returned; None for a row without the expected
    pipe structure.
    """
    parts = re.split(r"(?<!\\)\|", row)
    if len(parts) < 3:
        return None
    segs = []
    for p in parts[1:-1]:
        m = re.fullmatch(r"(\s*)(.*?)(\s*)", p, re.DOTALL)
        segs.append((m.group(1), m.group(2), m.group(3)))
    return segs


def _row_cell_texts(row: str) -> list[str]:
    segs = _split_row_cells(row)
    return [core.strip() for _l, core, _t in segs] if segs else []


def _splice_cells(row: str,
                  segs: list[tuple[str, str, str]],
                  replacements: dict[int, str]) -> str:
    """Rebuild a row with only the given cell cores replaced (skeleton kept)."""
    parts = re.split(r"(?<!\\)\|", row)
    for k, new in replacements.items():
        lead, _core, trail = segs[k]
        parts[k + 1] = lead + new + trail
    return "|".join(parts)


def _is_toc_like(lines: list[str], min_long_len: int = 12) -> bool:
    """True if the chunk is a table of contents (extracted from the PDF TOC).

    TOC rows carry at most ONE distinct long cell — the entry title ending
    in its page number — sometimes duplicated into sibling cells by the
    extractor. Datasheet characteristic tables look similar (one long
    description cell per row + short numeric cells), but their description
    cells do not END with a bare page number — that signature is what
    separates the two. Register maps have several distinct long cells per
    row. Both non-TOC shapes are processable; the TOC shape is unfixable for
    the model (the only 'correction' it can make is deduplication or
    rewording, which never verifies), so it is skipped deterministically
    instead of burning requests and retries.

    Tolerant by design: up to ~10% of rows may deviate (the extractor
    occasionally splits a title across two cells), so one malformed row does
    not turn the whole TOC into expensive per-cell requests.
    """
    rows = [l for l in lines if _is_table_row(l) and not _is_separator_row(l)]
    if not rows:
        return False
    saw_long = False
    bad = 0
    bad_limit = max(1, len(rows) // 10)
    for row in rows:
        distinct = {c.strip() for c in _row_cell_texts(row)
                    if len(c.strip()) >= min_long_len}
        if distinct and not all(_PAGE_TAIL_RE.search(c) for c in distinct):
            bad += 1
            if bad > bad_limit:
                return False
        elif distinct:
            saw_long = True
    return saw_long


# A cell is defect-suspect if it may contain a falsely split word: a space
# inside an alphabetic run. Deliberately over-eager — a clean cell that gets
# sent anyway just verifies trivially, while a missed defect is a lost (and
# minor) fix. All-numeric/id cells never match, which is what makes the
# ~90% skip rate measured on rm0410 possible.
_SUSPICIOUS_ANY = re.compile(r"[A-Za-z] [a-z]")
_SUSPICIOUS_SHORT = re.compile(r"\b[A-Za-z] [A-Za-z]{1,2}\b")


def _suspicious_cell(text: str) -> bool:
    return bool(_SUSPICIOUS_ANY.search(text) or _SUSPICIOUS_SHORT.search(text))


_IDX_LINE_RE = re.compile(r"^\s*(\d+)\s*\|\s?(.*)$")

# a TOC-entry long cell ends with its page number ('Clocks  152'); a
# datasheet description cell ('Standard operating voltage') does not
_PAGE_TAIL_RE = re.compile(r"[.\s]*\d{1,4}\s*$")


def _parse_indexed_lines(resp: str, want: set[int]) -> dict[int, str]:
    """Parse a 'N| text' echo answer.

    Continuation lines (no index) are appended to the previous index, so a
    long wrapped line is not lost. The appended continuation must never
    capture the CONTEXT block (measured failure mode: the model echoes
    'CONTEXT: ...' after the cells, which used to poison the last cell), so
    parsing stops at the context marker and never captures raw table rows.
    Indices outside `want` are ignored.
    """
    got: dict[int, str] = {}
    last: int | None = None
    for raw in resp.split("\n"):
        stripped_line = raw.strip()
        if stripped_line.startswith(("CONTEXT", "context", "row:", "Row:")):
            break
        m = _IDX_LINE_RE.match(raw)
        if m:
            last = int(m.group(1))
            if last in want:
                got[last] = m.group(2)
        elif (stripped_line and last is not None and last in want
              and not stripped_line.startswith("|")):
            got[last] += "\n" + raw
    return got


def _verify_chunk(orig: str, out: str) -> str | None:
    """Verify a whole chunk. Returns None if accepted, else a reason.

    Strict mode: canonical invariant A + numeric tokens + table invariant B.
    """
    reason = _verify_pair(orig, out)
    if reason:
        return reason

    orig_lines = orig.split("\n")
    out_lines = out.split("\n")

    # Invariant B: table rows must keep their cell count and '|' positions.
    orig_rows = [l for l in orig_lines if _is_table_row(l)]
    out_rows = [l for l in out_lines if _is_table_row(l)]
    if len(orig_rows) != len(out_rows):
        return "table row added or removed"
    for orow, orow_out in zip(orig_rows, out_rows):
        if orow.count("|") != orow_out.count("|"):
            return f"table cell count changed: {orow_out[:60]!r}"
        # per-cell canonical edit check (invariant A already passed at chunk
        # level, so equality here is implied; kept as defense in depth)
        ocells = re.split(r"(?<!\\)\|", orow)
        ncells = re.split(r"(?<!\\)\|", orow_out)
        for oc, nc in zip(ocells, ncells):
            if _ws_canon(nc) != _ws_canon(oc):
                return f"cell content changed: {nc.strip()[:60]!r}"
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
    """Split sampling config into litellm standard kwargs vs extra_body.

    ``sampling`` may be empty: an empty dict means NO sampling parameters are
    sent and the server-side defaults apply. ``DEFAULT_SAMPLING`` below is
    kept only as a suggested example for the llm_sampling config key.
    """
    std = {k: v for k, v in sampling.items() if k in _STANDARD_SAMPLING_KEYS}
    extra = {k: v for k, v in sampling.items() if k not in _STANDARD_SAMPLING_KEYS}
    return std, extra


def _call_llm(prompt_system: str, chunk: str, model: str, endpoint: str,
              api_key: str, sampling: dict | None = None,
              retry_hint: str | None = None) -> tuple[str, str | None]:
    import litellm  # lazy import

    litellm.suppress_debug_info = True
    std, extra = _split_sampling(sampling or {})
    user_content = chunk
    if retry_hint:
        user_content += (
            f"\n\nNOTE: your previous output was REJECTED ({retry_hint}). "
            "Return the corrected text exactly as instructed: no additions, "
            "no omissions, no format changes."
        )
    # max_tokens is capped at ~the input length (output_token_cap): a looping
    # model is cut off quickly and the truncated output is rejected/salvaged.
    try:
        resp = litellm.completion(
            model=f"openai/{model}",
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": user_content},
            ],
            api_base=endpoint,
            api_key=api_key,
            max_tokens=output_token_cap(len(user_content)),
            timeout=300,
            extra_body={**extra, "chat_template_kwargs": {"enable_thinking": False}},
            **std,
        )
    except Exception as e:  # network/model error: caller keeps the original
        return "", f"llm error: {type(e).__name__}: {e}"[:200]
    finish = getattr(resp.choices[0], "finish_reason", None)
    return (resp.choices[0].message.content or "").strip(), finish


def _verify_line_in_context(o_lines: list[str], idx: int, c_line: str) -> str | None:
    """Verify a single-line replacement with neighbouring lines as context."""
    prev = o_lines[idx - 1] if idx > 0 else ""
    nxt = o_lines[idx + 1] if idx + 1 < len(o_lines) else ""
    ctx_o = prev + "\n" + o_lines[idx] + "\n" + nxt
    ctx_c = prev + "\n" + c_line + "\n" + nxt
    return _verify_pair(ctx_o, ctx_c)


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


def _salvage(orig: str, cand: str) -> tuple[str, int, int, list[str], set[int]]:
    """Line/block-level salvage from a rejected whole-chunk candidate.

    Line-diff original vs candidate. Every differing piece that independently
    passes verification is applied (single lines are verified in the context
    of their neighbours; unequal-count regions are verified as whole blocks);
    everything else reverts to the original. The result is therefore always
    safe by construction, even when the candidate was hallucinated.

    Returns (salvaged_text, pieces_fixed, pieces_total, reasons,
    failed_orig_indices) where failed_orig_indices are the 0-based original
    line numbers the candidate tried to change (or dropped) without passing
    verification — the input for the batched disputed-line re-ask.
    """
    o_lines = orig.split("\n")
    c_lines = cand.split("\n")
    sm = difflib.SequenceMatcher(None, o_lines, c_lines, autojunk=False)
    out_lines: list[str] = []
    reasons: list[str] = []
    failed: set[int] = set()
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
                    failed.add(i1 + k)
                    continue
                if _is_table_row(o_line) or _is_table_row(c_line):
                    reason = _verify_pair(o_line, c_line)
                else:
                    reason = _verify_line_in_context(o_lines, i1 + k, c_line)
                if reason is None:
                    out_lines.append(c_line)
                    fixed += 1
                else:
                    reasons.append(reason)
                    failed.add(i1 + k)
                    out_lines.append(o_line)
        else:
            # unequal line counts: first try the block as a whole (this
            # handles legitimate false-line-break joins); if that fails, pair
            # rows by similarity so one deleted line does not poison the block
            o_text = "\n".join(o_blk)
            c_text = "\n".join(c_blk)
            if c_text.strip() and _verify_pair(o_text, c_text) is None:
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
                    if c_line is None and o_line.strip():
                        failed.add(i1 + k)   # candidate dropped this line
                    continue
                total += 1
                if not c_line.strip():
                    out_lines.append(o_line)
                    failed.add(i1 + k)
                    continue
                abs_idx = i1 + k
                if _is_table_row(o_line) or _is_table_row(c_line):
                    reason = _verify_pair(o_line, c_line)
                else:
                    reason = _verify_line_in_context(o_lines, abs_idx, c_line)
                if reason is None:
                    out_lines.append(c_line)
                    fixed += 1
                else:
                    reasons.append(reason)
                    failed.add(abs_idx)
                    out_lines.append(o_line)
    return "\n".join(out_lines), fixed, total, reasons, failed


def _echo_units(
    system_prompt: str,
    payload: str,
    context: str | None,
    want: set[int],
    model: str,
    endpoint: str,
    api_key: str,
    sampling: dict | None,
    hint: str | None = None,
) -> tuple[dict[int, str], str | None]:
    """ONE batched 'N| ...' echo request; parse the answer.

    Retry rounds — for malformed replies and for units that fail verification
    — are managed by the caller, which re-requests only the failed subset
    with a rejection-reason hint. Sampling is whatever the user/server
    configured (never overridden), so a failed attempt may simply recover on
    the next one.

    Returns (got: {index: text}, finish_reason).
    """
    user = payload + ("\n\nCONTEXT:\n" + context if context else "")
    if hint:
        user += ("\n\nNOTE: your previous output was REJECTED (" + hint + "). "
                 "Return the corrected lines exactly as instructed.")
    resp, finish = _call_llm(system_prompt, user, model, endpoint, api_key,
                             sampling=sampling)
    resp = _strip_thinking(resp)
    return _parse_indexed_lines(resp, want), finish


def _verified_rounds(
    system_prompt: str,
    units: dict[int, str],
    context: str | None,
    verify,
    model: str,
    endpoint: str,
    api_key: str,
    sampling: dict | None,
    retries: int,
    state: dict,
    strip: bool = False,
) -> tuple[dict[int, str], list[int], dict[int, str], str | None]:
    """Send 'N|' echo requests for `units` and verify each returned text.

    Retries (up to `retries` extra rounds) target only the subset that fails
    parsing (malformed reply) or verification, with a rejection-reason hint.
    Sampling is never overridden — a failed attempt may simply recover on the
    next round, since the verifier, not sampling, is the safety gate.

    verify(idx, new_text) -> None when the replacement is accepted.
    Returns (accepted {idx: text}, still_failing [idx], last_fail_reasons,
    last_finish_reason); request counters accumulate into ``state``.
    """
    pending = sorted(units)
    fail_reasons: dict[int, str] = {}
    accepted: dict[int, str] = {}
    fin: str | None = None
    for round_no in range(1 + max(0, retries)):
        payload = "\n".join(f"{k}| {units[k]}" for k in pending)
        hint = None
        if round_no:
            uniq = list(dict.fromkeys(fail_reasons.values()))
            hint = "; ".join(uniq)[:150] or "malformed reply"
        got, fin = _echo_units(system_prompt, payload, context, set(pending),
                               model, endpoint, api_key, sampling, hint=hint)
        state["n_calls"] += 1
        state["retries_used"] += 1 if round_no else 0
        state["truncated"] += 1 if fin == "length" else 0
        if set(got) != set(pending):
            fail_reasons = {k: "malformed reply" for k in pending}
            continue
        new_pending: list[int] = []
        for k in pending:
            new = got[k].strip() if strip else got[k]
            if not new.strip() or new.strip() == units[k].strip():
                continue
            reason = verify(k, new)
            if reason is None:
                accepted[k] = new
            else:
                fail_reasons[k] = reason
                new_pending.append(k)
        pending = new_pending
        if not pending:
            break
    return accepted, pending, fail_reasons, fin


def _run_chunk(
    idx: int,
    total: int,
    chunk: str,
    sep: str,
    system_prompt: str,
    line_prompt: str,
    cell_prompt: str,
    model: str,
    endpoint: str,
    api_key: str,
    sampling: dict | None,
    retries: int,
) -> tuple[str, dict]:
    """Process ONE chunk: structure-aware units + per-unit verification.

    This is the whole per-chunk logic, shared by the sequential and the
    parallel path. Routing (rationale in the module docstring):
      - TOC-like table chunks: deterministic skip, zero calls;
      - prose chunks: one whole-chunk attempt -> deterministic line salvage
        of the candidate -> at most one batched re-ask of the disputed lines;
      - table/mixed chunks: per-row batches of suspect cells (the row itself
        is the context, the skeleton is spliced back untouched) plus one
        line-mode batch for the non-table lines.

    Every unit (chunk, line, cell) is verified with `_verify_pair` (or
    `_verify_chunk` for whole results) before it is applied, so the assembled
    result is safe by construction; a final whole-chunk verification runs as
    belt-and-braces. Chunks are independent: the result text is
    ``verified_chunk + sep`` so reassembly is exact concatenation.

    Returns (result_text, per-chunk stats delta).
    """
    print(f"  llm: chunk {idx}/{total} ({len(chunk)} chars) ...", flush=True)
    chunk_start = time.monotonic()
    o_lines = chunk.split("\n")
    out_lines = list(o_lines)
    units_fixed = 0
    units_total = 0
    units_failed = 0
    cells_sent = 0
    cells_fixed = 0
    reasons: list[str] = []
    state = {"n_calls": 0, "retries_used": 0, "truncated": 0}
    toc_skipped = False

    row_idx = [i for i, l in enumerate(o_lines) if _is_table_row(l)]

    if row_idx and _is_toc_like(o_lines):
        # Deterministic skip: every row duplicates a long cell, so no model
        # output can ever verify — dedup attempts are guaranteed rejections.
        toc_skipped = True
    elif not row_idx:
        # --- prose chunk ---
        candidate, finish = _call_llm(
            system_prompt, chunk, model, endpoint, api_key, sampling=sampling)
        state["n_calls"] += 1
        candidate = _strip_thinking(candidate)
        if finish == "length":
            state["truncated"] += 1
            reasons.append("whole-chunk output truncated (finish_reason=length)")
        if _verify_chunk(chunk, candidate) is None:
            out_lines = candidate.split("\n")
            units_fixed += 1
        else:
            salvaged, fixed, n_total, sreasons, failed_idx = _salvage(chunk, candidate)
            out_lines = salvaged.split("\n")
            units_fixed += fixed
            units_total += n_total
            reasons.extend(sreasons[:2])
            disputed = sorted(i for i in failed_idx if o_lines[i].strip())
            if not disputed and units_fixed == 0:
                # the candidate was useless (empty, garbage, or an unfixed
                # echo with junk): one batched line-mode attempt over every
                # line as the last resort
                disputed = [i for i, l in enumerate(o_lines) if l.strip()]
            if disputed:
                units = {i: o_lines[i] for i in disputed}
                accepted, pending, fr, fin = _verified_rounds(
                    line_prompt, units, None,
                    lambda k, t: _verify_line_in_context(o_lines, k, t),
                    model, endpoint, api_key, sampling, retries, state)
                for i, new in accepted.items():
                    out_lines[i] = new
                    units_fixed += 1
                if pending:
                    units_failed += len(pending)
                    reasons.append(fin if fin and fin.startswith("llm error")
                                   else f"lines {pending[:4]}: {fr[pending[0]]}")
    else:
        # --- table/mixed chunk: cell-level work, skeleton untouched ---
        for i in row_idx:
            line = o_lines[i]
            if _is_separator_row(line):
                continue
            if "\\|" in line:
                # escaped literal pipes: models reliably drop the backslash,
                # which changes the cell structure -> row never sent, skeleton
                # keeps it verbatim
                continue
            segs = _split_row_cells(line)
            if segs is None:
                continue
            cells = [core for _l, core, _t in segs]
            # Cells duplicated within their row (equal to, or contained in,
            # a sibling cell — the extractor sometimes splits a title across
            # two cells) are extraction artifacts: the model reliably tries
            # to deduplicate or reword them, which is a content change, so
            # they are never sent. A duplicated cell is already identical to
            # its sibling — there is nothing to fix in it anyway.
            stripped = [c.strip() for c in cells]
            keys = [re.sub(r"[^0-9a-z]+", "", c.lower()) for c in stripped]

            def _is_dup(k: int) -> bool:
                key = keys[k]
                if len(key) < 8:
                    return False
                return any(j != k and key in other for j, other in enumerate(keys))

            targets = [k for k, c in enumerate(cells)
                       if _suspicious_cell(c) and not _is_dup(k)]
            if not targets:
                continue
            cells_sent += len(targets)
            units = {k: cells[k] for k in targets}
            accepted, pending, fr, fin = _verified_rounds(
                cell_prompt, units, "row: " + line,
                lambda k, t: _verify_pair(cells[k], t),
                model, endpoint, api_key, sampling, retries, state, strip=True)
            repl: dict[int, str] = {}
            for k, new in accepted.items():
                repl[k] = new
                units_fixed += 1
                cells_fixed += 1
            if repl:
                out_lines[i] = _splice_cells(line, segs, repl)
            if pending:
                units_failed += len(pending)
                reasons.append(fin if fin and fin.startswith("llm error")
                               else f"row {i} cell {pending[0]}: {fr[pending[0]]}")
        # non-table lines of a mixed chunk (headings, captions, notes)
        prose_idx = [i for i, l in enumerate(o_lines)
                     if l.strip() and not _is_table_row(l)]
        if prose_idx:
            units = {i: o_lines[i] for i in prose_idx}
            accepted, pending, fr, fin = _verified_rounds(
                line_prompt, units, None,
                lambda k, t: _verify_line_in_context(o_lines, k, t),
                model, endpoint, api_key, sampling, retries, state)
            for i, new in accepted.items():
                out_lines[i] = new
                units_fixed += 1
            if pending:
                units_failed += len(pending)
                reasons.append(fin if fin and fin.startswith("llm error")
                               else f"lines {pending[:4]}: {fr[pending[0]]}")

    result_body = "\n".join(out_lines)
    if result_body != chunk:
        # belt & braces: whatever was assembled must verify as a whole;
        # on any internal inconsistency the original chunk is kept
        final_reason = _verify_chunk(chunk, result_body)
        if final_reason is not None:
            reasons.append(f"internal: final verification failed ({final_reason})")
            result_body = chunk
            units_fixed = 0
            units_failed = max(1, units_failed)

    if toc_skipped:
        delta: dict = {"index": idx, "toc_skipped": True, "accepted": False,
                       "salvaged": False, "rejected": False, "blocks_fixed": 0,
                       "rejection": None}
        result = chunk + sep
    elif units_failed == 0 and units_fixed == 0:
        delta = {"index": idx, "accepted": True, "blocks_fixed": 0,
                 "rejection": None}
        result = result_body + sep
    elif units_failed == 0:
        delta = {"index": idx, "accepted": True, "blocks_fixed": units_fixed,
                 "rejection": None}
        result = result_body + sep
    elif units_fixed > 0:
        delta = {"index": idx, "salvaged": True, "blocks_fixed": units_fixed,
                 "rejection": None}
        result = result_body + sep
    else:
        result = chunk + sep
        reason = "; ".join(reasons[:3]) if reasons else "no usable output"
        delta = {
            "index": idx,
            "rejected": True,
            "blocks_fixed": 0,
            "rejection": {
                "chunk": idx,
                "reason": reason,
                "preview": chunk[:120],
            },
        }
    delta["retries_used"] = state["retries_used"]
    delta["truncated"] = state["truncated"]
    delta["cells_sent"] = cells_sent
    delta["cells_fixed"] = cells_fixed
    delta["duration"] = time.monotonic() - chunk_start
    return result, delta


def _fmt_chunk_state(delta: dict) -> str:
    """One-line final state for a processed chunk: outcome, retries, salvage."""
    if delta.get("toc_skipped"):
        state = "toc-skipped (deterministic)"
    elif delta.get("accepted"):
        state = "accepted"
        if delta.get("blocks_fixed"):
            state += f" ({delta['blocks_fixed']} unit(s) fixed)"
    elif delta.get("salvaged"):
        state = f"salvaged {delta['blocks_fixed']} unit(s)"
    else:
        state = "REJECTED"
        # first rejection reason, trimmed: the progress line must explain WHY
        # without digging into meta.json ('llm error: ...' here also separates
        # verifier rejections from call failures — the latter show retries 0)
        reason = (delta.get("rejection") or {}).get("reason") or ""
        if reason:
            state += f": {reason.split(';')[0][:80]}"
    if delta.get("truncated"):
        state += f", truncated x{delta['truncated']}"
    state += f", retries {delta['retries_used']}"
    return state


def _finish_interrupted(stats: dict) -> None:
    """Ctrl+C path: stop work and abandon the pass entirely.

    A half-corrected document (some chunks fixed, others original) is worse
    than an uncorrected one, so no result is produced: the caller keeps the
    original pre-LLM text. Partial stats travel on LlmInterrupted.
    """
    done = (stats["chunks_accepted"] + stats["chunks_salvaged"]
            + stats["chunks_rejected"] + stats["chunks_toc_skipped"])
    stats["interrupted"] = {
        "chunks_completed": done,
        "chunks_pending": stats["chunks_total"] - done,
    }
    print(
        f"\n  llm: interrupted — {done}/{stats['chunks_total']} chunks were "
        "processed; the uncorrected .md is kept as-is",
        flush=True,
    )
    raise LlmInterrupted(stats)


def _apply_chunk_delta(stats: dict, delta: dict) -> None:
    """Merge one chunk's stats delta into the global stats dict."""
    if delta.get("toc_skipped"):
        stats["chunks_toc_skipped"] += 1
    elif delta.get("accepted"):
        stats["chunks_accepted"] += 1
        stats["blocks_fixed"] += delta["blocks_fixed"]
    elif delta.get("salvaged"):
        stats["chunks_salvaged"] += 1
        stats["blocks_fixed"] += delta["blocks_fixed"]
    elif delta.get("rejected"):
        stats["chunks_rejected"] += 1
        stats["rejections"].append(delta["rejection"])
    stats["cells_sent"] += delta.get("cells_sent", 0)
    stats["cells_fixed"] += delta.get("cells_fixed", 0)
    stats["retries_used"] += delta["retries_used"]
    stats["truncated_calls"] += delta.get("truncated", 0)


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
# Cap on auto-selected workers. Measured on ling-3.0-tiny-np8 (2026-10):
# w4→w8 ≈ 1.75x aggregate throughput (268s vs 470s on an 80-chunk fragment);
# w16 gave no further gain (264s) — the GPU is saturated at ~8 streams.
# The cap only limits auto-selection; --llm-workers overrides it.
_MAX_AUTO_WORKERS = 8


class LlmInterrupted(RuntimeError):
    """The correction pass was stopped by Ctrl+C.

    Carries the partial ``stats`` dict; the caller must treat the original
    (pre-LLM) text as the result — a half-corrected document is worse than
    an uncorrected one, so nothing is written.
    """

    def __init__(self, stats: dict) -> None:
        super().__init__("correction pass interrupted by user")
        self.stats = stats


class _DaemonPool:
    """Fixed pool of daemon worker threads with an unbounded task queue.

    ThreadPoolExecutor is unsuitable here because its worker threads are
    non-daemonic (CPython 3.9+): a Ctrl+C would block interpreter exit for
    up to the 300 s HTTP timeout per in-flight request — the user sees a
    dead console and a flood of tracebacks. Daemon threads die immediately
    at interpreter exit; tasks they had already picked up are simply lost,
    which is exactly the interrupt semantics we want (their chunks fall
    back to the original text).
    """

    def __init__(self, n_workers: int) -> None:
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._pending = 0
        self._error: BaseException | None = None
        self._threads = [
            threading.Thread(target=self._worker, daemon=True,
                             name=f"pdf4llm-llm-{k}")
            for k in range(max(1, n_workers))
        ]
        for t in self._threads:
            t.start()

    def submit(self, fn, *args) -> None:
        self._pending += 1
        self._queue.put((fn, args))

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            fn, args = item
            try:
                fn(*args)
            except BaseException as e:  # reported by drain(), never kills the pool
                if self._error is None:
                    self._error = e
            self._pending -= 1

    def drain_and_shutdown(self) -> None:
        """Wait until every submitted task ran, then stop the workers.

        Re-raises the first worker exception (mirrors Future.result()).
        Polling (not a blocking wait) keeps the main thread's Ctrl+C
        responsive at all times.
        """
        while self._pending > 0:
            time.sleep(0.05)
        self.shutdown_now()
        if self._error is not None:
            raise self._error

    def shutdown_now(self) -> None:
        """Drop everything queued and tell the workers to exit."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        for _ in self._threads:
            self._queue.put(None)


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

    The whole-chunk prose attempt may legitimately produce ~2x its input
    length (measured: alignment/padding rewrites), hence 3x the input
    estimate plus a margin for the system prompt and estimator error.
    """
    in_tokens = math.ceil(max_chunk_chars / _CHARS_PER_TOKEN)
    return 3 * in_tokens + _CTX_MARGIN_TOKENS


def resolve_workers(
    endpoint: str,
    api_key: str,
    model: str,
    max_chunk_chars: int,
    workers: int | None,
    note=None,
) -> tuple[int, dict | None]:
    """Probe llama-swappy; auto-set workers and check the context fit.

    Worker priority: explicit ``workers`` argument > ``min(slots, 8)`` from
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
    max_chars: int = 2000,
    classify: bool = True,
    sampling: dict | None = None,
    retries: int = 2,
    workers: int | None = None,
) -> tuple[str, dict]:
    """Run the guarded LLM correction pass (single strict mode).

    Returns (corrected_text, stats). Structure never passes through the
    model: table chunks are processed at cell level (suspect cells only,
    skeleton spliced back), TOC-like chunks are skipped deterministically,
    prose chunks get one whole-chunk attempt plus line-level salvage and at
    most one batched disputed-line re-ask. Every unit is verified
    algorithmically (canonical whitespace-level edits + numeric tokens +
    table structure) before it is applied; whatever fails stays as the
    original — rejection is always safe, never silent.

    ``max_chars`` is the chunk size; the default (2000) is deliberately small
    so that small local models stay on-task.

    ``workers`` > 1 processes chunks concurrently (daemon thread pool,
    litellm calls are thread-safe). Safety is unaffected: every chunk still
    goes through the same per-unit verification pipeline, chunks are
    independent and the output is reassembled strictly in original order.

    ``workers`` None (default) auto-selects from the llama-swappy info
    endpoint: min(slots, 8), falling back to 1 when the server does not
    self-describe. When the server reports its per-request context, a rough
    input+output estimate for the largest chunk is checked against it and
    the pass is aborted (LlmContextError) when a chunk provably cannot fit.

    Ctrl+C stops the pass instead of tearing it down: pending work is
    cancelled, nothing is written, and LlmInterrupted is raised carrying the
    partial stats — the caller keeps the original (pre-LLM) text.
    """
    text = dedupe_bullets(text)
    text, hr_removed = strip_horizontal_rules(text)
    text, dots_collapsed = collapse_dot_leaders(text)

    is_technical, source = (True, "heuristic")
    if classify:
        is_technical, source = classify_with_llm(
            text, model, endpoint, api_key, sampling=sampling
        )
    system_prompt = TECHNICAL_SYSTEM_PROMPT if is_technical else GENERAL_SYSTEM_PROMPT
    line_prompt = TECHNICAL_LINE_PROMPT if is_technical else GENERAL_LINE_PROMPT
    cell_prompt = TECHNICAL_CELL_PROMPT if is_technical else GENERAL_CELL_PROMPT
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
        "sampling": sampling if sampling else "server defaults",
        "classification": {
            "technical": is_technical,
            "source": source,
        },
        "subscripts_normalised": sub_count,
        "horizontal_rules_removed": hr_removed,
        "dot_leaders_collapsed": dots_collapsed,
        "chunks_total": len(chunks),
        "chunks_accepted": 0,
        "chunks_salvaged": 0,
        "chunks_rejected": 0,
        "chunks_toc_skipped": 0,
        "blocks_fixed": 0,
        "cells_sent": 0,
        "cells_fixed": 0,
        "retries_used": 0,
        "truncated_calls": 0,
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
        try:
            for i, (chunk, sep) in enumerate(chunks, 1):
                result, delta = _run_chunk(
                    i, len(chunks), chunk, sep, system_prompt, line_prompt,
                    cell_prompt, model, endpoint, api_key, sampling, retries,
                )
                out_parts[i - 1] = result
                _apply_chunk_delta(stats, delta)
                chunk_durations.append(delta["duration"])
                # unconditional progress: the LLM pass is slow and the user must
                # see that it is alive, with an ETA based on the avg chunk so far
                if i < len(chunks):
                    eta = (sum(chunk_durations) / len(chunk_durations)) * (len(chunks) - i)
                    print(
                        f"  llm: chunk {i}/{len(chunks)} done "
                        f"[{_fmt_chunk_state(delta)}] in "
                        f"{_fmt_duration(delta['duration'])}  |  elapsed "
                        f"{_fmt_duration(time.monotonic() - t0)}  |  "
                        f"eta ~{_fmt_duration(eta)}",
                        flush=True,
                    )
        except KeyboardInterrupt:
            _finish_interrupted(stats)
            raise  # unreachable, keeps type-checkers happy
    else:
        # Parallel path: daemon worker pool (litellm calls are thread-safe).
        # The pool caps in-flight requests at `workers`, so a huge doc cannot
        # queue unbounded. Each worker merges its own stats delta under a
        # lock; reassembly below is strictly in original chunk order.
        workers = min(workers, len(chunks))
        lock = threading.Lock()
        done_count = [0]

        def _worker(idx: int, chunk: str, sep: str) -> None:
            result, delta = _run_chunk(
                idx, len(chunks), chunk, sep, system_prompt, line_prompt,
                cell_prompt, model, endpoint, api_key, sampling, retries,
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
                f"  llm: {n_done}/{len(chunks)} done "
                f"[{_fmt_chunk_state(delta)}], elapsed "
                f"{_fmt_duration(elapsed)}, eta ~{_fmt_duration(eta)}",
                flush=True,
            )

        pool = _DaemonPool(workers)
        for i, (chunk, sep) in enumerate(chunks, 1):
            pool.submit(_worker, i, chunk, sep)
        try:
            pool.drain_and_shutdown()
        except KeyboardInterrupt:
            pool.shutdown_now()
            _finish_interrupted(stats)
            raise  # unreachable, keeps type-checkers happy

    # deterministic meta.json regardless of completion order
    stats["rejections"].sort(key=lambda r: r["chunk"])
    return "".join(out_parts), stats
