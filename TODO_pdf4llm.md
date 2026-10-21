# TODO: pdf4llm-batch — batch PDF→Markdown converter for datasheets / hardware manuals

Project for converting 10–20 datasheets & hardware manuals at a time into LLM-readable
Markdown, to be supplied as context for schematic / firmware development.

Reference case: `S:/Электроника/Дисплеи и камеры/OV5640 5 MPixel/OV5640_datasheet.pdf`
(2-column OmniVision datasheet, register maps as wide tables).

## Core engine

- Engine: `pymupdf4llm` (NOT bare pymupdf — its `_to_markdown` is just a shim calling
  pymupdf4llm; bare pymupdf only gives raw primitives: `get_text("dict")`,
  `find_tables()`, `get_drawings()`, layout analysis would have to be hand-written).
- markitdown (pdfminer.six-based) is NOT suitable for datasheets: no headings extracted,
  register tables collapse to jumbled paragraphs, 2-column reading order broken.
  Keep markitdown only for .docx/.pptx inputs if ever needed.

## Project setup (uv)

- `uv init` + `uv add pymupdf4llm` (pulls pymupdf + pymupdf-layout).
- Optional extras: `rapidfuzz`? no — `rapidocr-onnxruntime` for scanned pages
  (pymupdf4llm warns "RapidOCR is missing" when a page has no text layer).
- Python ≥ 3.10. CLI via `argparse` or `typer` (typer preferred, matches uv tooling).
- Console entry point: `pdf4llm = "src/pdf4llm/cli.py:app"`.

## CLI design

```
pdf4llm convert <input> [-o outdir] [options] [--prune]
pdf4llm check   <files-or-dir>             # sanity report only, no conversion
pdf4llm prune   <dir> [-r]                 # cleanup pass only, no conversion
```

- Two modes:
  - **single-file mode**: `<input>` is one PDF → one `.md` next to it (or `-o`).
  - **batch recursive mode**: `<input>` is a directory (or glob) → walk tree,
    convert every PDF, mirror structure under output dir; prune available.
- **Recursive mode**: `-r/--recursive` — walk dir tree for `*.pdf`, mirror structure
  under output dir. Windows: handle Cyrillic / spaces in paths ( pathlib, never
  shell=True, never PowerShell `>` redirection).
- `-o/--out DIR` (default `./md_out/`), `--overwrite | --skip-existing`.
- `--pages A-B,12,15` page-range subsetting (pymupdf4llm `pages=` param).
- `--layout | --no-layout` — pymupdf 2.0 uses the new layout engine by default
  (`use_layout`); expose fallback to legacy parser for odd PDFs.
- `--chunks` — additionally emit `pymupdf4llm.to_chunks()` JSON (one record per
  logical block + page/heading metadata) — useful for RAG-style retrieval later.
- `--workers N` — parallel conversion (CPU-bound; 2–4 is plenty).

## Duplicate-format cleanup (prune) — batch recursive mode

Purpose: retire artifacts of the old manual chains (ilovepdf→docx→convertio txt,
PowerShell `>` md) once this tool is the single conversion path.

- Discovery: for every PDF found, scan **its own folder only** for files with the
  exact same basename and extensions `.docx`, `.txt`, `.md` (case-insensitive on
  Windows). **PDF always wins** — it is the source of truth.
- Action matrix:
  - same-basename `.docx` / `.txt` → **delete**, mandatory confirmation
  - same-basename `.md` → **overwrite** (regenerate from PDF), mandatory confirmation
  - docx/txt/md with NO matching PDF → **never touched, never listed**
    (e.g. ESP32-CAM module docx files that exist without a PDF)
- Mandatory **per-file** confirmation (target dirs hold hundreds–thousands of
  PDFs; one global y/N is too risky). Each prompt names the existing PDF and the
  human-readable size of BOTH files, to prevent mistaken deletion of a valuable
  docx that merely shares a basename:

  ```
  OV5640_datasheet.docx  (1.6 MB)  ←  source OV5640_datasheet.pdf (1.7 MB).  Delete? [y/N]
  OV5640_datasheet.md    (0.6 MB)  ←  source OV5640_datasheet.pdf (1.7 MB).  Overwrite? [y/N]
  ```

- No `--yes` bypass flag by design — confirmation is mandatory.
- Before deleting/overwriting, log an undo record (path + sha256 + size) to a
  `.pdf4llm_prune.log` in the output dir, so mistakes are at least traceable.
- Runnable standalone without converting: `pdf4llm prune <dir> -r`.

## Per-file post-conversion sanity checks (the point of the tool)

For each output, report a one-line quality score:

1. File written, size, and encoding is UTF-8 (assert BOM-free UTF-8; reject UTF-16).
2. Heading count (`^#{1,6} `) — 0 headings ⇒ extraction likely failed.
3. Table rows: count of `^\|` lines; ratio of rows with equal column count.
4. Register/table hit density for electronics docs: count of
   `0x[0-9A-Fa-f]{2,4}` tokens and `\d+x\d+` resolutions (2592x1944 etc.).
5. Broken-glyph warnings: `(cid:` occurrences, `�` U+FFFD, lone `?` bullets.
6. Empty-page detection: pages producing < 20 chars (likely image-only — needs OCR
   or manual/vision handling; pin diagrams & reference schematics are ALWAYS
   image-only — text extractors never get them).
7. Exit non-zero / summary table if a file scored badly.

## Encoding & output rules (hard-won lessons)

- Always write UTF-8 without BOM. PowerShell `>` writes UTF-16LE — never redirect;
  use `-o`/`write_path` or Python file writes.
- Never convert PDF→docx→txt via ilovepdf/convertio chains: two lossy hops, mangled
  cp1252 symbols (°, µ), mixed CR/LF. Single hop PDF→md from the original.
- Preserve tables with `<br>` inside cells (pymupdf4llm does this); do not strip them.
- Keep original filename, extension → `.md`; write a `.meta.json` next to it
  (source path, page count, sha256, per-check scores, timestamp).

## Known artifacts to document in README (acceptable, post-filterable)

- Split table cells: `System Co<br>ntrol` in wide register tables.
- `00` prefix on section numbers (font-encoded numbering, e.g. "00features").
- Stray bullet glyphs (`�`), page headers/footers inline ("PRODUCT SPECIFICATION
  version 2.03", page numbers) — possible future `--drop-headers` heuristic filter.
- Reversed/rotated cover-page text ("0465VO").

## Later / nice to have

- `--incremental`: sha256 cache, re-convert only changed PDFs.
- Header/footer removal by repeated-line detection across pages.
- Merge of split cells (`Co<br>ntrol` → `Control`) via heuristic repair pass.
- Vision fallback hook for image-only pages (send page raster to a VLM, or embed
  `![page](...)` references so the agent knows to look at the PDF).
- Optional docling/marker backend flag for benchmark comparison.
- Tests: OV5640 datasheet as fixture; assert heading count > 100, register rows > 500,
  zero `(cid:` (after RapidOCR install check), UTF-8.

## Acceptance test

`pdf4llm convert "S:/Электроника/Дисплеи и камеры/**/*.pdf" -o S:/md_out -r`
→ every PDF gets an UTF-8 .md + .meta.json, sanity report printed,
OV5640 output contains `0x3008 SYSTEM CTROL0` inside a markdown table row.

`pdf4llm prune "S:/Электроника/Дисплеи и камеры" -r`
→ lists `OV5640_datasheet.docx/.txt/.md` (same folder as the PDF) with both file
  sizes, asks per-file y/N; untouched: `Модуль камеры OV5640 ... (C).docx` (no
  matching PDF) and everything in `Forums/` (no PDF there).
