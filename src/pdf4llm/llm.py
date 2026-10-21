"""Optional local-LLM broken-text correction pass.

No PDF-extraction library ships an LLM post-processing hook, so this is a
custom pass: chunk the extracted Markdown, ask an OpenAI-compatible local
LLM (via litellm) to fix broken line breaks / split words while preserving
Markdown tables, pipe characters, hex tokens (0x3008) and resolution tokens
(2592x1944). Opt-in via --llm.
"""
from __future__ import annotations

import re

# Chunk large sections by heading, then pack into size-bounded chunks so a
# single LLM call never receives a whole datasheet.
HEADING_SPLIT_RE = re.compile(r"(?m)(?=^#{1,6} )")


def _hard_split(text: str, max_chars: int) -> list[str]:
    """Split an oversized paragraph into <= max_chars windows at word bounds."""
    words = text.split(" ")
    out: list[str] = []
    cur = ""
    for w in words:
        if len(w) > max_chars:  # single token longer than the limit
            if cur:
                out.append(cur)
                cur = ""
            while len(w) > max_chars:
                out.append(w[:max_chars])
                w = w[max_chars:]
            cur = w
            continue
        if cur and len(cur) + 1 + len(w) > max_chars:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out

SYSTEM_PROMPT = (
    "You clean extracted PDF-to-Markdown text. Fix broken line breaks, words "
    "split across lines, and stray line wraps. You MUST preserve ALL Markdown "
    "tables, pipe characters, hex tokens like 0x3008, and resolution tokens "
    "like 2592x1944 exactly as they are. Do not add, remove, translate, or "
    "rephrase any content. Return only the corrected Markdown, with no "
    "commentary."
)


def chunk_markdown(text: str, max_chars: int = 6000) -> list[str]:
    """Split Markdown into LLM-sized chunks, preferring section boundaries."""
    sections = [s for s in HEADING_SPLIT_RE.split(text) if s.strip()]
    chunks: list[str] = []
    cur = ""
    for section in sections:
        if len(section) > max_chars:
            # Oversized single section: fall back to paragraph packing.
            if cur:
                chunks.append(cur)
                cur = ""
            for para in section.split("\n\n"):
                if len(para) > max_chars:
                    if cur:
                        chunks.append(cur)
                        cur = ""
                    chunks.extend(_hard_split(para, max_chars))
                elif cur and len(cur) + len(para) + 2 > max_chars:
                    chunks.append(cur)
                    cur = para
                else:
                    cur = (cur + "\n\n" + para).strip()
        else:
            if cur and len(cur) + len(section) > max_chars:
                chunks.append(cur)
                cur = section
            else:
                cur = (cur + section).strip()
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c.strip()]


def correct_with_llm(
    text: str,
    model: str,
    endpoint: str,
    api_key: str,
    verbose: bool = True,
    max_chars: int = 6000,
) -> str:
    """Run the LLM correction pass and return the corrected Markdown."""
    import litellm  # imported lazily so --llm is only needed when used

    chunks = chunk_markdown(text, max_chars)
    out: list[str] = []
    for i, chunk in enumerate(chunks, 1):
        if verbose:
            print(f"  llm: chunk {i}/{len(chunks)} ({len(chunk)} chars) ...")
        resp = litellm.completion(
            model=f"openai/{model}",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": chunk},
            ],
            api_base=endpoint,
            api_key=api_key,
        )
        out.append(resp.choices[0].message.content.strip())
    return "\n\n".join(out)
