"""Offline survey of the two underscore problem classes (no LLM calls).

For each raw (pre-LLM) markdown document:

1. Reproduce the exact pre-pass order of llm_run (dedupe_bullets,
   strip_horizontal_rules, fix_dash_bullets, collapse_dot_leaders,
   fix_br_word_splits), then simulate fix_subscripts with per-insertion
   context capture.
2. Classify every insertion under two candidate veto rules:
     EVIDENCE  — the underscore-free join of the whitespace-linked group
                 occurs in the doc vocab AND the underscored form occurs
                 NOWHERE in the doc (split-word debris, not a subscript);
     CHAIN     — the _gap_suspicious group around the pair is 3+ tokens
                 (genuine subscripts are 2-token groups; ligature debris
                 like 'f l a g' is a single-letter chain).
   CLEAN = neither veto fires.
3. Count ' _ ' spaced-underscore shapes (both-sided / space-after /
   space-before) that a deterministic join rule would touch, with samples.
4. Cross-check: hard-misfire shape 'X_y z' (single lowercase debris after
   an inserted underscore) in the post-subscript text.

Writes a JSON report to out/exp_underscore/report.json and prints a table.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pdf4llm import llm_prepass as lp
from pdf4llm.llm_batch import _gap_suspicious, _VOCAB_TOKEN_RE

DOCS = {
    "SAM9X60": Path(r"S:/Электроника/Microchip/SAM9X60/SAM9X60-Data-Sheet-DS60001579.md"),
    "rm0410": Path(r"D:/Source/pdf4llm/examples/rm0410-stm32f76xxx-and-stm32f77xxx-advanced-armbased-32bit-mcus-stmicroelectronics.md"),
    "CH32V208DS0": Path(r"D:/Source/pdf4llm/out/CH32V208DS0 2.7 2026-06-01.md"),
    "CH32FV2x_V3xRM": Path(r"S:/Электроника/WCH/CH32V208/CH32FV2x_V3xRM 2.5 2026-03-23.md"),
    "OV2640": Path(r"S:/Электроника/Дисплеи и камеры/OV2640 2 MPixel/OV2640_DS(1.6).md"),
}

# spaced-underscore shapes a deterministic join rule would consider
_BOTH_SIDED = re.compile(r"[A-Za-z0-9] +_ +[A-Za-z0-9]")
_SPACE_AFTER = re.compile(r"[A-Za-z0-9]_(?= +[A-Za-z0-9])")   # 'SDRAMC_ WPSR'
_SPACE_BEFORE = re.compile(r"(?<=[A-Za-z0-9]) +_(?=[A-Za-z0-9])")  # 'SDRAMC _WPSR'
# hard-misfire shape in post-subscript text: 'f_l a g', 't_yp e'
_MISFIRE_SHAPE = re.compile(r"\b[A-Za-z]_[a-z]{1,2} [A-Za-z]")

WORD = re.compile(r"[A-Za-z0-9]+")


def prepass(text: str) -> str:
    text = lp.dedupe_bullets(text)
    text, _ = lp.strip_horizontal_rules(text)
    text, _ = lp.fix_dash_bullets(text)
    text, _ = lp.collapse_dot_leaders(text)
    text, _ = lp.fix_br_word_splits(text)
    return text


def group_at(tokens: list[str], idx: int) -> tuple[int, int]:
    """Expand tokens[idx] to the maximal _gap_suspicious-linked group."""
    i = idx
    while i > 0 and _gap_suspicious(tokens[i - 1], tokens[i]):
        i -= 1
    j = idx
    while j < len(tokens) - 1 and _gap_suspicious(tokens[j], tokens[j + 1]):
        j += 1
    return i, j


def survey(name: str, text: str) -> dict:
    t0 = prepass(text)
    # vocabulary BEFORE the subscript pass (the proposed reorder)
    vocab = Counter(_VOCAB_TOKEN_RE.findall(t0.lower()))

    # token positions for group lookup
    tokens = WORD.findall(t0)
    tok_index: dict[int, int] = {}
    pos = 0
    for k, tok in enumerate(tokens):
        pos = t0.find(tok, pos)
        tok_index[pos] = k
        pos += len(tok)

    insertions: list[dict] = []
    for m in lp._SUB_PAIR_RE.finditer(t0):
        form = lp._sub_form(m.group(1), m.group(2))
        if form is None:
            continue
        k = tok_index.get(m.start(1))
        if k is None:
            continue
        i, j = group_at(tokens, k)
        group = tokens[i:j + 1]
        joined = "".join(group).lower()
        underscored = "_".join(group).lower()
        gsize = j - i + 1
        evidence = vocab.get(joined, 0) >= 1 and vocab.get(underscored, 0) == 0
        chain = gsize >= 3
        insertions.append({
            "form": form,
            "group": " ".join(group),
            "group_size": gsize,
            "evidence": evidence,
            "chain": chain,
            "ctx": t0[max(0, m.start() - 40):m.end() + 40].replace("\n", " "),
        })

    cats = Counter(
        "both" if x["evidence"] and x["chain"]
        else "evidence" if x["evidence"]
        else "chain" if x["chain"]
        else "clean"
        for x in insertions)

    def samples(pred, n=12):
        return [f"{x['form']} | grp[{x['group_size']}]: {x['group']} | …{x['ctx']}…"
                for x in insertions if pred(x)][:n]

    post, _ = lp.fix_subscripts(t0)
    hard = [m.group(0) for m in _MISFIRE_SHAPE.finditer(post)]
    # contexts of hard-misfire shapes for eyeballing
    hard_ctx = [post[max(0, m.start() - 50):m.end() + 50].replace("\n", " ")
                for m in list(_MISFIRE_SHAPE.finditer(post))[:12]]

    both = list(_BOTH_SIDED.finditer(t0))
    both_ctx = [t0[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")
                for m in both[:12]]

    return {
        "doc": name,
        "chars": len(t0),
        "insertions": len(insertions),
        "categories": dict(cats),
        "clean_samples": samples(lambda x: not x["evidence"] and not x["chain"]),
        "evidence_samples": samples(lambda x: x["evidence"] and not x["chain"]),
        "chain_samples": samples(lambda x: x["chain"] and not x["evidence"]),
        "both_samples": samples(lambda x: x["evidence"] and x["chain"]),
        "clean_group_sizes": dict(Counter(x["group_size"] for x in insertions
                                          if not x["evidence"] and not x["chain"])),
        "top_clean_forms": Counter(x["form"] for x in insertions
                                   if not x["evidence"] and not x["chain"]).most_common(15),
        "top_clean_groups": Counter(x["group"] for x in insertions
                                    if not x["evidence"] and not x["chain"]).most_common(15),
        "spaced_underscore_both": len(both),
        "spaced_underscore_after": len(_SPACE_AFTER.findall(t0)),
        "spaced_underscore_before": len(_SPACE_BEFORE.findall(t0)),
        "spaced_both_ctx": both_ctx,
        "misfire_shape_in_post": len(hard),
        "misfire_shape_tokens": Counter(hard).most_common(15),
        "misfire_shape_ctx": hard_ctx,
    }


def main() -> None:
    out_dir = Path("out/exp_underscore")
    out_dir.mkdir(parents=True, exist_ok=True)
    report = []
    for name, path in DOCS.items():
        if not path.exists():
            print(f"{name}: MISSING {path}")
            continue
        text = path.read_text(encoding="utf-8")
        r = survey(name, text)
        report.append(r)
        print(f"\n=== {name} ({r['chars']:,} chars) ===")
        print(f"  insertions: {r['insertions']}  categories: {r['categories']}")
        print(f"  clean group sizes: {r['clean_group_sizes']}")
        print(f"  top clean forms: {r['top_clean_forms'][:10]}")
        print(f"  top clean groups: {r['top_clean_groups'][:10]}")
        print(f"  spaced '_': both={r['spaced_underscore_both']}"
              f" after={r['spaced_underscore_after']}"
              f" before={r['spaced_underscore_before']}")
        print(f"  misfire 'X_y z' shapes in post text: {r['misfire_shape_in_post']}"
              f"  tokens: {r['misfire_shape_tokens'][:8]}")
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nreport -> {out_dir / 'report.json'}")


if __name__ == "__main__":
    main()
