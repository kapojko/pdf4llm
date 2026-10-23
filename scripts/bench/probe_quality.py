"""Document quality probe: run the full batched LLM pass on the prepared
document, record outcome + rejection reasons per chunk index.

Usage: probe_quality.py <name> <model> <workers>

Since cross-chunk batch aggregation the request unit is no longer the chunk,
so this probe measures the whole pipeline (batched cells/lines + whole-chunk
prose attempts) rather than isolated per-chunk calls; per-chunk final states
still come from meta-style deltas.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from pdf4llm import llm_prepass, llm_run
from pdf4llm.config import load_config

NAME, MODEL, WORKERS = sys.argv[1], sys.argv[2], int(sys.argv[3])
cfg = load_config()
ENDPOINT, API_KEY = cfg["endpoint"], cfg["api_key"]

orig = Path("out/CH32V208DS0 2.7 2026-06-01.md").read_text(encoding="utf-8")
text = llm_prepass.dedupe_bullets(orig)
text, _ = llm_prepass.strip_horizontal_rules(text)
text, _ = llm_prepass.fix_subscripts(text)

deltas: list[dict] = []
orig_apply = llm_run._apply_chunk_delta


def recording_apply(stats, delta):
    deltas.append(delta)
    return orig_apply(stats, delta)


llm_run._apply_chunk_delta = recording_apply
t0 = time.monotonic()
with open(Path(__file__).resolve().parent / "bench_logs" / f"probe_{NAME}.log",
          "w", encoding="utf-8") as log:
    import contextlib
    with contextlib.redirect_stdout(log):
        _corrected, stats = llm_run.correct_with_llm(
            text, MODEL, ENDPOINT, API_KEY,
            sampling=None,  # server-side defaults (never overridden)
            retries=2, workers=WORKERS, classify=False,
        )
llm_run._apply_chunk_delta = orig_apply
wall = time.monotonic() - t0

summary = {
    "name": NAME, "model": MODEL, "workers": WORKERS, "wall_secs": round(wall, 1),
    "accepted": stats["chunks_accepted"],
    "salvaged": stats["chunks_salvaged"],
    "rejected": stats["chunks_rejected"],
    "toc_skipped": stats["chunks_toc_skipped"],
    "blocks_fixed": stats["blocks_fixed"],
    "units_sent": stats.get("units_sent", 0),
    "units_fixed": stats.get("units_fixed", 0),
    "units_failed": stats.get("units_failed", 0),
    "units_skipped": stats.get("units_skipped", 0),
    "batches": stats.get("batches", 0),
    "retries_used": stats["retries_used"],
    "truncated_calls": stats["truncated_calls"],
    "wholechunk_attempts": stats.get("wholechunk_attempts", 0),
    "wholechunk_accepted": stats.get("wholechunk_accepted", 0),
    "wholechunk_linejoin_fixes": stats.get("wholechunk_linejoin_fixes", 0),
    "rejected_reasons": [
        {"chunk": r["chunk"], "reason": r["reason"][:160]}
        for r in stats["rejections"]
    ],
    "unit_fail_log": stats.get("unit_fail_log", [])[:200],
}
(Path(__file__).resolve().parent / f"probe_{NAME}.json").write_text(
    json.dumps(summary, indent=1, ensure_ascii=False))
print(json.dumps({k: v for k, v in summary.items()
                  if k not in ("rejected_reasons", "unit_fail_log")}, indent=1))
