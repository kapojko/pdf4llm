"""Experiment 5: temperature effect, malformed-group retry, fix-value check.

1. Whole-chunk prose calls at temp=0 vs temp=0.6 -> verdicts
   (is the editorial instinct partly a sampling artifact?).
2. Malformed cell/line groups: one retry with a hint -> malformed rate after.
3. Print actual cell fixes from cell mode (are they genuine false-space fixes?).
4. Show a prose paragraph with candidate false-space patterns (is there
   anything to fix at all in these chunks?).
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import config as cfg
from pdf4llm.llm_client import DEFAULT_SAMPLING, _strip_thinking, output_token_cap
from pdf4llm.llm_verify import _num_check, _verify_chunk
from exp2_llm_smart_chunks import (
    BASELINE_PROMPT, CELL_LINE_RE, CELL_PROMPT, call, load_chunks,
)
from exp4_prose_counters import LINE_PROMPT

SUSPICIOUS_RE = re.compile(r"[a-z] [a-z]")


def whole_chunk(chunk, ctx, sampling):
    cand, finish = call(BASELINE_PROMPT, chunk,
                        max_tokens=output_token_cap(len(chunk)),
                        sampling=sampling, **{k: v for k, v in ctx.items() if k != "sampling"})
    cand = _strip_thinking(cand)
    r = _verify_chunk(chunk, cand)
    return {"finish": finish, "verdict": "accepted" if r is None else "rejected"}


def line_mode_retry(chunk, ctx):
    lines = [l for l in chunk.split("\n")]
    idx = {n: l for n, l in enumerate(lines) if l.strip()}
    payload = "\n".join(f"{n}| {lines[n]}" for n in sorted(idx))
    fixed = violated = 0
    for attempt in range(2):
        resp, finish = call(LINE_PROMPT, payload,
                            max_tokens=output_token_cap(len(payload)) + 64, **ctx)
        resp = _strip_thinking(resp)
        got = {}
        for rl in resp.split("\n"):
            m = CELL_LINE_RE.match(rl.strip())
            if m:
                got[int(m.group(1))] = m.group(2)
        if set(got) != set(idx):
            if attempt == 0:
                payload = (payload + "\n\nIMPORTANT: your previous reply did not "
                           "contain every line. Re-send ALL lines 'N| text', "
                           "same count and order, no other text.")
                continue
            return {"malformed_after_retry": True}
        for n, new in got.items():
            old = idx[n]
            if new == old:
                continue
            if ("".join(new.split()) == "".join(old.split())
                    and _num_check(old, new) is None):
                fixed += 1
            else:
                violated += 1
        return {"malformed_after_retry": False, "lines_fixed": fixed,
                "lines_violated": violated}
    return {}


def main():
    c = cfg.load_config()
    ctx = dict(model=c["model"], endpoint=c["endpoint"], api_key=c["api_key"],
               sampling=c.get("llm_sampling") or DEFAULT_SAMPLING)
    chunks = load_chunks()
    PROSE_IDX = [139, 140, 141, 142, 144, 145, 152]

    t0 = dict(ctx["sampling"], temperature=0.0)

    print("=== whole-chunk prose: temp=0.6 vs temp=0 ===")
    with ThreadPoolExecutor(6) as ex:
        r06 = list(ex.map(lambda i: whole_chunk(chunks[i][0], ctx, ctx["sampling"]), PROSE_IDX))
        r00 = list(ex.map(lambda i: whole_chunk(chunks[i][0], ctx, t0), PROSE_IDX))
    for i, a, b in zip(PROSE_IDX, r06, r00):
        print(f"  chunk {i:>4}: temp0.6={a['verdict']:<9} temp0={b['verdict']:<9}")

    print("\n=== prose line-mode WITH retry ===")
    with ThreadPoolExecutor(4) as ex:
        for i, r in zip(PROSE_IDX, ex.map(lambda i: line_mode_retry(chunks[i][0], ctx), PROSE_IDX)):
            print(f"  chunk {i:>4}: {r}")

    print("\n=== genuine cell fixes (sample) ===")
    shown = 0
    for i in [3, 4, 2, 7]:
        chunk = chunks[i][0]
        for line in chunk.split("\n"):
            if not line.lstrip().startswith("|"):
                continue
            cells = [cc.strip() for cc in line.strip().strip("|").split("|")]
            targets = [k for k, cc in enumerate(cells) if SUSPICIOUS_RE.search(cc)]
            if not targets:
                continue
            payload = "\n".join(f"{k}| {cells[k]}" for k in targets)
            content = f"CONTEXT ROW:\n{line}\n\nCELLS:\n{payload}"
            resp, _ = call(CELL_PROMPT, content,
                           max_tokens=output_token_cap(len(payload)) + 64,
                           sampling=dict(ctx["sampling"], temperature=0.0),
                           model=ctx["model"], endpoint=ctx["endpoint"], api_key=ctx["api_key"])
            resp = _strip_thinking(resp)
            got = {}
            for rl in resp.split("\n"):
                m = CELL_LINE_RE.match(rl.strip())
                if m:
                    got[int(m.group(1))] = m.group(2).strip()
            if set(got) != set(targets):
                continue
            for k in targets:
                if (got[k] != cells[k]
                        and "".join(got[k].split()) == "".join(cells[k].split())
                        and _num_check(cells[k], got[k]) is None):
                    print(f"  chunk {i}: {cells[k]!r} -> {got[k]!r}")
                    shown += 1
            if shown >= 12:
                return

    print("\n=== candidate false-space patterns in prose chunk 142 (manual look) ===")
    for m in re.finditer(r"\b\w{1,3} \w{1,3}\b", chunks[142][0]):
        pass
    txt = chunks[142][0]
    print(txt[:900])


if __name__ == "__main__":
    main()
