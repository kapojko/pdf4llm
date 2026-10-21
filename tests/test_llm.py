"""Offline tests for the LLM correction pass: chunking, verifier, classifiers.

No network access needed — only the pure functions are exercised (the parallel
--llm-workers path and the llama-swappy probe are tested with stubs).
"""
import importlib
import json

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
# parallel chunk processing (--llm-workers > 1)
# ---------------------------------------------------------------------------

PAR_TEXT = (
    "## 1. General description\n"
    "\n"
    "The 74HC74 is a dual D-t yp e fli p -flo p with V CC supply.\n"
    "\n"
    "## 2. Features\n"
    "\n"
    "Wide supply voltage range from 2.0 to 6.0 V.\n"
    "\n"
    "## 3. Ordering information\n"
    "\n"
    "Orderin g code SOT108 - 1.\n"
    "\n"
    "## 4. Applications\n"
    "\n"
    "Logic design and fli p -flo p applications.\n"
    "\n"
    "## 5. Revision history\n"
    "\n"
    "Rev. 9 — 2 April 2024.\n"
)


def _fixed(chunk: str) -> str:
    """A realistic 'model' answer: safe whitespace-only fixes."""
    return (chunk
            .replace("D-t yp e", "D-type")
            .replace("fli p -flo p", "flip-flop")
            .replace("V CC", "VCC")
            .replace("Orderin g", "Ordering")
            .replace("SOT108 - 1", "SOT108-1"))


def _prep(text: str) -> str:
    """Mirror correct_with_llm's deterministic pre-passes (classify=False path)."""
    text, _ = llm.strip_horizontal_rules(llm.dedupe_bullets(text))
    text, _ = llm.fix_subscripts(text)
    return text


# small max_chars so PAR_TEXT splits into several chunks
MAXC = 80


def test_parallel_reassembles_in_order_and_merges_stats(monkeypatch):
    calls: list[str] = []

    def fake_call(system_prompt, chunk, *a, **kw):
        calls.append(chunk)
        return _fixed(chunk), None

    monkeypatch.setattr(llm, "_call_llm", fake_call)

    out, stats = llm.correct_with_llm(
        PAR_TEXT, "m", "http://x", "k", verbose=False,
        classify=False, max_chars=MAXC, workers=3,
    )
    # reassembly is exact and in original order (nothing lost/reordered)
    assert out == _fixed(_prep(PAR_TEXT))
    assert len(calls) == stats["chunks_total"] > 2
    assert stats["chunks_accepted"] == stats["chunks_total"]
    assert stats["chunks_rejected"] == 0 and stats["chunks_salvaged"] == 0
    assert stats["retries_used"] == 0 and stats["rejections"] == []


def test_parallel_output_identical_to_sequential(monkeypatch):
    def fake_call(system_prompt, chunk, model, endpoint, api_key,
                  sampling=None, retry_hint=None):
        # first attempt 'hallucinates' -> exercises salvage; retry hint path
        if retry_hint is None and "Ordering" in chunk:
            return chunk + " extra hallucinated content", None
        return _fixed(chunk), None

    monkeypatch.setattr(llm, "_call_llm", fake_call)
    out1, stats1 = llm.correct_with_llm(
        PAR_TEXT, "m", "http://x", "k", verbose=False,
        classify=False, max_chars=MAXC, retries=2, workers=1)
    out4, stats4 = llm.correct_with_llm(
        PAR_TEXT, "m", "http://x", "k", verbose=False,
        classify=False, max_chars=MAXC, retries=2, workers=4)
    assert out1 == out4 == _fixed(_prep(PAR_TEXT))
    for key in ("chunks_total", "chunks_accepted", "chunks_salvaged",
                "chunks_rejected", "blocks_fixed", "retries_used"):
        assert stats1[key] == stats4[key], key


def test_parallel_completions_out_of_order_still_ordered(monkeypatch):
    import threading
    import time as _time

    order: list[int] = []
    order_lock = threading.Lock()
    # chunk -> 1-based index, mirroring the pipeline's pre-processing so the
    # stub can look up which chunk it got (works whatever the chunking does)
    chunk_idx = {c: i for i, (c, _s) in
                 enumerate(llm.chunk_markdown(_prep(PAR_TEXT), MAXC), 1)}

    def fake_call(system_prompt, chunk, model, endpoint, api_key,
                  sampling=None, retry_hint=None):
        # make LATER chunks finish FIRST so completion order != chunk order
        delay = max(1.0 - 0.15 * chunk_idx[chunk], 0.05)
        _time.sleep(delay)
        with order_lock:
            order.append(chunk_idx[chunk])
        return _fixed(chunk), None

    monkeypatch.setattr(llm, "_call_llm", fake_call)
    out, stats = llm.correct_with_llm(
        PAR_TEXT, "m", "http://x", "k", verbose=False,
        classify=False, max_chars=MAXC, workers=5)
    assert out == _fixed(_prep(PAR_TEXT))   # output still in original order
    assert sorted(order) == list(range(1, stats["chunks_total"] + 1))


def test_parallel_rejections_carry_chunk_indices(monkeypatch):
    def fake_call(system_prompt, chunk, *a, **kw):
        return "totally unrelated hallucinated text", None  # invariant A fails,
        # salvage yields nothing -> rejected, original kept

    monkeypatch.setattr(llm, "_call_llm", fake_call)
    out, stats = llm.correct_with_llm(
        PAR_TEXT, "m", "http://x", "k", verbose=False,
        classify=False, max_chars=MAXC, retries=1, workers=2)
    assert out == _prep(PAR_TEXT)           # every original kept verbatim
    assert stats["chunks_rejected"] == stats["chunks_total"]
    idxs = sorted(r["chunk"] for r in stats["rejections"])
    assert idxs == list(range(1, stats["chunks_total"] + 1))


def test_workers_default_is_one(monkeypatch):
    # workers=None with no swappy info endpoint -> sequential path (exact
    # current behaviour); the probe fails fast offline and is never fatal
    seen = []

    def fake_call(system_prompt, chunk, *a, **kw):
        seen.append(chunk)
        return chunk, None

    monkeypatch.setattr(llm, "_call_llm", fake_call)
    out, stats = llm.correct_with_llm(
        PAR_TEXT, "m", "http://x", "k", verbose=False, classify=False,
        max_chars=MAXC)
    assert stats["chunks_accepted"] == stats["chunks_total"]
    assert out == _prep(PAR_TEXT)
    assert "swappy" not in stats


# ---------------------------------------------------------------------------
# llama-swappy probe: auto workers + context check
# ---------------------------------------------------------------------------

SWAPPY_INFO = {
    "version": "1.3",
    "models": [
        {"key": "m-np1", "contextSize": 147456, "slots": 1},
        {"key": "m-np4", "contextSize": 36864, "slots": 4},
        {"key": "m-np8", "contextSize": 18432, "slots": 8},
    ],
}


def test_probe_swappy_urls_and_failure(monkeypatch):
    hits = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(SWAPPY_INFO).encode()

    def fake_urlopen(req, timeout):
        hits.append(req.full_url)
        if len(hits) == 1:
            raise llm.urllib.error.HTTPError(req.full_url, 404, "nope", {}, None)
        return FakeResp()

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    info = llm.probe_swappy("http://host:12380/v1", "key")
    assert info == SWAPPY_INFO
    # /v1-stripped base tried first, endpoint as given second; fallback works
    assert hits == ["http://host:12380/llama-swappy/info",
                    "http://host:12380/v1/llama-swappy/info"]


def test_probe_swappy_first_url_wins(monkeypatch):
    hits = []

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(SWAPPY_INFO).encode()

    def fake_urlopen(req, timeout):
        hits.append(req.full_url)
        return FakeResp()

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    assert llm.probe_swappy("http://host:12380/v1", "key") == SWAPPY_INFO
    assert hits == ["http://host:12380/llama-swappy/info"]


def test_probe_swappy_never_raises(monkeypatch):
    def boom(req, timeout):
        raise OSError("no network")

    monkeypatch.setattr(llm.urllib.request, "urlopen", boom)
    assert llm.probe_swappy("http://x/v1", "k") is None


def test_resolve_workers_auto_from_slots(monkeypatch):
    monkeypatch.setattr(llm, "probe_swappy", lambda ep, ak: SWAPPY_INFO)
    notes = []
    w, entry = llm.resolve_workers("http://x", "k", "m-np4", 6000, None,
                                   note=notes.append)
    assert w == 4 and entry["key"] == "m-np4"        # min(slots, 8)
    w8, _ = llm.resolve_workers("http://x", "k", "m-np8", 6000, None,
                                note=notes.append)
    assert w8 == 8                                    # capped at 8
    w1, _ = llm.resolve_workers("http://x", "k", "m-np1", 6000, None,
                                note=notes.append)
    assert w1 == 1                                    # np=1 -> sequential
    assert any("workers=4" in n for n in notes)


def test_resolve_workers_explicit_overrides_slots(monkeypatch):
    monkeypatch.setattr(llm, "probe_swappy", lambda ep, ak: SWAPPY_INFO)
    w, _ = llm.resolve_workers("http://x", "k", "m-np4", 6000, 2,
                               note=lambda m: None)
    assert w == 2


def test_resolve_workers_no_info_endpoint(monkeypatch):
    monkeypatch.setattr(llm, "probe_swappy", lambda ep, ak: None)
    assert llm.resolve_workers("http://x", "k", "m", 6000, None)[0] == 1
    assert llm.resolve_workers("http://x", "k", "m", 6000, 3)[0] == 3


def test_resolve_workers_missing_model_degrades(monkeypatch):
    monkeypatch.setattr(llm, "probe_swappy", lambda ep, ak: SWAPPY_INFO)
    notes = []
    w, entry = llm.resolve_workers("http://x", "k", "unknown", 6000, None,
                                   note=notes.append)
    assert w == 1 and entry is None
    assert any("no entry" in n for n in notes)


def test_resolve_workers_context_check(monkeypatch):
    monkeypatch.setattr(llm, "probe_swappy", lambda ep, ak: SWAPPY_INFO)
    # 36864 tok/request is plenty for a 6000-char chunk (~3.9k tokens est.)
    llm.resolve_workers("http://x", "k", "m-np4", 6000, None, note=lambda m: None)
    # but a 200k-char monster chunk does not fit -> abort
    with pytest.raises(llm.LlmContextError, match="context too small"):
        llm.resolve_workers("http://x", "k", "m-np4", 200_000, None,
                            note=lambda m: None)


def test_correct_with_llm_aborts_when_context_too_small(monkeypatch):
    tiny_info = {"version": "1.3",
                 "models": [{"key": "m", "contextSize": 500, "slots": 2}]}
    monkeypatch.setattr(llm, "probe_swappy", lambda ep, ak: tiny_info)

    def must_not_call(*a, **kw):
        raise AssertionError("LLM must not be called when the context check fails")

    monkeypatch.setattr(llm, "_call_llm", must_not_call)
    with pytest.raises(llm.LlmContextError):
        llm.correct_with_llm(PAR_TEXT, "m", "http://x", "k", verbose=False,
                             classify=False, max_chars=MAXC)


def test_correct_with_llm_records_swappy_and_auto_workers(monkeypatch):
    info = {"version": "1.3",
            "models": [{"key": "m", "contextSize": 36864, "slots": 4}]}
    monkeypatch.setattr(llm, "probe_swappy", lambda ep, ak: info)
    monkeypatch.setattr(llm, "_call_llm",
                        lambda system_prompt, chunk, *a, **kw: (_fixed(chunk), None))
    out, stats = llm.correct_with_llm(
        PAR_TEXT, "m", "http://x", "k", verbose=False, classify=False,
        max_chars=MAXC)   # workers=None -> auto: min(4 slots, 4) = 4
    assert out == _fixed(_prep(PAR_TEXT))
    assert stats["swappy"] == {"key": "m", "slots": 4,
                               "context_per_request": 36864, "workers": 4}


def test_estimate_chunk_tokens_sanity():
    # ~3.5 chars/token in, same-size out, plus margin
    assert llm.estimate_chunk_tokens(0) == llm._CTX_MARGIN_TOKENS
    need = llm.estimate_chunk_tokens(6000)
    assert 2 * (6000 / 4) < need < 2 * (6000 / 3) + 512 + 1


# ---------------------------------------------------------------------------
# sampling config plumbing
# ---------------------------------------------------------------------------

def test_split_sampling_standard_vs_extra():
    std, extra = llm._split_sampling(llm.DEFAULT_SAMPLING)
    assert std["temperature"] == 0.6
    assert "top_k" in extra and "min_p" in extra
    assert "top_k" not in std


# ---------------------------------------------------------------------------
# output token cap (loop killer) + thinking strip
# ---------------------------------------------------------------------------

def test_output_token_cap_is_close_to_input_size():
    # a 2000-char chunk is ~570 input tokens; the cap must be tight (not the
    # old 2x-chars = 4000-token budget) but leave margin for fence/hint error
    cap = llm.output_token_cap(2000)
    assert 570 < cap < 900
    assert llm.output_token_cap(0) == llm._OUT_MARGIN_TOKENS + 1


def test_run_chunk_caps_max_tokens(monkeypatch):
    seen = {}

    def fake_call(system_prompt, chunk, *a, **kw):
        seen["kwargs"] = kw
        return chunk, None

    monkeypatch.setattr(llm, "_call_llm", fake_call)
    result, delta = llm._run_chunk(
        1, 1, "some chunk", "", "sys", "m", "http://x", "k", None, 0)
    assert delta["accepted"]
    # no max_tokens argument is passed at all: _call_llm computes the cap
    # itself from the content length
    assert "max_tokens" not in seen["kwargs"]


def test_run_chunk_records_truncation(monkeypatch):
    def fake_call(system_prompt, chunk, *a, **kw):
        # 'looping' model: answer cut off mid-text by the output cap
        return chunk[: len(chunk) // 2], "length"

    monkeypatch.setattr(llm, "_call_llm", fake_call)
    result, delta = llm._run_chunk(
        1, 1, "text alpha beta", "", "sys", "m", "http://x", "k", None, 0)
    assert delta["rejected"] and delta["truncated"] == 1
    assert any("finish_reason=length" in r for r in
               delta["rejection"]["reason"].split("; "))
    assert result == "text alpha beta"        # original kept


def test_strip_thinking_blocks():
    open_tag = "<" + "think>"
    close_tag = "<" + "/" + "think>"
    body = "Dual D-type flip-flop"
    assert llm._strip_thinking(
        f"{open_tag}reasoning here{close_tag}\n{body}") == body
    assert llm._strip_thinking(
        f"  {open_tag}a{close_tag} {open_tag}b{close_tag}\n{body}") == body
    assert llm._strip_thinking(f"{open_tag}never closed") == ""
    assert llm._strip_thinking(body) == body


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
