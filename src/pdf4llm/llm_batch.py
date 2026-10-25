"""Cross-chunk batch aggregation — the request-unit scheduler.

Decouples the verification unit (a cell or a line — small) from the request
unit: suspect units from ALL chunks are collected into kind-separated queues
(never mixed in one call: one call = one task type) and packed into batched
echo requests (~5k chars of fragment text per call, CONTEXT row attached once
per row-group). Every unit is verified individually before it is applied
back to its chunk.

Failure semantics — PURE GLOBAL REQUEUE: a unit that fails parsing,
verification, or was missing from a (truncated) reply is never retried in
place. It goes back to the END of its queue with attempts+1 and its
rejection reason; the next batch it lands in carries the reason as a
per-unit NOTE line (mixed-reason batches stay coherent, and each retry gets
a fresh position in the echo — drift-isolated by construction). After
`retries` extra attempts the unit is finalized as failed and keeps the
original text. A unit that succeeds after requeueing is drift evidence in
itself: it failed at one batch ordinal and passed at another.

Safety is unchanged: the verifier is the only gate, rejection is always
safe, and chunk final states are computed only at drain time from the
per-chunk totals.
"""
from __future__ import annotations

import re
import time
from collections import Counter, deque

from .llm_prepass import has_residual_br
from .llm_protocol import _echo_units
from .progress import LineProgress, _fmt_duration
from .llm_table import _split_row_cells, _splice_cells
from .llm_verify import (
    _verify_chunk,
    _verify_line_in_context,
    _verify_pair,
)


# ~10k chars of *fragments* per batched call (context rows attached once per
# row-group, not per cell; slot context is 32k tok/request, so input is not
# the constraint — generated output length is; the output cap scales with
# the fragment total, see llm_client.output_cap_chars).
# Benchmarked on ling-3.0-tiny-np8 (2026-10, batched pipeline, dflash
# server): 10k beat 5k by ~16% wall time (77-102s vs 93-106s on the 80-chunk
# CH32V208DS0 fixture); 20k added nothing and truncated once. Quality
# (75/80 chunks accepted) was identical across 2.5k/5k/10k/20k.
BATCH_CHARS = 10000

# Failures per unit are logged for the batch-size drift measurement: flat
# per-ordinal failure distribution -> batch size can grow; tail-clustered ->
# ceiling found.
_FAIL_LOG_CAP = 2000


# ---------------------------------------------------------------------------
# Vocabulary as a SEND/SKIP filter (never an applier)
# ---------------------------------------------------------------------------

# Punctuation stripped from token edges when forming join candidates ('.'
# in 'R es .', '*' in '*Table'). Dashes are included so 'p -flo p' sees the
# continuation token; internal hyphens ('D-t', 'flip-flop') are kept.
_EDGE_CHARS = ".,:;!?*()[]{}\"'\u2019\u201c\u201d-"

_VOCAB_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z_0-9-]*")


class DocVocab:
    """Word-frequency map of THIS document (as-extracted, after pre-passes).

    Used ONLY to decide whether a suspicious fragment is sent to the model:
    if the joined form of a falsely-split word already occurs in the
    document ('Re set' -> 'Reset' x80), the join is plausible — send as
    usual; if the joined form never occurs ('Power down' -> 'Powerdown' x0),
    the spacing is probably legitimate — skip. The map never edits text; a
    wrong skip costs one unfixed defect (recall), never corruption. On a
    sparse document the filter denies more often, which degrades recall,
    not safety.
    """

    def __init__(self, text: str) -> None:
        self.counts = Counter(_VOCAB_TOKEN_RE.findall(text.lower()))

    def _hit(self, candidate: str) -> bool:
        return self.counts.get(candidate, 0) >= 1

    def admits(self, text: str) -> bool:
        """True -> send the fragment to the model; False -> skip it.

        Fragments with mechanical suspicion the vocabulary cannot judge are
        always admitted: residual '<br>' markers (the join target is the
        tag, not a word), double spaces / tabs (pure whitespace artifacts),
        and very long fragments (candidate space explodes — conservative).
        """
        if has_residual_br(text) or "  " in text or "\t" in text:
            return True
        tokens = text.split()
        if len(tokens) > 48:
            return True
        i = 0
        while i < len(tokens):
            j = i
            while j < len(tokens) - 1 and _gap_suspicious(tokens[j], tokens[j + 1]):
                j += 1
            if j > i:
                # group of tokens linked by suspicious gaps: every contiguous
                # sub-join is a candidate ('D-t yp e' -> 'D-type' needs the
                # full group; 'Orderin g code' needs the 'Orderin|g' pair)
                if j - i + 1 > 12:
                    return True
                cores = [t.strip(_EDGE_CHARS) for t in tokens[i:j + 1]]
                for a in range(len(cores)):
                    joined = cores[a]
                    for b in range(a + 1, len(cores)):
                        joined += cores[b]
                        if len(joined) >= 3 and self._hit(joined.lower()):
                            return True
            i = j + 1
        return False


def _gap_suspicious(left_tok: str, right_tok: str) -> bool:
    """Whitespace gap between two tokens looks like a falsely split word?

    Mirrors the two cell-suspicion patterns of llm_table:
      '[A-Za-z] [a-z]'            — letter followed by lowercase word start;
      '\\b[A-Za-z] [A-Za-z]{1,2}\\b' — single letter + 1-2 letter token.
    """
    l = left_tok.strip(_EDGE_CHARS)
    r = right_tok.strip(_EDGE_CHARS)
    if not l or not r:
        return False
    lc, rc = l[-1], r[0]
    if not (lc.isascii() and lc.isalpha() and rc.isascii() and rc.isalpha()):
        return False
    if rc.islower():
        return True
    return len(l) == 1 and len(r) <= 2


# ---------------------------------------------------------------------------
# Units and per-chunk state
# ---------------------------------------------------------------------------


class Unit:
    """One verification unit with global identity (registry entry)."""

    __slots__ = ("gid", "chunk", "line", "cell", "kind", "text", "context",
                 "attempts", "last_fail")

    def __init__(self, gid: int, chunk: int, line: int, kind: str, text: str,
                 cell: int | None = None, context: str | None = None) -> None:
        self.gid = gid
        self.chunk = chunk          # index into the chunk list
        self.line = line            # line index within the chunk
        self.cell = cell            # cell index within the row (kind == 'cell')
        self.kind = kind            # 'cell' | 'line'
        self.text = text
        self.context = context      # 'row: | ... |' for cells, None for lines
        self.attempts = 0           # extra attempts used (requeues)
        self.last_fail: str | None = None

    @property
    def where(self) -> str:
        if self.kind == "cell":
            return f"row {self.line} cell {self.cell}"
        return f"line {self.line}"


class ChunkState:
    """Per-chunk buffers and counters (touched by producer + batch tasks)."""

    __slots__ = ("index", "chunk", "sep", "o_lines", "out_lines", "toc_skipped",
                 "produced", "units_total", "units_enqueued", "units_fixed",
                 "units_failed", "units_unchanged", "enq_done", "units_skipped",
                 "cells_sent", "cells_fixed", "reasons", "truncated",
                 "retries_used", "salvage_note")

    def __init__(self, index: int, chunk: str, sep: str) -> None:
        self.index = index
        self.chunk = chunk
        self.sep = sep
        self.o_lines = chunk.split("\n")
        self.out_lines = list(self.o_lines)
        self.toc_skipped = False
        self.produced = False  # producer finished scanning this chunk
        self.units_total = 0
        self.units_enqueued = 0  # unique units ever enqueued (requeues don't add)
        self.units_fixed = 0
        self.units_failed = 0
        self.units_unchanged = 0  # model echoed the original: done, nothing applied
        self.enq_done = 0  # enqueued units resolved (fixed/failed/unchanged)
        self.units_skipped = 0
        self.cells_sent = 0
        self.cells_fixed = 0
        self.reasons: list[str] = []
        self.truncated = 0
        self.retries_used = 0
        self.salvage_note = False

    def note_reason(self, reason: str, cap: int = 8) -> None:
        if len(self.reasons) < cap:
            self.reasons.append(reason)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class BatchScheduler:
    """Kind-separated unit queues -> batched echo requests -> verify/apply.

    The main thread runs :meth:`run`: it packs batches from the queues and
    submits them to the shared worker pool alongside the chunk producers.
    Drain condition: all producers done, queues empty, no batch in flight.
    """

    def __init__(self, states: list[ChunkState], prompts: dict[str, str],
                 vocab: DocVocab, *, model: str, endpoint: str, api_key: str,
                 sampling: dict | None, retries: int, stats: dict,
                 lock, pool, note=None, batch_chars: int = BATCH_CHARS,
                 verbose: bool = False) -> None:
        self.states = states
        self.prompts = prompts          # kind -> system prompt
        self.vocab = vocab
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key
        self.sampling = sampling
        self.retries = retries
        self.stats = stats
        self.lock = lock
        self.pool = pool
        self.note = note or (lambda msg: None)
        self.batch_chars = batch_chars
        self.queues: dict[str, deque[Unit]] = {"cell": deque(), "line": deque()}
        self.active = 0
        self.producers_total = len(states)
        self.producers_done = 0
        self.batches_sent = 0
        self.prog: LineProgress | None = None
        self.t0: float | None = None
        self.verbose = verbose  # gates TTY line-breaks before plain prints
        self._gid = 0

    # -- enqueue (producer side, lock held inside) ---------------------------

    def _next_gid(self) -> int:
        self._gid += 1
        return self._gid - 1

    def enqueue_cell(self, chunk: int, line: int, cell: int, text: str,
                     row: str) -> None:
        with self.lock:
            unit = Unit(self._next_gid(), chunk, line, "cell", text,
                        cell=cell, context="row: " + row)
            self.queues["cell"].append(unit)
            self.states[chunk].cells_sent += 1
            self.states[chunk].units_enqueued += 1
            self.stats["units_sent"] += 1

    def enqueue_line(self, chunk: int, line: int, text: str) -> None:
        with self.lock:
            unit = Unit(self._next_gid(), chunk, line, "line", text)
            self.queues["line"].append(unit)
            self.states[chunk].units_enqueued += 1
            self.stats["units_sent"] += 1

    def skip_unit(self, chunk: int) -> None:
        """Vocabulary filter denied the send: counted, never edited."""
        with self.lock:
            self.states[chunk].units_skipped += 1

    def producer_done(self) -> None:
        with self.lock:
            self.producers_done += 1

    # -- packing (main thread, lock held) ------------------------------------

    def _queue_chars(self, q: deque[Unit]) -> int:
        return sum(len(u.text) for u in q)

    def _pack(self, kind: str) -> list[Unit]:
        q = self.queues[kind]
        batch: list[Unit] = []
        chars = 0
        while q and chars < self.batch_chars:
            u = q.popleft()
            batch.append(u)
            chars += len(u.text)
        return batch

    def _packable(self, kind: str) -> bool:
        q = self.queues[kind]
        if not q:
            return False
        if self.producers_done >= self.producers_total:
            return True  # drain phase: send whatever there is
        return self._queue_chars(q) >= self.batch_chars

    # -- main loop ------------------------------------------------------------

    def run(self) -> None:
        self.t0 = time.monotonic()
        self.prog = LineProgress()
        while True:
            batch = None
            progress = ""
            with self.lock:
                for kind in ("cell", "line"):
                    if self._packable(kind):
                        batch = self._pack(kind)
                        self.active += 1
                        break
                done = (self.producers_done >= self.producers_total
                        and not self.queues["cell"] and not self.queues["line"]
                        and self.active == 0)
                if not done:
                    progress = self._progress_text_locked()
            if progress:
                self.prog.update(progress)
            if batch is not None:
                self.pool.submit(self._batch_task, batch)
                continue
            if done:
                return
            time.sleep(0.05)

    # -- live progress (main thread; text built under lock) --------------------

    def _progress_text_locked(self) -> str:
        """One-line live state: settled chunks with outcomes, ETA.

        A chunk is SETTLED when its producer finished and every unit it
        enqueued is resolved (fixed / failed / unchanged-echo) — the same
        condition under which finalize() would classify it, so the live
        counts converge to the final summary. Deliberately chunk-level
        only: unit counts and failure reasons belong to the final summary
        and meta.json, not to a (terminal-width-capped) progress line.
        """
        elapsed = time.monotonic() - self.t0
        total = self.producers_total
        ok = salv = rej = toc = settled = 0
        for cs in self.states:
            # only enqueued (batch) units are counted here: salvage fixes
            # resolve synchronously inside the producer, so a chunk settles
            # when its producer finished and every enqueued unit is resolved
            done_u = cs.enq_done
            if cs.produced and done_u >= cs.units_enqueued:
                settled += 1
                if cs.toc_skipped:
                    toc += 1
                elif cs.units_failed and not cs.units_fixed:
                    rej += 1
                elif cs.units_failed:
                    salv += 1
                else:
                    ok += 1
        text = (
            f"  llm: chunks {settled}/{total} (ok {ok}, salv {salv}, rej {rej}"
            + (f", toc {toc}" if toc else "")
            + f"), {self.batches_sent} batch(es), {_fmt_duration(elapsed)}"
        )
        if settled:
            eta = elapsed / settled * (total - settled)
            text += f", ~{_fmt_duration(eta)} left"
        return text

    def stop_progress(self) -> None:
        """Clear the progress line (idempotent; safe before run() too)."""
        if self.prog is not None:
            self.prog.finish()
            self.prog = None

    # -- batch execution (worker thread) --------------------------------------

    def _build_payload(self, batch: list[Unit]) -> tuple[str, int]:
        """Indexed fragment lines, per-unit NOTE hints, CONTEXT per row-group."""
        parts: list[str] = []
        frag_chars = 0
        i = 0
        while i < len(batch):
            j = i
            ctx = batch[i].context
            while j < len(batch) and batch[j].context == ctx:
                j += 1
            for u in batch[i:j]:
                parts.append(f"{u.gid}| {u.text}")
                frag_chars += len(u.text)
                if u.last_fail:
                    parts.append(
                        f"NOTE {u.gid}: your previous answer for unit {u.gid} "
                        f"was REJECTED ({u.last_fail}). Return the corrected "
                        "text exactly as instructed.")
            if ctx:
                parts.append("")
                parts.append("CONTEXT:")
                parts.append(ctx)
                parts.append("")
            i = j
        return "\n".join(parts), frag_chars

    def _batch_task(self, batch: list[Unit]) -> None:
        try:
            kind = batch[0].kind
            payload, frag_chars = self._build_payload(batch)
            want = {u.gid for u in batch}
            got, finish = _echo_units(
                self.prompts[kind], payload, want, self.model, self.endpoint,
                self.api_key, self.sampling, output_cap_chars=frag_chars)
            with self.lock:
                self.batches_sent += 1
                self.stats["batches"] += 1
                if finish == "length":
                    # per-chunk counters merge into truncated_calls at finalize
                    for c in {u.chunk for u in batch}:
                        self.states[c].truncated += 1
                self._process_batch(batch, got, finish)
                # verbose batch lines must not clobber the in-place progress
                # line on a TTY (only when a line is actually printed)
                if self.verbose and self.prog is not None:
                    self.prog.line_break()
                self.note(
                    f"  llm: batch {self.batches_sent}: {len(batch)} fragment(s), "
                    f"{frag_chars} chars"
                    + (", truncated" if finish == "length" else ""))
        finally:
            with self.lock:
                self.active -= 1

    def _process_batch(self, batch: list[Unit], got: dict[int, str],
                       finish: str | None) -> None:
        """Verify every returned unit; apply or requeue. Lock held."""
        for ordinal, u in enumerate(batch, 1):
            cs = self.states[u.chunk]
            new = got.get(u.gid)
            if new is None:
                if finish and finish.startswith("llm error"):
                    reason = finish
                elif finish == "length":
                    reason = "missing from truncated output"
                else:
                    reason = "malformed reply (missing index)"
                self._fail(u, reason, ordinal)
                continue
            if u.kind == "cell":
                new = new.strip()
            if not new.strip() or new.strip() == u.text.strip():
                cs.units_unchanged += 1
                cs.enq_done += 1
                continue  # unchanged (or empty) echo: nothing to apply
            if u.kind == "cell":
                reason = _verify_pair(u.text, new)
            else:
                reason = _verify_line_in_context(cs.o_lines, u.line, new)
            if reason is not None:
                self._fail(u, reason, ordinal)
                continue
            # accepted: apply back to the chunk buffer
            if u.kind == "cell":
                segs = _split_row_cells(cs.o_lines[u.line])
                if segs is not None:
                    cs.out_lines[u.line] = _splice_cells(
                        cs.o_lines[u.line], segs, {u.cell: new})
                cs.cells_fixed += 1
            else:
                cs.out_lines[u.line] = new
            cs.units_fixed += 1
            cs.enq_done += 1
            if u.attempts:
                self.stats["units_fixed_after_requeue"] += 1

    def _fail(self, u: Unit, reason: str, ordinal: int) -> None:
        """Requeue (never in-place retries) or finalize as failed. Lock held."""
        u.attempts += 1
        u.last_fail = reason
        cs = self.states[u.chunk]
        if len(self.stats["unit_fail_log"]) < _FAIL_LOG_CAP:
            self.stats["unit_fail_log"].append({
                "gid": u.gid, "kind": u.kind, "chunk": u.chunk,
                "ordinal": ordinal, "attempt": u.attempts, "reason": reason[:120],
            })
        if u.attempts <= self.retries:
            self.queues[u.kind].append(u)
            cs.retries_used += 1  # merged into retries_used at finalize
            self.stats["units_requeued"] += 1
            return
        # retries exhausted: the original text stays — rejection is safe
        cs.units_failed += 1
        cs.enq_done += 1
        self.stats["units_failed"] += 1
        cs.note_reason(f"{u.where}: {reason}")

    # -- finalization (main thread, after run()) ------------------------------

    def finalize(self) -> tuple[list[str], list[dict]]:
        """Assemble results and per-chunk outcome deltas (drain-time states)."""
        results: list[str] = []
        deltas: list[dict] = []
        for cs in self.states:
            result_body = "\n".join(cs.out_lines)
            if result_body != cs.chunk:
                # belt & braces: whatever was assembled must verify as a whole;
                # on any internal inconsistency the original chunk is kept
                final_reason = _verify_chunk(cs.chunk, result_body)
                if final_reason is not None:
                    cs.note_reason(
                        f"internal: final verification failed ({final_reason})")
                    result_body = cs.chunk
                    cs.units_fixed = 0
                    cs.units_failed = max(1, cs.units_failed)
            idx1 = cs.index + 1  # meta.json chunk indices are 1-based
            if cs.toc_skipped:
                delta = {"index": idx1, "toc_skipped": True,
                         "accepted": False, "salvaged": False, "rejected": False,
                         "blocks_fixed": 0, "rejection": None}
                result = cs.chunk + cs.sep
            elif cs.units_failed == 0 and cs.units_fixed == 0:
                delta = {"index": idx1, "accepted": True, "blocks_fixed": 0,
                         "rejection": None}
                result = result_body + cs.sep
            elif cs.units_failed == 0:
                delta = {"index": idx1, "accepted": True,
                         "blocks_fixed": cs.units_fixed, "rejection": None}
                result = result_body + cs.sep
            elif cs.units_fixed > 0:
                delta = {"index": idx1, "salvaged": True,
                         "blocks_fixed": cs.units_fixed, "rejection": None}
                result = result_body + cs.sep
            else:
                result = cs.chunk + cs.sep
                reason = "; ".join(cs.reasons[:3]) if cs.reasons \
                    else "no usable output"
                delta = {
                    "index": idx1,
                    "rejected": True,
                    "blocks_fixed": 0,
                    "rejection": {
                        "chunk": idx1,
                        "reason": reason,
                        "preview": cs.chunk[:120],
                    },
                }
            delta["retries_used"] = cs.retries_used
            delta["truncated"] = cs.truncated
            delta["cells_sent"] = cs.cells_sent
            delta["cells_fixed"] = cs.cells_fixed
            delta["units_skipped"] = cs.units_skipped
            delta["duration"] = 0.0
            results.append(result)
            deltas.append(delta)
        return results, deltas
