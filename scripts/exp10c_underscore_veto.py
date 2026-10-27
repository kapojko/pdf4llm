"""Experiment v3/v4: refined subscript veto.

v2 (pair-join lowercase evidence) left multi-token debris survivors
('t yp e' -> 't_yp e', pair join 'typ' is not a doc token).

v3: veto if ANY contiguous sub-join of the whitespace-linked group that
includes the matched pair occurs as an all-lowercase token in the doc.

v4: v3 + fallback — the sub-join (case-insensitive) is in a small baked-in
list of common English words (catches 'Type' in docs where 'type' never
occurs lowercase, e.g. CH32FV2x headings).

Metrics: insertions, vetoes, hard 'X_y z' shapes in post text, samples.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import llm_prepass as lp
from pdf4llm.llm_batch import _VOCAB_TOKEN_RE, _gap_suspicious

DOCS = {
    "SAM9X60": Path(r"S:/Электроника/Microchip/SAM9X60/SAM9X60-Data-Sheet-DS60001579.md"),
    "rm0410": Path(r"D:/Source/pdf4llm/examples/rm0410-stm32f76xxx-and-stm32f77xxx-advanced-armbased-32bit-mcus-stmicroelectronics.md"),
    "CH32V208DS0": Path(r"D:/Source/pdf4llm/out/CH32V208DS0 2.7 2026-06-01.md"),
    "CH32FV2x_V3xRM": Path(r"S:/Электроника/WCH/CH32V208/CH32FV2x_V3xRM 2.5 2026-03-23.md"),
    "OV2640": Path(r"S:/Электроника/Дисплеи и камеры/OV2640 2 MPixel/OV2640_DS(1.6).md"),
}

_MISFIRE_SHAPE = re.compile(r"\b[A-Za-z]_[a-z]{1,2} [A-Za-z]")
WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")

# v4 fallback: common English words observed in misfire joins (subset; the
# case-sensitive document evidence covers the rest)
COMMON_EN = {
    "type", "types", "flag", "flags", "effect", "effects", "field", "fields",
    "offset", "offsets", "register", "registers", "test", "tests", "valid",
    "read", "reset", "pull", "power", "multi", "null", "ready", "chip",
    "last", "round", "frame", "table", "input", "inputs", "output",
    " Typical", "typical", "current", "voltage", "high", "low", "level",
    "point", "mode", "modes", "state", "error", "errors", "event", "events",
}


def prepass(text: str) -> str:
    text = lp.dedupe_bullets(text)
    text, _ = lp.strip_horizontal_rules(text)
    text, _ = lp.fix_dash_bullets(text)
    text, _ = lp.collapse_dot_leaders(text)
    text, _ = lp.fix_br_word_splits(text)
    return text


def sub_joins(tokens: list[str], lo: int, hi: int) -> list[str]:
    """All contiguous joins of tokens[lo:hi+1] that include the pair
    (the pair is the LAST two tokens of the window here)."""
    out = []
    for i in range(lo, hi):
        out.append("".join(tokens[i:hi + 1]).lower())
    return out


def group_bounds(tokens: list[str], k: int) -> tuple[int, int]:
    i = k
    while i > 0 and _gap_suspicious(tokens[i - 1], tokens[i]):
        i -= 1
    j = k
    while j < len(tokens) - 1 and _gap_suspicious(tokens[j], tokens[j + 1]):
        j += 1
    return i, j


def fix_v(text: str, use_common: bool) -> tuple[str, int, list[str]]:
    lower_tokens = {t for t in _VOCAB_TOKEN_RE.findall(text) if t.islower()}
    any_tokens = {t.lower() for t in _VOCAB_TOKEN_RE.findall(text)}
    count = 0
    vetoed: list[str] = []
    tokens = WORD.findall(text)
    tok_index: dict[int, int] = {}
    pos = 0
    for k, tok in enumerate(tokens):
        pos = text.find(tok, pos)
        tok_index[pos] = k
        pos += len(tok)

    def repl(m: re.Match) -> str:
        nonlocal count
        prefix, suffix = m.group(1), m.group(2)
        form = lp._sub_form(prefix, suffix)
        if form is None:
            return m.group(0)
        if suffix.islower():
            k = tok_index.get(m.start(1))
            if k is not None:
                i, j = group_bounds(tokens, k)
                # the pair occupies tokens (j-1, j); extend one past the
                # suffix only while the chain continues (debris lookahead)
                j2 = j
                if j2 < len(tokens) - 1 and _gap_suspicious(tokens[j2], tokens[j2 + 1]):
                    j2 += 1
                joins = sub_joins(tokens, i, j2)
                hit = next((x for x in joins if x in lower_tokens), None)
                if hit is None and use_common:
                    hit = next((x for x in joins if x in COMMON_EN), None)
                if hit is not None:
                    vetoed.append(f"{form} <- {' '.join(tokens[i:j2+1])} "
                                  f"(join '{hit}')")
                    return m.group(0)
        count += 1
        return form

    return lp._SUB_PAIR_RE.sub(repl, text), count, vetoed


def main() -> None:
    for name, path in DOCS.items():
        if not path.exists():
            print(f"{name}: MISSING")
            continue
        t0 = prepass(path.read_text(encoding="utf-8"))
        base, n_base = lp.fix_subscripts(t0)
        print(f"\n=== {name} (base insertions {n_base}) ===")
        for label, use_common in (("v3", False), ("v4", True)):
            out, n, vetoed = fix_v(t0, use_common)
            hard = len(_MISFIRE_SHAPE.findall(out))
            print(f"  {label}: insertions={n} vetoed={len(vetoed)} "
                  f"hard_shapes={hard} (base {len(_MISFIRE_SHAPE.findall(base))})")
            for s in list(dict.fromkeys(vetoed))[:10]:
                print(f"      {s}")
            if hard and label == "v4":
                toks = Counter(_MISFIRE_SHAPE.findall(out)).most_common(8)
                print(f"      surviving: {toks}")
                for m in list(_MISFIRE_SHAPE.finditer(out))[:4]:
                    print(f"      …{out[max(0,m.start()-60):m.end()+60].replace(chr(10),' ')}…")


if __name__ == "__main__":
    main()
