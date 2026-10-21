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

## LLM correction

No PDF-extraction library ships an LLM post-processing hook, so this is a custom
pass: the Markdown is chunked by heading/size and each chunk is sent to your
**local OpenAI-compatible LLM** (via **litellm**) to fix broken line breaks and
split words while preserving tables, pipe characters, `0x…` and `\d+x\d+` tokens.

Set credentials once:

```powershell
pdf4llm --llm-auth
```

Saved to the user config dir (Windows: `%APPDATA%\pdf4llm\config.json`,
POSIX: `~/.config/pdf4llm\config.json`) as `{endpoint, api_key, model}`. Then:

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
