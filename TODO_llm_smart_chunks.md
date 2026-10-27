# TODO — structure-aware `--llm` pipeline

Status of the verifier-first `--llm` pipeline. Design contract: sampling is
never overridden (server-side defaults unless `llm_sampling` is configured),
every unit is verified before it is applied, failed units keep the original
text after `llm_retries` extra attempts (default 2), and rejection is always
safe (the original text is kept).

## Module layout

Focused modules: `llm_prepass`, `llm_classify`, `llm_chunk`, `llm_prompts`,
`llm_verify`, `llm_table`, `llm_salvage`, `llm_protocol`, `llm_client`,
`llm_tokens` (token counting + output budget), `llm_server`, `llm_run`
(plus `llm_batch`, the cross-chunk batch scheduler).

## Measured cross-document baseline (pre-item-1/2 pipeline, 1 worker)

| doc | pages/chunks | rejected | cells sent/fixed | wholechunk acc | truncated | duration |
|---|---|---|---|---|---|---|
| CH32V208DS0 | 49 / 80 | 0% | 45/1 | 7/23 | 0 | 78 s |
| CH32FV2x_V3xRM | 627 / 1528 | 1.9% | 799/103 (13%) | 125/259 (48%) | 242 | 30 min |
| rm0410 (STM32F7) | 1942 / 2937 | 2.4% | 346/0 (0%) | 808/1848 (44%) | 230 | 2 h |
| SAM9X60 (Microchip) | 2288 / 3947 | **17.6%** | 3201/839 (26%) | 431/957 (45%) | **1556** | 96 min |

Conclusions:

- **Cell pass yield is document-class dependent, not zero.** 0–1% on
  WCH/STMCU-style docs, 13–26% on dense Microchip register docs. Global
  demotion rejected.
- **Whole-chunk prose attempt earns its keep everywhere** (44–48% accepted).
  Conditional skip rejected by measurement.
- **Two failure regimes**: invariant-A drift dominates on prose-heavy RMs
  (rm0410: 1353/2000 fail entries); **missing-index malformed replies**
  dominate on dense register tables (SAM9X60: 1172/2000, chunks 1190–1480).
- **Truncation is a shared tax**: 230–1556 calls, requeue salvages only
  6–9% of requeued units.
- Server tokenizer (llama-swappy `/llama/tokenize`, routed since 1.3+):
  prose 3.3 chars/token, dense cells/hex ~2.2–2.5 — the old 3.5 scalar was
  3x wrong for dense batches, baking truncation in.

## Resolved: model-unreachable failure classes (SAM9X60 fragment experiments)

Top SAM9X60 failure classes are **independent of the model** — invariant A
cannot accept the repair any model would produce. Fixed deterministically:

- **Dash bullets (`- –   text`, 554 lines)**: two-level '•'/'–' lists;
  `llm_prepass.fix_dash_bullets` nests/flattens deterministically, never
  matches without whitespace after the glyph. meta: `dash_bullets_fixed`.
- **Container-direction duplicate cells (RGBMODE-style, 1454 rows)**:
  `llm_table.dup_cell_indices` skips both directions (contained-key >= 8,
  3x container ratio; false skip only loses a fix, safe rejection is cheap).

## Done: items 1–5 (approved plan, all landed)

1. **Missing-index inference** (`llm_protocol._parse_reply` +
   `llm_batch._try_infer_missing`): when exactly one requested ordinal is
   absent (no duplicates, no truncation), recover it from (a) the previous
   unit's continuation-merged echo or (b) an orphan block after a
   CONTEXT/NOTE reset; every candidate passes the unit verifier, ambiguity
   keeps the normal failure path. meta: `units_inferred_missing`.
   Bug found + fixed en route: two fixed cells of the SAME row overwrote
   each other; splicing is now cumulative.
2. **Exact-token cap and packing** (`llm_tokens.TokenMeter`): exact counts
   via the server tokenizer (cached, lazy-probed), naive `1 char = 1 token`
   fallback (pessimistic only). Cap = `EMA(kind) x echo_tokens + 256`, EMA
   learned from `usage.completion_tokens` per batch kind (init 2.0, clamp
   1–8). Packing by fragment tokens (`BATCH_TOKENS = 3000`, was 10000
   chars); CLI `--llm-batch-chars` -> `--llm-batch-tokens`. Context check
   counts the largest chunk exactly. meta: `tokens` block, `truncation_log`.
3. **Fail-log cap** 2000 -> 10k; entries carry `model`.
4. **Meta**: `chunk_offsets` ([start, end) per chunk, post-prepass text) +
   the above; per-chunk rollup skipped (derivable).
5. **Live capture run** (`out/exp_missing_index/`): six worst SAM9X60
   missing-index chunks through the real pipeline — 0 failures, 0 truncated,
   0 missing-index; exact tokenizer active, EMA learned ~1.75. Inference
   validated by replaying the REAL captured payload/reply with one index
   dropped (both shapes recovered, packing determinism proven).
   Side fix: whitespace-only chunks (table + trailing blanks) are never
   sent to the model (`test_blank_chunk_never_sent`).
6. **Escalation-experiment groundwork**: fail-log entries carry `line`/`cell`
   (exact unit coordinates -> fragment reconstruction via `chunk_offsets`);
   CLI flags `--llm-keep-prellm` (writes `<name>.prellm.md`, the post-prepass
   text chunk_offsets refer to) and `--llm-capture` (writes
   `<name>.exchange.jsonl`, the full request/reply transcript incl. token
   usage). Both opt-in; smoke: 32 KB prellm + 56 KB transcript on 74HC_HCT74.
7. **Full SAM9X60 re-run** (`--llm-keep-prellm --llm-capture`): crashed at
   the very end with `IndexError: list assignment index out of range`
   (`llm_batch._process_batch`) — fixed en route (see below); 1.5 h of
   conversion survived (crash was in the LLM stage, after the .md was
   written), and the full exchange transcript + prellm snapshot are on disk.
   Stats reconstructed from the transcript via
   `scripts/replay_llm_exchange.py` (offline; 970/1070 captured payloads
   replayed exactly, remainder lost to batch-composition drift under
   replay-time — the meta `llm.replayed` block records the fidelity).
   **Recorded in `<doc>.meta.json` (`llm` block) next to the document;
   analysis is the next step.**

   Measured (item 1–2 pipeline vs the pre-item-1/2 baseline row):

   | metric | before | after |
   |---|---|---|
   | chunks rejected | 17.6% | 85/3947 (2.2%) |
   | truncated calls | 1556 | 242 |
   | cells sent / fixed | 3201 / 839 (26%) | 3091 / 337 (11%) |
   | units sent (replay) | — | 7807, 74 batches |
   | fail-log entries | 2000 (capped) | 823, each with line/cell coords |

   The 242 remaining truncated calls are dense CELL batches finishing at
   their exact caps (`truncation_log`: kind=cell, completion_tokens == cap);
   the fail log (spread over chunks 10–1410) is now dominated by "missing
   from truncated output" (449) with "malformed reply (missing index)"
   down to 159 (was 1172) — replay material for open item 2. Crash bug
   (fixed + regression-tested, tests 133 in
   `test_llm.py`): a rejected whole-chunk candidate whose SALVAGE accepted a
   cross-line join shrank `out_lines`, while disputed line units kept their
   ORIGINAL indices — an accepted fix then applied out of range (crash) or
   one line off (silent misapply). Fix: `_salvage` returns a join-aware
   `line_map` (original index -> output position, None = merged into an
   accepted block); `ChunkState.set_out_lines/apply_line` resolve apply
   positions through it and merged lines are never enqueued.

## Open work (priority order)

1. (Optional, low priority) NOTE hint variant for missing-index failures —
   mostly moot after item 1.
2. **Model escalation ladder for exhausted retries** — same-model requeue
   salvages only 6-9% of requeued units. Design (agreed): auto-switching
   proxy on the server (switching = changing the model id); config
   `llm_escalation: [{model, max_fraction, min_units}, ...]` via
   `--llm-auth` (level 0 = existing `model`). Salvage passes run AFTER the
   main pass: each level fires only if
   `failed_units/units_sent <= max_fraction` AND `failed_units >= min_units`
   (defaults 0.5 then 0.1). Reuses the batch scheduler/verifier/NOTE hints
   with fresh batch positions; final failures keep the original text;
   sampling stays server-side per model. Scope v1: units only. meta:
   per-level `escalation: [{model, units_sent, units_fixed,
   truncated_calls, duration}]` + `escalation_skipped` reasons; the
   fail-log `model` field is already in place. Prereqs (items 1–2) landed.
   Validate on the deferred full SAM9X60 re-run.

## Rejected ideas (recorded so they are not re-proposed)

- **JSON wire format without grammar enforcement**: adds JSON failure modes
  without the guarantees; +30–50% token overhead over the `N| ` protocol,
  measured at zero content violations. (`response_format`/grammar ruled out
  earlier — grammar masking can hurt speculative decoding.)
- **Targeted-edits-only responses** (return only changed units): a missing
  index is ambiguous between "unchanged" and "forgot" — silent recall loss.
  Echo-all under dflash is nearly free anyway.
- **Section-scale echo / AST rewrite**: reintroduces the geometry/counting
  failure at array level; pays full-section output tokens to fix ~10% of
  content. Geometry is code's job, cell text is the model's job.
- **Paired-line unit for cross-line joins**: detection unreliable on real
  extraction garbage; whole-chunk attempt covers the case.
- **Pre-built / cross-document vocabularies**: overfit risk; per-document
  maps only.
- **In-place retry rounds**: replaced by pure global requeue — each retry
  gets a fresh position in the echo (drift-isolated), hints stay per-unit
  coherent in mixed-reason batches.
- **Conditional skip of whole-chunk prose attempts**: rejected by
  measurement — wholechunk yield is 44–48%, nowhere near zero.
- **Global demotion of the cell pass**: rejected by measurement — yield is
  a document-class property (0–1% WCH/ST vs 13–26% Microchip).
- **Atomic-token masking** (`[Figure-n](x,y,w,h)`, `(cid:...)`): no
  evidence — `cid_tokens` is 0 in all baseline metas.

## Validation status

- Full-document runs of the pre-item-1/2 pipeline: all done (table above);
  baselines preserved next to the documents.
- Items 1–5 validation: offline suite; live fragment run + real-content
  replay (see item 5); finalize check on 74HC_HCT74 / tlv62569 /
  CH32V208DS0 — 0 rejections, 0 failed units, 0 truncated calls, meta
  additions present (`out/finalize_check/`).
- Item 7: full SAM9X60 run executed (crashed at the end; bug fixed, stats
  reconstructed — see above). Artifacts on disk next to the PDF:
  `.exchange.jsonl` (1070 request/reply pairs, raw material for the
  escalation experiment), `.prellm.md`, `.replayed.md` (reconstructed
  corrected text), `.meta.json` with the replayed `llm` stats block.
- Remaining: **analyse the recorded SAM9X60 stats + transcript** (next
  session), then implement open item 2.

## Done (for context)

- Canonical verifier (bidirectional dash/quote/bullet/ellipsis map,
  `\|` tolerance, numeric-token check on canonicalized text, `<br>`
  split-marker projection).
- TOC-like chunk detection with deterministic skip (140 on rm0410).
- Cell-level table processing: suspect cells only (dup/contained cells and
  escaped-pipe rows never sent), row as context, skeleton spliced back.
- Prose: whole-chunk attempt -> line salvage -> batched disputed-line units.
- Echo protocol (`N| text`) with per-unit verification and requeue retries.
- Cross-chunk batch aggregation, worked examples in every unit prompt,
  `<br>` split-cell repair, heading-aligned chunk boundaries, in-document
  vocabulary SEND/SKIP filter, per-unit yield accounting in meta.json.
- Per-unit rejection-reason hints as NOTE lines.
- Sampling never overridden; CLI single strict mode.
- Tests: offline suite in `tests/test_llm.py` (133) covers the batch
  scheduler, token meter, missing-index inference, `<br>` classes,
  chunking, verifier adversarial cases, TOC detection, escaped pipes,
  sampling pass-through, join-aware line mapping (crash regression).
