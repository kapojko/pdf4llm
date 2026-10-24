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

import re
import threading
import time
from types import SimpleNamespace

from .llm_batch import BatchScheduler, ChunkState, DocVocab
from .llm_chunk import chunk_markdown
from .llm_classify import classify_with_llm
from .llm_client import _call_llm, _strip_thinking
from .llm_prepass import (
    collapse_dot_leaders,
    dedupe_bullets,
    fix_br_word_splits,
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
)
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
    candidate, finish = _call_llm(
        cfg.system_prompt, chunk, cfg.model, cfg.endpoint, cfg.api_key,
        sampling=cfg.sampling)
    with sched.lock:
        cfg.stats["wholechunk_attempts"] += 1
    candidate = _strip_thinking(candidate)
    if finish == "length":
        cs.truncated += 1  # merged into truncated_calls at finalize
        cs.note_reason("whole-chunk output truncated (finish_reason=length)")
    if _verify_chunk(chunk, candidate) is None:
        cs.out_lines = candidate.split("\n")
        cs.units_fixed += 1
        with sched.lock:
            cfg.stats["wholechunk_accepted"] += 1
            if len(cs.out_lines) != len(o_lines):
                # the whole-chunk call's UNIQUE yield: a cross-line join
                cfg.stats["wholechunk_linejoin_fixes"] += 1
        return
    salvaged, fixed, n_total, sreasons, failed_idx = _salvage(chunk, candidate)
    cs.out_lines = salvaged.split("\n")
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
        # Cells duplicated within their row (equal to, or contained in, a
        # sibling cell — the extractor sometimes splits a title across two
        # cells) are extraction artifacts: the model reliably tries to
        # deduplicate or reword them, which is a content change, so they are
        # never sent. A duplicated cell is already identical to its sibling —
        # there is nothing to fix in it anyway.
        stripped = [c.strip() for c in cells]
        keys = [re.sub(r"[^0-9a-z]+", "", c.lower()) for c in stripped]

        def _is_dup(k: int) -> bool:
            key = keys[k]
            if len(key) < 8:
                return False
            return any(j != k and key in other for j, other in enumerate(keys))

        targets = [k for k, c in enumerate(cells)
                   if _suspicious_cell(c) and not _is_dup(k)]
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
    text, br_joined = fix_br_word_splits(text)

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
    if verbose:
        print(
            f"  llm: document classified {'technical' if is_technical else 'general'} "
            f"({source})"
            + (f"; {sub_count} subscripts normalised" if sub_count else "")
            + (f"; {br_joined} '<br>' splits joined" if br_joined else ""),
            flush=True,
        )

    # per-document vocabulary (as-extracted, after pre-passes): SEND/SKIP
    # filter only — it never edits text
    vocab = DocVocab(text)
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
        "br_joined": br_joined,
        "horizontal_rules_removed": hr_removed,
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
        "batches": 0,
        "cells_sent": 0,
        "cells_fixed": 0,
        "wholechunk_attempts": 0,
        "wholechunk_accepted": 0,
        "wholechunk_linejoin_fixes": 0,
        "retries_used": 0,
        "truncated_calls": 0,
        "rejections": [],
        "unit_fail_log": [],
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
    )
    sched = BatchScheduler(
        states, {"cell": cell_prompt, "line": line_prompt}, vocab,
        model=model, endpoint=endpoint, api_key=api_key, sampling=sampling,
        retries=retries, stats=stats, lock=lock, pool=pool, note=note,
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
    stats["duration"] = time.monotonic() - t0
    if verbose:
        print(
            f"  llm: done in {_fmt_duration(stats['duration'])}: "
            f"{len(chunks)} chunks ({stats['chunks_accepted']} accepted, "
            f"{stats['chunks_salvaged']} salvaged, {stats['chunks_rejected']} "
            f"rejected, {stats['chunks_toc_skipped']} toc-skipped); "
            f"{stats['units_sent']} unit(s) sent in {stats['batches']} batch(es), "
            f"{stats['blocks_fixed']} fixed, {stats['units_failed']} failed, "
            f"{stats['units_skipped']} vocab-skipped",
            flush=True,
        )

    # deterministic meta.json regardless of completion order
    stats["rejections"].sort(key=lambda r: r["chunk"])
    return "".join(results), stats
