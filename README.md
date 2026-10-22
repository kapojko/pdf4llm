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
| `--locate-rebuild` | force a fresh `--locate` scan and rewrite the index file in FOLDER |
| `--copy FOLDER` | after the (optional) LLM pass, additionally copy the **final** `.md` into FOLDER (created if missing); if the file exists there, ask y/N — or overwrite silently with `--force` |
| `--force` | skip all y/N confirmations (delete / overwrite / copy-overwrite); actions are still logged to `.pdf4llm_prune.log` |
| `--dry-run` | show the full plan (locate result, cleanup actions, output/meta/copy paths) without converting, writing, deleting or prompting |
| `--version` | print the pdf4llm version and exit |
| `--llm` | run local-LLM broken-text correction (default **off**) |
| `--llm-workers N` | parallel LLM chunk requests. Default: **auto** from the llama-swappy info endpoint (`min(slots, 8)`), else 1; an explicit value overrides the server |
| `--llm-chunk-chars N` | max chunk size (chars) for the LLM pass; default **2000** (config key `llm_chunk_chars`). Smaller chunks are more stable on small local models |
| `--llm-content-only` | relaxed LLM verification: only letters, digits, underscores and numeric values are protected; punctuation, ASCII decoration and table geometry may change (config key `llm_content_only`) |
| `--llm-auth` | interactively set & save LLM credentials |
| `--model NAME` | override LLM model (else from saved config) |
| `-v/--verbose` | verbose output |

No subcommands. For each PDF the tool:
1. scans its own folder for **exact-basename** `.docx`/`.txt` (delete) and `.md`
   (overwrite), asking a **mandatory per-file y/N** (shows both file sizes;
   bypass only with `--force`). An undo record (path + sha256 + size) is
   written to `.pdf4llm_prune.log`.
2. converts to `<basename>.md` (**UTF-8, no BOM**) + `<basename>.meta.json`.
3. optionally runs the `--llm` correction pass.
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
   (`SOT108 - 1` → `SOT108-1`), false line-break removal. Nothing else.
3. **Algorithmic verifier** (per chunk, non-negotiable) — two levels:
   - *strict* (default): whitespace-level edits only. Whitespace-stripped
     input and output must be byte-identical (invariant A), numeric tokens
     must survive as an ordered sequence, and table rows keep their cell
     count (invariant B). The numeric-token check blocks whitespace merges
     that would corrupt a value (`2 0` → `20`, `0x30 08` → `0x3008`,
     `-40` → `40`); harmless joins (`25 °C` → `25°C`, `VCC + 0.5`) pass.
   - *content* (`--llm-content-only` or config `llm_content_only`): only the
     DATA is protected — the ordered sequence of letters, digits and
     underscores (`0-9A-Za-z_`) plus numeric tokens (digits with their
     internal separators and sign: `0.5`, `11:0`, `-40`, `0x020000`) must be
     byte-identical; everything else — punctuation, ASCII decoration,
     whitespace, table geometry — may change. Letters/digits can never be
     inserted, deleted, reordered or recased; duplicated lines/cells are not
     collapsible. Use for noisy pseudo-ASCII documents (dot leaders,
     decoration artifacts) where strict mode rejects too much.
4. **Recovery** — a rejected chunk is not simply discarded: it goes through
   line/block-level **salvage** (only independently verified pieces are
   applied, the rest reverts), then up to `llm_retries` regeneration attempts
   with a rejection-reason hint, keeping the best. Whatever still fails
   verification stays as the original — rejection is always safe, never
   silent. All decisions are logged to `meta.json` (`llm` section:
   classification, accepted/salvaged/rejected counts, per-chunk reasons).

Deterministic pre-passes run before the LLM pass — no model involvement:
duplicated-bullet cleanup (`- • x` → `- x`), horizontal-rule stripping, and
TOC dot-leader collapsing (runs of 4+ dots → one space; models reliably try
to trim dot leaders themselves, which poisons whole chunks).

Set credentials once:

```powershell
pdf4llm --llm-auth
```

Saved to the user config dir (Windows: `%APPDATA%\pdf4llm\config.json`,
POSIX: `~/.config/pdf4llm\config.json`) as `{endpoint, api_key, model}`.
Optional keys: `llm_sampling` (dict forwarded to the model; defaults to the
Ornith-1.5-9B card's precise-coding set: `temperature 0.6, top_p 0.95,
top_k 20, min_p 0.0, presence_penalty 0.0`), `llm_retries` (default 2),
`llm_chunk_chars` (default 2000; same as `--llm-chunk-chars`) and
`llm_content_only` (default false; same as `--llm-content-only`).
Then:

```powershell
pdf4llm <file.pdf> --llm --pages 1-10
```

Chunks are processed one after another unless parallelism is available. The
pass prints unconditional progress: a start line per chunk (`llm: chunk 10/104
(1976 chars) ...`) and a completion line with the final state — `accepted`,
`salvaged N block(s)` or `REJECTED` — plus retry/truncation counts, elapsed
time and an ETA. With
a llama-swappy server (v1.3+) the tool probes its `GET /llama-swappy/info`
self-description endpoint and:

- sets the number of workers automatically to `min(slots, 8)` (measured on
  ling-3.0-tiny-np8: w4→w8 ≈ 1.75x aggregate throughput; w16 gave no further
  gain — the GPU saturates at ~8 streams); an explicit `--llm-workers`
  overrides this;
- reads the per-request `contextSize` (total `-c` divided by slots) and checks
  a rough token estimate (input + same-size output + margin, ~3.5 chars/token)
  for the **largest actual chunk** against it; if a chunk provably cannot fit,
  the pass is **aborted before any LLM call** (exit code 4) — reduce the chunk
  size or raise the server context.

Missing data degrades safely: no info endpoint → 1 worker, current behaviour;
model key not listed / no `contextSize` → warning, check skipped. The detected
server capabilities and worker count are recorded in `meta.json` (`llm.swappy`).
With a plain OpenAI-compatible endpoint (Ollama, bare llama-server) the
behaviour is unchanged: `--llm-workers N` for parallelism, 1 otherwise.

Safety is unaffected by parallelism: every chunk still goes through the same
verify → salvage → retry pipeline, chunks are independent and the output is
reassembled strictly in original chunk order, so the result and the meta.json
stats are identical to the sequential run.

#### Model choice (measured, 49-page datasheet, 80 chunks)

| model | throughput | rejected | notes |
|-------|-----------|----------|-------|
| ornith-1.5-9b (dense, np4, w4) | 225 chars/s | 18/80 | baseline |
| ling-3.0-tiny (MoE A1.3B, np8, w8) | 341 chars/s | 24–27/80 | **1.5x faster** |

Both are equally safe (verifier-gated); the trade-off is repair recall: ling
occasionally rewrites/drops whole lines, which the verifier rejects as a whole
chunk (`candidate rewrite beyond salvage` in meta.json), so ~8% more of the
document stays unrepaired. ling also scales to more slots (w4→w8 ≈ 1.75x;
w16 adds nothing — GPU saturates ~8 streams), while the dense model does not.
Rule of thumb: ling for long documents where wall-clock matters, ornith for
quality-critical output. Rerun with `scripts/bench/` (`bench_llm_local.py`,
`probe_quality.py`) when changing models or servers.

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
- `max_tokens` per chunk is **capped at ~the input length** (3.5 chars/token
  + 256 margin): the pass is whitespace-only, so a healthy answer fits
  easily, while a looping model is cut off after one chunk-worth of tokens
  instead of burning thousands. The truncated output then fails verification
  and the normal salvage/retry machinery runs. Truncated calls are counted
  in `meta.json` (`llm.truncated_calls`).
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

- Split table cells: `System Co<br>ntrol` in wide register tables.
- `00` prefix on section numbers (font-encoded numbering).
- Stray bullet glyphs, inline page headers/footers, reversed/rotated cover text.
