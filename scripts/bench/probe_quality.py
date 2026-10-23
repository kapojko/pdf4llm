"""Per-chunk quality probe: run every chunk through a model, record outcome
+ rejection reasons per chunk index. Usage: probe_quality.py <name> <model> <workers>
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from pdf4llm import llm_chunk, llm_client, llm_prepass, llm_prompts, llm_run
from pdf4llm.config import load_config

NAME, MODEL, WORKERS = sys.argv[1], sys.argv[2], int(sys.argv[3])
cfg = load_config()
ENDPOINT, API_KEY = cfg["endpoint"], cfg["api_key"]

orig = Path("out/CH32V208DS0 2.7 2026-06-01.md").read_text(encoding="utf-8")
text = llm_prepass.dedupe_bullets(orig)
text, _ = llm_prepass.strip_horizontal_rules(text)
text, _ = llm_prepass.fix_subscripts(text)
chunks = llm_chunk.chunk_markdown(text, 2000)

sys_prompt = llm_prompts.TECHNICAL_SYSTEM_PROMPT
deltas: dict[int, dict] = {}
t0 = time.monotonic()

def run(i: int, chunk: str, sep: str) -> None:
    _res, delta = llm._run_chunk(
        i, len(chunks), chunk, sep, sys_prompt, MODEL, ENDPOINT,
        API_KEY, llm_client.DEFAULT_SAMPLING, retries=2,
    )
    deltas[i] = delta

with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    futs = [ex.submit(run, i, c, s) for i, (c, s) in enumerate(chunks, 1)]
    for f in futs:
        f.result()

wall = time.monotonic() - t0
summary = {
    "name": NAME, "model": MODEL, "workers": WORKERS, "wall_secs": round(wall, 1),
    "accepted": sum(1 for d in deltas.values() if d.get("accepted")),
    "salvaged": sum(1 for d in deltas.values() if d.get("salvaged")),
    "rejected": sum(1 for d in deltas.values() if d.get("rejected")),
    "blocks_fixed": sum(d.get("blocks_fixed", 0) for d in deltas.values() if d.get("salvaged")),
    "retries_used": sum(d["retries_used"] for d in deltas.values()),
    "rejected_reasons": [
        {"chunk": i, "reasons": [
            # keep only the reason text before the offending snippet
            (d.get("rejection") or {}).get("reason", "")[:160]
        ]}
        for i, d in sorted(deltas.items()) if d.get("rejected")
    ],
}
(Path(__file__).resolve().parent / f"probe_{NAME}.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
print(json.dumps({k: v for k, v in summary.items() if k != "rejected_reasons"}, indent=1))
print("\nrejected chunks:")
for r in summary["rejected_reasons"]:
    print(f"  chunk {r['chunk']}: {r['reasons'][0][:130]}")
