"""Deterministic pre-passes (no LLM involved).

Applied before any model call: they remove extraction noise the models
reliably try to "fix" (which would poison chunks) and restore source forms
the converter garbled (spaced underscores, flattened subscript terms). All
of it is deterministic and guarded, and nothing here inserts characters the
source does not attest — cleanup must not introduce new entities.
"""
from __future__ import annotations

import re


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
    """Remove '•' (U+2022) glyphs that duplicate a Markdown list marker.

    In this document family '•' is always the TOP-level bullet glyph, so a
    '•' right after the '- ' marker is an extraction artifact and its
    deletion is always right (both with and without a preceding list item).
    En/em dashes are NOT handled here — they are the level-2 bullet glyph,
    so 'marker + dash' needs list CONTEXT; see :func:`fix_dash_bullets`.
    Only the LEAD position is touched — a glyph at line END is ambiguous
    (ranges, 'see 3–') and is left alone.
    """
    text = _BULLET_LEAD_RE.sub(r"\1 ", text)
    text = _BULLET_TRAIL_RE.sub(r"\1", text)
    return text


# ---------------------------------------------------------------------------
# Deterministic pre-pass: marker + en/em dash bullet repair (no LLM).
# PDF lists are two-level: '•' bullets at top level, '–'/'—' bullets one
# level deeper. The converter emits the markdown marker AND keeps the PDF
# glyph, producing '- –   text' — which reads as a double bullet, and every
# model 'fixes' it by deleting the marker (a content change -> invariant-A
# rejection; SAM9X60: 554 lines, unfixable by any model). The real repair
# depends on list context:
#   previous list item is another marker+dash line -> SAME level as it
#     (inherit its disposition: nested runs stay nested, flat runs stay flat);
#   previous line is any other list item -> NEST one level under it
#     ('- Parent:' then '- –   child' becomes '  - child');
#   otherwise (paragraph/heading/table) -> top-level '–' list -> FLATTEN
#     (delete the glyph: '- –   text' becomes '- text').
# The dash must be followed by whitespace: '- -5' (negative number), ranges
# and '– – – –' separator lines never match (0 occurrences in SAM9X60).
# Whitespace/glyph edits only — words and digits are physically untouched.
# Runs AFTER strip_horizontal_rules: page-break '---' artifacts split lists,
# and with them gone the nearest non-blank line is the true list context.
# ---------------------------------------------------------------------------

_DASH_BULLET_RE = re.compile(r"^(\s*)([-*+])[ \t]+[\u2013\u2014][ \t]+(\S.*)$")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])[ \t]+\S")


def fix_dash_bullets(text: str) -> tuple[str, int]:
    """Repair 'marker + en/em dash' bullet lines (nested-list artifacts).

    Returns (text, repaired_line_count). See the block comment above for
    the rule; the previous non-blank line decides, and a dash line that
    FOLLOWS a dash line inherits that line's disposition so runs stay at a
    consistent level across hr/blank interruptions.
    """
    lines = text.split("\n")
    out: list[str] = []
    n = 0
    last_indent: str | None = None  # None = flattened, else nested indent
    last_dash_idx = -1              # index in `out` of the last repaired line
    for line in lines:
        m = _DASH_BULLET_RE.match(line)
        if m:
            mark, rest = m.group(2), m.group(3)
            prev_idx = next((len(out) - 1 - k for k, l in enumerate(reversed(out))
                             if l.strip()), -1)
            if prev_idx == last_dash_idx:
                indent = last_indent            # sibling: inherit level
            elif prev_idx >= 0 and _LIST_ITEM_RE.match(out[prev_idx]):
                prev = out[prev_idx]
                pind = len(prev) - len(prev.lstrip())
                indent = prev[:pind] + "  "     # child of the parent item
                last_indent = indent
            else:
                indent = None                   # top-level dash list
                last_indent = None
            out.append(f"{mark} {rest}" if indent is None
                       else f"{indent}{mark} {rest}")
            last_dash_idx = len(out) - 1
            n += 1
            continue
        out.append(line)
    return "\n".join(out), n


# ---------------------------------------------------------------------------
# Deterministic pre-pass: '<br>' split-word joins (no LLM involved).
# PDF extraction leaves '<br>' where a visual line broke inside one word
# ('Co<br>ntrol'). When the next character is lowercase, the join is
# mechanical and document-independent — it is what '<br>' MEANS in a split
# word ('over<br>view' -> 'overview', 'R<br>es .' -> 'Res .'). Ambiguous
# cases (uppercase/digit after the tag, e.g. 'Control<br>Register') are NOT
# joined here; those lines are sent to the model as batched units, gated by
# the invariant-A '<br>' projection in llm_verify.
# ---------------------------------------------------------------------------

_BR_SPLIT_RE = re.compile(r"([A-Za-z])(?i:<br\s*/?>)(?=[a-z])")


def fix_br_word_splits(text: str) -> tuple[str, int]:
    """Join '<br>'-split words where the next char is lowercase (mechanical).

    Returns (text, joined_tag_count). Only the unambiguous class is touched;
    every remaining '<br>' stays for the model pass.
    """
    return _BR_SPLIT_RE.subn(r"\1", text)


def has_residual_br(text: str) -> bool:
    """True if any '<br>' tag survived the mechanical pre-pass.

    Such lines are always admitted to the model pass (the vocabulary filter
    has no join candidates for them and would otherwise skip the only fix).
    """
    return bool(_BR_TAG_SEARCH_RE.search(text))


_BR_TAG_SEARCH_RE = re.compile(r"(?i)<br\s*/?>")


# ---------------------------------------------------------------------------
# Deterministic pre-pass: subscript term joining (no LLM involved).
# PDF extraction flattens subscript typography: V with a small 'CC' becomes
# 'V CC', T with 'amb' becomes 'T amb'. This pass joins a quantity symbol
# with its subscript ONLY when the joined form already occurs in THIS
# document ('V CC' -> 'VCC' iff the token 'VCC' appears elsewhere): the
# document's own usage is the evidence that the joined spelling is the
# intended one. Everything else is left EXACTLY as extracted.
#
# No underscores are ever inserted. 'T_amb' is a notation the source never
# used — an insertion is an irreversible bet that violates the pipeline's
# prime rule (cleanup must not introduce new entities). Measured on
# SAM9X60: ~17% of insertions were misfires ('f l a g' -> 'f_l a g' broke
# common prose words the LLM stage could then no longer repair), and the
# joined forms they were meant to produce ('VCC', 'Tamb') are equally
# readable for the LLM consumer. Leftover spaced pairs ('T amb') are
# whitespace-only fixable by the LLM stage wherever it sees them.
#
# Deterministic + guarded: prefix/suffix whitelists, English-stopword
# filter, in-document evidence for every join — prose like 'I do' or
# 'a few' can never be rewritten, and neither can debris ('C LU' stays:
# 'CLU' never occurs in the document).
# ---------------------------------------------------------------------------

_SUB_PAIR_RE = re.compile(r"(?<![A-Za-z_\-])([A-Za-z]) ([A-Za-z][A-Za-z0-9+]{0,3}(?:\+\d+)?)\b")

# Document token pattern, shared with the DocVocab SEND/SKIP filter
# (re-exported from llm_batch): identifier-like tokens, '_' kept so that
# register names ('SDRAMC_WPSR') count as one token.
_VOCAB_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9-]*")

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
    """Return the candidate joined 'prefixSuffix' term, or None.

    Only uppercase suffixes of 2+ letters are candidates ('V CC' -> 'VCC',
    'V IH' -> 'VIH', 't PLH' -> 'tPLH', 'I EEE' -> 'IEEE'); lowercase,
    mixed and single-letter suffixes are never rewritten.
    """
    if prefix not in _SUB_PREFIXES and prefix != "I":
        return None  # prefix is not a known quantity symbol -> leave alone
    if prefix in {"A", "a", "i"}:
        return None  # article/pronoun readings dominate
    if suffix.lower() in _SUB_STOPWORDS:
        return None
    if suffix.isupper() and len(suffix) >= 2:
        return f"{prefix}{suffix}"
    return None  # mixed/lowercase/single-letter suffix: leave as extracted


def fix_subscripts(text: str) -> tuple[str, int]:
    """Join flattened subscript terms attested by this document's usage.

    'V CC' -> 'VCC' only when the token 'VCC' occurs (as written) elsewhere
    in the document; everything else — including 'T amb'-style pairs with no
    joined precedent — is left unchanged. Never inserts new characters.
    Returns (text, join_count).
    """
    evidence = set(_VOCAB_TOKEN_RE.findall(text))
    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        form = _sub_form(m.group(1), m.group(2))
        if form is None or form not in evidence:
            return m.group(0)
        count += 1
        return form

    return _SUB_PAIR_RE.sub(repl, text), count


# ---------------------------------------------------------------------------
# Deterministic pre-pass: spaced underscores (no LLM involved).
# PDF text extraction inserts false spaces around '_' inside register and
# signal names ('SDRAMC _ WPSR' for SDRAMC_WPSR, 'R8 _ USB _ CTRL'). The
# underscore itself is real — only the spaces are artifacts — so joining
# them is a whitespace-only restoration of the source form, never an edit
# of content (the invariant-A projection treats the two as identical).
# Guarded: a single '_' with word characters on BOTH sides is joined;
# one-sided variants ('A_ B', 'A _B') and bare underscore runs ('___') are
# left alone — unmeasured, and a one-sided join would also rewrite
# extraction debris the LLM stage should see unchanged.
# ---------------------------------------------------------------------------

_SPACED_UNDERSCORE_RE = re.compile(r"(?<=[A-Za-z0-9]) +_ +(?=[A-Za-z0-9])")


def fix_spaced_underscores(text: str) -> tuple[str, int]:
    """Join false spaces around '_' between word characters ('A _ B' -> 'A_B').

    Returns (text, joined_gap_count).
    """
    return _SPACED_UNDERSCORE_RE.subn("_", text)
