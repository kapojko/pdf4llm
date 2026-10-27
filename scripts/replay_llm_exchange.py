"""One-off: reconstruct LLM-pass stats from a captured --llm exchange.

A run that crashes (or is killed) after the LLM pass started loses its
meta.json ``llm`` block — but with ``--llm-capture`` every request/reply
pair was flushed to <name>.exchange.jsonl as it happened. This script
replays the captured transcript through the real pipeline:

  * the captured replies are served by a fake transport (no model calls);
  * the server tokenizer is still probed for exact fragment token counts,
    so batch packing reproduces the live request sequence;
  * the captured per-call token usage feeds the meter's EMA, as live.

When every captured payload is consumed exactly once, the replay is
request-for-request identical to the live run (workers=1 default), and the
resulting stats + corrected text are what the crashed run would have
produced — with the crashing batch now applying cleanly (post-fix).

Usage:
  python scripts/replay_llm_exchange.py <converted.md> [options]

  --exchange PATH   transcript (default: <stem>.exchange.jsonl next to input)
  --model NAME      model id (default: config)
  --out PATH        write the corrected text here (default: print stats only)
  --write-meta PATH merge the replayed llm stats into this meta.json
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import checks, config, llm_prompts, llm_protocol, llm_run


def parse_opts(argv: list[str]) -> tuple[Path, dict[str, str]]:
    md_path = Path(argv[0])
    opts: dict[str, str] = {}
    rest = argv[1:]
    i = 0
    while i < len(rest):
        key = rest[i]
        if not key.startswith("--"):
            raise SystemExit(f"unexpected argument: {key}")
        if i + 1 < len(rest) and not rest[i + 1].startswith("--"):
            opts[key] = rest[i + 1]
            i += 2
        else:
            opts[key] = ""
            i += 1
    return md_path, opts


def main() -> int:
    if not sys.argv[1:]:
        print(__doc__)
        return 2
    md_path, opts = parse_opts(sys.argv[1:])
    exchange = Path(opts.get("--exchange",
                             md_path.with_suffix(".exchange.jsonl")))
    model = opts.get("--model") or config.load_config().get("model")
    if not model:
        print("error: no model (pass --model or configure one)", file=sys.stderr)
        return 2

    entries = [json.loads(line) for line in
               exchange.read_text(encoding="utf-8").splitlines() if line.strip()]
    # index by request payload; identical payloads must carry identical replies
    by_user: dict[str, dict] = {}
    for e in entries:
        prev = by_user.get(e["user"])
        if prev is not None and (prev["reply"], prev["finish"]) != \
                (e["reply"], e["finish"]):
            print("error: conflicting replies for one payload "
                  f"({e['user'][:60]!r}...)", file=sys.stderr)
            return 2
        by_user[e["user"]] = e
    print(f"  replay: {len(entries)} captured exchange(s), "
          f"{len(by_user)} unique payload(s)")

    # classification never goes through the captured transport (litellm
    # direct) — recover its result from the captured system prompt instead
    first_system = entries[0]["system"] if entries else ""
    is_technical = first_system != llm_prompts.GENERAL_SYSTEM_PROMPT

    unmatched: list[str] = []
    matched = [0]

    def replaying(system, user, *a, **kw):
        e = by_user.pop(user, None)
        if e is None:
            unmatched.append(user)
            return user, None  # neutral echo: verifies as unchanged, no fix
        matched[0] += 1
        sink = kw.get("usage_sink")
        if sink is not None:
            sink["prompt_tokens"] = e.get("prompt_tokens")
            sink["completion_tokens"] = e.get("completion_tokens")
        return e["reply"], e["finish"]

    real_call = llm_run._call_llm
    real_classify = llm_run.classify_with_llm
    llm_run._call_llm = replaying
    llm_protocol._call_llm = replaying
    llm_run.classify_with_llm = (  # no model call: verdict from the capture
        lambda *a, **kw: (is_technical, "replayed-from-capture"))
    try:
        c = config.load_config()
        text = md_path.read_text(encoding="utf-8")

        # sanity: the input must reproduce the captured prellm snapshot
        # (proves the prepass chain is idempotent on this input)
        prellm_snapshot = md_path.with_suffix(".prellm.md")
        tmp = None
        if prellm_snapshot.exists():
            tmp = tempfile.NamedTemporaryFile(
                suffix=".md", delete=False)
            tmp.close()
        corrected, stats = llm_run.correct_with_llm(
            text, model, c.get("endpoint"), c.get("api_key"), verbose=False,
            sampling=c.get("llm_sampling"),
            retries=int(c.get("llm_retries", 2)),
            max_chars=int(c.get("llm_chunk_chars", 2000)),
            keep_prellm=(tmp.name if tmp is not None else None),
        )
        if tmp is not None:
            replayed_prellm = Path(tmp.name).read_text(encoding="utf-8")
            live_prellm = prellm_snapshot.read_text(encoding="utf-8")
            if replayed_prellm != live_prellm:
                print("  replay: WARNING — prepass output differs from the "
                      "captured <name>.prellm.md; batch boundaries may drift",
                      file=sys.stderr)
            else:
                print("  replay: prepass output matches the captured "
                      "<name>.prellm.md exactly")
            Path(tmp.name).unlink()
    finally:
        llm_run._call_llm = real_call
        llm_protocol._call_llm = real_call
        llm_run.classify_with_llm = real_classify

    n_left = len(by_user)
    print(f"  replay: {matched[0]} payload(s) served, {n_left} captured but "
          f"never requested, {len(unmatched)} request(s) without capture")
    if n_left or unmatched:
        print("  replay: WARNING — sequence not fully reproduced; stats are "
              "approximate for the affected units")

    stats["replayed"] = {
        "exchange": str(exchange),
        "captured": len(entries),
        "matched": matched[0],
        "unmatched_requests": len(unmatched),
        "uncaptured_requests": n_left,
    }

    if "--out" in opts:
        Path(opts["--out"]).write_text(corrected, encoding="utf-8")
        print(f"  replay: corrected text written to {opts['--out']}")

    meta_path = opts.get("--write-meta")
    if meta_path:
        meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
        meta["llm"] = stats
        meta["llm_model"] = model
        meta["checks"] = checks.run_checks(corrected, meta["page_chars"])
        Path(meta_path).write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  replay: llm stats merged into {meta_path}")

    print(f"  replay: {stats['chunks_total']} chunks "
          f"({stats['chunks_accepted']} accepted, {stats['chunks_salvaged']} "
          f"salvaged, {stats['chunks_rejected']} rejected, "
          f"{stats['chunks_toc_skipped']} toc-skipped); "
          f"{stats['units_sent']} units sent in {stats['batches']} batch(es), "
          f"{stats['blocks_fixed']} fixed, {stats['units_failed']} failed, "
          f"{stats['units_skipped']} vocab-skipped; "
          f"{stats['truncated_calls']} truncated calls; pipeline time "
          f"{stats['duration']:.0f}s (excl. server latency)")
    return 0 if (not n_left and not unmatched) else 1


if __name__ == "__main__":
    raise SystemExit(main())
