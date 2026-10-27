"""LLM transport: the single place that talks to the model.

Sampling is never overridden: user-configured llm_sampling is forwarded
verbatim, otherwise no sampling parameters are sent and server-side
defaults apply. max_tokens is capped relative to the input to terminate
false loops cheaply; thinking blocks are stripped before verification.
"""
from __future__ import annotations

import math
import re


# Rough chars-per-token for technical English datasheet/manual prose. Used
# ONLY for the coarse "does the chunk fit the context" estimate — never for
# anything safety-relevant (the verifier is the safety mechanism).
_CHARS_PER_TOKEN = 3.5


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

# Sampling is NOT forced by the tool. When the user configures llm_sampling,
# it is forwarded verbatim on every request; otherwise NO sampling parameters
# are sent and the server-side defaults apply. The set below is only a
# suggested example (from a 9B model card's 'precise coding' preset) for the
# llm_sampling config key — never sent automatically.
DEFAULT_SAMPLING: dict = {
    "temperature": 0.6,
    "top_p": 0.95,
    "top_k": 20,
    "min_p": 0.0,
    "presence_penalty": 0.0,
}

# Keys litellm accepts as standard completion kwargs; everything else in the
# sampling dict is forwarded via extra_body (OpenAI-compatible extensions
# like top_k / min_p).
_STANDARD_SAMPLING_KEYS = {"temperature", "top_p", "presence_penalty", "frequency_penalty"}

# Output token cap. The task is nearly echo-like, but measured rewrites —
# cell re-alignment, whitespace padding — can reach ~2x the input length,
# and the previous 1x cap truncated 419/2936 calls on rm0410 (about half of
# them completable at 4x). 2x keeps a looping (or secretly reasoning) model
# on a short leash while letting legitimate rewrites finish; the truncated
# output then fails verification (invariant A) and the usual salvage
# machinery takes over. This is what terminates false loops cheaply.
_OUT_MARGIN_TOKENS = 256  # code fence + retry hint + estimator error


def output_token_cap(n_chars: int) -> int:
    """max_tokens for one request: 2x input tokens (3.5 chars/token) + margin."""
    return 2 * math.ceil(max(1, n_chars) / _CHARS_PER_TOKEN) + _OUT_MARGIN_TOKENS


# Belt-and-braces against reasoning output: the request already sends
# chat_template_kwargs {enable_thinking: false}, but some servers/templates
# ignore it. A leading <think>...</think> block is stripped before
# verification; an unclosed <think> means the output is all thinking.
_THINK_BLOCK_RE = re.compile(r"^(?:\s*<think>.*?</think>)+\s*", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """Remove a leading <think>...</think> block (or an all-thinking output)."""
    text = _THINK_BLOCK_RE.sub("", text)
    if text.lstrip().startswith("<think>"):
        return ""
    return text


def _split_sampling(sampling: dict) -> tuple[dict, dict]:
    """Split sampling config into litellm standard kwargs vs extra_body.

    ``sampling`` may be empty: an empty dict means NO sampling parameters are
    sent and the server-side defaults apply. ``DEFAULT_SAMPLING`` below is
    kept only as a suggested example for the llm_sampling config key.
    """
    std = {k: v for k, v in sampling.items() if k in _STANDARD_SAMPLING_KEYS}
    extra = {k: v for k, v in sampling.items() if k not in _STANDARD_SAMPLING_KEYS}
    return std, extra


def _call_llm(prompt_system: str, chunk: str, model: str, endpoint: str,
              api_key: str, sampling: dict | None = None,
              retry_hint: str | None = None,
              output_cap_chars: int | None = None,
              output_cap_tokens: int | None = None,
              usage_sink: dict | None = None) -> tuple[str, str | None]:
    import litellm  # lazy import

    litellm.suppress_debug_info = True
    std, extra = _split_sampling(sampling or {})
    user_content = chunk
    if retry_hint:
        user_content += (
            f"\n\nNOTE: your previous output was REJECTED ({retry_hint}). "
            "Return the corrected text exactly as instructed: no additions, "
            "no omissions, no format changes."
        )
    # max_tokens is capped relative to the input: a looping model is cut off
    # quickly and the truncated output is rejected/salvaged. Batched echo
    # requests pass output_cap_tokens (computed by the scheduler from the
    # exact fragment token count x the measured expansion factor); the
    # char-based formula below is the fallback for callers without a meter.
    # In either case the cap is relative to the EXPECTED OUTPUT volume, not
    # the whole prompt: CONTEXT rows and retry notes inflate the prompt but
    # not the expected output.
    if output_cap_tokens is not None:
        max_tokens = output_cap_tokens
    else:
        cap_src = (output_cap_chars if output_cap_chars is not None
                   else len(user_content))
        max_tokens = output_token_cap(cap_src)
    try:
        resp = litellm.completion(
            model=f"openai/{model}",
            messages=[
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": user_content},
            ],
            api_base=endpoint,
            api_key=api_key,
            max_tokens=max_tokens,
            timeout=300,
            extra_body={**extra, "chat_template_kwargs": {"enable_thinking": False}},
            **std,
        )
    except Exception as e:  # network/model error: caller keeps the original
        return "", f"llm error: {type(e).__name__}: {e}"[:200]
    if usage_sink is not None:
        u = getattr(resp, "usage", None)
        if u is not None:
            pt = getattr(u, "prompt_tokens", None) or 0
            ct = getattr(u, "completion_tokens", None) or 0
            usage_sink["prompt_tokens"] = usage_sink.get("prompt_tokens", 0) + pt
            usage_sink["completion_tokens"] = (
                usage_sink.get("completion_tokens", 0) + ct)
    finish = getattr(resp.choices[0], "finish_reason", None)
    return (resp.choices[0].message.content or "").strip(), finish
