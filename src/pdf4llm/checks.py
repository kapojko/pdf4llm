"""Per-file post-conversion sanity checks (the point of the tool)."""
from __future__ import annotations

import re

HEADING_RE = re.compile(r"^#{1,6} ", re.M)
TABLE_ROW_RE = re.compile(r"^\s*\|", re.M)
HEX_RE = re.compile(r"0x[0-9A-Fa-f]{2,4}")
RES_RE = re.compile(r"\b\d+x\d+\b")
CID_RE = re.compile(r"\(cid:")
REPLACEMENT = "\uFFFD"


def table_column_ratio(text: str) -> float:
    """Fraction of table rows sharing the most common column count."""
    rows = [l for l in text.splitlines() if l.lstrip().startswith("|")]
    if not rows:
        return 0.0
    cols = [l.count("|") for l in rows]
    most = max(set(cols), key=cols.count)
    return sum(1 for c in cols if c == most) / len(cols)


def _score(headings: int, hex_hits: int, cid: int, replacement: int, empty_pages: int) -> int:
    s = 100
    if headings == 0:
        s -= 40
    s -= min(30, cid * 2 + replacement * 2)
    if empty_pages:
        s -= min(20, empty_pages * 2)
    if hex_hits == 0:
        s -= 10
    return max(0, s)


def run_checks(text: str, page_chars: list[int]) -> dict:
    """Return a quality metrics dict + 0-100 score.

    page_chars: per-page character counts from the source PDF (for
    empty / image-only page detection).
    """
    headings = len(HEADING_RE.findall(text))
    table_rows = len(TABLE_ROW_RE.findall(text))
    col_ratio = table_column_ratio(text)
    hex_hits = len(HEX_RE.findall(text))
    res_hits = len(RES_RE.findall(text))
    cid = len(CID_RE.findall(text))
    replacement = text.count(REPLACEMENT)
    empty_pages = sum(1 for c in page_chars if c < 20)
    return {
        "chars": len(text),
        "headings": headings,
        "table_rows": table_rows,
        "table_col_ratio": round(col_ratio, 3),
        "hex_tokens": hex_hits,
        "resolution_tokens": res_hits,
        "cid_tokens": cid,
        "replacement_chars": replacement,
        "empty_pages": empty_pages,
        "score": _score(headings, hex_hits, cid, replacement, empty_pages),
    }
