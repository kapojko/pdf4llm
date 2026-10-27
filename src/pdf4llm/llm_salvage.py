"""Line/block-level salvage from rejected whole-chunk candidates.

Every surviving line is independently verified, so the salvaged text is
safe by construction even when the candidate was hallucinated.
"""
from __future__ import annotations

import difflib

from .llm_table import _is_table_row
from .llm_verify import _verify_line_in_context, _verify_pair


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
    failed_orig_indices, line_map) where failed_orig_indices are the 0-based
    original line numbers the candidate tried to change (or dropped) without
    passing verification — the input for the batched disputed-line re-ask —
    and line_map[i] is the index of original line i in the returned text's
    lines, or None when the line was merged into an accepted multi-line block
    (no safe standalone apply position for a later fix).
    """
    o_lines = orig.split("\n")
    c_lines = cand.split("\n")
    sm = difflib.SequenceMatcher(None, o_lines, c_lines, autojunk=False)
    out_lines: list[str] = []
    reasons: list[str] = []
    failed: set[int] = set()
    line_map: list[int | None] = [None] * len(o_lines)
    fixed = 0
    total = 0

    def emit(o_idx: int, line: str) -> None:
        # append one output line and record where original line o_idx landed
        line_map[o_idx] = len(out_lines)
        out_lines.append(line)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                emit(k, o_lines[k])
            continue
        o_blk = o_lines[i1:i2]
        c_blk = c_lines[j1:j2]
        if len(o_blk) == len(c_blk):
            for k, (o_line, c_line) in enumerate(zip(o_blk, c_blk)):
                if o_line == c_line:
                    emit(i1 + k, o_line)
                    continue
                total += 1
                if not c_line.strip():
                    emit(i1 + k, o_line)
                    failed.add(i1 + k)
                    continue
                if _is_table_row(o_line) or _is_table_row(c_line):
                    reason = _verify_pair(o_line, c_line)
                else:
                    reason = _verify_line_in_context(o_lines, i1 + k, c_line)
                if reason is None:
                    emit(i1 + k, c_line)
                    fixed += 1
                else:
                    reasons.append(reason)
                    failed.add(i1 + k)
                    emit(i1 + k, o_line)
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
                continue  # merged originals keep line_map[i] = None
            pairs = _pair_by_similarity(o_blk, c_blk)
            for k, o_line in enumerate(o_blk):
                j = pairs.get(k)
                c_line = c_blk[j] if j is not None else None
                if c_line is None or o_line == c_line:
                    emit(i1 + k, o_line)
                    if c_line is None and o_line.strip():
                        failed.add(i1 + k)   # candidate dropped this line
                    continue
                total += 1
                if not c_line.strip():
                    emit(i1 + k, o_line)
                    failed.add(i1 + k)
                    continue
                abs_idx = i1 + k
                if _is_table_row(o_line) or _is_table_row(c_line):
                    reason = _verify_pair(o_line, c_line)
                else:
                    reason = _verify_line_in_context(o_lines, abs_idx, c_line)
                if reason is None:
                    emit(abs_idx, c_line)
                    fixed += 1
                else:
                    reasons.append(reason)
                    failed.add(abs_idx)
                    emit(abs_idx, o_line)
    return "\n".join(out_lines), fixed, total, reasons, failed, line_map
