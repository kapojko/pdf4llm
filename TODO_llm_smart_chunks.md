# TODO — structure-aware `--llm` pipeline

Status of the verifier-first `--llm` pipeline. Design contract: sampling is
never overridden (server-side defaults unless `llm_sampling` is configured),
every unit is verified before it is applied, failed units keep the original
text after `llm_retries` extra attempts (default 2), and rejection is always
safe (the original text is kept).

## Module layout

`llm.py` is split into focused modules: `llm_prepass`, `llm_classify`,
`llm_chunk`, `llm_prompts`, `llm_verify`, `llm_table`, `llm_salvage`,
`llm_protocol`, `llm_client`, `llm_server`, `llm_run` (plus `llm_batch`,
the cross-chunk batch scheduler).

## Resolved: WCH cell-failure investigation

The old open question (CH32V208DS0 in-run cell rejections not reproducing in
isolation) is closed. Full re-run with the current server config
(`ling-3.0-tiny-np8`, dflash, **1 worker**, server-default sampling):
**0 rejections, 0 truncated calls** vs 13/20 in the old 4/8-worker runs with
client-side sampling. The probe/production gap was server state under
multiple streams and/or sampling override, as suspected. Note: with the new
server config, 1 worker with dflash is faster than any multi-worker setup —
worker count is not a tuning knob to revisit.

## Measured cross-document baseline (current pipeline, 1 worker)

| doc | pages/chunks | rejected | cells sent/fixed | wholechunk acc | truncated | duration |
|---|---|---|---|---|---|---|
| CH32V208DS0 | 49 / 80 | 0% | 45/1 | 7/23 | 0 | 78 s |
| CH32FV2x_V3xRM | 627 / 1528 | 1.9% | 799/103 (13%) | 125/259 (48%) | 242 | 30 min |
| rm0410 (STM32F7) | 1942 / 2937 | 2.4% | 346/0 (0%) | 808/1848 (44%) | 230 | 2 h |
| SAM9X60 (Microchip) | 2288 / 3947 | **17.6%** | 3201/839 (26%) | 431/957 (45%) | **1556** | 96 min |

Conclusions drawn from this data:

- **Cell pass yield is document-class dependent, not zero.** 0–1% on
  WCH/STMCU-style docs (few suspect cells; the vocab filter now skips most),
  13–26% on dense Microchip register docs. Global demotion rejected.
- **Whole-chunk prose attempt earns its keep everywhere** (44–48% accepted,
  3–342 line-join fixes). The conditional-skip idea (old item 7) is
  rejected by measurement.
- **Two distinct failure regimes**: invariant-A drift dominates on
  prose-heavy RMs (rm0410: 1353/2000 fail entries); **missing-index
  malformed replies** dominate on dense register tables (SAM9X60: 1172/2000,
  concentrated in chunks 1190–1480, chunk 1205 = 64 alone).
- **Truncation is a shared tax**: 230–1556 calls, requeue salvages only
  6–9% of requeued units.
- The 2000-entry `unit_fail_log` cap truncates the evidence itself
  (SAM9X60: 1604 failed units vs 2000 log entries).

## Open work (priority order)

1. **Deterministic missing-index inference** — highest value.
   `malformed reply (missing index)` is the #1 SAM9X60 failure (1001 cell +
   171 line). When a batch reply contains all ordinals present and unique
   *except one*, the missing unit is unambiguously identifiable: infer it,
   then verify content as usual (invariant A still gates it). Safe, no prompt
   changes, attacks ~57% of that document's failures.
2. **Adaptive batch packing by fragment length** — the packer currently
   targets ~5k fragment chars regardless of fragment size; dense register
   cells blow the 2x-fragment output cap (1556 truncations on SAM9X60) and
   requeue only salvages 9%. Pack so estimated echo output stays under the
   cap with margin (shrink the batch when average fragment length is large)
   instead of paying a full requeue round. Measure on a SAM9X60 re-run
   before committing.
3. **Fail-log cap** — raise from 2000 to ~10k entries (or store per-reason
   counts + N samples) so full-document runs are diagnosable.
4. (Optional, low priority) NOTE hint variant for missing-index failures
   ("your previous reply dropped the index") — cheap, but item 1 makes most
   of these moot.

## Rejected ideas (recorded so they are not re-proposed)

- **JSON wire format without grammar enforcement**: adds JSON failure modes
  (unbalanced quotes, escaping — cell text contains quotes/backslashes)
  without the guarantees; +30–50% token overhead over the `N| ` protocol,
  whose string content is where errors live anyway. The indexed line
  protocol has exactly one metacharacter and is measured at zero content
  violations. (`response_format`/grammar was ruled out earlier — grammar
  masking can hurt speculative decoding.) Missing-index failures argue for
  *repairing* the indexed protocol (open item 1), not replacing it.
- **Targeted-edits-only responses** (return only changed units): a missing
  index is ambiguous between "unchanged" and "forgot" — silent recall loss,
  no recall measurability; small models are bad at "return nothing for
  unchanged". Echo-all under dflash is nearly free anyway.
- **Section-scale echo / AST rewrite** (feed whole sections, model echoes
  JSON): reintroduces the geometry/counting failure at array level (~70%
  rejection on whole-table chunks was the pipe version of the same wall);
  pays full-section output tokens to fix ~10% of content; "too-long
  section" devolves back to chunking. Geometry is code's job, cell text is
  the model's job.
- **Paired-line unit for cross-line joins**: detection unreliable on real
  extraction garbage; whole-chunk attempt covers the case.
- **Pre-built / cross-document vocabularies**: overfit risk to 1–2
  documents; per-document maps only.
- **In-place retry rounds** (re-asking the failed subset inside the same
  batch handler): replaced by pure global requeue — each retry gets a fresh
  position in the echo (drift-isolated), hints stay per-unit coherent in
  mixed-reason batches.
- **Conditional skip of whole-chunk prose attempts** for chunks without
  suspicious cross-line patterns: rejected by measurement — wholechunk yield
  is 44–48% of attempts accepted with real line-join fixes on all four
  baseline documents, nowhere near zero.
- **Global demotion of the cell pass**: rejected by measurement — yield is
  0–1% on WCH/STMCU docs but 13–26% on Microchip register docs; it is a
  document-class property, not a dead heuristic.
- **Atomic-token masking** (`[Figure-n](x,y,w,h)`, `(cid:...)`): no evidence
  — `cid_tokens` is 0 in all baseline metas and no rejection reason
  implicates atomic tokens. Keep the per-unit fallback; revisit only if
  meta stats show rejections.

## Validation status

- Full-document runs: **all done** (CH32V208DS0, CH32FV2x_V3xRM, rm0410,
  SAM9X60 — table above). Old-vs-new meta comparison done; previous
  baselines preserved in `*.meta.json.bak` / `meta_main` / `meta_smart`
  files at the document locations.
- Local model bench (`scripts/bench/`): **dropped** — model choice is
  settled on the remote dflash server, where 1 worker is fastest.
- Remaining: re-run SAM9X60 after open items 1–3 land; expect the
  missing-index share of the fail log to collapse and `truncated_calls`
  to drop.

## Done (for context)

- Canonical verifier (bidirectional dash/quote/bullet/ellipsis map,
  `\|` tolerance, numeric-token check on canonicalized text, `<br>`
  split-marker projection).
- 2x output token cap relative to fragments (was 1x; truncated 419/2936
  calls on rm0410 under the old pipeline).
- TOC-like chunk detection with deterministic skip (measured 140 on
  rm0410, matching prediction).
- Cell-level table processing: suspect cells only (dup/contained cells and
  escaped-pipe rows never sent), row as context, skeleton spliced back.
- Prose: whole-chunk attempt -> line salvage -> batched disputed-line units.
- Echo protocol (`N| text`) with per-unit verification and requeue retries.
- Cross-chunk batch aggregation, fragment-based output cap, worked examples
  in every unit prompt, `<br>` split-cell repair, heading-aligned chunk
  boundaries, in-document vocabulary SEND/SKIP filter, per-unit yield
  accounting in meta.json (`units_*`, `cells_*`, `wholechunk_*`,
  `unit_fail_log`).
- Per-unit rejection-reason hints as NOTE lines; `retries_used` counts
  extra attempts across batches.
- Sampling never overridden: no `llm_sampling` configured -> no sampling
  parameters sent at all; configured -> forwarded verbatim.
- CLI: `--llm-content-only` removed; single strict mode. Progress label
  relabelled to `no-recovery after N requeue(s)`.
- Tests: offline suite in `tests/test_llm.py` covers the batch scheduler
  (packing, requeue exhaustion, NOTE transport, kind separation, vocab
  filter, truncation requeue), `<br>` classes, heading-aligned chunking,
  multi-group parsing, adversarial verifier cases, TOC detection, escaped
  pipes, and sampling pass-through.
