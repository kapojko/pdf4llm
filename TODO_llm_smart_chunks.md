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
- **Truncation was over-counted**: the old `truncated_calls` is a per-chunk
  incidence counter, not HTTP calls. Ground truth (SAM9X60 v1.8.1 transcript,
  1070 calls): 43 real truncations (4%), all dense echo batches at cap — 19
  are renumbering drift (model restarts ordinals at 1 on requeue batches,
  whole batch lost regardless of cap), 24 genuine cap cuts (16/17 needed
  <= 1.31x cap, ~16k tokens total overrun; 7 lost nothing). Now measured
  honestly: `truncated_api_calls`.
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
   the very end (`IndexError` in `llm_batch._process_batch`) — fixed en
   route (see below), regression-tested; stats reconstructed from the
   transcript via `scripts/replay_llm_exchange.py` (970/1070 payloads
   replayed; meta `llm.replayed` records fidelity). Artifacts:
   `S:\Электроника\Microchip\SAM9X60\` (`.exchange.jsonl`, `.prellm.md`,
   `.replayed.md`, `.meta.json` with the replayed `llm` block).

   | metric | before | after |
   |---|---|---|
   | chunks rejected | 17.6% | 85/3947 (2.2%) |
   | truncated calls (per-chunk incidences) | 1556 | 242 (= 43 real calls, see run analysis) |
   | cells sent / fixed | 3201 / 839 (26%) | 3091 / 337 (11%) |
   | units sent (replay) | — | 7807, 74 batches |
   | fail-log entries | 2000 (capped) | 823, each with line/cell coords |

   Crash bug (fixed + regression-tested): a rejected whole-chunk candidate
   whose SALVAGE accepted a cross-line join shrank `out_lines`, while
   disputed line units kept their ORIGINAL indices — an accepted fix then
   applied out of range (crash) or one line off (silent misapply). Fix:
   `_salvage` returns a join-aware `line_map`; `ChunkState`
   `.set_out_lines/.apply_line` resolve apply positions through it and
   merged lines are never enqueued.

## Done: run analysis (item 7 artifacts, `S:\Электроника\Microchip\SAM9X60`)

- Item-1/2 pipeline vs baseline: rejected 694→85 chunks (2.2%), retries
  5392→660, final failed 163/7807 (2.1%), fail log 823 entries with
  line/cell coords + model (449 truncated-missing / 215 invariant-A /
  159 missing-index).
- Same-model requeue salvage measured: 43/660 = **6.5%** — escalation
  ladder (open item 1) is justified by hard data.
- Missing-index inference (item 1) never fired: the surviving failures are
  **consecutive pairs/triples**, and inference requires exactly one absent
  ordinal. Safe no-op; the tail is escalation material.
- Cell yield 26%→11% is expected: dash-bullet (554 lines) + dup-cell
  deterministic prepass fixes replaced model work. Net strongly positive.
- Truncation truth: 43/1070 calls (see corrected conclusion above); 19
  drift + 24 cap cuts. New hot spot: wide bit-matrix tables
  (`| Bit | 31 | 30 | ...` grids; chunk 1205 alone: 64 cell losses).
- Replay fidelity 970/1070 payloads (61 uncaptured, 100 unrequested) —
  stats approximate for the drifted tail; meta `duration` is replay wall
  time (real server time = sum of transcript `dt` ≈ 88 min).

## Done: cap headroom + renumbering-drift guard (v1.8.2)

1. **Cap headroom** (`llm_tokens.TokenMeter.cap_for`):
   `cap = 1.35 x EMA(kind) x echo_tokens + margin` — covers the measured
   tail error of the mean-based EMA (free: max_tokens is a limit).
2. **`truncated_api_calls`** — real finish=length HTTP calls, next to the
   incidence-based `truncated_calls` (live: 8→2 on tlv62569, 12→1 on
   CH32V208DS0).
3. **Drift guard** (`llm_batch._batch_task` / `llm_protocol._parse_reply`):
   a reply whose `N| ` ordinals are disjoint from the requested gids is
   flagged (`replies_renumbered`); a clean 1..n first-occurrence prefix is
   remapped positionally (`units_renumbered_recovered`, every text still
   passes the per-unit verifier); otherwise units fail with reason
   "renumbered reply (model drift)" and the requeue NOTE carries an
   anti-renumbering hint. Drift only ever observed on requeue batches with
   gids above the reply's 1..n range (SAM9X60: 19/43, ~1550 unit-losses —
   the dominant truncation-class damage).
- Tests: 211 in `tests/test_llm.py` (drift parse/recover/fail/hint,
  shifted-mapping safety, honest call counting, new cap formula).
- Live: 74HC_HCT74 / tlv62569 / CH32V208DS0 — 0 rejections, 0 failed
  units (`out/drift_check/`).

## Done: model-escalation probes (`scripts/exp9_escalation_probe.py`)

Two offline probes replayed failed units through candidate models with the
real protocol parser + verifier + drift recovery (production-style batches,
sampling = server defaults). Reports: `out/exp9_escalation/`.

- **163 final-failed units**: ornith-1.5-9b fixed 87–88 (53–54%),
  nemotron-74b-a9b 87 (53%), ling fresh positions 47–78 (drift variance).
  Nemotron ≈ ornith (failure overlap 60/62, rescues ~3% of ornith's tail at
  ~2.8x cost) → **dominated, not configured**. Zero drift/truncation on big
  models; ornith's fix sets identical across reps.
- **163 different fragments, same size** (borderline pool): ling 0 (heavy
  drift), ornith 32 (20%), nemotron 34 (21%, fixes 2 ornith misses).
- Conclusions: model diversity is the yield driver (53% vs 6.5% same-model
  requeue); a 16+23-unit hard core is failed by EVERY model (the
  subscript-misfire class, since resolved — see Done: underscore policy
  rebuild); same-model requeue economics refined (per round: 6.5%
  fix, ~30% unchanged echo, ~63% re-fail).

## Done: rescue pass (second-model salvage)

After the main pass drains, units failed after all retries are re-asked ONCE
on the configured rescue model (fresh gids, NOTE hint = level-0 rejection
reason, retries=0 — value is model diversity; same verifier/drift
guard/inference; sampling untouched). Fire gate `0 < failed/units_sent <=
max_fraction` (0.5; min_units dropped by decision). A rescued unit undoes
finalize-time failure accounting → chunks upgrade rejected→salvaged→accepted.
Config `llm_rescue` (model name or `[{model, max_fraction}]` levels),
`--llm-rescue MODEL` override (empty = disable), `--llm-auth` asks for it
('-' clears, empty keeps). Meta `llm.rescue = {levels[], skipped[]}`;
rescue failures join the shared fail-log with the model id. Level-0
`llm_retries=2` unchanged. Tests: 224 in `tests/test_llm.py` (13 new).

Server-behavior fixes found live (74HC_HCT74 smoke):

1. updated llama-swappy answers **503 'Loading'** while a model loads →
   bounded transport retry (`llm_client._completion_with_load_retry`,
   90 x 2 s; measured loads 75–100 s);
2. rescue TokenMeter probed the tokenizer before the model load and cached
   naive mode forever → periodic re-probe (`_PROBE_RETRY_S = 60`); explicit
   `exact=False` (offline) never probes.

Live smoke: fire path (real model switch, per-level meta), skip path, and a
4-unit ornith→ling rescue all verified; one Loading-503 hit en route → fix 1.

## Open work (priority order)

1. **NEXT: full SAM9X60 regeneration with the new code + rescue model**
   (user-run; `--llm-keep-prellm --llm-capture --llm-rescue ...`), then
   analysis of the artifacts, then this TODO gets finalized/trimmed.
   Compare against the v1.9.0 run: rejection/yield rates, rescue yield on
   a full document (probe-validated 53% on fragments, full-doc pending),
   prepass counters (spaced-underscore joins, evidence-gated subscript
   joins), and whether prompt/identifier-rule changes shift rejection
   reasons.
2. **Whole-chunk rescue for still-rejected chunks** (v2 candidate): a
   second whole-chunk echo attempt on the rescue model for chunks whose
   failures are not unit-shaped. Unmeasured on already-failed chunks;
   token-expensive (~2x chunk output). Only after unit-rescue data from
   the full-document run (open work 1).
3. **Pre-existing underscore debris in raw extraction** (small, separate
   class): a few documents ship converter artifacts like 'T_yp e' or
   'C_ADD R' (CH32FV2x headings, SAM9X60 register names) and false-split
   bitfield names ('WAIT CFG') — created by the PDF->MD converter, before
   any pdf4llm pass. Left faithful; the LLM stage may repair them
   (whitespace-only edits are verifier-legal), but no deterministic rule
   exists yet. Fixing 'WAIT CFG' -> 'WAITCFG' would also remove the one
   known false subscript join (see Done: underscore policy rebuild, item 5).

## Done: underscore policy rebuild (v1.9.1)

Human decision: **the pipeline must never insert entities the source does
not contain.** The old subscript underscore branch ('T amb' -> 'T_amb') was
an irreversible bet with a measured ~17% misfire rate (SAM9X60: 436/2591;
322 hard 'X_y z' debris shapes post-prepass, breaking prose words the LLM
could no longer repair). Landed instead:

1. `fix_subscripts` rewritten — **join-only, document-evidence-gated**:
   'V CC' -> 'VCC' only when the token 'VCC' occurs (as written) in the
   document; everything else stays as extracted. No underscores inserted.
   Whitespace-only, so verifier-legal in both directions; 2591 -> 431
   joins on SAM9X60, 1163 -> 263 on rm0410, 367 -> 108 on CH32V208DS0.
2. `fix_spaced_underscores` (new pre-pass): joins false spaces around '_'
   between word chars on both sides ('SDRAMC _ WPSR' -> 'SDRAMC_WPSR').
   One-sided variants untouched (unmeasured). 1858/119/157 joins on
   SAM9X60/rm0410/CH32FV2x, all sampled contexts register names.
3. Prompts: false "already normalised" claim replaced with the
   identifier-protection rule (TECHNICAL_SYSTEM/LINE), rule added to
   TECHNICAL_CELL (never had it); one 'V CC' -> 'VCC' example in the
   system prompt (whitespace-only, verifier-legal).
4. Hard 'X_y z' debris shapes: 322 -> 0 (SAM9X60), 8 -> 0 (rm0410).
   `_VOCAB_TOKEN_RE` moved to llm_prepass (shared with DocVocab).
   Tests: 229 in tests/test_llm.py.
5. Known limitation, accepted (694-join audit, rm0410 + SAM9X60):
   coincidental evidence can still enable a false join — the one found:
   rm0410 §9.3.6 'C FG' -> 'CFG' (2/694), attested solely by 'WAIT CFG'
   (itself a false-split bitfield name). A guard ("evidence must not
   follow an ALL-CAPS word + space") was measured — blocks exactly these
   2, zero collateral — but rejected as overfit to one example; the
   unjoined 'C FG' also reads better (preserves the C FG / C BG parallel
   structure; ALL-CAPS 'CFG' invites register-name misreading). Root
   cause: split-bitfield-name extraction class (open work 3).

Veto-heuristic experiments (scripts/exp10*_underscore_*.py: chain veto,
lowercase-evidence veto, common-English fallback) were abandoned — every
variant either false-vetoed genuine subscripts ('V DD' -> 'VDD', 63% false
for the chain rule) or needed an external lexicon; obsolete after the
insertion branch was removed.

## Rejected ideas (recorded so they are not re-proposed)

- **Subscript underscore insertion** ('T amb' -> 'T_amb'): the pipeline
  must not create entities absent from the source; measured ~17% misfire,
  unfixable downstream (prompt forbids, verifier rejects). Replaced by
  evidence-gated joining (see Done: underscore policy rebuild).
- **Subscript-insertion veto heuristics** (chain veto via _gap_suspicious
  groups, lowercase-evidence veto, common-English fallback lexicon):
  every variant either false-vetoed genuine subscripts ('V DD' -> 'VDD',
  63% false-veto for the chain rule) or needed a baked-in English lexicon;
  obsolete after the insertion branch was removed entirely.
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

- Offline suite: 229 tests in `tests/test_llm.py`.
- Underscore policy: offline-validated on 5 raw docs (SAM9X60, rm0410,
  CH32V208DS0, CH32FV2x_V3xRM, OV2640); all 694 subscript joins audited
  (2 known-false, accepted — see Done: underscore policy rebuild).
- Full-document SAM9X60 run of the item-1/2 pipeline: done, analysed (see
  Done above); artifacts on `S:\Электроника\Microchip\SAM9X60`.
- Cap headroom + drift guard: live-checked on 74HC_HCT74 / tlv62569 /
  CH32V208DS0 (`out/drift_check/`) — 0 rejections, 0 failed units.
- Rescue pass: probe-validated on SAM9X60 fail-log fragments; live-smoked
  on 74HC_HCT74 (fire + skip paths). Full-document rescue validation
  pending (open work 1: SAM9X60 regen with the new code).

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
- Tests: offline suite in `tests/test_llm.py` (211) covers the batch
  scheduler, token meter, missing-index inference, `<br>` classes,
  chunking, verifier adversarial cases, TOC detection, escaped pipes,
  sampling pass-through, join-aware line mapping (crash regression).
