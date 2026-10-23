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

import re
import threading
import time

from .llm_chunk import chunk_markdown
from .llm_classify import classify_with_llm
from .llm_client import _call_llm, _strip_thinking
from .llm_prepass import (
    collapse_dot_leaders,
    dedupe_bullets,
    fix_subscripts,
    strip_horizontal_rules,
)
from .llm_prompts import (
    GENERAL_CELL_PROMPT,
    GENERAL_LINE_PROMPT,
    GENERAL_SYSTEM_PROMPT,
    TECHNICAL_CELL_PROMPT,
    TECHNICAL_LINE_PROMPT,
    TECHNICAL_SYSTEM_PROMPT,
)
from .llm_protocol import _verified_rounds
from .llm_salvage import _salvage
from .llm_server import LlmInterrupted, _DaemonPool, resolve_workers
from .llm_table import (
    _is_separator_row,
    _is_table_row,
    _is_toc_like,
    _splice_cells,
    _split_row_cells,
    _suspicious_cell,
)
from .llm_verify import _verify_chunk, _verify_line_in_context, _verify_pair


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
