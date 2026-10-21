"""pdf4llm CLI — PDF -> Markdown converter.

No subcommands. One command:
    pdf4llm <input.pdf> [more.pdf ...] [options]

Flow (per input PDF):
  1. validate the input PDF (--locate can find it by name in a folder)
  2. prompt-delete same-basename .docx/.txt and prompt-overwrite .md
     (skip all prompts with --force; --dry-run only reports them)
  3. convert to Markdown (+ .meta.json), UTF-8 no BOM
  4. optional --llm broken-text correction
  5. optional --copy of the .md into an additional folder
  6. print a one-line sanity score; exit non-zero if it scored badly

With multiple inputs every file is processed independently; the final
exit code is the worst (highest) per-file exit code.
"""
from __future__ import annotations

from pathlib import Path

import getpass
import os
import shutil
import time
from datetime import datetime

import pymupdf
import typer

from . import __version__, checks, config as cfg, convert, llm, prune

app = typer.Typer(no_args_is_help=True)


def _setup_llm() -> None:
    """Interactively set & save LLM credentials to the user config file.

    Fetches the available model list from the endpoint (/v1/models) and lets
    the user pick one; falls back to manual entry if the list can't be fetched.
    """
    c = cfg.load_config()
    endpoint = input(
        f"endpoint (base url, e.g. http://127.0.0.1:11434/v1) "
        f"[{c.get('endpoint', '')}]: "
    ).strip()
    # getpass: the key is not echoed while typing; previous value masked.
    api_key = getpass.getpass(
        f"api key [{cfg.mask(c.get('api_key', ''))}]: "
    ).strip()
    if endpoint:
        c["endpoint"] = endpoint
    if api_key:
        c["api_key"] = api_key

    endpoint = c.get("endpoint", "")
    api_key = c.get("api_key", "")
    models = cfg.fetch_models(endpoint, api_key)
    current = c.get("model", "")
    model = ""
    if models:
        typer.echo("Available models:")
        for i, m in enumerate(models, 1):
            marker = "  (current)" if m == current else ""
            typer.echo(f"  {i}. {m}{marker}")
        choice = input(
            f"Select model [1-{len(models)}] "
            f"(current: {current or 'none'}; empty keeps current): "
        ).strip()
        if choice.isdigit() and 1 <= int(choice) <= len(models):
            model = models[int(choice) - 1]
        else:
            model = choice  # empty keeps `current`
    else:
        typer.echo("Could not fetch model list — enter the model name manually.")
        model = input(f"model name [{current or 'none'}]: ").strip()
    if model:
        c["model"] = model

    path = cfg.save_config(c)
    typer.echo(
        f"LLM config saved to {path}  "
        f"(model={c.get('model')}, endpoint={c.get('endpoint')}, "
        f"api_key={cfg.mask(c.get('api_key', ''))})"
    )


_LOCATE_IDX_NAME = ".pdf4llm_locate.idx"
_LOCATE_IDX_HEADER = "pdf4llm-locate-index 1"


def _locate_index_path(folder: Path) -> Path:
    return folder / _LOCATE_IDX_NAME


def _locate_build_index(folder: Path) -> dict[str, list[str]]:
    """Walk `folder` once, write the on-disk index, return the name mapping.

    The index maps lowercase file name -> list of absolute path strings, so
    repeated --locate runs (especially over slow network shares) skip the
    expensive recursive directory walk entirely.
    """
    idx_path = _locate_index_path(folder)
    mapping: dict[str, list[str]] = {}
    lines: list[str] = [
        _LOCATE_IDX_HEADER,
        f"folder={folder.as_posix()}",
        f"built={datetime.now().isoformat(timespec='seconds')}",
    ]
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name == _LOCATE_IDX_NAME:
                continue
            full = os.path.join(root, name)
            mapping.setdefault(name.lower(), []).append(full)
            lines.append(f"{name.lower()}\t{full}")
    tmp_path = idx_path.with_name(idx_path.name + ".tmp")
    try:
        tmp_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp_path, idx_path)
    except OSError:
        pass  # unwritable share: locate still works, just without caching
    return mapping


def _locate_load_index(folder: Path) -> dict[str, list[str]] | None:
    """Load the index for `folder`; None if missing, corrupt or for another folder."""
    try:
        lines = _locate_index_path(folder).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if (
        len(lines) < 4
        or lines[0] != _LOCATE_IDX_HEADER
        or lines[1] != f"folder={folder.as_posix()}"
    ):
        return None
    mapping: dict[str, list[str]] = {}
    for line in lines[3:]:
        name, sep, full = line.partition("\t")
        if sep:
            mapping.setdefault(name, []).append(full)
    return mapping


def _locate_files(inputs: list[Path], folder: Path, rebuild: bool = False) -> list[Path]:
    """Resolve every `inputs` entry (a bare file NAME) to a path under `folder`.

    Matching is case-insensitive on the file NAME only (any subfolder).
    Each name must match exactly one file; otherwise exit with the match list.
    Uses the index file inside `folder` when possible; a missing target or a
    vanished match triggers one rebuild so new files are always found.
    """
    folder = folder.expanduser().resolve()
    for i in inputs:
        if i.parent != Path("."):
            typer.echo(
                f"error: --locate takes a file NAME, not a path: {i}", err=True,
            )
            raise typer.Exit(2)
    if not folder.is_dir():
        typer.echo(f"error: --locate folder not found: {folder}", err=True)
        raise typer.Exit(2)

    targets = list(dict.fromkeys(i.name.lower() for i in inputs))

    index = None if rebuild else _locate_load_index(folder)
    if index is not None:
        fresh = all(t in index for t in targets) and all(
            os.path.isfile(p) for t in targets for p in index[t]
        )
        if not fresh:
            index = None  # miss or stale match -> one rebuild
    if index is None:
        reason = "--locate-rebuild" if rebuild else "missing or stale"
        typer.echo(f"locate: building index for {folder} ({reason})...")
        t0 = time.perf_counter()
        index = _locate_build_index(folder)
        n = sum(len(v) for v in index.values())
        typer.echo(
            f"locate: index built: {n} files, {time.perf_counter() - t0:.1f}s "
            f"({_locate_index_path(folder)})"
        )

    results: list[Path] = []
    for i in inputs:
        matches = sorted(Path(p) for p in index.get(i.name.lower(), []))
        if not matches:
            typer.echo(
                f"error: --locate: no file named '{i.name}' found under {folder}",
                err=True,
            )
            raise typer.Exit(2)
        if len(matches) > 1:
            typer.echo(
                f"error: --locate: multiple matches for '{i.name}' under {folder}:",
                err=True,
            )
            for m in matches:
                typer.echo(f"  {m}", err=True)
            typer.echo(
                "narrow the search folder (or rename files) so exactly one matches.",
                err=True,
            )
            raise typer.Exit(2)
        results.append(matches[0])
    return results


def _locate_file(input: Path, folder: Path) -> Path:
    """Single-input convenience wrapper around `_locate_files`."""
    return _locate_files([input], folder)[0]


def _copy_output(md_path: Path, copy_to: Path, force: bool) -> None:
    """Copy the finished .md into an additional output folder (created if needed).

    If the target file exists, the same overwrite rules as elsewhere apply:
    ask y/N, or overwrite silently with --force. Declining only skips the
    copy — the primary output is already written.
    """
    copy_dir = copy_to.expanduser().resolve()
    copy_dir.mkdir(parents=True, exist_ok=True)
    dest = copy_dir / md_path.name
    if dest.resolve() == md_path.resolve():
        typer.echo(f"  copy skipped: source and target are the same: {dest}", err=True)
        return
    if dest.exists() and not force:
        if not prune.confirm(f"{dest.name} exists in {copy_dir}. Overwrite? [y/N] "):
            typer.echo(f"  copy skipped (declined): {dest}", err=True)
            return
    shutil.copyfile(md_path, dest)
    typer.echo(f"  copied: {dest}")


def _print_summary(meta: dict) -> None:
    ch = meta["checks"]
    typer.echo(
        f"{Path(meta['output']).name}  "
        f"{ch['chars']} chars  headings={ch['headings']}  "
        f"table_rows={ch['table_rows']}  hex={ch['hex_tokens']}  "
        f"score={ch['score']}"
    )
    if ch["cid_tokens"]:
        typer.echo(f"  warning: {ch['cid_tokens']} (cid: tokens")
    if ch["replacement_chars"]:
        typer.echo(f"  warning: {ch['replacement_chars']} U+FFFD replacement chars")
    if ch["empty_pages"]:
        typer.echo(f"  warning: {ch['empty_pages']} image-only/empty page(s) — need OCR")
    if ch["headings"] == 0:
        typer.echo("  warning: 0 headings — extraction likely failed")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pdf4llm {__version__}")
        raise typer.Exit()


@app.command()
def convert_cmd(
    inputs: list[Path] = typer.Argument(
        None, help="Path(s) to PDF file(s) (optional with --llm-auth)"
    ),
    version: bool = typer.Option(
        None, "--version", callback=_version_callback, is_eager=True,
        help="Show the pdf4llm version and exit.",
    ),
    out: Path = typer.Option(
        None, "--out", "-o", help="Output directory (default: same folder as the PDF)"
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Skip all y/N confirmations (delete/overwrite/copy-overwrite)",
    ),
    locate: Path = typer.Option(
        None, "--locate", metavar="FOLDER",
        help="Treat INPUT as a file NAME and search for it recursively in FOLDER "
             "(must match exactly one file)",
    ),
    locate_rebuild: bool = typer.Option(
        False, "--locate-rebuild",
        help="Force a fresh --locate scan, rewriting the index file in FOLDER",
    ),
    copy_to: Path = typer.Option(
        None, "--copy", metavar="FOLDER",
        help="Additionally copy the final .md into FOLDER (created if missing; "
             "existing file: ask y/N, or overwrite with --force)",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Show what would be done (locate result, cleanup, output and copy "
             "paths) without converting, writing, deleting or prompting",
    ),
    llm_flag: bool = typer.Option(
        False, "--llm", help="Run local-LLM broken-text correction (default off)"
    ),
    llm_auth: bool = typer.Option(
        False, "--llm-auth", help="Interactively set & save LLM credentials"
    ),
    model: str = typer.Option(
        None, "--model", help="Override LLM model (else from saved config)"
    ),
    pages: str = typer.Option(
        None, "--pages", help="Page subset, e.g. '1,3,5-7' (useful for short LLM tests)"
    ),
    llm_workers: int = typer.Option(
        None, "--llm-workers", min=1,
        help="Parallel LLM chunk requests. Default: auto from llama-swappy info "
             "(min(slots, 4)), else 1. Explicit value overrides the server.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Convert one or more PDFs to LLM-readable Markdown with a sanity score."""
    if llm_auth:
        _setup_llm()
        if not inputs:
            raise typer.Exit(0)
    if not inputs:
        typer.echo("error: no input file(s) given", err=True)
        raise typer.Exit(2)

    if locate is not None:
        inputs = _locate_files(inputs, locate, rebuild=locate_rebuild)

    codes: list[int] = []
    for pdf in inputs:
        codes.append(
            _process_one(
                pdf, out=out, force=force, copy_to=copy_to, dry_run=dry_run,
                pages=pages, llm_flag=llm_flag, model=model,
                llm_workers=llm_workers, verbose=verbose,
            )
        )
    raise typer.Exit(max(codes))


def _process_one(
    pdf: Path,
    out: Path | None,
    force: bool,
    copy_to: Path | None,
    dry_run: bool,
    pages: str | None,
    llm_flag: bool,
    model: str | None,
    llm_workers: int | None,
    verbose: bool,
) -> int:
    """Convert one PDF; returns the exit code for this file (0 = ok)."""
    if not pdf.is_file():
        typer.echo(f"error: not a file: {pdf}", err=True)
        return 2
    if pdf.suffix.lower() != ".pdf":
        typer.echo(f"error: not a PDF: {pdf}", err=True)
        return 2

    out_dir = (out if out else pdf.parent).resolve()
    md_planned = out_dir / (pdf.stem + ".md")
    typer.echo(f"source: {pdf}")

    if dry_run:
        prune.prune(pdf, out_dir, verbose=True, force=force, dry_run=True)
        typer.echo(f"  would write: {md_planned}")
        typer.echo(f"  would write: {md_planned.with_suffix('.meta.json')}")
        if llm_flag:
            typer.echo("  would run: --llm broken-text correction")
        if copy_to is not None:
            dest = copy_to.expanduser().resolve() / md_planned.name
            note = (
                "  (exists — would ask to overwrite; --force skips the ask)"
                if dest.exists() else ""
            )
            typer.echo(f"  would copy to: {dest}{note}")
        typer.echo("  dry-run: nothing written, deleted, or overwritten.")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    if not prune.prune(pdf, out_dir, verbose=True, force=force):
        typer.echo(
            "aborted: existing .md was not overwritten (declined) — nothing written.",
            err=True,
        )
        return 1

    try:
        md_path, meta = convert.convert(pdf, out_dir, pages)
    except pymupdf.FileDataError as e:
        typer.echo(f"error: cannot read PDF {pdf.name}: {e}", err=True)
        return 2

    if copy_to is not None:
        _copy_output(md_path, copy_to, force)

    if llm_flag:
        c = cfg.load_config()
        endpoint = c.get("endpoint")
        api_key = c.get("api_key")
        model = model or c.get("model")
        if not (endpoint and model):
            typer.echo(
                "error: --llm requires LLM config. Run once with --llm-auth.",
                err=True,
            )
            return 3
        text = md_path.read_text(encoding="utf-8")
        try:
            text, llm_stats = llm.correct_with_llm(
                text, model, endpoint, api_key, verbose=verbose,
                sampling=c.get("llm_sampling"), retries=int(c.get("llm_retries", 2)),
                workers=llm_workers,
            )
        except llm.LlmContextError as e:
            typer.echo(f"error: --llm aborted: {e}", err=True)
            return 4
        md_path.write_text(text, encoding="utf-8")
        meta["llm"] = llm_stats
        meta["checks"] = checks.run_checks(text, meta["page_chars"])
        convert.write_meta(meta)

        if llm_stats.get("chunks_rejected") or llm_stats.get("chunks_salvaged"):
            typer.echo(
                f"  llm: {llm_stats['chunks_accepted']}/{llm_stats['chunks_total']} "
                f"chunks accepted, {llm_stats.get('chunks_salvaged', 0)} salvaged "
                f"({llm_stats.get('blocks_fixed', 0)} blocks fixed), "
                f"{llm_stats['chunks_rejected']} rejected "
                "(originals kept — see meta.json)"
            )

    _print_summary(meta)

    return 0 if meta["checks"]["score"] >= 40 else 1


if __name__ == "__main__":
    app()
