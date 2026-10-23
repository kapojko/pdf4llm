"""Deterministic pre-passes (no LLM involved).

Applied before any model call: they remove extraction noise the models
reliably try to "fix" (which would poison chunks) and normalise known
flattened-subscript forms. All of it is deterministic and guarded, so it
cannot corrupt prose.
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
