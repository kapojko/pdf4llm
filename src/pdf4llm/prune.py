"""Duplicate-format cleanup for a single PDF's folder.

For every PDF, scan its own folder for files with the EXACT same basename
and extensions .docx/.txt (delete) or .md (overwrite). The PDF is the
source of truth. Per-file mandatory confirmation, bypassed only by the
explicit --force CLI flag (prune(..., force=True)).
An undo record (path + sha256 + size) is logged to .pdf4llm_prune.log.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

DELETE_EXTS = {".docx", ".txt"}
OVERWRITE_EXTS = {".md"}


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_duplicates(pdf: Path, out_dir: Path) -> list[Path]:
    """Exact-basename .docx/.txt/.md files in the output directory.

    The output dir is where the new .md (and any retired .docx/.txt) would
    live, so conflicts are checked there — not in the PDF's source folder.
    """
    if not out_dir.is_dir():
        return []
    base = pdf.stem
    out: list[Path] = []
    for p in out_dir.iterdir():
        if not p.is_file():
            continue
        if p.stem == base and p.suffix.lower() in (DELETE_EXTS | OVERWRITE_EXTS):
            out.append(p)
    return sorted(out)


def confirm(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def prune(
    pdf: Path, out_dir: Path, verbose: bool = True,
    force: bool = False, dry_run: bool = False,
) -> bool:
    """Prompt-delete .docx/.txt and prompt-overwrite .md for exact basenames.

    With force=True all confirmations are skipped and every duplicate is
    deleted/overwritten without asking (still logged to the undo log).

    With dry_run=True nothing is deleted, overwritten, prompted or logged;
    only a report of the actions that WOULD be taken is printed.

    Returns True to proceed with conversion, False if the user declined to
    overwrite an existing .md (which is the output file, so we must abort).
    """
    dups = find_duplicates(pdf, out_dir)
    if not dups:
        if verbose:
            print("  no same-basename .docx/.txt/.md found — nothing to clean up.")
        return True

    if dry_run:
        for p in dups:
            action = "delete" if p.suffix.lower() in DELETE_EXTS else "overwrite"
            how = " (forced)" if force else " (after y/N prompt)"
            print(f"  would {action}{how}: {p}")
        return True

    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / ".pdf4llm_prune.log"
    for p in dups:
        action = "delete" if p.suffix.lower() in DELETE_EXTS else "overwrite"
        verb = "Delete" if action == "delete" else "Overwrite"
        try:
            size = p.stat().st_size
            src_size = pdf.stat().st_size
        except OSError:
            continue
        prompt = (
            f"{p.name}  ({human_size(size)})  ←  source {pdf.name} "
            f"({human_size(src_size)}).  {verb}? [y/N] "
        )
        if force:
            if verbose:
                print(f"  forced: {action} {p.name} (--force)")
        elif not confirm(prompt):
            if verbose:
                print(f"  skipped {p.name}")
            if action == "overwrite":
                # declining means we can't write our own .md output
                return False
            continue
        try:
            digest = sha256_file(p)
        except OSError:
            digest = "unreadable"
        with open(log_path, "a", encoding="utf-8") as lf:
            lf.write(
                f"{datetime.now(timezone.utc).isoformat()}\t{action}\t{p}\t{size}\t{digest}\n"
            )
        if action == "delete":
            p.unlink()
            if verbose:
                print(f"  deleted {p.name}")
        else:
            if verbose:
                print(f"  will overwrite {p.name} (converter rewrites it)")
    return True
