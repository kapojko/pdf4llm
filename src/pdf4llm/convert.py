"""Single-file PDF -> Markdown conversion + .meta.json output.

Uses the pymupdf 2.x layout engine (pymupdf4llm 2.x is an empty stub; the
Markdown code now lives in ``pymupdf.layout``). The engine is a neural layout
analyzer (BoxRFDGNN) — heavier than the old shim but higher quality.
"""
from __future__ import annotations

import hashlib
import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

# pymupdf 2.x internals still import the legacy `fitz` alias; silence it.
warnings.filterwarnings("ignore", category=FutureWarning)

import pymupdf
from pymupdf.layout.MultiProcessWrapper import MultiProcessWrapper

from . import checks

_WRAPPER: MultiProcessWrapper | None = None


def _get_wrapper() -> MultiProcessWrapper:
    global _WRAPPER
    if _WRAPPER is None:
        _WRAPPER = MultiProcessWrapper()
    return _WRAPPER


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_pages(pages: str | None, page_count: int) -> list[int] | None:
    """Parse '1,3,5-7' into 0-based page indices; None means all pages."""
    if not pages:
        return None
    idx: set[int] = set()
    for part in pages.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            idx.update(range(int(a) - 1, int(b)))
        else:
            idx.add(int(part) - 1)
    return sorted(i for i in idx if 0 <= i < page_count)


def convert(pdf: Path, out_dir: Path, pages: str | None = None) -> tuple[Path, dict]:
    """Convert one PDF to Markdown next to (or in) out_dir.

    Returns (md_path, meta). Writes UTF-8 (no BOM) .md and .meta.json.
    """
    doc = pymupdf.open(str(pdf))
    page_chars = [len(p.get_text("text").strip()) for p in doc]
    page_count = doc.page_count
    idx = _parse_pages(pages, page_count)

    wrapper = _get_wrapper()
    if idx is None:
        md = wrapper.to_markdown(str(pdf))
    else:
        parts = [wrapper.to_markdown(doc[i]) for i in idx]
        md = "\n\n".join(p for p in parts if p.strip())
    doc.close()

    if isinstance(md, bytes):
        md = md.decode("utf-8")

    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / (pdf.stem + ".md")
    md_path.write_text(md, encoding="utf-8")

    result = checks.run_checks(md, page_chars)
    meta = {
        "source": str(pdf),
        "source_sha256": sha256_file(pdf),
        "page_count": page_count,
        "pages": pages,
        "output": str(md_path),
        "page_chars": page_chars,
        "checks": result,
        "llm": False,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    meta_path = out_dir / (pdf.stem + ".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return md_path, meta


def write_meta(meta: dict) -> None:
    meta_path = Path(meta["output"]).with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
