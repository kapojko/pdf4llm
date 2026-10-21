"""Single-file PDF -> Markdown conversion + .meta.json output.

Uses the pymupdf 2.x layout engine (pymupdf4llm 2.x is an empty stub; the
Markdown code now lives in ``pymupdf.layout``). The engine is a neural layout
analyzer (BoxRFDGNN) — heavier than the old shim but higher quality.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

# pymupdf 2.x internals still import the legacy `fitz` alias and emit a
# FutureWarning. Suppress it in this process AND in the worker subprocesses
# the layout engine spawns (Windows uses spawn, so workers re-import from
# scratch and do NOT inherit in-process warning filters). Setting
# PYTHONWARNINGS in the environment reaches the child interpreters too.
os.environ.setdefault("PYTHONWARNINGS", "ignore::FutureWarning")
warnings.filterwarnings("ignore", category=FutureWarning)

import pymupdf
from pymupdf.layout.MultiProcessWrapper import MultiProcessWrapper

from . import checks
from .llm import _fmt_duration

_WRAPPER: MultiProcessWrapper | None = None
_DML_PATCHED = False


def _patch_dml_providers() -> None:
    """Teach pymupdf's BoxRFDGNN about DirectML.

    Its own resolver only knows CUDAExecutionProvider and falls back to CPU
    even when onnxruntime-directml is installed. The patch is applied in this
    process only — spawned pool workers re-import the library from scratch,
    so with DirectML the caller must run single-process (see _gpu_setup).
    """
    global _DML_PATCHED
    if _DML_PATCHED:
        return
    import onnxruntime as ort
    from pymupdf.layout.onnx.BoxRFDGNN import BoxRFDGNN

    def _resolve(use_gpu):
        if not use_gpu:
            return ["CPUExecutionProvider"]
        available = ort.get_available_providers()
        for provider in ("CUDAExecutionProvider", "DmlExecutionProvider"):
            if provider in available:
                return [provider, "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    BoxRFDGNN._resolve_providers = staticmethod(_resolve)
    _DML_PATCHED = True


def _cuda_dll_dirs() -> list[Path]:
    """bin dirs of the nvidia-* pip packages (CUDA/cuDNN runtime DLLs).

    Layouts seen in the wild: nvidia/<pkg>/bin, nvidia/cu13/bin/x86_64
    (nvidia-cublas 13.8 win wheels), nvidia/<pkg>/lib etc.
    """
    import sysconfig
    base = Path(sysconfig.get_paths()["purelib"])
    nvidia = base / "nvidia"
    if not nvidia.is_dir():
        return []
    dirs: set[Path] = set()
    for dll in nvidia.rglob("*.dll"):
        dirs.add(dll.parent)
    return sorted(dirs)


def _cuda_dlls_ok() -> bool:
    """True if a cublas runtime DLL is loadable (the DLL onnxruntime-gpu's
    CUDA provider is first to fail on). Non-Windows: assume OK."""
    if os.name != "nt":
        return True
    import ctypes
    for v in (13, 12, 11):
        try:
            ctypes.WinDLL(f"cublasLt64_{v}.dll")
            return True
        except OSError:
            continue
    return False


def _register_cuda_dll_dirs(dirs: list[Path]) -> None:
    """Make the CUDA DLL dirs visible to every loader that needs them.

    - PATH: used by onnxruntime's own LoadLibrary (C side) and inherited by
      the spawn-based pool worker processes;
    - os.add_dll_directory: needed by Python >=3.8, which no longer resolves
      bare-name ctypes loads via PATH.
    """
    for d in dirs:
        os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
        try:
            os.add_dll_directory(str(d))
        except (AttributeError, OSError):
            pass


def _gpu_setup() -> tuple[int, str]:
    """Execution setup for the neural layout engine. GPU is always requested.

    The default dependency is onnxruntime-gpu (CUDA); its runtime DLLs come
    from the optional 'cuda' extra (nvidia-cublas, nvidia-cuda-runtime,
    nvidia-cudnn-cu13). Their bin dirs are prepended to PATH here — spawn-based pool
    workers inherit the environment, so the provider works there too. With
    DirectML (Windows, AMD/Intel GPUs — optional extra) a small patch is
    needed instead, and spawned worker processes cannot inherit it, so
    conversion runs single-process there. Without any GPU provider pymupdf
    falls back to CPU on its own.

    Returns (n_workers, note).
    """
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
    except Exception:
        return 4, ""
    if "CUDAExecutionProvider" in available:
        _register_cuda_dll_dirs(_cuda_dll_dirs())
        if not _cuda_dlls_ok():
            return 4, (
                "layout engine: CUDA runtime DLLs not found (cublasLt64_*.dll) "
                "— install the 'cuda' extra (nvidia-cublas, nvidia-cudnn-cu13, "
                "...) or put CUDA on PATH; using CPU"
            )
        return 4, ""
    if "DmlExecutionProvider" in available:
        try:
            _patch_dml_providers()
        except Exception:
            return 1, ""
        return 1, (
            "layout engine: DirectML works only in the main process, "
            "conversion runs single-threaded"
        )
    # No GPU provider at all: pymupdf will silently run on CPU. This is a
    # degraded setup (slow on big datasheets) and must be visible up front.
    return 4, (
        "WARNING: layout engine has no GPU execution provider — running on CPU. "
        "For NVIDIA install onnxruntime-gpu with the 'cuda' extra (CUDA runtime "
        "DLLs); for AMD/Intel on Windows install the 'directml' extra"
    )


def _get_wrapper() -> MultiProcessWrapper:
    global _WRAPPER
    if _WRAPPER is None:
        print("  layout engine: loading model (BoxRFDGNN) ...", flush=True)
        n_workers, note = _gpu_setup()
        if note:
            # notes are always degraded-setup warnings -> stderr, so they are
            # impossible to miss at the start of the run
            print(f"  {note}", flush=True, file=sys.stderr)
        _WRAPPER = MultiProcessWrapper(use_gpu=True, n_workers=n_workers)
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
    page_count = doc.page_count
    page_chars = [len(p.get_text("text").strip()) for p in doc]
    idx = _parse_pages(pages, page_count)

    n = len(idx) if idx is not None else page_count
    print(
        f"  converting {n}/{page_count} page(s) with the neural layout engine "
        "— this can take minutes; fan noise means it is working ...",
        flush=True,
    )
    t0 = time.perf_counter()
    wrapper = _get_wrapper()
    if idx is None:
        md = wrapper.to_markdown(str(pdf))
    else:
        parts = [wrapper.to_markdown(doc[i]) for i in idx]
        md = "\n\n".join(p for p in parts if p.strip())
    doc.close()
    print(
        f"  layout engine: done in {_fmt_duration(time.perf_counter() - t0)} "
        "(includes model load on first use)",
        flush=True,
    )

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
