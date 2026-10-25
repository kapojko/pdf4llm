"""Tests for --locate-mode discovery (pdf4llm 1.7.0) and meta provenance."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pdf4llm import __version__
from pdf4llm import cli as cli_mod
from pdf4llm.locate_index import (
    DiscoveryError,
    build_index,
    discover,
    staleness_reason,
)

runner = CliRunner()


# ------------------------------------------------------------- staleness

def _write_meta(path: Path, **fields) -> Path:
    meta = {"pdf4llm_version": __version__, "llm_model": "m1", "llm": {}}
    meta.update(fields)
    path.write_text(json.dumps(meta), encoding="utf-8")
    return path


def test_staleness_fresh(tmp_path: Path):
    mp = _write_meta(tmp_path / "a.meta.json")
    assert staleness_reason(mp, __version__, "m1", llm_enabled=True) is None


def test_staleness_old_version(tmp_path: Path):
    mp = _write_meta(tmp_path / "a.meta.json", pdf4llm_version="0.9.0")
    assert "0.9.0" in staleness_reason(mp, __version__, "m1", llm_enabled=True)


def test_staleness_no_version_field(tmp_path: Path):
    mp = tmp_path / "a.meta.json"
    mp.write_text(json.dumps({"llm": False}), encoding="utf-8")
    r = staleness_reason(mp, __version__, "m1", llm_enabled=True)
    assert r is not None and "pdf4llm_version" in r


def test_staleness_corrupt_meta(tmp_path: Path):
    mp = tmp_path / "a.meta.json"
    mp.write_text("{not json", encoding="utf-8")
    r = staleness_reason(mp, __version__, "m1", llm_enabled=True)
    assert r is not None and "unreadable" in r


def test_staleness_missing_meta(tmp_path: Path):
    r = staleness_reason(tmp_path / "a.meta.json", __version__, "m1", llm_enabled=True)
    assert r is not None and "missing" in r


def test_staleness_no_llm_model_when_llm_enabled(tmp_path: Path):
    mp = _write_meta(tmp_path / "a.meta.json", llm_model=None)
    r = staleness_reason(mp, __version__, "m1", llm_enabled=True)
    assert r is not None and "without the LLM pass" in r


def test_staleness_different_model(tmp_path: Path):
    mp = _write_meta(tmp_path / "a.meta.json", llm_model="old-model")
    r = staleness_reason(mp, __version__, "m1", llm_enabled=True)
    assert r is not None and "old-model" in r


def test_staleness_model_ignored_when_llm_disabled(tmp_path: Path):
    mp = _write_meta(tmp_path / "a.meta.json", llm_model="old-model")
    assert staleness_reason(mp, __version__, "m1", llm_enabled=False) is None


# -------------------------------------------------------------- discovery

@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """stale.pdf / fresh.pdf / side.docx+plain.pdf / md-only.pdf / bare.pdf."""
    f = tmp_path / "fresh.pdf"
    f.write_bytes(b"%PDF")
    _write_meta(f.with_suffix(".meta.json"))
    s = tmp_path / "stale.pdf"
    s.write_bytes(b"%PDF")
    _write_meta(s.with_suffix(".meta.json"), pdf4llm_version="0.9.0")
    p = tmp_path / "plain.pdf"
    p.write_bytes(b"%PDF")
    (tmp_path / "plain.docx").write_text("x")
    m = tmp_path / "mdonly.pdf"
    m.write_bytes(b"%PDF")
    (tmp_path / "mdonly.md").write_text("x")
    b = tmp_path / "bare.pdf"
    b.write_bytes(b"%PDF")
    build_index(tmp_path)
    return tmp_path


def test_discover_update_only_stale(tree: Path):
    got = [e.pdf.stem for e in discover(tree, "update", current_version=__version__, current_model="m1")]
    assert got == ["stale"]


def test_discover_update_all_converted(tree: Path):
    got = sorted(e.pdf.stem for e in discover(
        tree, "update-all", current_version=__version__, current_model="m1"))
    assert got == ["fresh", "stale"]


def test_discover_convert_includes_side_files(tree: Path):
    got = sorted(e.pdf.stem for e in discover(
        tree, "convert", current_version=__version__, current_model="m1"))
    assert got == ["fresh", "mdonly", "plain", "stale"]


def test_discover_convert_all_everything(tree: Path):
    got = sorted(e.pdf.stem for e in discover(
        tree, "convert-all", current_version=__version__))
    assert got == ["bare", "fresh", "mdonly", "plain", "stale"]


def test_discover_actions(tree: Path):
    by_stem = {e.pdf.stem: e for e in discover(
        tree, "convert-all", current_version=__version__, current_model="m1")}
    assert by_stem["stale"].action == "update"
    assert "0.9.0" in by_stem["stale"].reason
    assert by_stem["fresh"].action == "reconvert"
    assert by_stem["plain"].action == "convert"
    assert "plain.docx" in by_stem["plain"].reason
    assert by_stem["mdonly"].action == "convert"
    assert "mdonly.md" in by_stem["mdonly"].reason
    assert by_stem["bare"].action == "convert"


def test_discover_requires_index(tmp_path: Path):
    (tmp_path / "x.pdf").write_bytes(b"%PDF")
    with pytest.raises(DiscoveryError):
        discover(tmp_path, "update-all", current_version=__version__)


def test_discover_rebuild_builds_index(tmp_path: Path):
    (tmp_path / "x.pdf").write_bytes(b"%PDF")
    got = discover(tmp_path, "convert-all", rebuild=True, current_version=__version__)
    assert [e.pdf.stem for e in got] == ["x"]
    assert (tmp_path / ".pdf4llm_locate.idx").exists()


def test_discover_unknown_mode(tree: Path):
    with pytest.raises(DiscoveryError):
        discover(tree, "nope", current_version=__version__)


def test_discover_llm_enabled_missing_model_is_stale(tree: Path):
    # fresh.pdf was converted with model m1; run would use m2 -> stale
    got = [e.pdf.stem for e in discover(
        tree, "update", current_version=__version__,
        current_model="m2", llm_enabled=True)]
    assert got == ["fresh", "stale"]


# -------------------------------------------------------------- CLI gate

@pytest.fixture()
def fake_llm(monkeypatch):
    monkeypatch.setattr(cli_mod.cfg, "load_config", lambda: {"model": "m1"})


@pytest.fixture()
def fake_process(monkeypatch):
    calls: list[Path] = []

    def fake(pdf, **kwargs):
        calls.append(pdf)
        return 0

    monkeypatch.setattr(cli_mod, "_process_one", fake)
    return calls


def test_cli_locate_mode_without_locate_errors():
    res = runner.invoke(cli_mod.app, ["--locate-mode", "update-all"])
    assert res.exit_code == 2
    assert "--locate-mode" in res.output


def test_cli_locate_mode_with_inputs_errors(fake_llm, tree: Path):
    res = runner.invoke(cli_mod.app, [
        "stale.pdf", "--locate", str(tree), "--locate-mode", "update-all"])
    assert res.exit_code == 2


def test_cli_locate_mode_unknown_errors(fake_llm, tree: Path):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "nope"])
    assert res.exit_code == 2
    assert "nope" in res.output


def test_cli_discovery_without_index_errors(fake_llm, tmp_path: Path):
    (tmp_path / "x.pdf").write_bytes(b"%PDF")
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tmp_path), "--locate-mode", "update-all"])
    assert res.exit_code == 2
    assert "--locate-rebuild" in res.output


def test_cli_discovery_dry_run_lists_without_prompt(fake_llm, tree: Path):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update-all", "--dry-run"])
    assert res.exit_code == 0
    assert "2 file(s)" in res.output
    assert "dry-run" in res.output


def test_cli_discovery_declined_aborts(fake_llm, tree: Path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update-all"])
    assert res.exit_code == 1
    assert "declined" in res.output


def test_cli_discovery_force_processes_list(fake_llm, tree: Path, fake_process):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update-all", "--force",
        "--no-llm"])
    assert res.exit_code == 0, res.output
    assert sorted(p.stem for p in fake_process) == ["fresh", "stale"]


def test_cli_discovery_update_mode_through_cli(fake_llm, tree: Path, fake_process):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update", "--force",
        "--no-llm"])
    assert res.exit_code == 0, res.output
    assert [p.stem for p in fake_process] == ["stale"]
    assert "update" in res.output


def test_cli_discovery_convert_mode_through_cli(fake_llm, tree: Path, fake_process):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "convert", "--force",
        "--no-llm"])
    assert res.exit_code == 0, res.output
    assert sorted(p.stem for p in fake_process) == \
        ["fresh", "mdonly", "plain", "stale"]


def test_cli_discovery_approval_accepts(fake_llm, tree: Path, fake_process,
                                        monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "convert-all", "--no-llm"])
    assert res.exit_code == 0, res.output
    assert len(fake_process) == 5


def test_cli_discovery_llm_without_config_errors(tree: Path, monkeypatch):
    monkeypatch.setattr(cli_mod.cfg, "load_config", lambda: {})
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update-all", "--force"])
    assert res.exit_code == 3
    assert "--llm-auth" in res.output


# ------------------------------------------------- meta provenance fields

def test_meta_has_version_and_llm_model_fields():
    from pdf4llm import convert

    examples = Path(__file__).resolve().parent.parent / "examples"
    pdf = examples / "74HC_HCT74.pdf"
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        _, meta = convert.convert(pdf, Path(td))
        assert meta["pdf4llm_version"] == __version__
        assert meta["llm_model"] is None  # filled in after the LLM pass
