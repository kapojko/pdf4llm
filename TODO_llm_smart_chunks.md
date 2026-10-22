# TODO — llm_smart_chunks branch

Status of the structure-aware `--llm` pipeline rewrite (replaces both the old
whole-chunk mode and the removed `--llm-content-only`). Everything below
assumes the verifier-first design: sampling is never overridden (server-side
defaults unless `llm_sampling` is configured), every unit is verified before
it is applied, and failed units are retried up to `llm_retries` times
(default 2) with a rejection-reason hint.

## Open investigation (highest priority)

**WCH datasheet cell failures do not reproduce in isolation.**
On `CH32V208DS0` the in-run pass still rejects ~14/80 chunks with
`invariant A violated` on individual cells (`row 10 cell 1`, `row 11 cell 1`,
`row 16 cell 0/1`, ...), while isolated probes of the same rows/cells (same
payload format, same sampling) show the model echoing cells faithfully with
zero verification failures. Run-to-run variance is real (the whole-chunk
prose attempt uses the server sampling), but the probe/production gap is
unexplained.

Next step: cross-reference the failing cells against the captured full-run
exchange log `out/e2e_wch_exchange_log.jsonl` (one JSON per request:
prompt / request / response / finish reason). Check specifically:
- is the failing cell's request payload identical to the isolated probe's?
- does the response contain extra context echo / thinking / fences that the
  parser mishandles in that combination?
- are the failures clustered in specific chunk-worker interleavings
  (parallel path) — try workers=1 vs 8 on the same file.

## Known behaviour gaps

- `cells_fixed` yield on WCH datasheets is near zero (0/365, 0/274 sent) —
  either the suspicious-cell filter over-sends harmless cells, or the model
  genuinely cannot improve these cells and they only produce rejection risk.
  Measure the fix/no-change/fail distribution per protocol once the
  investigation above is resolved.
- Progress label `REJECTED: ... retries 0` is confusing: content failures do
  not regenerate outside the retry rounds; `retries` counts extra rounds
  only. Consider relabelling to `no-recovery` or showing round counts.
- Cross-line word joins in prose (`examp` / `le` split across two physical
  lines) are only fixable by the whole-chunk attempt; per-line protocol
  cannot join. A paired-line unit could be added if meta stats show the
  whole-chunk path misses them.
- Atomic tokens (`[Figure-n](x,y,w,h)`, `(cid:...)`) are handled by
  per-unit fallback only. Add masking (placeholder substitution) if meta
  stats show them causing rejections.
- `_verify_chunk` invariant-B per-cell check splits on unescaped pipes; a
  row whose *original* contains unbalanced escaped pipes (`\|`) is
  guarded at run level (never sent), but the defense check could use the
  same canonicalized projection for full symmetry.

## Validation still to do (requires owner approval for long runs)

- Full-document runs to replace the page/chunk-slice evidence:
  - `rm0410` (1942 pages, ~3 min conversion + LLM pass) — expect the TOC
    region to skip ~140 chunks deterministically and the register region to
    hold the measured 7.5% rejection / 2x fix yield.
  - `CH32FV2x_V3xRM` (the WCH reference manual with the translated prose
    that the old pipeline reworded beyond salvage).
  - `CH32V208DS0` re-run after the open investigation is resolved; the
    previous comparison baseline is preserved in `*.meta.json.bak`.
- Compare meta.json old (`*.bak`) vs new per document; watch
  `chunks_toc_skipped`, `cells_sent`/`cells_fixed`, `truncated_calls`
  (should stay near zero with the 2x output cap).

## Done on this branch (for context)

- Canonical verifier (bidirectional dash/quote/bullet/ellipsis map,
  `\|` tolerance, numeric-token check on canonicalized text).
- 2x output token cap (was 1x; truncated 419/2936 calls on rm0410).
- TOC-like chunk detection (one distinct long cell per row ending in a page
  number, ~10% row tolerance) with deterministic skip.
- Cell-level table processing: suspect cells only (dup/contained cells and
  escaped-pipe rows never sent), row as context, skeleton spliced back.
- Prose: whole-chunk attempt -> line salvage -> disputed-line re-asks.
- Echo protocol (`N| text`) with per-unit verification and hinted retry
  rounds (`llm_retries`, default 2, failed subset only).
- Sampling never overridden: no `llm_sampling` configured -> no sampling
  parameters sent at all; configured -> forwarded verbatim (echo requests
  included; the former temp-0 override is removed).
- CLI: `--llm-content-only` removed; single strict mode.
- Tests: 122 passing (see `tests/test_llm.py`), including adversarial
  verifier cases, TOC detection, escaped pipes, retry-recovery, and
  sampling pass-through.
