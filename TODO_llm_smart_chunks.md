# TODO — llm_smart_chunks branch

Status of the structure-aware `--llm` pipeline. Everything below assumes the
verifier-first design: sampling is never overridden (server-side defaults
unless `llm_sampling` is configured), every unit is verified before it is
applied, failed units keep the original text after `llm_retries` extra
attempts (default 2), and rejection is always safe (the original text is
kept).

## Module layout (post-refactor baseline)

`llm.py` has been split into focused modules: `llm_prepass`, `llm_classify`,
`llm_chunk`, `llm_prompts`, `llm_verify`, `llm_table`, `llm_salvage`,
`llm_protocol`, `llm_client`, `llm_server`, `llm_run` (plus `llm_batch`,
the cross-chunk batch scheduler).

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

## Decided improvements

### 1. Cross-chunk batch aggregation — DONE

Implemented in `llm_batch.py` (`Unit` registry, kind-separated global
queues, batch packer ~5k fragment chars, CONTEXT row once per row-group,
pure global requeue failure semantics, per-unit NOTE hints, drain phase,
per-ordinal failure log for drift measurement). Producers (scan + whole-chunk
prose attempts) and batch requests share the worker pool via a priority heap
(batches interleave with producers). Chunk final states are computed at
drain time; safety gates unchanged.

### 2. Output token cap relative to fragments — DONE

Batched echo requests cap `max_tokens` at 2x the FRAGMENT volume + margin
(`output_cap_chars` through `_call_llm`), not the whole prompt; truncation
handling unchanged (missing tail units are requeued).

### 3. One-shot example in every unit prompt — DONE

Both line and cell prompts carry one worked example (one fixed fragment +
one clean-echoed fragment) plus the NOTE-line convention, in the system
message.

### 4. `<br>` split-cell repair — DONE

Deterministic pre-pass joins `letter<br>lowercase` mechanically; the
invariant-A projection strips `<br>` variants from both sides (numeric-token
check does NOT see the projection, so `2<br>0` -> `20` stays rejected);
lines with residual `<br>` are always admitted as batched units.

### 5. Heading-aligned chunk boundaries — DONE

`llm_chunk.py` aligns overflow breaks to the last ATX heading in-window
(the heading opens the next chunk) whenever that leaves a non-degenerate
chunk; table-swallow and paragraph-fold behaviour unchanged.

### 6. In-document vocabulary as a SEND/SKIP filter — DONE

`DocVocab` in `llm_batch.py`: per-document word map built after pre-passes;
a fragment is admitted when some contiguous sub-join of its suspicious-gap
groups occurs in the document (or when it carries residual `<br>`, double
spaces/tabs, or is very long). Skipped units are counted (`units_skipped`),
never edited. Not applied to targeted disputed-line re-asks of the prose
path.

### 7. Whole-chunk prose attempt: measure, then condition — HALF DONE

Measurement is in place: meta.json carries `wholechunk_attempts`,
`wholechunk_accepted`, `wholechunk_linejoin_fixes` (the unique yield).
Still open: the conditional skip for chunks without suspicious cross-line
patterns, gated on measured yield being near zero on real documents. (The
paired-line unit idea remains REJECTED — see below.)

### 8. Rule yield accounting and pruning — instrumentation DONE

meta.json now reports `units_sent/fixed/failed/skipped` per pass plus
`cells_sent/cells_fixed` and the per-unit fail log. Still open: the actual
prune/demote decision for zero-yield heuristics (prime suspect: the cell
pass on WCH datasheets, `cells_fixed` 0/365, 0/274 sent) once the open
investigation is resolved.

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
- **In-place retry rounds** (re-asking the failed subset inside the same
  batch handler): replaced by pure global requeue — each retry gets a fresh
  position in the echo (drift-isolated), hints stay per-unit coherent in
  mixed-reason batches.

## Minor items (keep, low priority)

- Atomic tokens (`[Figure-n](x,y,w,h)`, `(cid:...)`) are handled by
  per-unit fallback only. Add masking (placeholder substitution) if meta
  stats show them causing rejections.

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
- Re-run the local bench (`scripts/bench/`, `bench_llm_local.py`,
  `probe_quality.py`) — batch aggregation changes the throughput/rejection
  trade-off the model-choice table is based on.

## Done on this branch (for context)

- Canonical verifier (bidirectional dash/quote/bullet/ellipsis map,
  `\|` tolerance, numeric-token check on canonicalized text, `<br>`
  split-marker projection).
- 2x output token cap (was 1x; truncated 419/2936 calls on rm0410).
- TOC-like chunk detection with deterministic skip.
- Cell-level table processing: suspect cells only (dup/contained cells and
  escaped-pipe rows never sent), row as context, skeleton spliced back.
- Prose: whole-chunk attempt -> line salvage -> batched disputed-line units.
- Echo protocol (`N| text`) with per-unit verification and requeue retries.
- Cross-chunk batch aggregation (item 1), fragment-based output cap (2),
  worked examples (3), `<br>` repair (4), heading-aligned boundaries (5),
  vocabulary SEND/SKIP filter (6), yield accounting (8).
- Per-unit rejection-reason hints as NOTE lines; `retries_used` now counts
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
