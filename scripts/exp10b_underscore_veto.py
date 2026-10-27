"""Experiment v2: case-sensitive evidence veto for fix_subscripts.

Hypothesis from exp10: every subscript misfire ('f l a g' -> 'f_l a g')
joins to a word that also occurs in the document written all-lowercase
('flag', 'type', 'effect'), while genuine subscripts join to acronyms/
symbols written uppercase ('V DD' -> 'VDD', 'f MCK' -> 'fMCK').

Veto rule under test: do NOT insert '_' when
  - the suffix is lowercase (the underscore branch), AND
  - the lowercase-joined form (prefix+suffix, or the whole whitespace-
    linked group) occurs >= 1 time in the document as an all-lowercase
    written token.

End metric: count of hard-misfire shapes ('X_y z', e.g. 'f_l a g') in the
post-subscript text WITHOUT vs WITH the veto, plus vetoed samples for
eyeballing false vetoes.
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
WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")


def prepass(text: str) -> str:
    text = lp.dedupe_bullets(text)
    text, _ = lp.strip_horizontal_rules(text)
    text, _ = lp.fix_dash_bullets(text)
    text, _ = lp.collapse_dot_leaders(text)
    text, _ = lp.fix_br_word_splits(text)
    return text


def fix_subscripts_v2(text: str) -> tuple[str, int, list[str]]:
    """fix_subscripts + case-sensitive lowercase-evidence veto."""
    lower_tokens = {t for t in _VOCAB_TOKEN_RE.findall(text)
                    if t.islower()}
    count = 0
    vetoed: list[str] = []

    def repl(m: re.Match) -> str:
        nonlocal count
        prefix, suffix = m.group(1), m.group(2)
        form = lp._sub_form(prefix, suffix)
        if form is None:
            return m.group(0)
        if suffix.islower():
            joined = (prefix + suffix).lower()
            if joined in lower_tokens:
                vetoed.append(f"{form} <- {' '.join(m.group(0).split())} "
                              f"(join '{joined}' occurs lowercase)")
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
        v2, n_v2, vetoed = fix_subscripts_v2(t0)
        hard_base = len(_MISFIRE_SHAPE.findall(base))
        hard_v2 = len(_MISFIRE_SHAPE.findall(v2))
        print(f"\n=== {name} ===")
        print(f"  insertions: base={n_base}  v2={n_v2}  vetoed={len(vetoed)}")
        print(f"  hard 'X_y z' shapes in post text: base={hard_base}  v2={hard_v2}")
        print(f"  vetoed samples:")
        for s in list(dict.fromkeys(vetoed))[:15]:
            print(f"    {s}")
        if hard_v2:
            print(f"  surviving hard shapes:")
            toks = Counter(_MISFIRE_SHAPE.findall(v2)).most_common(10)
            print(f"    {toks}")
            for m in list(_MISFIRE_SHAPE.finditer(v2))[:5]:
                print(f"    …{v2[max(0,m.start()-60):m.end()+60].replace(chr(10),' ')}…")


if __name__ == "__main__":
    main()
