"""E2E check of the new --llm pipeline on a bounded slice of real rm0410 data.

Takes the first N chunks of the pre-converted (pure) rm0410 markdown, runs
correct_with_llm() on them (no PDF re-conversion), and reports the chunk
outcome distribution for comparison with the old pipeline's meta.json
(22% chunk-level rejections on the full document).
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import config as cfg
from pdf4llm import llm

MD = Path("examples/rm0410-stm32f76xxx-and-stm32f77xxx-advanced-armbased-32bit-mcus-stmicroelectronics.md")
N_CHUNKS = 80
MAX_CHARS = 2000

c = cfg.load_config()
text = MD.read_text(encoding="utf-8")
chunks = llm.chunk_markdown(text, MAX_CHARS)
slice_text = "".join(ch + sep for ch, sep in chunks[:N_CHUNKS])
print(f"slice: {N_CHUNKS} chunks, {len(slice_text)} chars; model={c['model']}")

_out, stats = llm.correct_with_llm(
    slice_text, c["model"], c["endpoint"], c["api_key"],
    verbose=False, sampling=c.get("llm_sampling"), workers=8,
)

total = stats["chunks_total"]
print(f"\nchunks_total={total}")
for k in ("chunks_accepted", "chunks_salvaged", "chunks_rejected",
          "chunks_toc_skipped", "blocks_fixed", "cells_sent", "cells_fixed",
          "retries_used", "truncated_calls"):
    print(f"  {k} = {stats[k]}")
acc = stats["chunks_accepted"] + stats["chunks_salvaged"]
print(f"\nnon-rejected: {acc}/{total} = {acc / total:.1%}  "
      f"(old pipeline on full rm0410: 78%)")
print("rejection reasons:")
cnt = Counter((r["reason"].split(";")[0][:70]) for r in stats["rejections"])
for reason, n in cnt.most_common():
    print(f"  {n}x {reason}")
