"""Optional local-LLM broken-text correction pass (single strict mode).

Design (safety-first):

1. Classification (technical vs general) picks only the *prompt* — never the
   safety rules. LLM classifier on the document head; keyword heuristic
   fallback; any ambiguity/error defaults to the strict technical prompt.
2. Deterministic pre-passes (no LLM involved) remove known extraction noise
   the models reliably try to "fix" and thereby poison chunks with:
   horizontal rules, TOC dot leaders, duplicate bullet glyphs; plus guarded
   subscript normalisation ('V CC' -> 'VCC', 'T amb' -> 'T_amb') and
   mechanical '<br>' split-word joins ('Co<br>ntrol' -> 'Control').
3. Structure never passes through the model:
   - table chunks are processed at cell level: only cells whose content looks
     defect-suspect are sent (deterministic pre-filter; ~90% of cells are
     skipped), each batch with its row as context; the row skeleton (pipes,
     padding, separator rows) is spliced back untouched;
   - TOC-like chunks (every row duplicates a long cell) are skipped
     deterministically: no model output can ever verify against them;
   - prose chunks get ONE whole-chunk attempt (the only unit that can join
     falsely split lines), then a deterministic line-level salvage of the
     candidate; disputed lines are re-asked as batched units.
4. Cross-chunk batch aggregation (llm_batch): the verification unit (cell or
   line) is decoupled from the request unit. Suspect units from ALL chunks
   are collected into kind-separated global queues and packed into batched
   echo requests ('N| text', ~5k chars of fragments per call). A failed unit
   is never retried in place: it is requeued to the END of its queue with
   its rejection reason, up to ``llm_retries`` extra attempts, and the next
   batch carries the reason as a per-unit NOTE line. Exhausted retries keep
   the original text — rejection is always safe, never silent.
5. Every model output is verified algorithmically before any part of it is
   accepted: canonical/whitespace-level edits only (typographic punctuation
   classes — dashes, quotes, bullets, ellipsis — accepted in either direction
   via a closed canonical map; '<br>' split-marker removal as a narrowed edit
   class), numeric-token protection, table structure checks. Words and
   numbers are physically immutable. Whatever fails verification is kept as
   the original; per-chunk outcomes are logged into meta.json.

A per-document word-frequency map (DocVocab) gates WHICH suspect units are
sent: fragments whose suspicious join form never occurs in the document are
skipped (probably legitimate spacing). The vocabulary never edits text.
"""
from __future__ import annotations

import json
import re
import threading
import time
from types import SimpleNamespace

from . import llm_classify, llm_protocol
from .llm_batch import BATCH_TOKENS, BatchScheduler, ChunkState, DocVocab
from .llm_chunk import chunk_markdown
from .llm_classify import classify_with_llm
from .llm_client import _call_llm, _strip_thinking
from .llm_prepass import (
    collapse_dot_leaders,
    dedupe_bullets,
    fix_br_word_splits,
    fix_dash_bullets,
    fix_spaced_underscores,
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
from .llm_salvage import _salvage
from .llm_server import LlmInterrupted, _DaemonPool, resolve_workers
from .progress import _fmt_duration
from .llm_table import (
    _is_separator_row,
    _is_table_row,
    _is_toc_like,
    _split_row_cells,
    _suspicious_cell,
    dup_cell_indices as _dup_cell_indices,
)
from .llm_tokens import TokenMeter
from .llm_verify import _verify_chunk


# ---------------------------------------------------------------------------
# Chunk producers (run in the worker pool; units go to the scheduler queues)
# ---------------------------------------------------------------------------


def _produce_chunk(sched: BatchScheduler, cfg: SimpleNamespace, idx: int) -> None:
    """Scan ONE chunk deterministically and enqueue its suspect units.

    Prose chunks additionally get their one whole-chunk attempt here (the
    only unit that can join falsely split lines); its disputed lines are
    enqueued as line units. Table/mixed chunks contribute suspect cells
    (row as context) plus vocabulary-admitted prose lines. TOC-like chunks
    are skipped deterministically. No unit is ever sent from here — the
    batch scheduler owns all requests.
    """
    cs = sched.states[idx]
    chunk = cs.chunk
    o_lines = cs.o_lines
    try:
        if not chunk.strip():
            # whitespace-only chunk (e.g. leading blank lines): nothing to
            # correct, never send it to the model (a whole-chunk attempt on
            # empty input is a wasted request the verifier rejects anyway)
            return
        row_idx = [i for i, l in enumerate(o_lines) if _is_table_row(l)]
        if row_idx and _is_toc_like(o_lines):
            cs.toc_skipped = True
            return
        if not row_idx:
            _produce_prose(sched, cfg, cs, chunk)
        else:
            _produce_table(sched, cfg, cs, chunk, row_idx)
    finally:
        cs.produced = True
        sched.producer_done()


def _produce_prose(sched: BatchScheduler, cfg: SimpleNamespace, cs: ChunkState,
                   chunk: str) -> None:
    """Whole-chunk attempt -> deterministic line salvage -> disputed units."""
    o_lines = cs.o_lines
    echo_tokens = cfg.meter.count(chunk)
    cap = cfg.meter.cap_for("chunk", echo_tokens)
    sink: dict = {}
    candidate, finish = _call_llm(
        cfg.system_prompt, chunk, cfg.model, cfg.endpoint, cfg.api_key,
        sampling=cfg.sampling, output_cap_tokens=cap, usage_sink=sink)
    with sched.lock:
        cfg.stats["wholechunk_attempts"] += 1
        cfg.meter.record("chunk", echo_tokens, sink)
    candidate = _strip_thinking(candidate)
    if finish == "length":
        cs.truncated += 1  # merged into truncated_calls at finalize
        with sched.lock:
            cfg.stats["truncated_api_calls"] += 1
        cs.note_reason("whole-chunk output truncated (finish_reason=length)")
    if _verify_chunk(chunk, candidate) is None:
        # whole-chunk accepted: the producer returns immediately, so no line
        # units are ever enqueued for this chunk afterwards (identity map)
        cs.set_out_lines(candidate)
        cs.units_fixed += 1
        with sched.lock:
            cfg.stats["wholechunk_accepted"] += 1
            if len(cs.out_lines) != len(o_lines):
                # the whole-chunk call's UNIQUE yield: a cross-line join
                cfg.stats["wholechunk_linejoin_fixes"] += 1
        return
    salvaged, fixed, n_total, sreasons, failed_idx, line_map = _salvage(
        chunk, candidate)
    cs.set_out_lines(salvaged, line_map)
    cs.units_fixed += fixed
    cs.units_total += n_total
    for r in sreasons[:2]:
        cs.note_reason(r)
    disputed = sorted(i for i in failed_idx if o_lines[i].strip())
    if not disputed and cs.units_fixed == 0:
        # the candidate was useless (empty, garbage, or an unfixed echo with
        # junk): one batched line-mode attempt over every line as the last
        # resort (targeted re-asks: NOT gated by the vocabulary filter)
        disputed = [i for i, l in enumerate(o_lines) if l.strip()]
    # lines merged into an accepted join have no standalone output position
    # (their text already lives inside the merged line): skip them rather
    # than enqueue a fix that could not be applied safely
    disputed = [i for i in disputed if cs.out_index(i) is not None]
    for i in disputed:
        sched.enqueue_line(cs.index, i, o_lines[i])


def _produce_table(sched: BatchScheduler, cfg: SimpleNamespace, cs: ChunkState,
                   chunk: str, row_idx: list[int]) -> None:
    """Suspect cells (row context) + vocabulary-admitted prose lines."""
    o_lines = cs.o_lines
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
        # Cells duplicated within their row (see dup_cell_indices) are
        # extraction artifacts: the model reliably tries to deduplicate or
        # reword them, which is a content change, so they are never sent.
        dups = _dup_cell_indices(cells)
        targets = [k for k, c in enumerate(cells)
                   if _suspicious_cell(c) and k not in dups]
        for k in targets:
            if cfg.vocab.admits(cells[k]):
                sched.enqueue_cell(cs.index, i, k, cells[k], line)
            else:
                # joined form never occurs in this document: probably
                # legitimate spacing -> skip (saves a call and avoids
                # 'helpful' rewrites that only produce rejection risk)
                sched.skip_unit(cs.index)
    # non-table lines of a mixed chunk (headings, captions, notes)
    prose_idx = [i for i, l in enumerate(o_lines)
                 if l.strip() and not _is_table_row(l)]
    for i in prose_idx:
        if cfg.vocab.admits(o_lines[i]):
            sched.enqueue_line(cs.index, i, o_lines[i])
        else:
            sched.skip_unit(cs.index)


# ---------------------------------------------------------------------------
# Stats plumbing
# ---------------------------------------------------------------------------


def _fmt_chunk_state(delta: dict) -> str:
    """One-line final state for a processed chunk: outcome, requeues."""
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
        # first rejection reason, trimmed: the line must explain WHY without
        # digging into meta.json ('llm error: ...' here also separates
        # verifier rejections from call failures)
        reason = (delta.get("rejection") or {}).get("reason") or ""
        if reason:
            state += f": {reason.split(';')[0][:80]}"
        state += ", no-recovery"
        if delta.get("retries_used"):
            state += f" after {delta['retries_used']} requeue(s)"
    if delta.get("truncated"):
        state += f", truncated x{delta['truncated']}"
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


# ---------------------------------------------------------------------------
# Rescue pass (second-model salvage for exhausted units)
# ---------------------------------------------------------------------------


def normalize_rescue(spec) -> list[dict]:
    """Normalize the ``llm_rescue`` config/CLI spec into level dicts.

    Accepts None/[]/"" (no rescue), a model name (one level, default
    ceiling 0.5), or a list of model names / {"model": ..., "max_fraction":
    ...} dicts. Malformed entries raise ValueError — a silently ignored
    rescue config would look like a working one.
    """
    if spec is None:
        return []
    if isinstance(spec, str):
        spec = [spec]
    if not isinstance(spec, list):
        raise ValueError(
            "llm_rescue must be a model name or a list of "
            "{model, max_fraction} levels")
    levels: list[dict] = []
    for item in spec:
        if isinstance(item, str):
            levels.append({"model": item, "max_fraction": 0.5})
        elif isinstance(item, dict) and item.get("model"):
            levels.append({"model": str(item["model"]),
                           "max_fraction": float(item.get("max_fraction", 0.5))})
        else:
            raise ValueError(f"bad llm_rescue level: {item!r}")
    return [lv for lv in levels if lv["model"]]


def _rescue_stats() -> dict:
    """Fresh per-level stats dict with every key the scheduler touches."""
    return {
        "units_sent": 0,
        "units_fixed": 0,
        "units_failed": 0,
        "units_requeued": 0,
        "units_fixed_after_requeue": 0,
        "units_inferred_missing": 0,
        "batches": 0,
        "truncated_api_calls": 0,
        "replies_renumbered": 0,
        "units_renumbered_recovered": 0,
        "unit_fail_log": [],
        "truncation_log": [],
    }


def _run_rescue(states, prompts, vocab, levels, *, endpoint, api_key,
                sampling, stats, lock, workers, note, verbose, batch_tokens,
                prev_failed) -> int:
    """Rescue passes: re-ask final-failed units on the next configured model.

    Runs AFTER the main pass drained. Each level fires only when there is
    something to rescue AND the failure fraction is within its ceiling
    (max_fraction, fraction of the main pass's units_sent); the model switch
    happens server-side on the level's first request. One single pass per
    level (retries=0): the value is model diversity, not more attempts —
    measured on SAM9X60 (2026-10): same-model requeue salvage is ~6.5% per
    round, while a fresh diverse model fixes ~53% of the exhausted tail in
    one pass (probe: ornith-1.5-9b 87-88/163, nemotron-74b 87/163). Every
    unit still passes the normal verifier; a unit that fails on the rescue
    model too is final (original text kept). Sampling is never overridden.

    Returns the number of units rescued (applied fixes on previously failed
    units); per-level blocks land in ``stats['rescue']``.
    """
    from .llm_batch import _FAIL_LOG_CAP

    blocks: list[dict] = []
    skipped: list[dict] = []
    pool_units = list(prev_failed)
    rescued_total = 0
    for li, level in enumerate(levels, 1):
        rmodel = level["model"]
        max_fraction = float(level.get("max_fraction", 0.5))
        n = len(pool_units)
        if n == 0:
            skipped.append({"model": rmodel, "reason": "no failed units"})
            break
        fraction = n / max(1, stats["units_sent"])
        if fraction > max_fraction:
            skipped.append({
                "model": rmodel,
                "reason": f"failed fraction {fraction:.3f} exceeds "
                          f"max_fraction {max_fraction}",
            })
            continue
        note(
            f"  llm: rescue {li}/{len(levels)}: model {rmodel}, {n} failed "
            f"unit(s) ({fraction:.1%} of sent) — first call may stall while "
            "the server loads the model",
        )
        rstats = _rescue_stats()
        rsched = BatchScheduler(
            states, prompts, vocab, model=rmodel, endpoint=endpoint,
            api_key=api_key, sampling=sampling, retries=0, stats=rstats,
            lock=lock, pool=_DaemonPool(workers), note=note,
            batch_tokens=batch_tokens,
            meter=TokenMeter(rmodel, endpoint, api_key), verbose=verbose,
        )
        with lock:
            for u in pool_units:
                u.attempts = 0  # fresh SINGLE attempt on this model
                # u.last_fail stays: the NOTE hint carries the reason the
                # previous model finally rejected this unit
                rsched.queues[u.kind].append(u)
                states[u.chunk].units_enqueued += 1
                rstats["units_sent"] += 1
            # no producers: pure drain of the pre-loaded queues
            rsched.producers_done = rsched.producers_total
        t_level = time.monotonic()
        try:
            rsched.run()
            rsched.stop_progress()
            rsched.pool.drain_and_shutdown()
        except KeyboardInterrupt:
            rsched.pool.shutdown_now()
            rsched.stop_progress()
            _finish_interrupted(stats)
            raise  # unreachable, keeps type-checkers happy
        # a rescued unit is no longer failed: undo the finalize-time failure
        # accounting so chunk classification reflects the post-rescue state
        # (_process_batch already added the fix to cs.units_fixed)
        applied_gids = {u.gid for u in rsched.applied}
        with lock:
            for u in pool_units:
                if u.gid in applied_gids:
                    states[u.chunk].units_failed -= 1
                    rescued_total += 1
        for e in rstats["unit_fail_log"]:
            if len(stats["unit_fail_log"]) < _FAIL_LOG_CAP:
                stats["unit_fail_log"].append(e)
        blocks.append({
            "model": rmodel,
            "units_sent": rstats["units_sent"],
            "units_fixed": len(rsched.applied),
            "units_failed": rstats["units_failed"],
            "batches": rstats["batches"],
            "truncated_calls": rstats["truncated_api_calls"],
            "duration": round(time.monotonic() - t_level, 1),
            "tokens": rsched.meter.meta(),
        })
        note(
            f"  llm: rescue {li}: {rstats['units_fixed']} of {n} failed "
            f"unit(s) fixed in {_fmt_duration(time.monotonic() - t_level)}",
        )
        pool_units = rsched.final_failed
    stats["rescue"] = {"levels": blocks, "skipped": skipped}
    return rescued_total


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
    stats["retries_used"] += delta.get("retries_used", 0)
    stats["truncated_calls"] += delta.get("truncated", 0)
    stats["units_skipped"] += delta.get("units_skipped", 0)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


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
    batch_tokens: int | None = None,
    keep_prellm: str | None = None,
    capture_path: str | None = None,
    rescue: list[dict] | None = None,
) -> tuple[str, dict]:
    """Run the guarded LLM correction pass (single strict mode).

    ``keep_prellm`` writes the post-prepass markdown (the EXACT text the
    pass chunks; meta's chunk_offsets refer to it) to the given path.
    ``capture_path`` appends every LLM request/reply pair (full payloads,
    replies, finish reason, token usage) to a JSONL transcript — the raw
    material for offline replay / rescue-pass experiments. Both are
    opt-in; ordinary runs write only the corrected .md and meta.json.
    ``rescue`` (optional) is a normalized level list (see normalize_rescue):
    after the main pass, units that failed all retries are re-asked ONCE on
    each configured rescue model whose failure-fraction ceiling allows it.
    """
    real_call = _call_llm
    capture_fh = None
    if capture_path:
        capture_fh = open(capture_path, "w", encoding="utf-8")

        def capturing(system, user, *a, **kw):
            t0 = time.monotonic()
            reply, finish = real_call(system, user, *a, **kw)
            sink = kw.get("usage_sink") or {}
            capture_fh.write(json.dumps({
                "system": system, "user": user,
                "cap_tokens": kw.get("output_cap_tokens"),
                "reply": reply, "finish": finish,
                "prompt_tokens": sink.get("prompt_tokens"),
                "completion_tokens": sink.get("completion_tokens"),
                "dt": round(time.monotonic() - t0, 2),
            }, ensure_ascii=False) + "\n")
            capture_fh.flush()
            return reply, finish

        _set_transport(capturing)
    try:
        return _correct_with_llm(
            text, model, endpoint, api_key, verbose, max_chars, classify,
            sampling, retries, workers, batch_tokens, keep_prellm, rescue)
    finally:
        if capture_fh is not None:
            _set_transport(real_call)
            capture_fh.close()


def _set_transport(fn) -> None:
    """Point every module-level transport reference at ``fn`` (and back)."""
    globals()["_call_llm"] = fn
    llm_protocol._call_llm = fn
    llm_classify._call_llm = fn


def _correct_with_llm(
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
    batch_tokens: int | None = None,
    keep_prellm: str | None = None,
    rescue: list[dict] | None = None,
) -> tuple[str, dict]:
    """Run the guarded LLM correction pass (single strict mode).

    Returns (corrected_text, stats). Structure never passes through the
    model: table chunks are processed at cell level (suspect cells only,
    skeleton spliced back), TOC-like chunks are skipped deterministically,
    prose chunks get one whole-chunk attempt plus line-level salvage of the
    candidate. Suspect units from all chunks are batched across chunk
    boundaries (kind-separated, ~5k fragment chars per call) and every unit
    is verified algorithmically before it is applied; failures are requeued
    up to ``retries`` extra attempts with a per-unit rejection hint, and
    whatever still fails stays as the original — rejection is always safe,
    never silent.

    ``max_chars`` is the chunk size; the default (2000) is deliberately small
    so that small local models stay on-task.

    ``workers`` > 1 runs chunk producers and batch requests concurrently
    (daemon thread pool, litellm calls are thread-safe). Safety is
    unaffected: every unit still goes through the same verification
    pipeline, chunks are independent and the output is reassembled strictly
    in original order.

    ``batch_tokens`` overrides the fragment-token volume packed into one
    batched echo request (default: llm_batch.BATCH_TOKENS). Fragment tokens
    are counted by the server's own tokenizer (llama-swappy /llama/tokenize)
    when reachable, else the naive 1 char = 1 token estimate.

    ``workers`` None (default) runs a single worker: one batched request
    already saturates the server's decode (benchmarked; --llm-workers
    overrides). The llama-swappy probe still provides the per-request
    context check: a rough input+output estimate for the largest chunk is
    compared against the reported contextSize and the pass is aborted
    (LlmContextError) when a chunk provably cannot fit.

    Ctrl+C stops the pass instead of tearing it down: pending work is
    cancelled, nothing is written, and LlmInterrupted is raised carrying the
    partial stats — the caller keeps the original (pre-LLM) text.
    """
    text = dedupe_bullets(text)
    text, hr_removed = strip_horizontal_rules(text)
    text, dash_fixed = fix_dash_bullets(text)
    text, dots_collapsed = collapse_dot_leaders(text)
    text, br_joined = fix_br_word_splits(text)
    text, spaced_underscores = fix_spaced_underscores(text)

    # always shown (not verbose-gated): the first LLM call can stall for a
    # long time if the server must load the model — silence here looks
    # like a hang
    print(
        f"  llm: starting (model {model}) — the first call may take a while "
        "if the server has to load the model",
        flush=True,
    )

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
    if keep_prellm:
        from pathlib import Path
        Path(keep_prellm).write_text(text, encoding="utf-8")
    if verbose:
        print(
            f"  llm: document classified {'technical' if is_technical else 'general'} "
            f"({source})"
            + (f"; {sub_count} subscript terms joined" if sub_count else "")
            + (f"; {spaced_underscores} spaced underscores joined"
               if spaced_underscores else "")
            + (f"; {br_joined} '<br>' splits joined" if br_joined else "")
            + (f"; {dash_fixed} dash bullets repaired" if dash_fixed else ""),
            flush=True,
        )

    # per-document vocabulary (as-extracted, after pre-passes): SEND/SKIP
    # filter only — it never edits text
    vocab = DocVocab(text)
    chunks = chunk_markdown(text, max_chars)

    # byte offsets of every chunk in the EXACT text chunked above (after the
    # deterministic pre-passes, before the LLM pass): fail-log chunk indices
    # resolve back into the document via [start, end) character ranges
    offsets: list[list[int]] = []
    pos = 0
    for chunk, sep in chunks:
        offsets.append([pos, pos + len(chunk)])
        pos += len(chunk) + len(sep)

    # llama-swappy probe: auto workers + context-sufficiency check. Runs on
    # the ACTUAL largest chunk (an oversized single line can exceed
    # max_chars), before any LLM call so an abort costs nothing. The token
    # meter counts the largest chunk exactly when /llama/tokenize answers;
    # its availability is probed here, before the pass, either way.
    meter = TokenMeter(model, endpoint, api_key)
    swappy_entry: dict | None = None
    if chunks:
        biggest_idx = max(range(len(chunks)), key=lambda i: len(chunks[i][0]))
        biggest = len(chunks[biggest_idx][0])
        workers, swappy_entry = resolve_workers(
            endpoint, api_key, model, biggest, workers,
            note=lambda msg: print(msg, flush=True),
            meter=meter, largest_chunk_text=chunks[biggest_idx][0],
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
        "br_joined": br_joined,
        "horizontal_rules_removed": hr_removed,
        "dash_bullets_fixed": dash_fixed,
        "dot_leaders_collapsed": dots_collapsed,
        "chunks_total": len(chunks),
        "chunks_accepted": 0,
        "chunks_salvaged": 0,
        "chunks_rejected": 0,
        "chunks_toc_skipped": 0,
        "blocks_fixed": 0,
        "units_sent": 0,
        "units_fixed": 0,
        "units_failed": 0,
        "units_skipped": 0,
        "units_requeued": 0,
        "units_fixed_after_requeue": 0,
        "units_inferred_missing": 0,
        "batches": 0,
        "cells_sent": 0,
        "cells_fixed": 0,
        "wholechunk_attempts": 0,
        "wholechunk_accepted": 0,
        "wholechunk_linejoin_fixes": 0,
        "retries_used": 0,
        "truncated_calls": 0,
        "truncated_api_calls": 0,
        "replies_renumbered": 0,
        "units_renumbered_recovered": 0,
        "rejections": [],
        "unit_fail_log": [],
        "truncation_log": [],
        "chunk_offsets": offsets,
    }
    if swappy_entry is not None:
        stats["swappy"] = {
            "key": swappy_entry.get("key"),
            "slots": swappy_entry.get("slots"),
            "context_per_request": swappy_entry.get("contextSize"),
            "workers": workers,
        }
    if not chunks:
        return "", stats

    states = [ChunkState(i, chunk, sep) for i, (chunk, sep) in enumerate(chunks)]
    lock = threading.Lock()
    t0 = time.monotonic()
    pool = _DaemonPool(workers)

    def note(msg: str) -> None:
        if verbose:
            print(msg, flush=True)

    cfg = SimpleNamespace(
        system_prompt=system_prompt, model=model, endpoint=endpoint,
        api_key=api_key, sampling=sampling, stats=stats, vocab=vocab,
        meter=meter,
    )
    sched = BatchScheduler(
        states, {"cell": cell_prompt, "line": line_prompt}, vocab,
        model=model, endpoint=endpoint, api_key=api_key, sampling=sampling,
        retries=retries, stats=stats, lock=lock, pool=pool, note=note,
        batch_tokens=batch_tokens if batch_tokens else BATCH_TOKENS,
        meter=meter,
        verbose=verbose,
    )

    try:
        for i in range(len(chunks)):
            # producers are lower priority than batch requests (see
            # _DaemonPool): batches packed from scanned chunks must interleave
            pool.submit(_produce_chunk, sched, cfg, i, priority=1)
        sched.run()
        sched.stop_progress()
        pool.drain_and_shutdown()
    except KeyboardInterrupt:
        pool.shutdown_now()
        sched.stop_progress()
        _finish_interrupted(stats)
        raise  # unreachable, keeps type-checkers happy

    rescued = 0
    if rescue:
        rescued = _run_rescue(
            states, {"cell": cell_prompt, "line": line_prompt}, vocab,
            rescue, endpoint=endpoint, api_key=api_key, sampling=sampling,
            stats=stats, lock=lock, workers=workers, note=note,
            verbose=verbose,
            batch_tokens=batch_tokens if batch_tokens else BATCH_TOKENS,
            prev_failed=sched.final_failed,
        )
        stats["units_failed"] -= rescued

    results, deltas = sched.finalize()
    for delta in deltas:
        _apply_chunk_delta(stats, delta)
        if verbose and (delta.get("rejected") or delta.get("salvaged")):
            print(
                f"  llm: chunk {delta['index']}/{len(chunks)} "
                f"[{_fmt_chunk_state(delta)}]",
                flush=True,
            )
    stats["units_fixed"] = stats["blocks_fixed"]
    stats["tokens"] = meter.meta()
    stats["duration"] = time.monotonic() - t0
    if verbose:
        print(
            f"  llm: done in {_fmt_duration(stats['duration'])}: "
            f"{len(chunks)} chunks ({stats['chunks_accepted']} accepted, "
            f"{stats['chunks_salvaged']} salvaged, {stats['chunks_rejected']} "
            f"rejected, {stats['chunks_toc_skipped']} toc-skipped); "
            f"{stats['units_sent']} unit(s) sent in {stats['batches']} batch(es), "
            f"{stats['blocks_fixed']} fixed, {stats['units_failed']} failed, "
            f"{stats['units_skipped']} vocab-skipped"
            + (f"; rescue: {rescued} rescued by "
               + " + ".join(lv["model"] for lv in stats["rescue"]["levels"])
               if rescued else ""),
            flush=True,
        )

    # deterministic meta.json regardless of completion order
    stats["rejections"].sort(key=lambda r: r["chunk"])
    return "".join(results), stats
