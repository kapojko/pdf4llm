"""Diagnose why the first N chunks are rejected by the LLM correction pass.

Replicates the exact pipeline from llm.correct_with_llm (pre-passes, chunking,
prompts, sampling, max_tokens cap) and prints, per chunk:
  - the raw model output's finish_reason
  - the verifier rejection reason for the raw output
  - a char-level preview of the first whitespace-edit violation
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import config as cfg
from pdf4llm.llm import (
    DEFAULT_SAMPLING,
    collapse_dot_leaders,
    _call_llm,
    _strip_thinking,
    _verify_chunk,
    chunk_markdown,
    dedupe_bullets,
    fix_subscripts,
    strip_horizontal_rules,
)

N_CHUNKS = int(sys.argv[1]) if len(sys.argv) > 1 else 8
MAX_CHARS = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
MD = Path("examples/rm0410-stm32f76xxx-and-stm32f77xxx-advanced-armbased-32bit-mcus-stmicroelectronics.md")

c = cfg.load_config()
endpoint, api_key, model = c["endpoint"], c["api_key"], c["model"]
sampling = c.get("llm_sampling") or DEFAULT_SAMPLING

text = MD.read_text(encoding="utf-8")
text = dedupe_bullets(text)
text, hr_removed = strip_horizontal_rules(text)
text, dots = collapse_dot_leaders(text)
print(f'pre-passes: hr_removed={hr_removed} dots_collapsed={dots}')
text, sub_count = fix_subscripts(text)
print(f"pre-passes: hr_removed={hr_removed} subscripts={sub_count}")

chunks = chunk_markdown(text, MAX_CHARS)
print(f"chunks: {len(chunks)} (max_chars={MAX_CHARS})\n")

import difflib

def first_ws_violation(orig: str, out: str):
    sm = difflib.SequenceMatcher(None, orig, out, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        removed, inserted = orig[i1:i2], out[j1:j2]
        yield (tag, removed, inserted, orig[max(0, i1-30):i2+30])

for i, (chunk, sep) in enumerate(chunks[:N_CHUNKS], 1):
    print("=" * 78)
    print(f"CHUNK {i}  ({len(chunk)} chars, {chunk.count(chr(10))+1} lines)")
    print("-" * 78)
    cand, finish = _call_llm(
        # TECHNICAL prompt (doc classified technical in the user's run)
        __import__("pdf4llm.llm", fromlist=["TECHNICAL_SYSTEM_PROMPT"]).TECHNICAL_SYSTEM_PROMPT,
        chunk, model, endpoint, api_key, sampling=sampling,
    )
    cand = _strip_thinking(cand)
    print(f"finish_reason={finish}  output_chars={len(cand)}")
    reason = _verify_chunk(chunk, cand)
    if reason is None:
        print("VERDICT: accepted")
        continue
    print(f"VERDICT: REJECTED -> {reason}")
    # Diff the whitespace-stripped strings: exactly what invariant A sees.
    so = "".join(chunk.split())
    sc = "".join(cand.split())
    sm = difflib.SequenceMatcher(None, so, sc, autojunk=False)
    shown = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        print(f"  {tag}: {so[i1:i2]!r} -> {sc[j1:j2]!r}")
        print(f"    in : ...{so[max(0, i1-40):i2+40]!r}...")
        print(f"    out: ...{sc[max(0, j1-40):j2+40]!r}...")
        shown += 1
        if shown >= 4:
            break
    if shown == 0:
        print("  (stripped strings identical — reason came from table invariants)")
    print()
