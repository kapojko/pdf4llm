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


def test_staleness_patch_version_difference_not_stale(tmp_path: Path):
    # patch-only differences (either direction) do not require an update
    mp = _write_meta(tmp_path / "a.meta.json", pdf4llm_version="1.4.0")
    assert staleness_reason(mp, "1.4.3", "m1", llm_enabled=True) is None
    mp2 = _write_meta(tmp_path / "b.meta.json", pdf4llm_version="1.4.9")
    assert staleness_reason(mp2, "1.4.0", "m1", llm_enabled=True) is None


def test_staleness_minor_version_difference_stale(tmp_path: Path):
    mp = _write_meta(tmp_path / "a.meta.json", pdf4llm_version="1.4.0")
    r = staleness_reason(mp, "1.5.0", "m1", llm_enabled=True)
    assert r is not None and "1.4.0" in r


def test_staleness_unparseable_version_stale(tmp_path: Path):
    mp = _write_meta(tmp_path / "a.meta.json", pdf4llm_version="dev")
    assert staleness_reason(mp, __version__, "m1", llm_enabled=True) is not None


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


def test_discover_update_reprocess_all_converted(tree: Path):
    got = sorted(e.pdf.stem for e in discover(
        tree, "update", current_version=__version__, current_model="m1",
        reprocess=True))
    assert got == ["fresh", "stale"]


def test_discover_convert_includes_side_files(tree: Path):
    got = sorted(e.pdf.stem for e in discover(
        tree, "convert", current_version=__version__, current_model="m1"))
    assert got == ["mdonly", "plain", "stale"]


def test_discover_all_skips_current(tree: Path):
    # all: new files and side-file siblings included, but previously
    # converted files that are already current are skipped
    got = sorted(e.pdf.stem for e in discover(
        tree, "all", current_version=__version__, current_model="m1"))
    assert got == ["bare", "mdonly", "plain", "stale"]


def test_discover_all_reprocess_includes_current(tree: Path):
    got = sorted(e.pdf.stem for e in discover(
        tree, "all", current_version=__version__, current_model="m1",
        reprocess=True))
    assert got == ["bare", "fresh", "mdonly", "plain", "stale"]


def test_discover_actions(tree: Path):
    by_stem = {e.pdf.stem: e for e in discover(
        tree, "all", current_version=__version__, current_model="m1",
        reprocess=True)}
    assert by_stem["stale"].action == "update"
    assert "0.9.0" in by_stem["stale"].reason
    assert by_stem["fresh"].action == "reconvert"
    assert "--locate-reprocess" in by_stem["fresh"].reason
    assert by_stem["plain"].action == "convert"
    assert "plain.docx" in by_stem["plain"].reason
    assert by_stem["mdonly"].action == "convert"
    assert "overwrite .md" in by_stem["mdonly"].reason
    assert by_stem["bare"].action == "convert"


def test_discover_requires_index(tmp_path: Path):
    (tmp_path / "x.pdf").write_bytes(b"%PDF")
    with pytest.raises(DiscoveryError):
        discover(tmp_path, "update", current_version=__version__)


def test_discover_rebuild_builds_index(tmp_path: Path):
    (tmp_path / "x.pdf").write_bytes(b"%PDF")
    got = discover(tmp_path, "all", rebuild=True, current_version=__version__)
    assert [e.pdf.stem for e in got] == ["x"]
    assert (tmp_path / ".pdf4llm_locate.idx").exists()


def test_discover_unknown_mode(tree: Path):
    with pytest.raises(DiscoveryError):
        discover(tree, "nope", current_version=__version__)


def test_evaluate_pdf_matches_discover(tree: Path):
    # the per-file filter used for explicit inputs shares discovery criteria
    from pdf4llm.locate_index import evaluate_pdf, skip_reason
    fresh, stale = tree / "fresh.pdf", tree / "stale.pdf"
    # all: current previously converted files qualify only via reprocess
    assert evaluate_pdf(fresh, "all", __version__, "m1", llm_enabled=True) is None
    assert evaluate_pdf(
        fresh, "all", __version__, "m1", llm_enabled=True,
        reprocess=True) is not None
    assert "--locate-reprocess" in skip_reason(fresh, "all", has_meta=True)
    assert evaluate_pdf(fresh, "update", __version__, "m1", llm_enabled=True) is None
    assert skip_reason(fresh, "update", has_meta=True) == "already current"
    assert evaluate_pdf(stale, "update", __version__, "m1", llm_enabled=True) is not None
    bare = tree / "bare.pdf"
    assert evaluate_pdf(bare, "convert", __version__, "m1", llm_enabled=True) is None
    assert "new file" in skip_reason(bare, "convert", has_meta=False)


def test_discover_trusts_index_for_existence(tree: Path):
    # vanished PDF is still evaluated from the index (no stat walk);
    # dropping it is the caller's (CLI) job via _filter_existing
    (tree / "stale.pdf").unlink()
    got = [e.pdf.stem for e in discover(
        tree, "update", current_version=__version__, current_model="m1")]
    assert got == ["stale"]


def test_discover_progress_callback(tree: Path):
    seen: list[tuple[int, int]] = []
    discover(tree, "update", current_version=__version__,
             current_model="m1", reprocess=True,
             progress=lambda d, t: seen.append((d, t)))
    assert seen and seen[-1] == (len(seen), len(seen))


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
    res = runner.invoke(cli_mod.app, ["--locate-mode", "update"])
    assert res.exit_code == 2
    assert "--locate-mode" in res.output


def test_cli_locate_mode_with_inputs_filters(fake_llm, tree: Path, fake_process):
    # explicit inputs + --locate-mode: only the qualifying files are passed on
    res = runner.invoke(cli_mod.app, [
        "stale.pdf", "fresh.pdf", "plain.pdf",
        "--locate", str(tree), "--locate-mode", "update", "--force", "--no-llm"])
    assert res.exit_code == 0, res.output
    assert [p.stem for p in fake_process] == ["stale"]
    assert "1/3 passed file(s) need update" in res.output
    assert "fresh.pdf: skipped (already current)" in res.output
    assert "plain.pdf: skipped (meta.json missing" in res.output


def test_cli_locate_mode_with_inputs_without_locate(fake_llm, tree: Path,
                                                     fake_process):
    # plain paths work too: the staleness check only needs the .meta.json
    res = runner.invoke(cli_mod.app, [
        str(tree / "stale.pdf"), str(tree / "fresh.pdf"),
        "--locate-mode", "update", "--force", "--no-llm"])
    assert res.exit_code == 0, res.output
    assert [p.stem for p in fake_process] == ["stale"]


def test_cli_locate_mode_with_inputs_none_selected(fake_llm, tree: Path,
                                                    fake_process):
    # all current -> short note, exit 0, nothing processed
    res = runner.invoke(cli_mod.app, [
        "fresh.pdf", "--locate", str(tree), "--locate-mode", "update",
        "--force", "--no-llm"])
    assert res.exit_code == 0, res.output
    assert "0/1 passed file(s) need update" in res.output
    assert fake_process == []


def test_cli_locate_mode_with_inputs_other_modes(fake_llm, tree: Path,
                                                  fake_process):
    res = runner.invoke(cli_mod.app, [
        "stale.pdf", "fresh.pdf", "plain.pdf", "bare.pdf",
        "--locate", str(tree), "--locate-mode", "update", "--force",
        "--no-llm", "--locate-reprocess"])
    assert res.exit_code == 0, res.output
    assert sorted(p.stem for p in fake_process) == ["fresh", "stale"]
    # convert = update (meta.json present) + sibling files
    fake_process.clear()
    res = runner.invoke(cli_mod.app, [
        "stale.pdf", "fresh.pdf", "plain.pdf", "bare.pdf",
        "--locate", str(tree), "--locate-mode", "convert", "--force",
        "--no-llm"])
    assert res.exit_code == 0, res.output
    assert sorted(p.stem for p in fake_process) == ["plain", "stale"]


def test_cli_locate_mode_with_inputs_dry_run(fake_llm, tree: Path):
    # filter + --dry-run: notes printed, standard per-file dry-run details,
    # nothing written (real _process_one, no fake)
    res = runner.invoke(cli_mod.app, [
        "stale.pdf", "fresh.pdf",
        "--locate", str(tree), "--locate-mode", "update", "--dry-run",
        "--no-llm"])
    assert res.exit_code == 0, res.output
    assert "1/2 passed file(s) need update" in res.output
    assert "fresh.pdf: skipped (already current)" in res.output
    assert "would write:" in res.output
    assert "dry-run: nothing written" in res.output
    assert not (tree / "stale.md").exists()


def test_cli_locate_mode_with_inputs_llm_without_config_errors(
        tree: Path, monkeypatch):
    monkeypatch.setattr(cli_mod.cfg, "load_config", lambda: {})
    res = runner.invoke(cli_mod.app, [
        "stale.pdf", "--locate", str(tree), "--locate-mode", "update"])
    assert res.exit_code == 3
    assert "--llm-auth" in res.output


def test_cli_locate_without_mode_defaults_to_update(fake_llm, tree: Path,
                                                    fake_process):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--force", "--no-llm"])
    assert res.exit_code == 0, res.output
    assert "defaulting to 'update'" in res.output
    assert [p.stem for p in fake_process] == ["stale"]


def test_cli_discovery_missing_selected_files_warned(fake_llm, tree: Path,
                                                     fake_process):
    (tree / "stale.pdf").unlink()  # index still lists it
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update", "--force",
        "--no-llm"])
    assert res.exit_code == 0, res.output
    assert "no longer exist" in res.output
    assert fake_process == []  # vanished file dropped, not passed on


def test_cli_discovery_compact_list(fake_llm, tree: Path):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update", "--dry-run",
        "--locate-reprocess"])
    assert res.exit_code == 0, res.output
    # root printed once, relative paths, action column, per-line reason (mixed)
    assert f"--locate-mode update under {tree.resolve()}" in res.output
    assert "fresh.pdf  — --locate-reprocess (already current)" in res.output
    # list line + per-file dry-run 'source:' line
    assert res.output.count("fresh.pdf") == 2


def test_cli_discovery_shared_reason_grouped(fake_llm, tree: Path):
    # update mode on a version-homogeneous tree: one shared reason, one line
    for p in tree.glob("*.meta.json"):
        p.unlink()
    (tree / "fresh.meta.json").write_text(
        json.dumps({"pdf4llm_version": "0.5.0", "llm_model": "m1"}),
        encoding="utf-8")
    (tree / "stale.meta.json").write_text(
        json.dumps({"pdf4llm_version": "0.5.0", "llm_model": "m1"}),
        encoding="utf-8")
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update", "--dry-run",
        "--no-llm"])
    assert res.exit_code == 0, res.output
    assert "reason (all 2):" in res.output
    assert res.output.count("converted with pdf4llm 0.5.0") == 1


def test_cli_locate_mode_unknown_errors(fake_llm, tree: Path):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "nope"])
    assert res.exit_code == 2
    assert "nope" in res.output


def test_cli_discovery_without_index_errors(fake_llm, tmp_path: Path):
    (tmp_path / "x.pdf").write_bytes(b"%PDF")
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tmp_path), "--locate-mode", "update"])
    assert res.exit_code == 2
    assert "--locate-rebuild" in res.output


def test_cli_discovery_dry_run_lists_without_prompt(fake_llm, tree: Path):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update", "--dry-run",
        "--no-llm", "--locate-reprocess"])
    assert res.exit_code == 0
    assert "2 file(s)" in res.output
    # unified with explicit-input dry-run: per-file would-write details
    assert "would write:" in res.output
    assert "dry-run: nothing written" in res.output


def test_cli_discovery_dry_run_shows_copy_plan(fake_llm, tree: Path):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update", "--dry-run",
        "--no-llm", "--copy", str(tree / "copies")])
    assert res.exit_code == 0, res.output
    assert "would copy to:" in res.output
    assert "--copy with --locate-mode" in res.output  # collision warning


def test_cli_discovery_declined_aborts(fake_llm, tree: Path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update"])
    assert res.exit_code == 1
    assert "declined" in res.output


def test_cli_discovery_force_processes_list(fake_llm, tree: Path, fake_process):
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update", "--force",
        "--no-llm", "--locate-reprocess"])
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
        ["mdonly", "plain", "stale"]


def test_cli_discovery_approval_accepts(fake_llm, tree: Path, fake_process,
                                        monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    # all without --locate-reprocess skips the current file (fresh)
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "all", "--no-llm"])
    assert res.exit_code == 0, res.output
    assert len(fake_process) == 4
    # ... with it, every file is reconverted
    fake_process.clear()
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "all", "--no-llm",
        "--locate-reprocess"])
    assert res.exit_code == 0, res.output
    assert len(fake_process) == 5


def test_cli_locate_reprocess_with_inputs(fake_llm, tree: Path, fake_process):
    # --locate-reprocess with explicit inputs: previously current files
    # are no longer skipped
    res = runner.invoke(cli_mod.app, [
        "stale.pdf", "fresh.pdf",
        "--locate", str(tree), "--locate-mode", "update", "--force",
        "--no-llm", "--locate-reprocess"])
    assert res.exit_code == 0, res.output
    assert sorted(p.stem for p in fake_process) == ["fresh", "stale"]


def test_cli_discovery_reprocess(fake_llm, tree: Path, fake_process):
    # --locate-reprocess in discovery mode: both converted files selected
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update", "--force",
        "--no-llm", "--locate-reprocess"])
    assert res.exit_code == 0, res.output
    assert sorted(p.stem for p in fake_process) == ["fresh", "stale"]


def test_cli_discovery_llm_without_config_errors(tree: Path, monkeypatch):
    monkeypatch.setattr(cli_mod.cfg, "load_config", lambda: {})
    res = runner.invoke(cli_mod.app, [
        "--locate", str(tree), "--locate-mode", "update", "--force"])
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
