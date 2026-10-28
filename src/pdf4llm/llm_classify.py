"""Document classification: technical vs general prompt selection.

Classification picks only the *prompt*, never the safety rules. Any
ambiguity or error fails safe to the strict technical prompt.
"""
from __future__ import annotations

import re

from .llm_client import _split_sampling


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# Keyword heuristic — cheap fallback / sanity check for the LLM classifier.
_TECH_KEYWORDS: list[tuple[re.Pattern, int]] = [
    (re.compile(r"(?i)\bdatasheet\b|\bdata\s+sheet\b"), 4),
    (re.compile(r"(?i)\breference\s+manual\b"), 4),
    (re.compile(r"(?i)\bpin\s+(description|definition|out)\b"), 3),
    (re.compile(r"(?i)\brevision\s+history\b"), 3),
    (re.compile(r"(?i)\bregister\b"), 3),
    (re.compile(r"(?i)\b(peripheral|timer|GPIO|UART|USART|SPI|I2C|I2S|DMA|ADC|DAC|CRC)\b"), 2),
    (re.compile(r"(?i)\b(electrical|static|dynamic)\s+characteristics\b"), 3),
    (re.compile(r"(?i)\babsolute\s+maximum\s+ratings?\b"), 3),
    (re.compile(r"\b0x[0-9A-Fa-f]{2,}\b"), 3),
    (re.compile(r"(?i)\b(VCC|VDD|VSS|GND|VIO)\b"), 2),
    (re.compile(r"\bSOT\s?-?\s?\d+\b|\bLQFP\b|\bTSSOP\b|\bQFN\b|\bSOIC\b|\bBGA\b"), 3),
    (re.compile(r"(?i)\b(firmware|flash|SRAM|EEPROM|interrupt|clock tree|bootloader)\b"), 2),
    (re.compile(r"(?i)\b(typ|typ\.|min|max)\s*\.?\b"), 1),
    (re.compile(r"(?i)\bpackage\s+(outline|information)\b"), 3),
    (re.compile(r"(?i)\bbit\b.*\bfield\b|\breset\s+value\b"), 3),
]

TECH_SCORE_THRESHOLD = 8


def classify_heuristic(text: str, head_chars: int = 8000) -> tuple[bool, int]:
    """Keyword-based datasheet/manual detector. Returns (is_technical, score)."""
    head = text[:head_chars]
    score = sum(weight for pattern, weight in _TECH_KEYWORDS if pattern.search(head))
    return score >= TECH_SCORE_THRESHOLD, score


CLASSIFY_SYSTEM_PROMPT = (
    "You classify documents. Decide whether the given beginning of a document "
    "is from a TECHNICAL hardware document (electronic component datasheet, "
    "microcontroller reference manual, register specification) or GENERAL text. "
    "Answer with exactly one word: TECHNICAL or GENERAL. No other output."
)


def classify_with_llm(
    text: str,
    model: str,
    endpoint: str,
    api_key: str,
    head_chars: int = 4000,
    max_tokens: int = 1024,
    sampling: dict | None = None,
) -> tuple[bool, str]:
    """Classify the document head via LLM.

    Returns (is_technical, source) where source is 'llm' or 'heuristic-fallback'.
    Fails safe: any error or ambiguous answer falls back to the keyword
    heuristic, which itself defaults to strict/technical on a high score.
    """
    head = text[:head_chars]
    try:
        import litellm  # lazy import

        litellm.suppress_debug_info = True
        std, extra = _split_sampling(sampling or {})
        resp = litellm.completion(
            model=f"openai/{model}",
            messages=[
                {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
                {"role": "user", "content": head},
            ],
            api_base=endpoint,
            api_key=api_key,
            max_tokens=max_tokens,
            # Disable thinking: a reasoning model wastes its token budget on
            # deliberation for a one-word answer. Verified to be honoured by
            # llama-server for this model (passes through the llama-swappy
            # proxy untouched).
            extra_body={**extra, "chat_template_kwargs": {"enable_thinking": False}},
            **std,
        )
        answer = (resp.choices[0].message.content or "").strip().upper()
    except Exception:
        return classify_heuristic(text)[0], "heuristic-fallback"

    if "TECHNICAL" in answer and "GENERAL" not in answer:
        return True, "llm"
    if "GENERAL" in answer and "TECHNICAL" not in answer:
        return False, "llm"
    # Ambiguous (refusal, rambling, both words, empty) -> heuristic fallback.
    return classify_heuristic(text)[0], "heuristic-fallback"
