# TODO — llm_smart_chunks branch

Status of the structure-aware `--llm` pipeline. Everything below assumes the
verifier-first design: sampling is never overridden (server-side defaults
unless `llm_sampling` is configured), every unit is verified before it is
applied, failed units are retried up to `llm_retries` times (default 2) with
a rejection-reason hint, and rejection is always safe (the original text is
kept).

## Step 0 — refactor before any improvement (preliminary, blocking)

`llm.py` is ~1700 lines and mixes unrelated concerns. Split it into modules
BEFORE any behavioural change, verify with the existing test suite
(122 tests, must pass UNCHANGED — the refactor is pure code motion), commit,
and only then start the improvement items. This keeps every later diff small
and reviewable against a stable baseline.

Target split (each file ≤ 500 lines; 1000 only in exceptional cases):

- `llm_prepass.py` — deterministic pre-passes: `strip_horizontal_rules`,
  `collapse_dot_leaders`, `dedupe_bullets`, `fix_subscripts`. Future home of
  the deterministic `<br>` joiner (item 4 below).
- `llm_classify.py` — `classify_heuristic`, `classify_with_llm`.
- `llm_chunk.py` — `chunk_markdown`; future home of heading-aligned
  boundaries (item 5).
- `llm_prompts.py` — all prompt templates (whole-chunk / line / cell) and
  the one-shot examples (item 2). Prompts are iterated on most often; they
  must not be buried in logic.
- `llm_verify.py` — canonical map, `_ws_canon`, `_num_tokens`, `_num_check`,
  `_verify_pair`, `_verify_chunk`, `_verify_line_in_context`.
- `llm_table.py` — row/cell geometry: `_is_table_row`, `_is_separator_row`,
  `_split_row_cells`, `_row_cell_texts`, `_splice_cells`, `_is_toc_like`,
  `_suspicious_cell`.
- `llm_salvage.py` — `_pair_by_similarity`, `_salvage`.
- `llm_protocol.py` — indexed echo protocol: `_parse_indexed_lines`,
  `_echo_units`, `_verified_rounds`. Future home of the batch aggregator
  (item 1).
- `llm_client.py` — transport: `_call_llm`, `_split_sampling`,
  `output_token_cap`, `_strip_thinking`.
- `llm_server.py` — server capability probing and parallelism:
  `probe_swappy`, `resolve_workers`, `estimate_chunk_tokens`, `_DaemonPool`,
  `LlmInterrupted`, `LlmContextError`.
- `llm_run.py` — orchestration: `_run_chunk`, stats deltas, progress
  formatting, `correct_with_llm` entry point.

Refactor rules: no behaviour change, no renames of public entry points,
tests untouched except import paths. If a function must move with its
helpers, move the whole cluster (verifier helpers with `_verify_pair`, etc.).

## Open investigation (highest priority, before tuning anything)

**WCH datasheet cell failures do not reproduce in isolation.**
On `CH32V208DS0` the in-run pass rejects ~14/80 chunks with `invariant A
violated` on individual cells, while isolated probes of the same rows/cells
(same payload, same sampling) show zero failures. Run-to-run variance is
real, but the probe/production gap is unexplained — and it poisons the
measurements every tuning decision below depends on.

Next steps:
- cross-reference failing cells against `out/e2e_wch_exchange_log.jsonl`
  (payload identical to probe? extra echo/thinking/fences in response?);
- run the same file with `--llm-workers 1` vs 8 — if failures cluster in the
  parallel path, suspect server-side state under 8 streams first.

## Decided improvements (post-refactor, in implementation order)

### 1. Cross-chunk batch aggregation (main throughput lever)

Decouple the verification unit (cell/line — stays small) from the request
unit. Maintain global queues of suspect units across all chunks, with an
index registry mapping global index → (chunk, local unit, kind); pack
requests from the queues.

- **Kind-separated**: never mix cells and prose lines in one call (one call =
  one task type = simpler prompt for a small model).
- **Batch size**: start at ~5k chars of *fragments* per call (context rows
  attached once per row-group, not per cell). Slot context is 24k, so input
  is not the constraint — generated output length is.
- **Drift measurement**: log per-unit failure vs the unit's ordinal position
  in the response. Flat → raise batch size toward 10–15k; tail-clustered →
  the ceiling is found. Decide from data, not guesswork.
- Long streamed echo responses are the intended workload: copy tasks give
  near-total dflash acceptance, so echoing clean spans is nearly free.
- Safety unchanged: per-unit verification, index-based reassembly, missing
  indices → retry subset (existing `_verified_rounds` semantics).

### 2. Output token cap relative to fragments

`output_token_cap` currently scales with whole-prompt input; as context per
call grows (item 1), the cap inflates and gives degenerate input-repeat more
runway. Cap ≈ fragments volume + margin (current 1x+256 formula applied to
the fragment total, not the full prompt). Truncation handling unchanged.

### 3. One-shot example in every unit prompt

A single worked example kills the input-repeat-when-confused failure at the
source (the model was never trained on our CONTEXT convention). Sketch:

> System: You repair text-extraction defects. You get numbered fragments,
> sometimes with a CONTEXT block showing the surrounding row. Reply with the
> same numbers and the fragment, fixing only split words and false
> spaces/line-breaks. Never change words, numbers, punctuation. Never echo
> the CONTEXT. Copy clean fragments unchanged.
>
> Example request: `1| D-t yp e`, `2| Standard operating voltage`
> Example reply:  `1| D-type`, `2| Standard operating voltage`

One fixed fragment + one clean-echoed fragment, so both behaviours are
shown and the reply contains nothing else. Keep instructions in the system
message; per-call user content is only the CONTEXT block + indexed units.

### 4. `<br>` split-cell repair (new repair class)

Currently impossible by construction: joining `System Co<br>ntrol` deletes a
non-whitespace token, which the whitespace-only invariant must reject.
Introduce a narrowed edit class: the only permitted edit is replacing `<br>`
with `""` or `" "`.

- Verifier: strip all `<br>` from both sides, whitespace-collapse, require
  identity; numeric-token check unchanged. One extra canonical projection in
  `llm_verify.py`, same philosophy.
- Deterministic pre-pass (in `llm_prepass.py`): `letter<br>lowercase` → join
  without space. This case is mechanical and document-independent (it is
  what `<br>` *means* in a split word), not a per-PDF rule.
- Only ambiguous cases (capital/digit after `<br>`) go to the model, batched
  via item 1.
- Motivation: `Control` is searchable/embeddable, `Co<br>ntrol` is not; this
  un-accepts a "known acceptable artifact" that matters for LLM consumption.

### 5. Heading-aligned chunk boundaries

When a chunk must split anyway, prefer splitting at markdown headings.
Better model context, no risk. Minor, do when touching `llm_chunk.py`.

### 6. In-document vocabulary as a SEND/SKIP filter (never an applier)

Build a word-frequency map of the document as-extracted at pass start (one
regex pass; datasheets are highly repetitive). Use it ONLY to decide whether
a suspicious fragment is sent to the model:

- joined form occurs often in THIS document (`Re set` → `Reset` ×80) → send
  as usual; model + verifier do their job unchanged;
- joined form never occurs (`Power down` → `Powerdown` ×0) → probably
  legitimate spacing → skip; saves a call and avoids "helpful" rewrites that
  only produce rejection risk.

Hard rules: the vocabulary never edits text; a wrong skip costs one unfixed
defect (recall), never corruption; the map is rebuilt per document — nothing
hardcoded, nothing to overfit across PDFs; on a sparse/weird document the
behaviour degrades to the current design.

### 7. Whole-chunk prose attempt: measure, then condition

The whole-chunk call is the most expensive and most rejection-prone call
type; its UNIQUE capability is cross-line word joins (everything else the
line path does cheaper with finer salvage). From meta.json, count chunks
where state = `accepted` AND the diff changes the line count (a join) —
that is the whole-chunk call's unique yield.

If the yield is near-zero on real documents: skip the whole-chunk attempt
for chunks without suspicious cross-line patterns (lowercase line end +
lowercase next-line start, no sentence punctuation) and go straight to the
line path. Note: the paired-line unit idea was REJECTED (detection is
unreliable on real garbage — extra whitespace / non-printables inside
words), so the whole-chunk attempt remains the only cross-line fixer; this
item is measurement + conditional skip, not removal.

### 8. Rule yield accounting and pruning

Every selection heuristic must report sent/fixed/failed in meta.json (most
already do). Any heuristic with ~zero fix yield over several documents gets
pruned or demoted — selection rules can't corrupt anything, so the criterion
is purely economic. Current prime suspect: the cell pass on WCH datasheets
(`cells_fixed` 0/365, 0/274 sent) — measure the fix/no-change/fail
distribution once the open investigation is resolved, then decide whether
the suspicious-cell filter over-sends or the model genuinely cannot improve
those cells.

## Rejected ideas (recorded so they are not re-proposed)

- **JSON wire format without grammar enforcement**: adds JSON failure modes
  (unbalanced quotes, escaping — cell text contains quotes/backslashes)
  without the guarantees; +30–50% token overhead over the `N| ` protocol,
  whose string content is where errors live anyway. The indexed line
  protocol has exactly one metacharacter and is measured at zero content
  violations. (`response_format`/grammar was ruled out earlier — grammar
  masking can hurt speculative decoding.)
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
  extraction garbage; whole-chunk attempt covers the case (see item 7).
- **Pre-built / cross-document vocabularies**: overfit risk to 1–2
  documents; per-document maps only (item 6).

## Minor items (keep, low priority)

- Progress label `REJECTED: ... retries 0` is confusing (`retries` counts
  extra rounds only). Relabel to `no-recovery` or show round counts.
- Atomic tokens (`[Figure-n](x,y,w,h)`, `(cid:...)`) are handled by
  per-unit fallback only. Add masking (placeholder substitution) if meta
  stats show them causing rejections.
- `_verify_chunk` invariant-B per-cell check splits on unescaped pipes; the
  defense check could use the same canonicalized projection as the run-level
  guard for full symmetry.

## Validation still to do (requires owner approval for long runs)

- Full-document runs to replace page/chunk-slice evidence:
  - `rm0410` (1942 pages) — expect TOC region to skip ~140 chunks
    deterministically, register region to hold the measured 7.5% rejection /
    2x fix yield;
  - `CH32FV2x_V3xRM` (translated prose the old pipeline reworded beyond
    salvage);
  - `CH32V208DS0` re-run after the open investigation is resolved; previous
    baseline preserved in `*.meta.json.bak`.
- Compare meta.json old vs new per document; watch `chunks_toc_skipped`,
  `cells_sent`/`cells_fixed`, `truncated_calls` (should stay near zero).
- After item 1 lands: re-run the local bench (`scripts/bench/`,
  `bench_llm_local.py`, `probe_quality.py`) — batch aggregation changes the
  throughput/rejection trade-off the model-choice table is based on.

## Done on this branch (for context)

- Canonical verifier (bidirectional dash/quote/bullet/ellipsis map,
  `\|` tolerance, numeric-token check on canonicalized text).
- 2x output token cap (was 1x; truncated 419/2936 calls on rm0410).
- TOC-like chunk detection with deterministic skip.
- Cell-level table processing: suspect cells only (dup/contained cells and
  escaped-pipe rows never sent), row as context, skeleton spliced back.
- Prose: whole-chunk attempt -> line salvage -> disputed-line re-asks.
- Echo protocol (`N| text`) with per-unit verification and hinted retry
  rounds (`llm_retries`, default 2, failed subset only).
- Sampling never overridden: no `llm_sampling` configured -> no sampling
  parameters sent at all; configured -> forwarded verbatim.
- CLI: `--llm-content-only` removed; single strict mode.
- Tests: 122 passing (see `tests/test_llm.py`), including adversarial
  verifier cases, TOC detection, escaped pipes, retry-recovery, and
  sampling pass-through.
