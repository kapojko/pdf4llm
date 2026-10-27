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

## Resolved: model-unreachable failure classes (SAM9X60 fragment experiments)

Fragment-level reproduction runs (`out/exp_fragments/`, real pipeline with
captured request/reply logs) on the worst SAM9X60 chunks showed the top
failure classes are **independent of the model** — under invariant A the
desired repair is outside the verifier's acceptance set, so no model can
produce it; the only passing output is the verbatim echo (no repair):

- **Marker + en/em dash bullets (`- –   text`, 554 lines)**: the PDF uses
  two-level lists ('•' top, '–' sub-items); the converter emits the marker
  AND keeps the glyph. Models invariably delete the marker (content change
  -> rejection, all retries, NOTE hints don't help). Fixed deterministically:
  `llm_prepass.fix_dash_bullets` nests under the preceding list item (runs
  inherit the previous dash item's level; page-break `---` artifacts are
  stripped first so hr-split lists resolve), flattens when the context is a
  paragraph/heading (top-level '–' list), and never matches without
  whitespace after the glyph (negative numbers, ranges, '– – – –' separator
  lines). SAM9X60 snapshot: 554 lines repaired (537 nested, 17 flattened),
  0 residue. meta: `dash_bullets_fixed`.
- **Container-direction duplicate cells (RGBMODE-style, 1454 rows)**:
  description cell contains the name cell; the model tries to dedupe ->
  invariant-A rejection. `llm_table.dup_cell_indices` now skips both
  directions, gated on contained-key length (>= 8) and a 3x container ratio
  (a false miss is cheap — safe rejection; a false skip loses a real fix).
- Chunk 1205's 33 'missing from truncated output' cell failures do **not**
  reproduce in isolation — they are batch-packing artifacts, confirming
  open item 2 below. Missing-index failures are batch-size dependent and
  non-deterministic, confirming item 1.

Validation: offline suite extended (181 tests); fragment experiment
39->5 units sent, 7->0 failures, 28->0 cells on the 5-chunk set; full
pipeline on 74HC_HCT74 / tlv62569 / CH32V208DS0 — 0 unit failures, 0
rejected chunks, 0 residual double-bullets (`dash_bullets_fixed` = 0 there:
the two-level '•'/'–' convention is Microchip-specific). Full SAM9X60 LLM
re-run deferred until items 1-2 land — one run then validates all three.

## Open work (priority order)

1. **Deterministic missing-index inference** — highest value.
   `malformed reply (missing index)` is the #1 SAM9X60 failure (1001 cell +
   171 line). When a batch reply contains all ordinals present and unique
   *except one*, the missing unit is unambiguously identifiable: infer it,
   then verify content as usual (invariant A still gates it). Safe, no prompt
   changes, attacks ~57% of that document's failures.
2. **Token-aware output cap and batch packing** — the cap and the packer
   currently assume 3.5 chars/token (`llm_client._CHARS_PER_TOKEN`), but
   server-measured reality is text-class dependent: prose ≈ 3.3,
   register cells/hex ≈ 1.12-1.15 (3x error). For dense-cell batches the
   nominal 2x cap is therefore ~0.67x of the tokens actually needed —
   truncation is baked in (1556 truncated calls on SAM9X60; requeue
   salvages only 6-9% because retried tails re-enter the same char-based
   packing and truncate again).

   Two distinct unknowns, each estimated at its own source:
   - **tokenization ratio** — solved deterministically by the server's own
     tokenizer: llama-server exposes `POST /tokenize`; CHECK FIRST whether
     llama-swappy can route it (user-owned loader; nginx fronts /v1 +
     private endpoints). If available: exact pre-send token counts for
     fragments (echo size) and prompts (context-fit check in llm_server
     has the same 3x bias), no priors, no drift, per-model automatically.
   - **output expansion factor** (echo + rewrites, ~1-2x fragment volume;
     depends on model behavior, not tokenization) — measured from
     `usage.completion_tokens` in every response (returned by the server,
     currently discarded by the client). Per-model calibration, mandatory
     for the escalation ladder (item 5: different vocab AND different
     verbosity per model).

   Fallback layers when `/tokenize` is not available (keep — any future
   server may lack it):
   - per-class rolling ratios, not one scalar: the scheduler already knows
     batch kind (line vs cell); cell batches start from a pessimistic prior
     (~1.5 chars/token). Asymmetric error cost justifies pessimism:
     underestimate -> truncation -> requeue; overestimate -> slightly
     larger cap / smaller batch -> negligible. This kills the
     prose-then-tables drift failure (one scalar adapts to prose, then a
     dense batch truncates).
   - graceful degradation: truncated batches already apply the ordinals
     that arrived; requeued tails must be packed by token estimate (they
     are few), turning truncation into one extra round-trip instead of
     lost work.

   Pack by estimated OUTPUT TOKENS against a token budget (not fragment
   chars); cap = expansion_factor x expected_echo_tokens + margin (keeps
   the loop leash relative to real expected size). Validate on the deferred
   full SAM9X60 re-run.
3. **Fail-log cap** — raise from 2000 to ~10k entries (or store per-reason
   counts + N samples) so full-document runs are diagnosable.
4. (Optional, low priority) NOTE hint variant for missing-index failures
   ("your previous reply dropped the index") — cheap, but item 1 makes most
   of these moot.
5. **Model escalation ladder for exhausted retries** — same-model requeue
   salvages only 6-9% of requeued units, so the ladder replaces bare retry
   as the recovery mechanism. Design (agreed): auto-switching proxy on the
   server, so switching = changing the model id; config
   `llm_escalation: [{model, max_fraction, min_units}, ...]` via
   `--llm-auth` (level 0 = existing `model`). Salvage passes run AFTER the
   main pass (never mid-run): each level fires only if
   `failed_units/units_sent <= max_fraction` (ceiling on big-model exposure
   — bounds worst-case run time) AND `failed_units >= min_units` (no reload
   for 3 fragments). Defaults per the original proposal: 0.5 then 0.1.
   Salvage passes reuse the batch scheduler/verifier/NOTE hints with fresh
   batch positions (drift-isolated); final failures keep the original text
   (rejection-is-safe contract unchanged); sampling stays server-side per
   model. Scope v1: units only (not whole-chunk prose attempts — chunk-sized
   echoes are too expensive on a 10x model). meta: per-level
   `escalation: [{model, units_sent, units_fixed, truncated_calls,
   duration}]` + `escalation_skipped` reasons; fail log records the model
   that finally failed the unit (merges with item 3). Prereq: items 1-2 —
   deterministic repair first, so the gates measure only model-sensitive
   residue (the two model-unreachable classes above are already gone).
   Validate on the deferred full SAM9X60 re-run.

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
