"""Experiment 3: diagnose WHAT the model changes in rejected prose chunks."""
from __future__ import annotations

import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import config as cfg
from pdf4llm.llm_chunk import chunk_markdown
from pdf4llm.llm_client import DEFAULT_SAMPLING, _strip_thinking, output_token_cap
from pdf4llm.llm_prepass import (
    collapse_dot_leaders, dedupe_bullets, fix_subscripts,
    strip_horizontal_rules,
)
from pdf4llm.llm_verify import _verify_chunk
from exp2_llm_smart_chunks import BASELINE_PROMPT, call, load_chunks

c = cfg.load_config()
ctx = dict(model=c["model"], endpoint=c["endpoint"], api_key=c["api_key"],
           sampling=c.get("llm_sampling") or DEFAULT_SAMPLING)

chunks = load_chunks()
PROSE_IDX = [139, 140, 141, 142, 144, 145]

for i in PROSE_IDX:
    chunk = chunks[i][0]
    cand, finish = call(BASELINE_PROMPT, chunk, max_tokens=output_token_cap(len(chunk)), **ctx)
    cand = _strip_thinking(cand)
    reason = _verify_chunk(chunk, cand)
    if reason is None:
        print(f"--- chunk {i}: accepted\n")
        continue
    print(f"--- chunk {i}: REJECTED ({reason})")
    so, sc = "".join(chunk.split()), "".join(cand.split())
    sm = difflib.SequenceMatcher(None, so, sc, autojunk=False)
    shown = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        print(f"    [{tag}] {so[i1:i2][:60]!r} -> {sc[j1:j2][:60]!r}   "
              f"ctx: ...{so[max(0,i1-40):i1][-40:]}__")
        shown += 1
        if shown >= 6:
            break
    print()
