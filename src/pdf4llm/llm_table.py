"""Table row / cell geometry.

Row splitting on unescaped pipes, cell splicing back into the untouched
skeleton, TOC-like chunk detection and the suspicious-cell pre-filter.
"""
from __future__ import annotations

import re


# a TOC-entry long cell ends with its page number ('Clocks  152'); a
# datasheet description cell ('Standard operating voltage') does not
_PAGE_TAIL_RE = re.compile(r"[.\s]*\d{1,4}\s*$")


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
