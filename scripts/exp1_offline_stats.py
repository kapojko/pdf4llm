"""Experiment 1: offline (no-LLM) chunk composition statistics for smart-chunk planning.

Classifies chunks from chunk_markdown() into:
  - prose (no table rows)
  - table (>=1 table row)
  - toc-dup (table where a cell duplicates a neighbouring cell -> hopeless for
    the LLM under invariant A, candidate for deterministic skip)
  - mixed (table + prose in one chunk — should not happen per chunker design)

Also: cell counts, "clean cell" heuristic hit rate (cells with nothing to fix),
oversized single lines, and what the output token cap implies.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm.llm_chunk import chunk_markdown
from pdf4llm.llm_prepass import (
    collapse_dot_leaders,
    dedupe_bullets,
    fix_subscripts,
    strip_horizontal_rules,
)

MD = Path("examples/rm0410-stm32f76xxx-and-stm32f77xxx-advanced-armbased-32bit-mcus-stmicroelectronics.md")
MAX_CHARS = 2000

# A cell is "suspicious" (needs LLM) if it contains an intra-word single space
# pattern like 'D-t yp e', 'fli p -flo p': lowercase letter + space + lowercase
# letter inside an alphabetic word context, or similar false splits.
SUSPICIOUS_RE = re.compile(r"[a-z] [a-z]")


def cells_of_row(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def row_has_dup_cells(row: str) -> bool:
    cells = [c for c in cells_of_row(row) if c]
    return len(cells) != len(set(cells)) and len(cells) >= 2


def main() -> None:
    text = MD.read_text(encoding="utf-8")
    text = dedupe_bullets(text)
    text, _hr = strip_horizontal_rules(text)
    text, _dots = collapse_dot_leaders(text)
    text, _subs = fix_subscripts(text)
    chunks = chunk_markdown(text, MAX_CHARS)
    print(f"chunks: {len(chunks)}  (max_chars={MAX_CHARS})")

    kinds = Counter()
    table_chunks = 0
    total_rows = 0
    total_cells = 0
    suspicious_cells = 0
    dup_chunks = 0          # >=1 row with duplicated cells
    all_dup_chunks = 0      # every non-empty row has duplicated cells
    prose_rej_candidates = 0
    oversized_lines = 0

    for chunk, _sep in chunks:
        lines = chunk.split("\n")
        rows = [l for l in lines if l.lstrip().startswith("|")]
        if any(len(l) > MAX_CHARS for l in lines):
            oversized_lines += 1
        if not rows:
            kinds["prose"] += 1
            continue
        table_chunks += 1
        total_rows += len(rows)
        has_dup = False
        all_dup = True
        for row in rows:
            cs = cells_of_row(row)
            total_cells += len(cs)
            for c in cs:
                if SUSPICIOUS_RE.search(c):
                    suspicious_cells += 1
            if row_has_dup_cells(row):
                has_dup = True
            else:
                all_dup = False
        if has_dup:
            dup_chunks += 1
        if all_dup:
            all_dup_chunks += 1
            kinds["toc-dup"] += 1
        else:
            kinds["table"] += 1
        if len(rows) < len(lines):
            kinds["mixed(prose+table)"] += 1

    print(f"prose chunks:            {kinds['prose']}")
    print(f"table chunks:            {table_chunks}  (of which all-dup/TOC-like: {all_dup_chunks})")
    print(f"chunks with >=1 dup row: {dup_chunks}")
    print(f"mixed chunks:            {kinds['mixed(prose+table)']}")
    print(f"oversized-line chunks:   {oversized_lines}")
    print(f"table rows total:        {total_rows}")
    print(f"cells total:             {total_cells}")
    print(f"suspicious cells:        {suspicious_cells} ({suspicious_cells / max(1, total_cells):.1%})")
    print(f"clean cells (skip-able): {total_cells - suspicious_cells} ({1 - suspicious_cells / max(1, total_cells):.1%})")


if __name__ == "__main__":
    main()
