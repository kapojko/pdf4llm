"""Experiment v5: bounded-window subscript veto (final candidate rule).

Veto a subscript insertion (prefix+single/lowercase suffix -> 'X_y') when
some contiguous token span that INCLUDES the pair (pair +/- up to 2 tokens,
single-space separated) joins (lowercased) to a token that occurs in the
document written all-lowercase, or (fallback v4) to a common English word.

Rationale: genuine subscripts join to acronyms/symbols written uppercase
('V DD'->'VDD', 't MCK'->'tMCK'); ligature debris joins to English words
('f l a g'->'flag', 't yp e'->'type') that occur in the doc as lowercase
prose.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import llm_prepass as lp
from pdf4llm.llm_batch import _VOCAB_TOKEN_RE

DOCS = {
    "SAM9X60": Path(r"S:/Электроника/Microchip/SAM9X60/SAM9X60-Data-Sheet-DS60001579.md"),
    "rm0410": Path(r"D:/Source/pdf4llm/examples/rm0410-stm32f76xxx-and-stm32f77xxx-advanced-armbased-32bit-mcus-stmicroelectronics.md"),
    "CH32V208DS0": Path(r"D:/Source/pdf4llm/out/CH32V208DS0 2.7 2026-06-01.md"),
    "CH32FV2x_V3xRM": Path(r"S:/Электроника/WCH/CH32V208/CH32FV2x_V3xRM 2.5 2026-03-23.md"),
    "OV2640": Path(r"S:/Электроника/Дисплеи и камеры/OV2640 2 MPixel/OV2640_DS(1.6).md"),
}

_MISFIRE_SHAPE = re.compile(r"\b[A-Za-z]_[a-z]{1,2} [A-Za-z]")
TOK = re.compile(r"[A-Za-z][A-Za-z0-9]*")

COMMON_EN = {
    "type", "types", "flag", "flags", "effect", "effects", "field", "fields",
    "offset", "offsets", "register", "registers", "test", "tests", "valid",
    "read", "reset", "pull", "power", "multi", "null", "ready", "chip",
    "last", "round", "frame", "table", "input", "inputs", "output",
    "typical", "current", "voltage", "high", "low", "level", "point",
    "mode", "modes", "state", "error", "errors", "event", "events",
}


def prepass(text: str) -> str:
    text = lp.dedupe_bullets(text)
    text, _ = lp.strip_horizontal_rules(text)
    text, _ = lp.fix_dash_bullets(text)
    text, _ = lp.collapse_dot_leaders(text)
    text, _ = lp.fix_br_word_splits(text)
    return text


def fix_v5(text: str, use_common: bool) -> tuple[str, int, list[str]]:
    lower_tokens = {t for t in _VOCAB_TOKEN_RE.findall(text) if t.islower()}
    count = 0
    vetoed: list[str] = []
    tokens = TOK.findall(text)
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
        if not suffix.islower():
            count += 1
            return form
        k = tok_index.get(m.start(1))
        if k is None:
            count += 1
            return form
        # bounded window: pair (k, k+1) +/- up to 2 tokens, single-space gaps
        hit = None
        for a in range(max(0, k - 2), k + 1):
            for b in range(k + 1, min(len(tokens), k + 3)):
                span = "".join(tokens[a:b + 1]).lower()
                if span in lower_tokens or (use_common and span in COMMON_EN):
                    hit = (a, b, span)
                    break
            if hit:
                break
        if hit:
            a, b, span = hit
            vetoed.append(f"{form} <- {' '.join(tokens[a:b+1])} (join '{span}')")
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
        base_hard = len(_MISFIRE_SHAPE.findall(base))
        print(f"\n=== {name} (base insertions {n_base}, base hard {base_hard}) ===")
        for label, use_common in (("v5", False), ("v5+EN", True)):
            out, n, vetoed = fix_v5(t0, use_common)
            hard = len(_MISFIRE_SHAPE.findall(out))
            print(f"  {label}: insertions={n} vetoed={len(vetoed)} hard={hard}")
            for s in list(dict.fromkeys(vetoed))[:12]:
                print(f"      {s}")
            if hard:
                toks = Counter(_MISFIRE_SHAPE.findall(out)).most_common(8)
                print(f"      surviving: {toks}")
                for m in list(_MISFIRE_SHAPE.finditer(out))[:3]:
                    print(f"      …{out[max(0,m.start()-55):m.end()+55].replace(chr(10),' ')}…")


if __name__ == "__main__":
    main()
