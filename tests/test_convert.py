import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# Always-present fixture (committed to the repo).
SEVEN4 = EXAMPLES / "74HC_HCT74.pdf"
# Optional, larger fixtures (not committed).
OV2640 = EXAMPLES / "OV2640_DS(1.6).pdf"
CH32V208 = EXAMPLES / "CH32V208DS0 2.7 2026-06-01.PDF"


@pytest.fixture(scope="module")
def seven4_md(tmp_path_factory):
    from pdf4llm import convert

    out = tmp_path_factory.mktemp("seven4")
    md, meta = convert.convert(SEVEN4, out)
    return md, meta


def test_convert_writes_utf8_md(seven4_md):
    md, _ = seven4_md
    raw = md.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")  # no BOM
    raw.decode("utf-8")  # valid UTF-8


def test_convert_has_headings(seven4_md):
    _, meta = seven4_md
    assert meta["checks"]["headings"] > 0


def test_meta_written(seven4_md):
    md, meta = seven4_md
    meta_path = md.with_suffix(".meta.json")
    assert meta_path.exists()
    assert meta["page_count"] >= 1
    assert len(meta["source_sha256"]) == 64


@pytest.mark.skipif(not OV2640.exists(), reason="fixture missing")
def test_ov2640_tables(tmp_path):
    from pdf4llm import convert

    _, meta = convert.convert(OV2640, tmp_path)
    ch = meta["checks"]
    assert ch["headings"] > 0
    assert ch["table_rows"] > 0
    assert ch["hex_tokens"] > 0


@pytest.mark.skipif(not CH32V208.exists(), reason="fixture missing")
def test_ch32_tables(tmp_path):
    from pdf4llm import convert

    _, meta = convert.convert(CH32V208, tmp_path)
    assert meta["checks"]["table_rows"] > 0


def test_find_duplicates_exact_basename(tmp_path):
    from pdf4llm import prune

    pdf = tmp_path / "demo.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    (tmp_path / "demo.docx").write_bytes(b"x")
    (tmp_path / "demo.txt").write_bytes(b"x")
    (tmp_path / "demo.md").write_bytes(b"# demo")
    (tmp_path / "other.md").write_bytes(b"# other")  # no match

    found = {p.name for p in prune.find_duplicates(pdf)}
    assert found == {"demo.docx", "demo.txt", "demo.md"}


def test_chunk_markdown_sizes():
    from pdf4llm import llm

    text = "### A\n" + ("word " * 2000) + "\n### B\n" + ("x " * 2000)
    chunks = llm.chunk_markdown(text, max_chars=500)
    assert all(len(c) <= 500 for c in chunks)
    assert len(chunks) > 1


def test_score_penalizes_no_headings():
    from pdf4llm import checks

    bad = checks.run_checks("just text", [100, 100])
    good = checks.run_checks("# H\n| a | b |\n0x1234", [100, 100])
    assert bad["score"] < good["score"]
