"""Tests for the 1.0.0 CLI additions: --force, --locate, --copy, --version."""
from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import pymupdf

from pdf4llm import __version__
from pdf4llm.cli import _locate_file, app
from pdf4llm.prune import prune

runner = CliRunner()


# ---------------------------------------------------------------- --version

def test_version_flag():
    res = runner.invoke(app, ["--version"])
    assert res.exit_code == 0
    assert __version__ in res.output
    assert "pdf4llm" in res.output


# ---------------------------------------------------------------- --locate

def test_locate_finds_unique_file(tmp_path: Path):
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    target = sub / "manual.pdf"
    target.write_bytes(b"%PDF-1.4")
    (tmp_path / "other.txt").write_text("x")

    got = _locate_file(Path("manual.pdf"), tmp_path)
    assert got == target


def test_locate_is_case_insensitive(tmp_path: Path):
    (tmp_path / "Manual.PDF").write_bytes(b"%PDF-1.4")
    assert _locate_file(Path("manual.pdf"), tmp_path) == tmp_path / "Manual.PDF"


def test_locate_no_match_exits(tmp_path: Path):
    with pytest.raises(typer.Exit) as e:
        _locate_file(Path("missing.pdf"), tmp_path)
    assert e.value.exit_code == 2


def test_locate_multiple_matches_exits(tmp_path: Path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "dup.pdf").write_bytes(b"1")
    (tmp_path / "b" / "dup.pdf").write_bytes(b"2")
    with pytest.raises(typer.Exit) as e:
        _locate_file(Path("dup.pdf"), tmp_path)
    assert e.value.exit_code == 2


def test_locate_rejects_path_input(tmp_path: Path):
    with pytest.raises(typer.Exit) as e:
        _locate_file(Path("sub/dir/file.pdf"), tmp_path)
    assert e.value.exit_code == 2


# ---------------------------------------------------------------- --force

def test_prune_force_deletes_without_asking(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    stale = tmp_path / "doc.txt"
    stale.write_text("stale")

    def fail_input(prompt=""):  # any prompt would mean --force didn't apply
        raise AssertionError("prompted despite --force")

    monkeypatch.setattr("builtins.input", fail_input)
    assert prune(pdf, tmp_path, force=True) is True
    assert not stale.exists()
    log = tmp_path / ".pdf4llm_prune.log"
    assert log.exists() and "delete" in log.read_text(encoding="utf-8")


def test_prune_force_overwrites_md(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    (tmp_path / "doc.md").write_text("old")

    def fail_input(prompt=""):
        raise AssertionError("prompted despite --force")

    monkeypatch.setattr("builtins.input", fail_input)
    assert prune(pdf, tmp_path, force=True) is True
    assert (tmp_path / "doc.md").exists()  # still there, converter rewrites it


def test_prune_without_force_still_asks(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    stale = tmp_path / "doc.txt"
    stale.write_text("stale")

    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert prune(pdf, tmp_path) is True
    assert stale.exists()  # declined -> kept


# ---------------------------------------------------------------- --dry-run

def _fake_pdf(tmp_path: Path, name: str = "doc.pdf") -> Path:
    """Create a small but VALID PDF (pymupdf must be able to open it)."""
    p = tmp_path / name
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Chapter One")
    page.insert_text((72, 92), "Some body text for the converter to chew on. " * 10)
    doc.save(str(p))
    doc.close()
    return p


def test_dry_run_writes_nothing(tmp_path: Path):
    pdf = _fake_pdf(tmp_path)
    outdir = tmp_path / "out"
    outdir.mkdir()
    (outdir / "doc.txt").write_text("stale")   # would be deleted
    (outdir / "doc.md").write_text("old")      # would be overwritten

    res = runner.invoke(app, [str(pdf), "-o", str(outdir), "--dry-run"])
    assert res.exit_code == 0
    assert "would delete" in res.output
    assert "would overwrite" in res.output
    assert "would write" in res.output and "dry-run" in res.output
    # nothing happened
    assert (outdir / "doc.txt").exists()
    assert (outdir / "doc.md").read_text(encoding="utf-8") == "old"
    assert not list(outdir.glob("*.meta.json"))
    assert not (outdir / ".pdf4llm_prune.log").exists()


def test_dry_run_reports_copy_plan(tmp_path: Path):
    pdf = _fake_pdf(tmp_path)
    copydir = tmp_path / "copy"
    copydir.mkdir()
    (copydir / "doc.md").write_text("old copy")

    res = runner.invoke(app, [str(pdf), "-o", str(tmp_path / "out"),
                              "--copy", str(copydir), "--dry-run"])
    assert res.exit_code == 0
    assert "would copy to" in res.output
    assert "exists" in res.output  # overwrite note for existing copy target
    assert (copydir / "doc.md").read_text(encoding="utf-8") == "old copy"


# ------------------------------------------------------------- multi inputs

def test_multiple_inputs_all_converted(tmp_path: Path):
    a = _fake_pdf(tmp_path, "a.pdf")
    b = _fake_pdf(tmp_path, "b.pdf")
    outdir = tmp_path / "out"
    # tiny PDFs may score below 40 -> accept either exit code, but both
    # output files must exist
    res = runner.invoke(app, [str(a), str(b), "-o", str(outdir)])
    assert (outdir / "a.md").exists()
    assert (outdir / "b.md").exists()
    assert (outdir / "a.meta.json").exists()
    assert (outdir / "b.meta.json").exists()


def test_multiple_inputs_bad_file_fails_run(tmp_path: Path):
    a = _fake_pdf(tmp_path, "a.pdf")
    notpdf = tmp_path / "nope.txt"
    notpdf.write_text("x")
    res = runner.invoke(app, [str(a), str(notpdf), "-o", str(tmp_path / "out")])
    assert res.exit_code == 2
    assert "not a PDF" in res.output


def test_no_inputs_errors():
    res = runner.invoke(app, [])
    assert res.exit_code == 2
    assert "no input file(s) given" in res.output
