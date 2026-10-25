"""--locate index file handling and --locate-mode file discovery.

Index: `.pdf4llm_locate.idx` inside the locate folder maps lowercase file
name -> absolute path, so repeated --locate runs (especially over slow
network shares) skip the expensive recursive directory walk entirely.

Discovery trusts the index: it does NOT stat every indexed PDF to check it
still exists (thousands of slow network round-trips). Existence of the
files actually selected for processing is verified separately (small set,
parallel); vanished files are reported as stale index entries.

Discovery (--locate-mode without explicit input names): selects the files
to process from the folder using the SAME index (no second walk). The
modes nest, each including the previous one:

    update < update-all < convert < convert-all

  update      previously converted (meta.json present) files that are
              stale: missing/invalid pdf4llm_version or llm_model, a
              pdf4llm version that differs in major.minor (patch-only
              differences are accepted), or — when the LLM pass is enabled —
              a different LLM model than the one this run would use;
  update-all  all previously converted files (with meta.json);
  convert     update-all plus PDFs that have same-basename .docx/.txt/.md
              siblings (i.e. files conversion would delete/overwrite);
  convert-all every PDF in the folder.

The index is never rebuilt automatically for discovery (it can be big and
expensive); use --locate-rebuild to (re)build it.
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

_LOCATE_IDX_NAME = ".pdf4llm_locate.idx"
_LOCATE_IDX_HEADER = "pdf4llm-locate-index 1"

# nesting order: update < update-all < convert < convert-all
MODES = ("update", "update-all", "convert", "convert-all")


class DiscoveryError(Exception):
    """Fatal discovery problem (bad folder, missing index, bad mode)."""


# ------------------------------------------------------------------- index

def locate_index_path(folder: Path) -> Path:
    return folder / _LOCATE_IDX_NAME


def build_index(folder: Path) -> dict[str, list[str]]:
    """Walk `folder` once, write the on-disk index, return the name mapping.

    The index maps lowercase file name -> list of absolute path strings, so
    repeated --locate runs (especially over slow network shares) skip the
    expensive recursive directory walk entirely.
    """
    idx_path = locate_index_path(folder)
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


def load_index(folder: Path) -> dict[str, list[str]] | None:
    """Load the index for `folder`; None if missing, corrupt or for another folder."""
    try:
        lines = locate_index_path(folder).read_text(encoding="utf-8").splitlines()
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


# --------------------------------------------------------------- discovery

@dataclass
class DiscoveryEntry:
    pdf: Path
    action: str    # "update" | "reconvert" | "convert"
    reason: str    # human-readable why this file was selected / what happens


def staleness_reason(
    meta_path: Path,
    current_version: str,
    current_model: str | None,
    llm_enabled: bool,
) -> str | None:
    """Return why the conversion recorded in meta_path is stale, else None.

    Stale = meta.json missing/unreadable, a pdf4llm_version that differs in
    major.minor (a patch-only difference is NOT stale), or — when the LLM
    pass is enabled — no/other llm_model.
    """
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "meta.json missing or unreadable"
    ver = meta.get("pdf4llm_version")
    if not ver:
        return "meta.json has no pdf4llm_version (pre-1.7 conversion)"
    if ver != current_version:
        # patch-only differences (1.4.0 vs 1.4.3) do not make the file stale:
        # only major.minor carries conversion-behaviour changes
        mm_meta, mm_cur = _major_minor(str(ver)), _major_minor(current_version)
        if mm_meta is None or mm_cur is None or mm_meta != mm_cur:
            return f"converted with pdf4llm {ver}"
    if llm_enabled:
        m = meta.get("llm_model")
        if not m:
            return "converted without the LLM pass"
        if m != current_model:
            return f"converted with model {m}"
    return None


def _major_minor(version: str) -> tuple[int, int] | None:
    """(major, minor) of an 'X.Y[.Z...]' version string, else None."""
    m = re.match(r"(\d+)\.(\d+)", version.strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _side_files(pdf: Path) -> tuple[list[Path], Path | None]:
    """Existing same-basename .docx/.txt (deleted on conversion) and .md."""
    delete = [s for s in (pdf.with_suffix(".docx"), pdf.with_suffix(".txt"))
              if s.is_file()]
    md = pdf.with_suffix(".md")
    return delete, (md if md.is_file() else None)


def _reason_for(pdf: Path, stale: str | None, has_meta: bool) -> tuple[str, str]:
    """Build (action, reason) for one discovered file."""
    delete, md = _side_files(pdf)
    parts: list[str] = []
    if stale:
        parts.append(stale)
    elif has_meta:
        parts.append("already current")
    if md is not None:
        parts.append("overwrite .md")  # same stem, name adds no information
    if delete:
        parts.append("delete " + ", ".join(d.name for d in delete))
    if stale:
        return "update", "; ".join(parts)
    if has_meta:
        return "reconvert", "; ".join(parts) or "previously converted"
    return "convert", "; ".join(parts) or "new file"


_DISCOVERY_WORKERS = 32  # parallel meta.json/side-file network ops


def discover(
    folder: Path,
    mode: str,
    rebuild: bool = False,
    current_version: str = "",
    current_model: str | None = None,
    llm_enabled: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> list[DiscoveryEntry]:
    """Collect the files to process for `mode` (see module docstring).

    Uses the locate index; never rebuilds it implicitly. Raises
    DiscoveryError on a bad folder/mode or a missing/unusable index.

    Per-candidate work (meta.json staleness read, side-file stats) runs in a
    thread pool — on network shares it is latency-bound, so parallelism cuts
    wall time drastically. `progress(done, total)` is called from the caller's
    thread as candidates complete (for a progress line).
    """
    if mode not in MODES:
        raise DiscoveryError(
            f"unknown --locate-mode '{mode}' (valid: {', '.join(MODES)})")
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise DiscoveryError(f"--locate folder not found: {folder}")

    index = None if rebuild else load_index(folder)
    if index is None:
        if rebuild:
            index = build_index(folder)
        else:
            raise DiscoveryError(
                f"no usable locate index in {folder} — "
                "run once with --locate-rebuild to build it")

    # candidate PDFs straight from the index; existence is NOT checked here
    # (trusting the index avoids a stat per PDF over the network)
    pdfs: set[Path] = set()
    for name, paths in index.items():
        if name.endswith(".pdf"):
            pdfs.update(Path(p) for p in paths)
    ordered = sorted(pdfs, key=lambda p: p.as_posix().lower())
    total = len(ordered)

    def evaluate(pdf: Path) -> DiscoveryEntry | None:
        meta_path = pdf.with_suffix(".meta.json")
        has_meta = meta_path.is_file()
        stale = (
            staleness_reason(
                meta_path, current_version, current_model, llm_enabled)
            if has_meta else None
        )
        if mode == "update" and not stale:
            return None
        if mode == "update-all" and not has_meta:
            return None
        if mode == "convert" and not has_meta:
            delete, md = _side_files(pdf)
            if not delete and md is None:
                return None
        # convert-all: everything
        action, reason = _reason_for(pdf, stale, has_meta)
        return DiscoveryEntry(pdf, action, reason)

    selected: list[DiscoveryEntry] = []
    done = 0
    with ThreadPoolExecutor(max_workers=_DISCOVERY_WORKERS) as ex:
        futures = [ex.submit(evaluate, pdf) for pdf in ordered]
        for fut in as_completed(futures):
            done += 1
            if progress is not None:
                progress(done, total)
            entry = fut.result()
            if entry is not None:
                selected.append(entry)
    selected.sort(key=lambda e: e.pdf.as_posix().lower())
    return selected
