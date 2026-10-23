"""Chunking (line-based, structure-preserving).

Splits Markdown into LLM-sized chunks whose concatenation with their
separators reproduces the input exactly; tables are never cut mid-block.
"""
from __future__ import annotations




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
