"""Predict rejection behaviour of the NEW verification rules on real chunks.

Runs one live model call per sampled chunk (no retries) and classifies the
output under three verifiers:
  - current : invariant A (whitespace-only) + join whitelist + table B
  - strict-new : invariant A + numeric-token protection (replaces whitelist)
  - content-new: [0-9A-Za-z_] skeleton + numeric tokens (proposed --llm-content-only)
"""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, "src")
from pdf4llm import config as cfg
from pdf4llm.llm import (
    DEFAULT_SAMPLING, TECHNICAL_SYSTEM_PROMPT, _strip_thinking, _verify_chunk,
    chunk_markdown, collapse_dot_leaders, dedupe_bullets, fix_subscripts,
    strip_horizontal_rules,
)

N_SAMPLES = int(sys.argv[1]) if len(sys.argv) > 1 else 40
MAXC = 1000

NUM = re.compile(r"[+\-\u2013\u2014\u00b1]?\s*[0-9]+(?:\s*[.,:/]\s*[0-9]+)*")
SKEL = re.compile(r"[0-9A-Za-z_]+")

def _numtoks(s): return [re.sub(r"\s+", "", x) for x in NUM.findall(s)]

def _strip_fence(out):
    m = re.match(r"^\s*```[^\n]*\n(.*)\n```\s*$", out, re.DOTALL)
    return m.group(1) if m else out

def strict_new(orig, out):
    out = _strip_fence(out)
    if not out.strip(): return "empty output"
    if "".join(out.split()) != "".join(orig.split()):
        return "letters/punct changed (non-ws)"
    if _numtoks(orig) != _numtoks(out):
        return "numeric token changed"
    return None

def content_new(orig, out):
    out = _strip_fence(out)
    if not out.strip(): return "empty output"
    if "".join(SKEL.findall(orig)) != "".join(SKEL.findall(out)):
        return "letters/digits changed"
    if _numtoks(orig) != _numtoks(out):
        return "numeric token changed"
    return None

c = cfg.load_config()
text = Path("examples/rm0410-stm32f76xxx-and-stm32f77xxx-advanced-armbased-32bit-mcus-stmicroelectronics.md").read_text(encoding="utf-8")
text = dedupe_bullets(text)
text, _ = strip_horizontal_rules(text)
text, _ = collapse_dot_leaders(text)
text, _ = fix_subscripts(text)
chunks = chunk_markdown(text, MAXC)
total = len(chunks)

step = max(1, total // N_SAMPLES)
idxs = sorted(set(list(range(0, min(10, total))) + list(range(0, total, step))))
print(f"chunks={total}, sampling {len(idxs)}")

def run(i):
    chunk, _ = chunks[i]
    from pdf4llm.llm import _call_llm
    cand, finish = _call_llm(TECHNICAL_SYSTEM_PROMPT, chunk, c["model"], c["endpoint"], c["api_key"],
                             sampling=c.get("llm_sampling") or DEFAULT_SAMPLING)
    cand = _strip_thinking(cand)
    return i, finish, cand

results = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    for i, finish, cand in ex.map(run, idxs):
        results[i] = (finish, cand)

from collections import Counter
stats = {k: Counter() for k in ("current", "strict-new", "content-new")}
examples = {k: [] for k in ("current", "strict-new", "content-new")}
for i in idxs:
    finish, cand = results[i]
    chunk, _ = chunks[i]
    for name, fn in (("current", _verify_chunk), ("strict-new", strict_new), ("content-new", content_new)):
        reason = fn(chunk, cand)
        key = "accept" if reason is None else reason.split(":")[0][:60]
        stats[name][key] += 1
        if reason and len(examples[name]) < 6:
            examples[name].append((i + 1, reason[:150]))

for name in ("current", "strict-new", "content-new"):
    acc = stats[name].get("accept", 0)
    print(f"\n### {name}: {acc}/{len(idxs)} accepted")
    for reason, n in stats[name].most_common():
        if reason != "accept":
            print(f"  {n:3d}x {reason}")
    for i, r in examples[name][:4]:
        print(f"    e.g. chunk {i}: {r}")

# ---- dissect content-new failures ----
import difflib
print("\n" + "=" * 78)
print("DISSECTION of content-new rejections:")
for i in idxs:
    finish, cand = results[i]
    chunk, _ = chunks[i]
    if content_new(chunk, cand) is None:
        continue
    print(f"\n--- chunk {i+1} ---")
    so = "".join(SKEL.findall(chunk)); sc = "".join(SKEL.findall(cand))
    if so != sc:
        sm = difflib.SequenceMatcher(None, so, sc, autojunk=False)
        for tag, a1, a2, b1, b2 in sm.get_opcodes():
            if tag == "equal": continue
            print(f"  SKEL {tag}: {so[a1:a2][:70]!r} -> {sc[b1:b2][:70]!r}")
            print(f"     ctx: ...{so[max(0,a1-40):a2+40][:110]!r}...")
            break
    to, tc = _numtoks(chunk), _numtoks(cand)
    if to != tc:
        for a, b in zip(to, tc):
            if a != b:
                print(f"  NUM: {a!r} -> {b!r}")
                break
        else:
            print(f"  NUM len {len(to)} -> {len(tc)}: {to[len(tc):][:3]} extra/dropped")
