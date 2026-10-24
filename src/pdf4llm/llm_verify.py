"""Algorithmic verification (single strict mode) — the safety gate.

Invariant A: input and output are identical after whitespace-stripping
and canonicalisation — whitespace edits plus a CLOSED set of
bidirectional typographic normalisations, nothing else. The canonical map
never touches [0-9A-Za-z_], so register names, constants and words are
physically immutable. The numeric-token check blocks whitespace merges
that corrupt values ('2 0' -> '20', '-40' -> '40'). Invariant B: table
rows keep their cell count; edits are checked per cell.

'<br>' split-marker edit class: PDF extraction leaves '<br>' where a
visual line broke inside one word ('Co<br>ntrol'). The invariant-A
projection strips all '<br>' tags from both sides, so replacing a
'<br>' with '' or ' ' is accepted while every other edit of the tag
(deleting surrounding letters, swapping it for '-') stays rejected.
The numeric-token check deliberately does NOT see the projection (a
'<br>' inside a number keeps its tokens split), so a '<br>' can never
smuggle a '2 0' -> '20' merge through.
"""
from __future__ import annotations

import re

from .llm_table import _is_table_row


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

# '<br>' split-marker edit class (see module docstring): stripped in the
# invariant-A projection only — never in the numeric-token projection.
_BR_TAG_RE = re.compile(r"(?i)<br\s*/?>")

# escaped pipes are a markdown-table artifact ('\|' renders as '|'); models
# reliably unescape them, which must not count as a content change
_ESCAPED_PIPE_RE = re.compile(r"\\\|")


def canonicalize(text: str) -> str:
    """Map typographic glyph variants to one canonical form (see above)."""
    return _ESCAPED_PIPE_RE.sub("|", _CANON_RE.sub(lambda m: _CANON_SUBS[m.group(0)], text))


def _ws_canon(text: str) -> str:
    """Whitespace-stripped canonical form (the invariant-A projection).

    Includes the '<br>' split-marker projection: the tag is removed before
    comparison, so 'Co<br>ntrol' -> 'Control' and -> 'Co ntrol' both verify
    while any other edit of the tag stays rejected.
    """
    return canonicalize("".join(_BR_TAG_RE.sub("", text).split()))


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


def _verify_line_in_context(o_lines: list[str], idx: int, c_line: str) -> str | None:
    """Verify a single-line replacement with neighbouring lines as context."""
    prev = o_lines[idx - 1] if idx > 0 else ""
    nxt = o_lines[idx + 1] if idx + 1 < len(o_lines) else ""
    ctx_o = prev + "\n" + o_lines[idx] + "\n" + nxt
    ctx_c = prev + "\n" + c_line + "\n" + nxt
    return _verify_pair(ctx_o, ctx_c)
