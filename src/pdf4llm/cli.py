"""pdf4llm CLI — single-file PDF -> Markdown converter.

No subcommands. One command:
    pdf4llm <input.pdf> [options]

Flow:
  1. validate the input PDF
  2. prompt-delete same-basename .docx/.txt and prompt-overwrite .md
  3. convert to Markdown (+ .meta.json), UTF-8 no BOM
  4. optional --llm broken-text correction
  5. print a one-line sanity score; exit non-zero if it scored badly
"""
from __future__ import annotations

from pathlib import Path

import getpass

import typer

from . import checks, config as cfg, convert, llm, prune

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


@app.command()
def convert_cmd(
    input: Path = typer.Argument(
        None, help="Path to a single PDF file (optional with --llm-auth)"
    ),
    out: Path = typer.Option(
        None, "--out", "-o", help="Output directory (default: same folder as the PDF)"
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
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Convert one PDF to LLM-readable Markdown with a sanity score."""
    if llm_auth:
        _setup_llm()
        if input is None:
            raise typer.Exit(0)

    if input is None or not input.is_file():
        typer.echo(f"error: not a file: {input}", err=True)
        raise typer.Exit(2)
    if input.suffix.lower() != ".pdf":
        typer.echo(f"error: not a PDF: {input}", err=True)
        raise typer.Exit(2)

    out_dir = (out if out else input.parent).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    typer.echo(f"source: {input}")

    prune.prune(input, out_dir, verbose=True)

    md_path, meta = convert.convert(input, out_dir, pages)

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
            raise typer.Exit(3)
        text = md_path.read_text(encoding="utf-8")
        text = llm.correct_with_llm(text, model, endpoint, api_key, verbose=verbose)
        md_path.write_text(text, encoding="utf-8")
        meta["llm"] = True
        meta["checks"] = checks.run_checks(text, meta["page_chars"])
        convert.write_meta(meta)

    _print_summary(meta)

    score = meta["checks"]["score"]
    raise typer.Exit(0 if score >= 40 else 1)


if __name__ == "__main__":
    app()
