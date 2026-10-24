"""Local benchmark: worker counts and batch sizes on the batched pipeline.

Usage: python bench_llm_local.py <name> <model-key> <workers> [batch_chars]

batch_chars (optional, default: leave production value 5000) overrides the
scheduler's BATCH_CHARS for this run via a BatchScheduler.__init__ wrap —
no production-code change. Appends one result row to bench_results.json.
Per-run stdout is captured to bench_logs/<name>.log (the pass prints
unconditional progress lines).
"""
from __future__ import annotations

import contextlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from pdf4llm import llm_batch, llm_run
from pdf4llm.config import load_config

NAME, MODEL, WORKERS = sys.argv[1], sys.argv[2], int(sys.argv[3])
BATCH_CHARS = int(sys.argv[4]) if len(sys.argv) > 4 else None
cfg = load_config()
ENDPOINT, API_KEY = cfg["endpoint"], cfg["api_key"]

# batch-size override (bench-only): force every BatchScheduler instance of
# this run to pack BATCH_CHARS-char batches
if BATCH_CHARS is not None:
    _orig_init = llm_batch.BatchScheduler.__init__

    def _patched_init(self, *args, **kwargs):
        kwargs["batch_chars"] = BATCH_CHARS
        _orig_init(self, *args, **kwargs)

    llm_batch.BatchScheduler.__init__ = _patched_init

TEXT = Path("out/CH32V208DS0 2.7 2026-06-01.md").read_text(encoding="utf-8")


def main() -> None:
    log_path = Path(__file__).resolve().parent / "bench_logs"; log_path.mkdir(exist_ok=True)
    log_file = (log_path / f"{NAME}.log").open("w", encoding="utf-8")

    # warm-up: first request makes llama-swappy load the model (unload first
    # if another model is resident) — that load time must not pollute timing
    import litellm
    litellm.suppress_debug_info = True
    t_load = time.perf_counter()
    r = litellm.completion(
        model=f"openai/{MODEL}",
        messages=[{"role": "user", "content": "Answer with exactly: OK"}],
        api_base=ENDPOINT, api_key=API_KEY, max_tokens=8,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    load_secs = time.perf_counter() - t_load
    print(f"[{NAME}] warm-up reply={r.choices[0].message.content!r} "
          f"(incl. load/switch {load_secs:.1f}s)", flush=True)

    # record per-chunk deltas by wrapping _apply_chunk_delta (called once per
    # chunk at drain time in the batched pipeline)
    deltas: list[dict] = []
    orig_apply = llm_run._apply_chunk_delta

    def recording_apply(stats, delta):
        deltas.append(delta)
        return orig_apply(stats, delta)

    llm_run._apply_chunk_delta = recording_apply
    t0 = time.perf_counter()
    with contextlib.redirect_stdout(log_file):
        corrected, stats = llm_run.correct_with_llm(
            TEXT, MODEL, ENDPOINT, API_KEY,
            classify=False, workers=WORKERS,
        )
    wall = time.perf_counter() - t0
    log_file.close()
    llm_run._apply_chunk_delta = orig_apply

    # fix-quantity metrics vs the input text
    in_lines = TEXT.split("\n")
    out_lines = corrected.split("\n")
    changed_lines = sum(1 for a, b in zip(in_lines, out_lines) if a != b)

    # batch-size drift measurement (llm_batch._FAIL_LOG_CAP log): mean
    # ordinal of failures within their batches + coarse histogram. Flat
    # per-ordinal distribution -> batch can grow; tail-clustered -> ceiling.
    fail_log = stats.get("unit_fail_log", [])
    ordinals = [e["ordinal"] for e in fail_log if e.get("ordinal")]
    hist = {"1-4": 0, "5-8": 0, "9-16": 0, "17+": 0}
    for o in ordinals:
        hist["1-4" if o <= 4 else "5-8" if o <= 8 else "9-16" if o <= 16 else "17+"] += 1

    result = {
        "name": NAME, "model": MODEL, "workers": WORKERS,
        "batch_chars": BATCH_CHARS if BATCH_CHARS is not None else 5000,
        "fail_ordinal_mean": round(sum(ordinals) / len(ordinals), 2) if ordinals else None,
        "fail_ordinal_hist": hist if ordinals else None,
        "load_switch_secs": round(load_secs, 1),
        "wall_secs": round(wall, 1),
        "chars_per_sec": round(len(TEXT) / wall),
        "chunks": len(stats["chunks_total"]) if isinstance(stats["chunks_total"], list) else stats["chunks_total"],
        "accepted": stats["chunks_accepted"],
        "salvaged": stats["chunks_salvaged"],
        "rejected": stats["chunks_rejected"],
        "blocks_fixed": stats["blocks_fixed"],
        "retries_used": stats["retries_used"],
        "truncated_calls": stats["truncated_calls"],
        "changed_lines_vs_input": changed_lines,
        "units_sent": stats.get("units_sent", 0),
        "units_failed": stats.get("units_failed", 0),
        "units_skipped": stats.get("units_skipped", 0),
        "batches": stats.get("batches", 0),
        "corrected_chars": len(corrected),
    }
    out = Path(__file__).resolve().parent / "outputs" / f"bench_{NAME}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(corrected, encoding="utf-8")
    results_file = Path(__file__).resolve().parent / "bench_results.json"
    rows = json.loads(results_file.read_text()) if results_file.exists() else []
    rows = [r for r in rows if r["name"] != NAME] + [result]
    results_file.write_text(json.dumps(rows, indent=1))
    print(json.dumps(result, indent=1), flush=True)


if __name__ == "__main__":
    main()
