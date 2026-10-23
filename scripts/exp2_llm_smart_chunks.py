"""Experiment 2: LLM experiments for smart-chunk planning.

For a stratified sample of chunks (TOC-like tables, register-map tables, prose):
  A. BASELINE: one call with the current output_token_cap -> verdict + finish_reason.
  B. RAISED CAP: for every chunk that truncated in A, re-call with 4x cap and
     check whether the FULL output now passes _verify_chunk
     (answers: would raising the cap convert truncation-rejects into accepts?).
  C. CELL MODE: for table chunks, only suspicious cells are sent, one per line
     with an index prefix and the raw row as context; every returned cell is
     verified individually (whitespace-only + numeric tokens) and spliced back.
     Measures per-cell acceptance and end-to-end chunk completion.

No retries anywhere: single call per unit, we measure first-shot behaviour.
"""
from __future__ import annotations

import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import config as cfg
from pdf4llm.llm_chunk import chunk_markdown
from pdf4llm.llm_client import (
    DEFAULT_SAMPLING,
    _split_sampling,
    _strip_thinking,
    output_token_cap,
)
from pdf4llm.llm_prepass import (
    collapse_dot_leaders,
    dedupe_bullets,
    fix_subscripts,
    strip_horizontal_rules,
)
from pdf4llm.llm_verify import _num_check, _verify_chunk

MD = Path("examples/rm0410-stm32f76xxx-and-stm32f77xxx-advanced-armbased-32bit-mcus-stmicroelectronics.md")
MAX_CHARS = 2000
N_PER_CLASS = 8
WORKERS = 6

SUSPICIOUS_RE = re.compile(r"[a-z] [a-z]")
CELL_LINE_RE = re.compile(r"^\s*(\d+)\s*\|\s?(.*)$", re.DOTALL)

BASELINE_PROMPT = (
    "You fix whitespace defects in extracted PDF-to-Markdown text.\n"
    "ALLOWED ONLY: remove stray spaces inside words; collapse space runs; "
    "delete false line breaks inside a paragraph.\n"
    "FORBIDDEN: changing ANY non-whitespace character; removing/adding table "
    "rows or '|' characters; changing any digit; comments or explanations.\n"
    "Return ONLY the corrected Markdown, nothing else."
)

CELL_PROMPT = (
    "You fix whitespace defects in text extracted from a PDF table.\n"
    "First you see the original table row (CONTEXT). Then lines 'N| text': "
    "each is one table cell that contains falsely split words.\n"
    "Fix ONLY false spaces inside words ('D-t yp e' -> 'D-type', 'fli p -flo p' "
    "-> 'flip-flop'). Keep every digit, number, hex value, unit and symbol "
    "exactly as-is. Do not merge numbers ('2 0' must stay '2 0').\n"
    "Return EXACTLY the same 'N| ...' lines: same count, same order, same "
    "numbers after '|'. Nothing else."
)


def load_chunks():
    text = MD.read_text(encoding="utf-8")
    text = dedupe_bullets(text)
    text, _ = strip_horizontal_rules(text)
    text, _ = collapse_dot_leaders(text)
    text, _ = fix_subscripts(text)
    return chunk_markdown(text, MAX_CHARS)


def classify_chunks(chunks):
    toc, reg, prose = [], [], []
    for i, (chunk, _sep) in enumerate(chunks):
        rows = [l for l in chunk.split("\n") if l.lstrip().startswith("|")]
        if not rows:
            prose.append(i)
            continue
        long_dup = False
        for row in rows:
            cells = [c.strip() for c in row.strip().strip("|").split("|") if c.strip()]
            dups = {c for c in cells if cells.count(c) > 1 and len(c) > 25}
            if dups:
                long_dup = True
                break
        (toc if long_dup else reg).append(i)
    return toc, reg, prose


def call(prompt_system, content, model, endpoint, api_key, max_tokens, sampling=None):
    import litellm
    litellm.suppress_debug_info = True
    std, extra = _split_sampling(sampling or DEFAULT_SAMPLING)
    resp = litellm.completion(
        model=f"openai/{model}",
        messages=[{"role": "system", "content": prompt_system},
                  {"role": "user", "content": content}],
        api_base=endpoint, api_key=api_key,
        max_tokens=max_tokens, timeout=300,
        extra_body={**extra, "chat_template_kwargs": {"enable_thinking": False}},
        **std,
    )
    finish = getattr(resp.choices[0], "finish_reason", None)
    return (resp.choices[0].message.content or "").strip(), finish


# --- A. baseline ------------------------------------------------------------

def baseline_one(i, chunk, ctx):
    t0 = time.monotonic()
    try:
        cand, finish = call(BASELINE_PROMPT, chunk,
                            max_tokens=output_token_cap(len(chunk)), **ctx)
    except Exception as e:
        return {"i": i, "kind": None, "error": f"{type(e).__name__}: {e}", "dt": time.monotonic() - t0}
    cand = _strip_thinking(cand)
    reason = _verify_chunk(chunk, cand)
    return {"i": i, "chars": len(chunk), "out_chars": len(cand), "finish": finish,
            "verdict": "accepted" if reason is None else f"rejected: {reason}",
            "dt": time.monotonic() - t0}


# --- B. raised cap on truncated chunks --------------------------------------

def raised_cap_one(i, chunk, ctx):
    try:
        cand, finish = call(BASELINE_PROMPT, chunk,
                            max_tokens=output_token_cap(len(chunk)) * 4, **ctx)
    except Exception as e:
        return {"i": i, "error": f"{type(e).__name__}: {e}"}
    cand = _strip_thinking(cand)
    reason = _verify_chunk(chunk, cand)
    return {"i": i, "out_chars": len(cand), "finish": finish,
            "verdict": "accepted" if reason is None else f"rejected: {reason}"}


# --- C. cell mode -----------------------------------------------------------

def row_cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def cell_mode_chunk(i, chunk, ctx):
    """Send only suspicious cells of each row; verify+splice per cell."""
    lines = chunk.split("\n")
    t0 = time.monotonic()
    n_cells_sent = n_cells_fixed = n_cells_failed = 0
    malformed = 0
    out_lines = list(lines)
    for li, line in enumerate(lines):
        if not line.lstrip().startswith("|") or set(line.strip()) <= {"|", "-", " "}:
            continue  # separator / non-table line untouched
        cells = row_cells(line)
        targets = [k for k, c in enumerate(cells) if SUSPICIOUS_RE.search(c)]
        if not targets:
            continue
        payload = "\n".join(f"{k}| {cells[k]}" for k in targets)
        content = f"CONTEXT ROW:\n{line}\n\nCELLS:\n{payload}"
        try:
            resp, finish = call(CELL_PROMPT, content,
                                max_tokens=output_token_cap(len(payload)) + 64, **ctx)
        except Exception as e:
            malformed += 1
            continue
        resp = _strip_thinking(resp)
        got = {}
        for rl in resp.split("\n"):
            m = CELL_LINE_RE.match(rl.strip())
            if m:
                got[int(m.group(1))] = m.group(2).strip()
        if set(got) != set(targets):
            malformed += 1
            continue  # group failed: cells fall back to original
        for k in targets:
            n_cells_sent += 1
            orig_cell, new_cell = cells[k], got[k]
            if new_cell == orig_cell:
                continue
            if ("".join(new_cell.split()) == "".join(orig_cell.split())
                    and _num_check(orig_cell, new_cell) is None):
                n_cells_fixed += 1
                cells[k] = new_cell
            else:
                n_cells_failed += 1
        out_lines[li] = "|" + "|".join(f" {c} " for c in cells) + "|"
    fixed_chunk = "\n".join(out_lines)
    # end-to-end: does the spliced chunk still satisfy the strict verifier
    # against the original (it must, by construction — but check)?
    final_reason = _verify_chunk(chunk, fixed_chunk)
    return {"i": i, "cells_sent": n_cells_sent, "cells_fixed": n_cells_fixed,
            "cells_failed": n_cells_failed, "malformed_groups": malformed,
            "final_safe": final_reason is None, "dt": time.monotonic() - t0}


def main():
    c = cfg.load_config()
    endpoint, api_key, model = c["endpoint"], c["api_key"], c["model"]
    sampling = c.get("llm_sampling") or DEFAULT_SAMPLING
    print(f"model={model} endpoint={endpoint}\n")

    chunks = load_chunks()
    toc, reg, prose = classify_chunks(chunks)
    print(f"class sizes: toc-like={len(toc)} register-map={len(reg)} prose={len(prose)}")
    sample = (toc[:N_PER_CLASS], reg[:N_PER_CLASS], prose[:N_PER_CLASS])

    ctx = dict(model=model, endpoint=endpoint, api_key=api_key, sampling=sampling)

    # A. baseline
    print("\n=== A. BASELINE (current cap) ===")
    jobs = [(i, chunks[i][0], ctx, kind)
            for kind, idxs in zip(("toc", "reg", "prose"), sample) for i in idxs]
    results = {}
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(baseline_one, i, ch, ctx): (i, kind)
                for i, ch, kind in [(i, chunks[i][0], k) for k, idxs in zip(("toc", "reg", "prose"), sample) for i in idxs]}
        for f in futs:
            i, kind = futs[f]
            results[i] = {**f.result(), "kind": kind}
    for i in sorted(results):
        r = results[i]
        print(f"  [{r['kind']:>4}] chunk {i:>4} {r.get('chars','?'):>5}ch "
              f"finish={r.get('finish')} -> {r.get('verdict', r.get('error'))} "
              f"({r.get('dt', 0):.1f}s)")

    # B. raised cap for truncated ones
    trunc = [i for i, r in results.items() if r.get("finish") == "length"]
    print(f"\n=== B. RAISED CAP (4x) for {len(trunc)} truncated chunks ===")
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(raised_cap_one, i, chunks[i][0], ctx): i for i in trunc}
        for f in futs:
            i = futs[f]
            print(f"  chunk {i:>4} -> {f.result()}")

    # C. cell mode on table chunks
    print("\n=== C. CELL MODE (table chunks only) ===")
    table_jobs = [i for kind, idxs in zip(("toc", "reg"), sample[:2]) for i in idxs]
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(cell_mode_chunk, i, chunks[i][0], ctx): i for i in table_jobs}
        tot_sent = tot_fixed = tot_failed = tot_malformed = 0
        for f in futs:
            i = futs[f]
            r = f.result()
            tot_sent += r["cells_sent"]; tot_fixed += r["cells_fixed"]
            tot_failed += r["cells_failed"]; tot_malformed += r["malformed_groups"]
            print(f"  [{results[i]['kind']:>4}] chunk {i:>4}: sent={r['cells_sent']} "
                  f"fixed={r['cells_fixed']} failed={r['cells_failed']} "
                  f"malformed={r['malformed_groups']} final_safe={r['final_safe']} "
                  f"({r['dt']:.1f}s)")
    print(f"\n  TOTAL cells: sent={tot_sent} fixed={tot_fixed} failed={tot_failed} "
          f"malformed_groups={tot_malformed}")


if __name__ == "__main__":
    main()
