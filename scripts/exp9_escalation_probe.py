"""Escalation probe: replay final-failed units through candidate models.

Takes the units that were FINALIZED as failed on the current model (fail-log
entries at attempt == retries+1), reconstructs their exact fragments and row
context from <name>.prellm.md + meta chunk_offsets, packs them into batches
exactly like llm_batch._build_payload does (incl. the NOTE hint carrying the
previous attempt's rejection reason) and sends the SAME batches to every
model listed. Each reply goes through the real protocol parser and the real
cell verifier — the gates a fix must pass in production.

Timing is split as agreed:
  * model (re)load is measured separately, with a dummy request sent right
    before each model's test run (llama-swappy loads on first request for a
    new model id; the ling baseline is already warm -> its dummy number is
    the no-reload reference);
  * the test batches themselves run warm and are timed per call, with
    completion tokens from usage -> effective decode tok/s.

Sampling is never overridden (server-side defaults; llm_sampling is not set
in config). Temperature is whatever the server configured, so replies vary
between reps — that is expected and is why the baseline runs --reps 2.

Usage:
  python scripts/exp9_escalation_probe.py [--meta PATH] [--prellm PATH]
      [--models m1,m2,...] [--reps N] [--batch-tokens N] [--limit N]
      [--out PATH]

Defaults: SAM9X60 artifacts, models = config model + ornith-1.5-9b +
nemotron-3.5-bolt-74b-a9b, reps = 1, batch budget 1500 fragment tokens
(smaller than the pipeline's 3000 to keep the slow model's per-call output
cap well under the 300 s HTTP timeout; identical batches for every model,
so the comparison stays fair).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import config, llm_protocol, llm_prompts
from pdf4llm.llm_batch import BatchScheduler, Unit
from pdf4llm.llm_table import _split_row_cells
from pdf4llm.llm_tokens import TokenMeter
from pdf4llm.llm_verify import _verify_pair

SAM = Path(r"S:\Электроника\Microchip\SAM9X60\SAM9X60-Data-Sheet-DS60001579")
CELL_PROMPT = llm_prompts.TECHNICAL_CELL_PROMPT  # SAM9X60 classified technical


def parse_args(argv: list[str]) -> dict:
    opts = {"meta": str(SAM) + ".meta.json", "prellm": str(SAM) + ".prellm.md",
            "models": "", "reps": 1, "batch_tokens": 1500, "limit": 0,
            "pool": "final",
            "out": "out/exp9_escalation/report.json"}
    rest = argv[:]
    i = 0
    while i < len(rest):
        key = rest[i]
        if not key.startswith("--"):
            raise SystemExit(f"unexpected argument: {key}")
        val = rest[i + 1]
        opts[key[2:]] = val
        i += 2
    return opts


def reconstruct_units(meta: dict, prellm: str, retries: int,
                      limit: int, pool: str = "final") -> list[Unit]:
    """Failed units -> Unit objects with exact text + row context.

    pool='final': the units FINALIZED as failed (attempt == retries+1),
    NOTE hint = previous attempt's rejection reason (the live final retry
    shape). pool='ever': every unit that failed at least once but was NOT
    finalized (the borderline pool), NOTE hint = its first failure reason.
    """
    fl = meta["llm"]["unit_fail_log"]
    if pool == "final":
        final = [e for e in fl if e["attempt"] == retries + 1]
        prev_reason = {e["gid"]: e["reason"] for e in fl
                       if e["attempt"] == retries}
    else:
        max_att: dict[int, int] = {}
        first: dict[int, dict] = {}
        for e in fl:
            max_att[e["gid"]] = max(max_att.get(e["gid"], 0), e["attempt"])
            first.setdefault(e["gid"], e)
        final = [first[g] for g, a in max_att.items() if a <= retries]
        prev_reason = {e["gid"]: e["reason"] for e in fl}
    offsets = meta["llm"]["chunk_offsets"]
    final.sort(key=lambda e: (e["chunk"], e["line"], e["cell"] or 0))
    if limit:
        # stratified: spread across reason classes
        by_reason: dict[str, list] = {}
        for e in final:
            by_reason.setdefault(e["reason"][:40], []).append(e)
        picked: list = []
        i = 0
        while len(picked) < limit:
            for lst in by_reason.values():
                if i < len(lst) and len(picked) < limit:
                    picked.append(lst[i])
            i += 1
        final = picked
    units: list[Unit] = []
    for e in final:
        s, t = offsets[e["chunk"]]
        o_lines = prellm[s:t].split("\n")
        row = o_lines[e["line"]]
        segs = _split_row_cells(row)
        if segs is None:
            print(f"  skip gid {e['gid']}: row no longer splits "
                  f"(chunk {e['chunk']} line {e['line']})")
            continue
        cells = [core for _l, core, _t in segs]
        u = Unit(e["gid"], e["chunk"], e["line"], "cell", cells[e["cell"]],
                 cell=e["cell"], context="row: " + row)
        u.attempts = retries
        u.last_fail = prev_reason.get(e["gid"])
        units.append(u)
    return units


def pack(units: list[Unit], batch_tokens: int, meter: TokenMeter
         ) -> list[list[Unit]]:
    """Same packing rule as the scheduler (kind-separated: all cells here)."""
    batches, cur, tok = [], [], 0
    for u in units:
        t = meter.count(u.text)
        if cur and tok + t > batch_tokens:
            batches.append(cur)
            cur, tok = [], 0
        cur.append(u)
        tok += t
    if cur:
        batches.append(cur)
    return batches


def dummy_load_time(model: str, endpoint: str, api_key: str) -> tuple[float, str]:
    """Dummy request timed independently: includes model (re)load when the
    server must switch models; ~warm latency otherwise."""
    t0 = time.perf_counter()
    reply, finish = llm_protocol._call_llm(
        "Reply with the single word OK.", "Ping", model, endpoint, api_key,
        output_cap_chars=10)
    return time.perf_counter() - t0, (reply or "")[:40]


def run_batches(batches: list[list[Unit]], model: str, endpoint: str,
                api_key: str, meter: TokenMeter) -> tuple[list[dict], dict]:
    """Send every batch once; verify each unit with the real gates."""
    results: list[dict] = []
    agg = {"calls": 0, "wall_s": 0.0, "prompt_tokens": 0,
           "completion_tokens": 0, "truncated_calls": 0, "drift_replies": 0}
    for bi, batch in enumerate(batches):
        payload, frag_chars = BatchScheduler._build_payload(
            object.__new__(BatchScheduler), batch)
        want = {u.gid for u in batch}
        frag_tokens = sum(meter.count(u.text) for u in batch)
        cap = meter.cap_for("cell", frag_tokens)
        usage: dict = {}
        t0 = time.perf_counter()
        got, info, finish = llm_protocol._echo_units(
            CELL_PROMPT, payload, want, model, endpoint, api_key, None,
            output_cap_tokens=cap, usage_sink=usage)
        dt = time.perf_counter() - t0
        agg["calls"] += 1
        agg["wall_s"] += dt
        agg["prompt_tokens"] += usage.get("prompt_tokens") or 0
        agg["completion_tokens"] += usage.get("completion_tokens") or 0
        if finish == "length":
            agg["truncated_calls"] += 1
        drift = bool(info is not None and not got and info.ord_seq)
        drift_recovered = 0
        if drift:
            agg["drift_replies"] += 1
            # production path (llm_batch._recover_renumbered): a clean
            # 1..n first-occurrence prefix is remapped positionally; every
            # mapped text still passes the per-unit verifier below
            n = len(batch)
            if info.ord_seq[:n] == list(range(1, n + 1)):
                for u, pos in zip(batch, range(1, n + 1)):
                    got[u.gid] = info.ord_text[pos]
                drift_recovered = n
        n_missing = sum(1 for u in batch if u.gid not in got)
        if drift_recovered:
            print(f"    drift recovered positionally: {drift_recovered} units")
        for ordinal, u in enumerate(batch, 1):
            new = got.get(u.gid)
            if new is None:
                reason = (f"renumbered reply (drift, {drift_recovered} rec)" if drift else
                          "missing from truncated output" if finish == "length"
                          else "malformed reply (missing index)")
                outcome = "failed"
            elif not new.strip() or new.strip() == u.text.strip():
                outcome, reason = "unchanged", None
            else:
                reason = _verify_pair(u.text, new.strip())
                outcome = "failed" if reason is not None else "fixed"
            results.append({
                "gid": u.gid, "batch": bi, "chunk": u.chunk, "line": u.line,
                "cell": u.cell, "orig_fail": u.last_fail,
                "outcome": outcome, "reason": (reason or "")[:100],
                "batch_s": round(dt, 2), "frag_tokens": frag_tokens,
                "cap": cap, "finish": finish, "n_missing": n_missing,
                "reply_chars": len(got.get(u.gid, "") or ""),
            })
        print(f"    batch {bi + 1}/{len(batches)}: {len(batch)} units, "
              f"{frag_tokens} frag tok, cap {cap}, {dt:.1f}s, finish={finish}"
              f"{', DRIFT' if drift else ''}, missing={n_missing}")
    return results, agg


def main() -> int:
    o = parse_args(sys.argv[1:])
    c = config.load_config()
    endpoint, api_key = c["endpoint"], c["api_key"]
    models = ([m.strip() for m in o["models"].split(",") if m.strip()]
              or [c["model"], "ornith-1.5-9b", "nemotron-3.5-bolt-74b-a9b"])
    reps = int(o["reps"])
    retries = int(c.get("llm_retries", 2))

    meta = json.loads(Path(o["meta"]).read_text(encoding="utf-8"))
    prellm = Path(o["prellm"]).read_text(encoding="utf-8")
    units = reconstruct_units(meta, prellm, retries, int(o["limit"]),
                              pool=o.get("pool", "final"))
    n_by_reason: dict[str, int] = {}
    for u in units:
        n_by_reason[u.last_fail or "?"] = n_by_reason.get(u.last_fail or "?", 0) + 1
    print(f"probe: {len(units)} final-failed unit(s) {n_by_reason}; "
          f"models={models}, reps={reps}, batch_tokens={o['batch_tokens']}")

    # batches are built ONCE (packing meter is per-model only for token
    # counts; build with the first model's meter, counts are cached text->n)
    meter0 = TokenMeter(models[0], endpoint, api_key)
    batches = pack(units, int(o["batch_tokens"]), meter0)
    print(f"probe: {len(batches)} batch(es), "
          f"frag sizes {[len(b) for b in batches]}")

    report: dict = {"units": len(units), "reps": reps,
                    "batch_tokens": int(o["batch_tokens"]), "models": {}}
    for model in models:
        print(f"== {model} ==")
        load_s, dummy_reply = dummy_load_time(model, endpoint, api_key)
        print(f"  dummy/load request: {load_s:.1f}s (reply {dummy_reply!r})")
        m_report = {"load_dummy_s": round(load_s, 2), "reps": []}
        for rep in range(reps):
            meter = TokenMeter(model, endpoint, api_key)
            results, agg = run_batches(batches, model, endpoint, api_key, meter)
            outcomes = {k: sum(1 for r in results if r["outcome"] == k)
                        for k in ("fixed", "failed", "unchanged")}
            m_report["reps"].append({
                "outcomes": outcomes,
                "by_reason": _by_reason(results),
                "calls": agg["calls"],
                "wall_s": round(agg["wall_s"], 1),
                "prompt_tokens": agg["prompt_tokens"],
                "completion_tokens": agg["completion_tokens"],
                "tok_per_s": round(agg["completion_tokens"]
                                   / max(agg["wall_s"], 1e-9), 1),
                "truncated_calls": agg["truncated_calls"],
                "drift_replies": agg["drift_replies"],
                "results": results,
            })
            print(f"  rep {rep + 1}: {outcomes['fixed']} fixed, "
                  f"{outcomes['failed']} failed, {outcomes['unchanged']} "
                  f"unchanged | {agg['wall_s']:.1f}s warm, "
                  f"{agg['completion_tokens']} out tok "
                  f"({agg['completion_tokens'] / max(agg['wall_s'], 1e-9):.1f} tok/s), "
                  f"truncated={agg['truncated_calls']}, drift={agg['drift_replies']}")
        report["models"][model] = m_report

    out = Path(o["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False),
                   encoding="utf-8")
    print(f"probe: report written to {out}")
    return 0


def _by_reason(results: list[dict]) -> dict:
    """Outcome breakdown per ORIGINAL failure class."""
    out: dict[str, dict] = {}
    for r in results:
        key = (r["orig_fail"] or "?")[:40]
        d = out.setdefault(key, {"n": 0, "fixed": 0, "failed": 0,
                                 "unchanged": 0})
        d["n"] += 1
        d[r["outcome"]] += 1
    return out


if __name__ == "__main__":
    raise SystemExit(main())
