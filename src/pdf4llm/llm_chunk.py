"""Chunking (line-based, structure-preserving).

Splits Markdown into LLM-sized chunks whose concatenation with their
separators reproduces the input exactly; tables are never cut mid-block.
When a size overflow forces a break, the break is aligned to the last
markdown heading inside the window (the heading opens the NEXT chunk, so a
section always travels with its heading) whenever that does not produce a
degenerately small chunk.
"""
from __future__ import annotations

import re




# ---------------------------------------------------------------------------
# Chunking (line-based, structure-preserving)
# ---------------------------------------------------------------------------

_ATX_HEADING_RE = re.compile(r"#{1,6} \S")


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
        last_heading = None  # break position after the last ATX heading seen
        heading_size = 0     # accumulated size up to and incl. that heading
        while j < n:
            line_len = len(lines[j]) + 1
            if size + line_len > max_chars and j > i:
                # size overflow: prefer a heading-aligned break (the heading
                # then opens the next chunk together with its section) when
                # one exists in-window and leaves a non-degenerate chunk
                if (last_heading is not None and i < last_heading
                        and heading_size >= max_chars * 0.35):
                    j = last_heading
                    sep_extra = 0
                break
            size += line_len
            if _ATX_HEADING_RE.match(lines[j]):
                last_heading = j      # break position AT the heading line:
                heading_size = size   # the heading opens the NEXT chunk
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
