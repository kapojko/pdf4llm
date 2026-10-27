"""Token counting and the output-token budget for the LLM pass.

Exact token counts come from the server's own tokenizer: llama-swappy
routes ``POST /llama/tokenize`` under the ``/llama`` prefix (whitelisted in
the proxy; the endpoint never runs prefill or decode, so calls are cheap).
Counts are cached per text. When the endpoint is unavailable the meter
degrades to the naive ``1 char = 1 token`` estimate — deliberately
pessimistic, so the fallback can only shrink batches and enlarge caps,
never truncate.

The output cap is ``cap = EMA(kind) * echo_tokens + margin``. The EMA
starts at 2.0 (the measured rewrite ceiling) and tracks
``completion_tokens / echo_tokens`` per batch kind from response usage:
how much more than the echo a rewrite produces is model behaviour, not
tokenization — no input-side measurement can predict it.
"""
from __future__ import annotations

import json
import math
import re
import threading
import urllib.request

from .llm_client import _OUT_MARGIN_TOKENS

# EMA bounds: a rewrite can legitimately exceed the echo, but anything past
# 8x is a degenerate loop the verifier rejects anyway.
_EXP_MIN, _EXP_MAX = 1.0, 8.0
_EXP_EMA_ALPHA = 0.3   # weight of the newest observation
_EXP_INIT = 2.0        # nominal rewrite ceiling (measured on rm0410)

# Cache bound: fragment texts repeat (requeues, multi-batch docs); past the
# bound the cache simply resets — counting is cheap.
_CACHE_LIMIT = 8192


class TokenMeter:
    """Exact-or-naive token counts + the per-kind output expansion EMA.

    Thread-safe: count() runs in batch tasks and producers, record() merges
    usage from concurrent responses.
    """

    def __init__(self, model: str, endpoint: str, api_key: str, *,
                 exact: bool | None = None, timeout: float = 3.0) -> None:
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key
        self.timeout = timeout
        # True = /llama/tokenize answers; False = degraded to naive;
        # None = not probed yet (probed lazily on the first count()).
        self.exact = exact
        self._url: str | None = None
        self._cache: dict[str, int] = {}
        self.expansion: dict[str, float] = {k: _EXP_INIT
                                            for k in ("cell", "line", "chunk")}
        self.usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        self._lock = threading.Lock()

    # -- counting -------------------------------------------------------------

    def count(self, text: str) -> int:
        """Token count of ``text``: exact when the tokenizer answers."""
        if self.exact is not False:
            n = self._count_exact(text)
            if n is not None:
                return n
        return len(text)  # naive fallback: 1 char = 1 token (pessimistic)

    def _count_exact(self, text: str) -> int | None:
        if self.exact is None:
            self.exact = self._probe()
        if not self.exact or not text:
            return None
        with self._lock:
            cached = self._cache.get(text)
        if cached is not None:
            return cached
        toks = self._post_tokenize(text)
        if toks is None:
            return None
        with self._lock:
            if len(self._cache) >= _CACHE_LIMIT:
                self._cache.clear()
            self._cache[text] = toks
        return toks

    def _tokenize_url(self) -> str:
        if self._url:
            return self._url
        base = self.endpoint.rstrip("/")
        self._url = re.sub(r"/v1/?$", "", base) + "/llama/tokenize"
        return self._url

    def _probe(self) -> bool:
        return self._post_tokenize("0123456789") is not None

    def _post_tokenize(self, content: str) -> int | None:
        """POST /llama/tokenize -> number of tokens, None on any failure."""
        body = json.dumps({"model": self.model, "content": content,
                           "add_special": False}).encode()
        req = urllib.request.Request(
            self._tokenize_url(), data=body,
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                data = json.loads(r.read())
            toks = data.get("tokens")
            if isinstance(toks, list):
                return len(toks)
        except Exception:
            return None
        return None

    # -- output budget --------------------------------------------------------

    def cap_for(self, kind: str, echo_tokens: int) -> int:
        """max_tokens for one request: EMA expansion x echo tokens + margin."""
        exp = self.expansion.get(kind, _EXP_INIT)
        return math.ceil(exp * max(1, echo_tokens)) + _OUT_MARGIN_TOKENS

    def record(self, kind: str, echo_tokens: int, usage: dict | None) -> None:
        """Merge one response's usage; update the expansion EMA.

        Truncated calls are censored at the cap, which re-asserts the current
        EMA value — harmless, and an over-cap observation is the direction
        the cap should err in.
        """
        if not usage:
            return
        comp = usage.get("completion_tokens") or 0
        with self._lock:
            self.usage["calls"] += 1
            self.usage["prompt_tokens"] += usage.get("prompt_tokens") or 0
            self.usage["completion_tokens"] += comp
            if comp > 0 and echo_tokens > 0:
                obs = comp / echo_tokens
                old = self.expansion.get(kind, _EXP_INIT)
                new = (1 - _EXP_EMA_ALPHA) * old + _EXP_EMA_ALPHA * obs
                self.expansion[kind] = min(_EXP_MAX, max(_EXP_MIN, new))

    def meta(self) -> dict:
        """Summary for meta.json: tokenizer availability, EMA, usage totals."""
        with self._lock:
            return {"exact_tokenizer": self.exact is True,
                    "expansion": dict(self.expansion),
                    **self.usage}
