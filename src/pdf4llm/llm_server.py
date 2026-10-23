"""Server capability probing and parallelism.

llama-swappy self-description probe (auto workers + context-fit check),
the daemon thread pool used for parallel chunk processing, and the
interrupt/context exceptions raised to the caller.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
import urllib.request

from .llm_client import _CHARS_PER_TOKEN


# ---------------------------------------------------------------------------
# llama-swappy self-description probe (workers auto-set + context check)
# ---------------------------------------------------------------------------


# Slack for the system prompt, retry hint, code-fence wrapping and estimator
# error, added on top of the estimated input+output tokens.
_CTX_MARGIN_TOKENS = 512
# Cap on auto-selected workers. Measured on ling-3.0-tiny-np8 (2026-10):
# w4→w8 ≈ 1.75x aggregate throughput (268s vs 470s on an 80-chunk fragment);
# w16 gave no further gain (264s) — the GPU is saturated at ~8 streams.
# The cap only limits auto-selection; --llm-workers overrides it.
_MAX_AUTO_WORKERS = 8


class LlmInterrupted(RuntimeError):
    """The correction pass was stopped by Ctrl+C.

    Carries the partial ``stats`` dict; the caller must treat the original
    (pre-LLM) text as the result — a half-corrected document is worse than
    an uncorrected one, so nothing is written.
    """

    def __init__(self, stats: dict) -> None:
        super().__init__("correction pass interrupted by user")
        self.stats = stats


class _DaemonPool:
    """Fixed pool of daemon worker threads with a priority task queue.

    ThreadPoolExecutor is unsuitable here because its worker threads are
    non-daemonic (CPython 3.9+): a Ctrl+C would block interpreter exit for
    up to the 300 s HTTP timeout per in-flight request — the user sees a
    dead console and a flood of tracebacks. Daemon threads die immediately
    at interpreter exit; tasks they had already picked up are simply lost,
    which is exactly the interrupt semantics we want (their chunks fall
    back to the original text).

    Lower priority value runs first. Batch requests use priority 0, chunk
    producers priority 1: batches packed from already-scanned chunks must
    not wait behind every pending producer, or requeue rounds would
    serialize at the very end of the pass instead of overlapping with
    producer work (the pipelining the batch scheduler depends on).
    """

    def __init__(self, n_workers: int) -> None:
        import heapq
        self._heapq = heapq
        self._queue: list = []  # heap of (priority, seq, fn, args)
        self._seq = 0
        self._pending = 0
        self._error: BaseException | None = None
        self._closed = False
        self._cv = threading.Condition()
        self._threads = [
            threading.Thread(target=self._worker, daemon=True,
                             name=f"pdf4llm-llm-{k}")
            for k in range(max(1, n_workers))
        ]
        for t in self._threads:
            t.start()

    def submit(self, fn, *args, priority: int = 0) -> None:
        with self._cv:
            self._heapq.heappush(self._queue, (priority, self._seq, fn, args))
            self._seq += 1
            self._pending += 1
            self._cv.notify()

    def _worker(self) -> None:
        while True:
            with self._cv:
                while not self._queue and not self._closed:
                    self._cv.wait(0.05)
                if self._queue:
                    _prio, _seq, fn, args = self._heapq.heappop(self._queue)
                elif self._closed:
                    return
                else:
                    continue
            try:
                fn(*args)
            except BaseException as e:  # reported by drain(), never kills the pool
                if self._error is None:
                    self._error = e
            with self._cv:
                self._pending -= 1

    def drain_and_shutdown(self) -> None:
        """Wait until every submitted task ran, then stop the workers.

        Re-raises the first worker exception (mirrors Future.result()).
        Polling (not a blocking wait) keeps the main thread's Ctrl+C
        responsive at all times.
        """
        while self._pending > 0:
            time.sleep(0.05)
        self.shutdown_now()
        if self._error is not None:
            raise self._error

    def shutdown_now(self) -> None:
        """Drop everything queued and tell the workers to exit."""
        with self._cv:
            self._closed = True
            self._queue.clear()
            self._cv.notify_all()


class LlmContextError(RuntimeError):
    """The server context provably cannot hold a chunk's input + output."""


def probe_swappy(endpoint: str, api_key: str, timeout: float = 3.0) -> dict | None:
    """Fetch the llama-swappy self-description endpoint, if present.

    Tries ``<base>/llama-swappy/info`` where <base> is the endpoint with a
    trailing ``/v1`` stripped first, then the endpoint as given. Returns the
    parsed JSON dict, or None when the endpoint does not exist or does not
    answer (any ordinary OpenAI-compatible server, network issue, bad JSON).
    Never raises.
    """
    base = endpoint.rstrip("/")
    urls = [b + "/llama-swappy/info" for b in dict.fromkeys(
        [re.sub(r"/v1/?$", "", base), base])]
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            if isinstance(data, dict) and isinstance(data.get("models"), list):
                return data
        except Exception:
            continue
    return None


def estimate_chunk_tokens(max_chunk_chars: int) -> int:
    """Rough token estimate for the largest chunk: input + output + slack.

    The whole-chunk prose attempt may legitimately produce ~2x its input
    length (measured: alignment/padding rewrites), hence 3x the input
    estimate plus a margin for the system prompt and estimator error.
    """
    in_tokens = math.ceil(max_chunk_chars / _CHARS_PER_TOKEN)
    return 3 * in_tokens + _CTX_MARGIN_TOKENS


def resolve_workers(
    endpoint: str,
    api_key: str,
    model: str,
    max_chunk_chars: int,
    workers: int | None,
    note=None,
) -> tuple[int, dict | None]:
    """Probe llama-swappy; auto-set workers and check the context fit.

    Worker priority: explicit ``workers`` argument > ``min(slots, 8)`` from
    the info endpoint > 1 (unknown server). The context check compares a
    rough input+output estimate for the largest chunk against the per-request
    contextSize reported by llama-swappy (v1.3 semantics: total -c divided
    by slots) and raises LlmContextError when it does not fit. Missing data
    (no info endpoint, model key not listed, contextSize absent) degrades
    with a warning — never aborts.

    Returns (workers, swappy_model_entry_or_None).
    """
    if note is None:  # pragma: no cover
        def note(msg: str) -> None:
            print(msg, flush=True)

    info = probe_swappy(endpoint, api_key)
    if info is None:
        return (max(1, workers) if workers is not None else 1), None

    models = info.get("models") or []
    entry = next((m for m in models if m.get("key") == model), None)
    if entry is None and len(models) == 1:
        entry = models[0]
    if entry is None:
        note(f"  llm: note: llama-swappy info has no entry for model {model!r} "
             "— skipping context check")
        return (max(1, workers) if workers is not None else 1), None

    ctx = entry.get("contextSize")
    if ctx:
        need = estimate_chunk_tokens(max_chunk_chars)
        if need > ctx:
            raise LlmContextError(
                f"server context too small: {ctx} tokens/request available "
                f"(llama-swappy, model {entry.get('key')!r}), but the largest "
                f"chunk needs ~{need} tokens (in+out, rough estimate; "
                f"{max_chunk_chars} chars). Reduce the chunk size or increase "
                "the server context (-c, divided by -np)."
            )

    slots = entry.get("slots")
    if workers is not None:
        n_workers = max(1, workers)
        how = "explicit"
    elif slots:
        n_workers = min(int(slots), _MAX_AUTO_WORKERS)
        how = "from llama-swappy slots"
    else:
        n_workers = 1
        how = "default (slots unknown)"
    note(f"  llm: llama-swappy: slots={slots}, context={ctx} tok/request "
         f"-> workers={n_workers} ({how})")
    return n_workers, entry
