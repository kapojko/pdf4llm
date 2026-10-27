# pdf4llm

Single-file PDF → Markdown converter for datasheets / hardware manuals, producing
LLM-readable Markdown for use as context in schematic / firmware development.

## Why this tool

- Engine: **pymupdf4llm** (bare `pymupdf` only exposes raw primitives; markitdown
  collapses register tables and breaks 2-column reading order).
- Single hop PDF → Markdown (no ilovepdf/convertio docx/txt chains — two lossy hops
  that mangle `°`, `µ` and mix CR/LF).
- Per-file **sanity score** so a bad extraction is caught immediately.
- Optional **local-LLM correction** pass for broken newlines / split words.

## Install

```powershell
.\build_install.ps1            # NVIDIA (CUDA): default, installs the CUDA runtime DLLs
.\build_install.ps1 -DirectML  # AMD / Intel (incl. Intel XPU on Windows)
```

Uses `uv tool install` (isolated env + a `pdf4llm` command on PATH) and copies the
shim into `C:\Programs\Util`. Requires `uv` on PATH. The default install includes
the NVIDIA CUDA runtime DLLs (`nvidia-cublas` / `nvidia-cuda-runtime` /
`nvidia-cudnn-cu13`) — a ~1 GB one-time download; `-DirectML` swaps them for
`onnxruntime-directml` (the two GPU runtimes conflict, so pick one per machine).

To develop in-repo instead:

```powershell
uv sync
uv run pdf4llm <file.pdf>
```

## Usage

```
pdf4llm <input.pdf> [more.pdf ...] [options]
```

Multiple input PDFs are processed independently (per-file prompts, per-file
exit results); the final exit code is the worst per-file code.

| Flag | Purpose |
|------|---------|
| `input` | one or more PDF files (positional) |
| `-o/--out DIR` | output dir, **default = same folder as the PDF** |
| `--pages A-B,12,15` | page subset (useful for short LLM tests) |
| `--locate FOLDER` | treat `input` as a file **name** and search for it recursively in FOLDER; must match exactly one file (case-insensitive) or the run aborts with the match list. Uses an index file (`.pdf4llm_locate.idx`) inside FOLDER so repeat runs skip the slow recursive scan (big win on network shares); a missing or vanished match triggers one automatic rebuild, and all inputs are matched from a single scan |
| `--locate-rebuild` | force a fresh `--locate` scan and rewrite the index file in FOLDER (also the only way `--locate-mode` discovery refreshes the index — it is never rebuilt implicitly) |
| `--locate-mode MODE` | with `--locate FOLDER` and **no input names**: discover the files to process from the index. `update` = previously converted (meta.json present) files that are stale — older pdf4llm version or different LLM model; `update-all` = all previously converted files; `convert` = update-all plus PDFs that have same-basename `.docx`/`.txt`/`.md` siblings; `convert-all` = every PDF. Modes nest: `update < update-all < convert < convert-all`. The numbered result list is shown for approval (one y/N; `--force` approves, `--dry-run` lists without prompting) |
| `--copy FOLDER` | after the (optional) LLM pass, additionally copy the **final** `.md` into FOLDER (created if missing); if the file exists there, ask y/N — or overwrite silently with `--force` |
| `--force` | skip all y/N confirmations (delete / overwrite / copy-overwrite); actions are still logged to `.pdf4llm_prune.log` |
| `--dry-run` | show the full plan (locate result, cleanup actions, output/meta/copy paths) without converting, writing, deleting or prompting |
| `--version` | print the pdf4llm version and exit |
| `--llm / --no-llm` | run local-LLM broken-text correction (default **on**; `--no-llm` skips it) |
| `--llm-workers N` | parallel LLM chunk requests; default **1** (rationale: see the llama-swappy section below) |
| `--llm-chunk-chars N` | max chunk size (chars) for the LLM pass; default **2000** (config key `llm_chunk_chars`). Smaller chunks are more stable on small local models |
| `--llm-batch-tokens N` | fragment-token volume packed into one batched LLM echo request; default **3000** (config key `llm_batch_tokens`). Token counts come from the server tokenizer when reachable, else 1 char ≈ 1 token |
| `--llm-auth` | interactively set & save LLM credentials |
| `--llm-rescue NAME` | rescue model for this run: units the main model failed after all retries are re-asked ONCE on it (config key `llm_rescue`; an empty value disables rescue for the run) |
| `--model NAME` | override LLM model (else from saved config) |
| `-v/--verbose` | verbose output |

No subcommands. For each PDF the tool:
1. scans its own folder for **exact-basename** `.docx`/`.txt` (delete) and `.md`
   (overwrite), asking a **mandatory per-file y/N** (shows both file sizes;
   bypass only with `--force`). An undo record (path + sha256 + size) is
   written to `.pdf4llm_prune.log`.
2. converts to `<basename>.md` (**UTF-8, no BOM**) + `<basename>.meta.json`.
3. runs the LLM correction pass (`--no-llm` skips it).
4. optionally copies the final `.md` with `--copy`.
5. prints a one-line sanity score and exits non-zero if it scored badly.

## Layout engine GPU acceleration

The neural layout analyzer (BoxRFDGNN, pymupdf 2.x) runs on the **GPU by
default**: the GPU-enabled `onnxruntime-gpu` is a direct dependency and the
engine is always started with `use_gpu=True` (CPU is the automatic fallback).

- **NVIDIA (CUDA)** — the CUDA runtime DLLs are *not* bundled by the
  `onnxruntime-gpu` wheel. Without them the provider fails to load and
  conversion falls back to CPU (a loud warning is printed at startup).
  Install the runtime DLLs once:
  ```powershell
  .\build_install.ps1                 # adds nvidia-cublas/cuda-runtime/cudnn (default)
  # or manually: uv tool install --force . --with nvidia-cublas==13.8.0.4 \
  #     --with nvidia-cuda-runtime --with nvidia-cudnn-cu13
  ```
- **AMD / Intel (Windows, incl. Intel XPU)** — install the `directml` variant
  instead (`build_install.ps1 -DirectML`); never install both GPU runtimes.
  DirectML only works in the main process (pymupdf's worker processes cannot
  inherit it), so conversion then runs single-threaded — noted at startup.
- If no GPU provider is available at all, the run starts with a `WARNING:
  layout engine ... running on CPU` on stderr — treat it as a broken setup,
  not a normal mode.
- The conversion prints progress (`converting N/M pages ...` / `done in ...`);
  the first page batch also includes the model load.

## LLM correction (safe by construction)

No PDF-extraction library ships an LLM post-processing hook, so this is a custom
pass. It is built so that a hallucinating model **cannot** corrupt the document —
safety is enforced by an algorithmic verifier, never by trusting the model:

1. **Classification** — the document head is classified (datasheet/reference
   manual vs general) by the LLM, with a keyword-heuristic fallback; any
   ambiguity or error defaults to the strict technical prompt. This only
   selects the prompt — never the safety rules.
2. **Constrained edits** — the model may only perform formatting/whitespace
   fixes: join split words (`D-t yp e` → `D-type`), subscript joins
   (`V CC` → `VCC`, `T amb` → `T_amb`), part-number hyphen joins
   (`SOT108 - 1` → `SOT108-1`), false line-break removal, and `<br>`
   split-marker removal (see the verifier below). Nothing else.
3. **Structure never passes through the model** — the pass is
   structure-aware, and the granularity matches where a small model is
   actually reliable:
   - *table chunks* are processed at **cell level**: a deterministic
     pre-filter sends only cells that look defect-suspect (measured on a
     1942-page reference manual: ~90% of cells are skipped as clean), each
     batch with its row as context; the row skeleton — pipes, padding,
     separator rows — is spliced back untouched, so table geometry can
     never be damaged;
   - *TOC-like chunks* (every table row carries at most one distinct long
     cell — section title + page — sometimes duplicated into sibling cells;
     a common extraction artifact in tables of contents) are **skipped
     deterministically**: no model output can ever verify against them, so
     no requests are spent;
   - *prose chunks* get one whole-chunk attempt (the only unit that can join
     falsely split lines), then a deterministic line-level salvage of the
     candidate; disputed lines are re-asked as batched units.
   All unit-level requests use an indexed echo protocol (`N| text`);
   measured on a 9B/A1.3B model, they produced zero content
   violations where whole-table chunks were rejected ~70% of the time.

   **Cross-chunk batching** — the verification unit (a cell or a line) is
   decoupled from the request unit: suspect units from ALL chunks are
   collected into kind-separated global queues (cells and prose lines are
   never mixed in one call) and packed into batched echo requests of ~5k
   chars of fragment text, with the CONTEXT row attached once per row-group.
   A per-document word-frequency map (built after the pre-passes, used ONLY
   as a SEND/SKIP gate — it never edits text) skips fragments whose suspicious
   join form never occurs in the document (probably legitimate spacing),
   cutting the number of model calls roughly threefold on repetitive
   datasheets. A measured run on a 19-page datasheet: 77 units sent,
   141 skipped, 0 failed.
4. **Algorithmic verifier** (per unit, non-negotiable) — whitespace-level
   edits only: input and output must be identical after whitespace-stripping
   and a closed **canonical map** (dashes, quotes, bullets, ellipsis are
   interchangeable in BOTH directions — the model may rewrite `–` as `-` but
   can never delete it), numeric tokens must survive as an ordered sequence
   (blocks `2 0` → `20`, `0x30 08` → `0x3008`, `-40` → `40`; harmless joins
   like `25 °C` → `25°C` pass), table rows keep their cell count, and the
   `<br>` split-marker edit class is narrowly allowed: the invariant-A
   projection strips `<br>` tags from both sides, so `Co<br>ntrol` may become
   `Control` (or `Co ntrol`) but nothing else about the tag.
   The canonical map never touches `[0-9A-Za-z_]`, so register names,
   constants and words are physically immutable.
5. **Recovery** — a failed unit is not simply discarded: the whole-chunk
   candidate goes through line/block-level **salvage** (only independently
   verified pieces are applied, the rest reverts); a unit that fails parsing
   or verification is **requeued** — never retried in place — to the end of
   its batch queue with its rejection reason attached, up to `llm_retries`
   extra attempts; the next batch carries the reason as a per-unit NOTE line.
   Whatever still fails verification stays as
   the original — rejection is always safe, never silent.
   **Rescue pass**: when a rescue model is configured (`llm_rescue`, or
   `--llm-rescue`), units that exhausted all retries on the main model are
   re-asked once on the rescue model after the main pass ends (fresh batch
   positions, the rejection reason attached as a NOTE hint; same verifier).
   It fires only when the failure fraction is within the configured ceiling
   (default 0.5 of units sent); a fix on the rescue model counts like any
   other verified fix, a second failure keeps the original text. Measured
   on SAM9X60: a diverse rescue model fixes ~53% of the exhausted tail
   (vs ~6.5% for another same-model retry round).
   All decisions are
   logged to `meta.json` (`llm` section: classification, accepted/salvaged/
   rejected/toc-skipped counts, units sent/fixed/failed/skipped, batches,
   cells sent/fixed, whole-chunk yield, per-unit failure log, per-chunk
   reasons, `rescue` block with per-level stats and skip reasons).

Deterministic pre-passes run before the LLM pass — no model involvement:
duplicated-bullet cleanup (`- • x` → `- x`), horizontal-rule stripping,
TOC dot-leader collapsing (runs of 4+ dots → one space; models reliably try
to trim dot leaders themselves, which poisons whole chunks), and mechanical
`<br>` split-word joins (`Co<br>ntrol` → `Control` where the next character
is lowercase — the ambiguous cases go to the model as batched units).

Set credentials once:

```powershell
pdf4llm --llm-auth
```

Saved to the user config dir (Windows: `%APPDATA%\pdf4llm\config.json`,
POSIX: `~/.config/pdf4llm\config.json`) as `{endpoint, api_key, model}`.
Optional keys: `llm_sampling` (dict forwarded verbatim on every request;
when absent, **no sampling parameters are sent** and the server-side model
defaults apply — the tool never overrides temperature), `llm_retries`
(default 2; a unit that fails parsing or verification is requeued up to
this many extra times — never retried in place — and the next batch carries
its rejection reason as a per-unit NOTE line), `llm_rescue` (rescue model;
a model name or a list of `{model, max_fraction}` levels — after the main
pass, exhausted units are re-asked once on it when the failure fraction is
within `max_fraction`, default 0.5), `llm_batch_tokens` (default 3000; same
as `--llm-batch-tokens`) and `llm_chunk_chars`
(default 2000; same as `--llm-chunk-chars`).
Then:

```powershell
pdf4llm <file.pdf> --llm --pages 1-10
```

`meta.json` records the conversion provenance: `pdf4llm_version` (pdf4llm
version that produced the file) and `llm_model` (model used by the LLM
pass, `null` when skipped) — these are what `--locate-mode update` compares
against to detect stale conversions.

Chunk producers (deterministic scan + one whole-chunk prose attempt per
prose chunk) run concurrently with the batch requests in the worker pool.
The pass prints unconditional progress: a line per batch
(`llm: batch 12: 20 fragment(s), 4800 chars`), a per-chunk line at the end
for every rejected or salvaged chunk, and a totals summary — accepted /
salvaged / rejected / toc-skipped chunks, units sent/fixed/failed/skipped,
elapsed time. With
a llama-swappy server (v1.3+) the tool probes its `GET /llama-swappy/info`
self-description endpoint and:

- runs with **1 worker by default**: on the batched pipeline a single large request already saturates the server's decode (benchmarked on ling-3.0-tiny-np8 with dflash, 2026-10: w1/w2/w4/w8 within run-to-run noise at batch 10000; the pre-batching w4→w8 ≈ 1.75x scaling no longer applies). Slots are still surfaced in the probe line, and an explicit `--llm-workers` overrides the default;
- reads the per-request `contextSize` (total `-c` divided by slots) and checks
  a rough token estimate (input + up to 2x-size output + margin,
  ~3.5 chars/token) for the **largest actual chunk** against it; if a chunk
  provably cannot fit, the pass is **aborted before any LLM call** (exit code
  4) — reduce the chunk size or raise the server context.

Missing data degrades safely: no info endpoint → 1 worker, current behaviour;
model key not listed / no `contextSize` → warning, check skipped. The detected
server capabilities and worker count are recorded in `meta.json` (`llm.swappy`).
With a plain OpenAI-compatible endpoint (Ollama, bare llama-server) the
behaviour is unchanged: `--llm-workers N` for parallelism, 1 otherwise.

Safety is unaffected by parallelism: every unit still goes through the same
verify-and-requeue pipeline, chunks are independent and the output is
reassembled strictly in original chunk order.

#### Model choice

Current default (saved user config via `--llm-auth`): **ling-3.0-tiny-np8**
(MoE, A1.3B active). Measured on the current batched pipeline, 19-page
datasheet, 19.4k alphanumeric chars, 8 slots:

- **750 chars/s** wall (142s → 43s vs the pre-batching pipeline on the same
  document and server);
- **0 rejected chunks, 0 truncated calls, 0 failed units** — 13 requeued
  units, all recovered by the requeue machinery;
- 6 of 7 known split-word defects fixed (the old pipeline fixed 2 of 7 on
  the same document and left 5 in rejected chunks).

Safety is model-independent (verifier-gated). There is **no current
head-to-head comparison** of candidate models on the batched pipeline — the
older ornith-1.5-9b vs ling-3.0-tiny table described the pre-batching
whole-chunk pipeline, whose rejection profile no longer applies (whole-table
chunk sends and their `candidate rewrite beyond salvage` rejections are
gone). Such a comparison will be re-added once `scripts/bench/`
(`bench_llm_local.py`, `probe_quality.py`) is re-run per candidate model on
the current pipeline.

`litellm` is the pluggable client — it works with Ollama, llama.cpp
(llama-server), or any OpenAI-compatible endpoint.

### Loop / runaway-generation protection

- The request always sets `chat_template_kwargs: {enable_thinking: false}`;
  as a belt-and-braces, a leading `<think>...</think>` block is stripped from the answer
  before verification (some servers/templates ignore the flag).
  Server side, keep the llama.cpp default `--reasoning auto` — thinking is
  then controlled per request (verified on llama.cpp master, 2026-10, with
  ling-3.0-tiny: enabled → reasoning arrives in `message.reasoning_content`,
  disabled → none). Do **not** set `--reasoning on` (forces thinking for all
  requests). If a llama.cpp build ever stops honouring the per-request flag,
  the symptom is unmistakable — a spike of `REJECTED ... truncated x1` chunks
  at 2–4x the usual per-chunk time (thinking burns the output-token cap) —
  and the fix is `--reasoning off` on that server instance.
- `max_tokens` per request is **capped relative to the input** (2x input
  tokens, 3.5 chars/token + 256 margin; for batched echo requests the cap
  scales with the FRAGMENT volume, not the whole prompt — CONTEXT rows and
  retry notes inflate the prompt but not the expected output): the pass is
  whitespace-only, so a healthy answer fits easily, while a looping model is
  cut off quickly instead of burning thousands of tokens. The truncated
  output then fails verification and the normal requeue machinery runs.
  Truncated calls are counted in `meta.json` (`llm.truncated_calls`).
- Chunking default is a deliberately small 2000 chars (`--llm-chunk-chars`),
  which keeps small local models (e.g. 9B) on-task and makes per-chunk
  failures cheap.

## Sanity checks (per output)

1. UTF-8, no BOM (rejects UTF-16).
2. Heading count (`^#{1,6} `) — 0 ⇒ extraction likely failed.
3. Table rows (`^\|`) + equal-column ratio.
4. Register density: `0x[0-9A-Fa-f]{2,4}` and `\d+x\d+` tokens.
5. Broken glyphs: `(cid:`, `U+FFFD`.
6. Empty / image-only pages (< 20 chars) — pin diagrams & reference schematics are
   always image-only.

## Known acceptable artifacts (post-filterable)

- `00` prefix on section numbers (font-encoded numbering).
- Stray bullet glyphs, inline page headers/footers, reversed/rotated cover text.

(`<br>` split cells — `System Co<br>ntrol` in wide register tables — used to
be in this list; the current pass repairs them, see the LLM section.)
