"""Experiment 4: prose failure counters + cell-protocol robustness.

1. PROSE VARIANTS on the same prose chunks, single call each:
     V1 baseline prompt (as exp2)
     V2 baseline + explicit 'en dash / (R) / bullet are content' rules
     V3 line-mode protocol: lines sent as 'N| text', verified per line
        (like cell mode; a line that fails verification reverts to original)
2. CELL MALFORMED: capture raw responses of malformed cell groups to see
   what the model returns instead of the requested 'N| ...' lines.
"""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import config as cfg
from pdf4llm.llm_chunk import chunk_markdown
from pdf4llm.llm_client import DEFAULT_SAMPLING, _strip_thinking, output_token_cap
from pdf4llm.llm_verify import _num_check, _verify_chunk
from exp2_llm_smart_chunks import (
    BASELINE_PROMPT, CELL_LINE_RE, CELL_PROMPT, call, load_chunks,
)

DASH_RULES = (
    "ADDITIONAL HARD RULES:\n"
    "- En dashes ('–'), em dashes ('—'), hyphens in words ('Cortex-M7'), "
    "registered marks ('(R)' shown as '®') and bullet glyphs ('•') are CONTENT. "
    "Never delete, replace or move them. A line may legitimately START with "
    "'– ' — that is a list item, not a broken bullet; keep it byte-identical.\n"
    "- Never change the case of any letter.\n"
)

LINE_PROMPT = (
    "You fix whitespace defects in text extracted from a PDF.\n"
    "Input: lines 'N| text'. Fix ONLY false spaces inside words "
    "('examp le' -> 'example') and false line breaks that split a word "
    "across two lines. Keep every digit, punctuation mark, dash ('-', '–', "
    "'—'), '(R)'/'®', bullet and letter case exactly as-is. Do NOT merge "
    "numbers, do NOT fix grammar, do NOT reformat lists.\n"
    "Return EXACTLY the same 'N| ...' lines: same count, same order. "
    "Nothing else."
)


def prose_v2(chunk, ctx):
    cand, finish = call(BASELINE_PROMPT + "\n" + DASH_RULES, chunk,
                        max_tokens=output_token_cap(len(chunk)), **ctx)
    cand = _strip_thinking(cand)
    r = _verify_chunk(chunk, cand)
    return {"finish": finish, "verdict": "accepted" if r is None else f"rejected: {r}"}


def prose_line_mode(chunk, ctx):
    lines = [l for l in chunk.split("\n")]
    idx = {n: l for n, l in enumerate(lines) if l.strip()}
    payload = "\n".join(f"{n}| {lines[n]}" for n in sorted(idx))
    resp, finish = call(LINE_PROMPT, payload,
                        max_tokens=output_token_cap(len(payload)) + 64, **ctx)
    resp = _strip_thinking(resp)
    got = {}
    for rl in resp.split("\n"):
        m = CELL_LINE_RE.match(rl.strip())
        if m:
            got[int(m.group(1))] = m.group(2)
    malformed = set(got) != set(idx)
    if malformed:
        return {"finish": finish, "malformed": True,
                "n_got": len(got), "n_expected": len(idx),
                "lines_fixed": 0, "lines_violated": 0}
    fixed = violated = 0
    for n, new in got.items():
        old = idx[n]
        if new == old:
            continue
        if ("".join(new.split()) == "".join(old.split())
                and _num_check(old, new) is None):
            fixed += 1
        else:
            violated += 1
    return {"finish": finish, "malformed": False, "n_got": len(got),
            "lines_fixed": fixed, "lines_violated": violated}


def main():
    c = cfg.load_config()
    ctx = dict(model=c["model"], endpoint=c["endpoint"], api_key=c["api_key"],
               sampling=c.get("llm_sampling") or DEFAULT_SAMPLING)
    chunks = load_chunks()
    PROSE_IDX = [139, 140, 141, 142, 144, 145, 152]
    print(f"model={c['model']}\n")

    print("=== prose: V2 (dash/®/• protection rules) ===")
    with ThreadPoolExecutor(4) as ex:
        for i, r in zip(PROSE_IDX, ex.map(lambda i: prose_v2(chunks[i][0], ctx), PROSE_IDX)):
            print(f"  chunk {i:>4}: {r}")

    print("\n=== prose: V3 (line-mode protocol) ===")
    with ThreadPoolExecutor(4) as ex:
        for i, r in zip(PROSE_IDX, ex.map(lambda i: prose_line_mode(chunks[i][0], ctx), PROSE_IDX)):
            print(f"  chunk {i:>4}: {r}")

    print("\n=== cell malformed: raw responses (3 examples) ===")
    SUSPICIOUS_RE = re.compile(r"[a-z] [a-z]")
    shown = 0
    for i in [118, 114, 148]:
        chunk = chunks[i][0]
        for line in chunk.split("\n"):
            if not line.lstrip().startswith("|") or set(line.strip()) <= {"|", "-", " "}:
                continue
            cells = [cc.strip() for cc in line.strip().strip("|").split("|")]
            targets = [k for k, cc in enumerate(cells) if SUSPICIOUS_RE.search(cc)]
            if len(targets) < 2:
                continue
            payload = "\n".join(f"{k}| {cells[k]}" for k in targets)
            content = f"CONTEXT ROW:\n{line}\n\nCELLS:\n{payload}"
            resp, finish = call(CELL_PROMPT, content,
                                max_tokens=output_token_cap(len(payload)) + 64, **ctx)
            resp = _strip_thinking(resp)
            got = set()
            for rl in resp.split("\n"):
                m = CELL_LINE_RE.match(rl.strip())
                if m:
                    got.add(int(m.group(1)))
            if set(targets) != got:
                print(f"  chunk {i} row: {line[:100]!r}")
                print(f"    sent {len(targets)} cells {targets}; got {sorted(got)} (finish={finish})")
                print(f"    RAW: {resp[:400]!r}\n")
                shown += 1
            if shown >= 3:
                return


if __name__ == "__main__":
    main()
