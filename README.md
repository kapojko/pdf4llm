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
.\build_install.ps1
```

Uses `uv tool install` (isolated env + a `pdf4llm` command on PATH) and copies the
shim into `C:\Programs\Util`. Requires `uv` on PATH.

To develop in-repo instead:

```powershell
uv sync
uv run pdf4llm <file.pdf>
```

## Usage

```
pdf4llm <input.pdf> [options]
```

| Flag | Purpose |
|------|---------|
| `input` | one PDF file (positional) |
| `-o/--out DIR` | output dir, **default = same folder as the PDF** |
| `--pages A-B,12,15` | page subset (useful for short LLM tests) |
| `--llm` | run local-LLM broken-text correction (default **off**) |
| `--llm-auth` | interactively set & save LLM credentials |
| `--model NAME` | override LLM model (else from saved config) |
| `-v/--verbose` | verbose output |

No subcommands. For each PDF the tool:
1. scans its own folder for **exact-basename** `.docx`/`.txt` (delete) and `.md`
   (overwrite), asking a **mandatory per-file y/N** (shows both file sizes; no
   `--yes` bypass). An undo record (path + sha256 + size) is written to
   `.pdf4llm_prune.log`.
2. converts to `<basename>.md` (**UTF-8, no BOM**) + `<basename>.meta.json`.
3. optionally runs the `--llm` correction pass.
4. prints a one-line sanity score and exits non-zero if it scored badly.

## LLM correction (safe by construction)

No PDF-extraction library ships an LLM post-processing hook, so this is a custom
pass. It is built so that a hallucinating model **cannot** corrupt the document —
safety is enforced by an algorithmic verifier, never by trusting the model:

1. **Classification** — the document head is classified (datasheet/reference
   manual vs general) by the LLM, with a keyword-heuristic fallback; any
   ambiguity or error defaults to the strict technical prompt. This only
   selects the prompt — never the safety rules.
2. **Constrained edits** — the model may only perform whitespace-level fixes:
   join split words (`D-t yp e` → `D-type`), subscript joins (`V CC` → `VCC`,
   `T amb` → `Tamb`), part-number hyphen joins (`SOT108 - 1` → `SOT108-1`),
   false line-break removal. Nothing else.
3. **Algorithmic verifier** (per chunk, non-negotiable):
   - *Invariant A*: whitespace-stripped input and output are byte-identical —
     catches any inserted/deleted/reordered content character (rephrasing,
     translation, "helpful" completions).
   - *Invariant B*: table rows keep their cell count; cell edits are checked
     individually (most datasheet data lives in cells).
   - *Invariant C*: a removed whitespace run is only allowed where a whitelist
     says the join cannot corrupt a value (`letter|letter`, `digit|-`,
     `.|digit`, …). Digit-digit and digit/symbol joins (`2 0` → `20`,
     `0x30 08` → `0x3008`, `V CC + 0.5` → `VCC+ 0.5`, `25 °C` → `25°C`) are
     structurally forbidden.
4. **Recovery** — a rejected chunk is not simply discarded: it goes through
   line/block-level **salvage** (only independently verified pieces are
   applied, the rest reverts), then up to `llm_retries` regeneration attempts
   with a rejection-reason hint, keeping the best. Whatever still fails
   verification stays as the original — rejection is always safe, never
   silent. All decisions are logged to `meta.json` (`llm` section:
   classification, accepted/salvaged/rejected counts, per-chunk reasons).

A duplicated-bullet cleanup (`- • x` → `- x`) runs deterministically before the
LLM pass — no model involvement.

Set credentials once:

```powershell
pdf4llm --llm-auth
```

Saved to the user config dir (Windows: `%APPDATA%\pdf4llm\config.json`,
POSIX: `~/.config/pdf4llm\config.json`) as `{endpoint, api_key, model}`.
Optional keys: `llm_sampling` (dict forwarded to the model; defaults to the
Ornith-1.5-9B card's precise-coding set: `temperature 0.6, top_p 0.95,
top_k 20, min_p 0.0, presence_penalty 0.0`) and `llm_retries` (default 1).
Then:

```powershell
pdf4llm <file.pdf> --llm --pages 1-10
```

`litellm` is the pluggable client — it works with Ollama, llama.cpp
(llama-server), or any OpenAI-compatible endpoint.

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
