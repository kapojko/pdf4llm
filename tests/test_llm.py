"""Offline tests for the LLM correction pass: chunking, verifier, classifiers.

No network access needed — only the pure functions are exercised.
"""
import importlib

import pytest

llm = importlib.import_module("pdf4llm.llm")


# ---------------------------------------------------------------------------
# chunk_markdown: exact reconstruction
# ---------------------------------------------------------------------------

SAMPLE = """## 1. General description

The 74HC74 is a dual D-type flip-flop with V CC supply.

| V CC | 14 | supply voltage |
| 2RD | 13 | asynchronous reset-direct input |
| 2SD | 10 | asynchronous set-direct input |

Some closing prose here.

## 2. Next section

More prose."""


def test_chunk_reconstruction_exact():
    for max_chars in (20, 50, 120, 400, 10_000):
        chunks = llm.chunk_markdown(SAMPLE, max_chars=max_chars)
        assert "".join(c + s for c, s in chunks) == SAMPLE, f"max_chars={max_chars}"


def test_chunk_never_mixes_table_with_prose():
    chunks = llm.chunk_markdown(SAMPLE, max_chars=120)
    for chunk, _ in chunks:
        lines = [l for l in chunk.split("\n") if l.strip()]
        has_table = any(l.lstrip().startswith("|") for l in lines)
        has_prose = any(not l.lstrip().startswith("|") for l in lines)
        assert not (has_table and has_prose), chunk


def test_chunk_size_bounds():
    chunks = llm.chunk_markdown(SAMPLE, max_chars=50)
    for chunk, _ in chunks:
        # a single line may exceed the bound; multi-line chunks may not
        assert chunk.count("\n") == 0 or len(chunk) <= 60


# ---------------------------------------------------------------------------
# verifier
# ---------------------------------------------------------------------------

def test_verifier_accepts_good_edits():
    orig = "Dual D-t yp e fli p -flo p with V CC .\nand SOT108 - 1 pkg"
    out = "Dual D-type flip-flop with VCC.\nand SOT108-1 pkg"
    assert llm._verify_chunk(orig, out) is None


def test_verifier_accepts_false_newline_join():
    orig = "some text that was\nsplit across lines"
    out = "some text that was split across lines"
    assert llm._verify_chunk(orig, out) is None


def test_verifier_rejects_content_change():
    orig = "supply voltage range from 2.0 to 6.0 V"
    out = "supply voltage range from 2.0 to 6.6 V"
    reason = llm._verify_chunk(orig, out)
    assert reason and "invariant A" in reason


def test_verifier_rejects_digit_digit_join():
    orig = "values 2 0 mA and more"
    out = "values 20 mA and more"
    reason = llm._verify_chunk(orig, out)
    assert reason and "unsafe whitespace join" in reason


def test_verifier_rejects_hex_split_join():
    orig = "register 0x30 08 controls"
    out = "register 0x3008 controls"
    reason = llm._verify_chunk(orig, out)
    assert reason and "unsafe whitespace join" in reason


def test_verifier_rejects_value_symbol_join():
    orig = "V CC + 0.5 V margin"
    out = "VCC+ 0.5 V margin"
    reason = llm._verify_chunk(orig, out)
    assert reason and "unsafe whitespace join" in reason


def test_verifier_rejects_translation():
    orig = "The supply voltage range is wide."
    out = "Диапазон напряжения питания широкий."
    reason = llm._verify_chunk(orig, out)
    assert reason and "invariant A" in reason


def test_verifier_rejects_table_cell_count_change():
    orig = "| V CC | 14 | supply voltage |"
    out = "| VCC | 14 supply voltage |"
    # removing the '|' is a non-whitespace change -> invariant A rejects first;
    # the cell-count check stays as defense in depth.
    assert llm._verify_chunk(orig, out) is not None


def test_verifier_accepts_cell_whitespace_fix():
    orig = "| V CC | 14 | supply voltage |"
    out = "| VCC | 14 | supply voltage |"
    assert llm._verify_chunk(orig, out) is None


def test_verifier_accepts_code_fence_wrapped_output():
    orig = "Dual D-t yp e flip-flop"
    out = "```markdown\nDual D-type flip-flop\n```"
    assert llm._verify_chunk(orig, out) is None


def test_verifier_rejects_empty_output():
    assert llm._verify_chunk("some text", "") is not None


# ---------------------------------------------------------------------------
# adversarial verifier cases (safety gate coverage)
# ---------------------------------------------------------------------------

def test_verifier_rejects_number_reorder():
    # swapped values pass no matter how you look at it -> invariant A
    orig = "supply voltage from 2.0 to 6.0 V"
    out = "supply voltage from 6.0 to 2.0 V"
    assert llm._verify_chunk(orig, out) is not None


def test_verifier_rejects_unicode_lookalike_dash():
    orig = "Rev. 9 \u2014 2 April 2024"
    out = "Rev. 9 - 2 April 2024"
    assert llm._verify_chunk(orig, out) is not None


def test_verifier_rejects_degree_sign_removal():
    orig = "specified from -40 \u00b0C to +125 \u00b0C"
    out = "specified from -40C to +125C"
    assert llm._verify_chunk(orig, out) is not None


def test_verifier_rejects_celsius_space_join():
    # '25 \u00b0C' -> '25\u00b0C': joining a digit to a value symbol is not whitelisted
    orig = "ambient temperature 25 \u00b0C typical"
    out = "ambient temperature 25\u00b0C typical"
    reason = llm._verify_chunk(orig, out)
    assert reason and "unsafe whitespace join" in reason


def test_verifier_rejects_digit_join_across_newline():
    # false line break between a number and the next word must never be joined
    orig = "register value\n0x1F00\nnext"
    out = "register value\n0x1F00next"
    reason = llm._verify_chunk(orig, out)
    assert reason and "unsafe whitespace join" in reason
    orig2 = "write 2\n0 mA to the register"
    out2 = "write 20 mA to the register"
    reason2 = llm._verify_chunk(orig2, out2)
    assert reason2 and "unsafe whitespace join" in reason2


def test_verifier_rejects_model_preamble():
    orig = "Dual D-t yp e flip-flop"
    out = "Here is the corrected text:\n\nDual D-type flip-flop"
    assert llm._verify_chunk(orig, out) is not None


def test_verifier_rejects_lowercase_heading_fix():
    orig = "## 2.  Features and benefits"
    out = "## 2. Features and Benefits"
    assert llm._verify_chunk(orig, out) is not None


def test_verifier_rejects_cell_value_corruption():
    orig = "| V CC | 14 | -0.5 | +7 |"
    out = "| VCC | 14 | -0.5 | +0.7 |"
    assert llm._verify_chunk(orig, out) is not None


def test_verifier_accepts_nbsp_collapse():
    orig = "supply\u00a0\u00a0voltage range"
    out = "supply voltage range"
    assert llm._verify_chunk(orig, out) is None


def test_verifier_accepts_heading_space_collapse():
    orig = "## 3.  Ordering information"
    out = "## 3. Ordering information"
    assert llm._verify_chunk(orig, out) is None


def test_verifier_accepts_paragraph_line_joins():
    orig = "first half of a sentence\nthat was falsely split\ninto three lines"
    out = "first half of a sentence that was falsely split into three lines"
    assert llm._verify_chunk(orig, out) is None


def test_verifier_accepts_trailing_newline_diff():
    assert llm._verify_chunk("some text", "some text\n") is None


def test_verifier_rejects_subscript_join_in_prose_digit_context():
    # 'I 2C' -> 'I2C' would be nice, but '2 C' -> '2C' corruption is
    # indistinguishable from it at the character level -> both blocked.
    orig = "bus I 2C clock 2 CPHA"
    out = "bus I2C clock 2CPHA"
    reason = llm._verify_chunk(orig, out)
    assert reason and "unsafe whitespace join" in reason


# ---------------------------------------------------------------------------
# bullet dedup + heuristic classification
# ---------------------------------------------------------------------------

def test_dedupe_bullets():
    src = """- Wide supply voltage range from 2.0 to 6.0 V •

- • CMOS low power dissipation

- normal item"""
    out = llm.dedupe_bullets(src)
    assert "- Wide supply voltage range from 2.0 to 6.0 V" in out
    assert "- CMOS low power dissipation" in out
    assert "- normal item" in out
    assert "•" not in out


def test_classify_heuristic_technical():
    text = (
        "74HC74 Product data sheet Rev. 9\n"
        "Pin description, register 0x12, package SOT108-1, "
        "revision history, V CC supply, typ min max electrical characteristics."
    )
    is_tech, score = llm.classify_heuristic(text)
    assert is_tech and score >= llm.TECH_SCORE_THRESHOLD


def test_classify_heuristic_general():
    text = "Once upon a time in a quiet village, a baker made wonderful bread."
    is_tech, _ = llm.classify_heuristic(text)
    assert not is_tech


# ---------------------------------------------------------------------------
# block-level salvage
# ---------------------------------------------------------------------------

def test_salvage_keeps_good_lines_drops_bad():
    orig = (
        "Dual D-t yp e fli p -flo p trigger\n"
        "excess of V CC .\n"
        "*Table 1. Orderin g info*"
    )
    # candidate: title line hallucinated ('ed.' invented), rest fixed cleanly
    cand = (
        "Dual D-type flip-flop edge-triggered.\n"
        "excess of VCC.\n"
        "*Table 1. Ordering info*"
    )
    salvaged, fixed, total, _reasons = llm._salvage(orig, cand)
    assert "excess of VCC." in salvaged          # good fix kept
    assert "Ordering info" in salvaged           # good fix kept
    assert "D-t yp e" in salvaged                # hallucinated line reverted
    assert "edge-triggered." not in salvaged
    assert fixed == 2 and total == 3


def test_salvage_is_always_safe():
    # no matter what the candidate is, every surviving line must pass verify
    orig = "values 2 0 mA here\nand V CC supply"
    cand = "values 20 mA here\nand VCC supply"
    salvaged, fixed, total, _ = llm._salvage(orig, cand)
    assert fixed == 1 and total == 2     # digit-digit reverted, VCC kept
    assert "2 0 mA" in salvaged
    assert "VCC supply" in salvaged
    assert salvaged == "values 2 0 mA here\nand VCC supply"


def test_salvage_handles_line_join_blocks():
    orig = "text that was\nfalsely split\nend"
    cand = "text that was falsely split\nend"
    salvaged, fixed, _total, _ = llm._salvage(orig, cand)
    assert fixed == 1
    assert salvaged == "text that was falsely split\nend"


def test_salvage_rejects_inserted_content_block():
    orig = "alpha beta"
    cand = "alpha beta gamma delta"
    salvaged, fixed, _total, _ = llm._salvage(orig, cand)
    assert fixed == 0
    assert salvaged == orig


def test_salvage_empty_candidate_keeps_original():
    orig = "line one\nline two"
    salvaged, fixed, _total, _ = llm._salvage(orig, "")
    assert salvaged == orig and fixed == 0


# ---------------------------------------------------------------------------
# sampling config plumbing
# ---------------------------------------------------------------------------

def test_split_sampling_standard_vs_extra():
    std, extra = llm._split_sampling(llm.DEFAULT_SAMPLING)
    assert std["temperature"] == 0.6
    assert "top_k" in extra and "min_p" in extra
    assert "top_k" not in std


# ---------------------------------------------------------------------------
# deterministic subscript normalisation
# ---------------------------------------------------------------------------

def test_fix_subscripts_joins_established_terms():
    text = "in excess of V CC . | V IH | V IL | t PLH |"
    out, n = llm.fix_subscripts(text)
    assert "VCC" in out and "VIH" in out and "VIL" in out and "tPLH" in out
    assert n == 4


def test_fix_subscripts_underscore_for_mixed_suffixes():
    text = "T amb  = -40 ; P tot ; t pd ; C L ; R L ; Q n+1"
    out, n = llm.fix_subscripts(text)
    assert "T_amb" in out and "P_tot" in out and "t_pd" in out
    assert "C_L" in out and "R_L" in out and "Q_n+1" in out
    assert n == 6


def test_fix_subscripts_current_symbol_uses_underscore():
    # I+IK joined would read 'IIK' — unreadable, so underscore form
    out, n = llm.fix_subscripts("| I IK | input clamping current | I O |")
    assert "I_IK" in out and "I_O" in out and n == 2


def test_fix_subscripts_never_rewrites_prose():
    text = "as I do here; a few words; I am; the use of it; V to 5 V"
    out, _n = llm.fix_subscripts(text)
    assert out == text


def test_fix_subscripts_digit_prefixed_pair():
    out, n = llm.fix_subscripts("exceeds 0.5V CC margin")
    assert "0.5VCC" in out and n == 1


def test_fix_subscripts_never_touches_split_words():
    # 'D-t yp e' is a hyphenated word fragment, not a 't yp' subscript
    out, n = llm.fix_subscripts("Dual D-t yp e fli p -flo p")
    assert "t_yp" not in out
    assert out == "Dual D-t yp e fli p -flo p" and n == 0


def test_fix_subscripts_part_numbers_untouched():
    text = "74HC74D 74HCT74D SOT108 - 1 2 mm x 2 mm"
    out, _n = llm.fix_subscripts(text)
    assert out == text


def test_strip_horizontal_rules():
    src = "A\n\n---\n\nB\n***\nC\n ___ \nD\n| --- | \nE"
    out, n = llm.strip_horizontal_rules(src)
    assert n == 3
    hr_lines = [l for l in out.split("\n") if llm._is_hr_line(l)]
    assert hr_lines == []           # standalone rules gone
    assert "| --- |" in out         # table delimiter row must survive
    assert out == "A\nB\nC\nD\n| --- | \nE"


# ---------------------------------------------------------------------------
# similarity-based salvage (survives model deleting lines like '---')
# ---------------------------------------------------------------------------

def test_salvage_survives_deleted_horizontal_rule():
    orig = "---\n\n| V CC | 14 | supply voltage |\n| 2RD | 13 | reset |\n\n---"
    # model deleted the FIRST '---' but fixed cells
    cand = "\n| VCC | 14 | supply voltage |\n| 2RD | 13 | reset |\n\n---"
    salvaged, fixed, _total, _r = llm._salvage(orig, cand)
    assert "---" in salvaged                     # rule preserved from orig
    assert "| VCC | 14 | supply voltage |" in salvaged  # good row fix applied
    assert "| 2RD | 13 | reset |" in salvaged
    assert fixed >= 1  # one row genuinely changed (the other was identical)


def test_salvage_line_join_still_works():
    orig = "text that was\nfalsely split\nend"
    cand = "text that was falsely split\nend"
    salvaged, fixed, _total, _ = llm._salvage(orig, cand)
    assert fixed == 1
    assert salvaged == "text that was falsely split\nend"
