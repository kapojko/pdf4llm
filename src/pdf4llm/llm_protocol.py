"""Indexed echo protocol ('N| text') for unit-level model requests.

One batched echo request per call; the reply is parsed into {index: text}.
Retry rounds are managed by the batch scheduler (llm_batch), which
re-requests only failed units in later batches, with a per-unit rejection
hint attached as a NOTE line in the payload.
"""
from __future__ import annotations

import re

from .llm_client import _call_llm, _strip_thinking


_IDX_LINE_RE = re.compile(r"^\s*(\d+)\s*\|\s?(.*)$")
_CONTEXT_RE = re.compile(r"^(CONTEXT|context|row:|Row:)")
_NOTE_RE = re.compile(r"^NOTE\s+\d+\s*:")


def _parse_indexed_lines(resp: str, want: set[int]) -> dict[int, str]:
    """Parse a 'N| text' echo answer.

    Continuation lines (no index) are appended to the previous index, so a
    long wrapped line is not lost. Three things must never be captured as
    continuations or units:

    - CONTEXT blocks ('CONTEXT:' / 'row: ...') — the surrounding table row
      attached per row-group (measured failure mode: the model echoes the
      context after the cells, which used to poison the last cell);
    - NOTE lines ('NOTE k: ...') — per-unit rejection hints from the batch
      packer, not text to fix;
    - raw table rows ('| ...') — a model echoing the context row verbatim.

    A context/NOTE line resets ``last`` (so nothing can silently attach to
    the previous unit), but parsing CONTINUES: a batch payload may carry
    several row-groups, each followed by its own CONTEXT block. Indices
    outside `want` are ignored.
    """
    got: dict[int, str] = {}
    last: int | None = None
    for raw in resp.split("\n"):
        stripped_line = raw.strip()
        if _CONTEXT_RE.match(stripped_line) or _NOTE_RE.match(stripped_line):
            last = None
            continue
        m = _IDX_LINE_RE.match(raw)
        if m:
            last = int(m.group(1))
            if last in want:
                got[last] = m.group(2)
        elif (stripped_line and last is not None and last in want
              and not stripped_line.startswith("|")):
            got[last] += "\n" + raw
    return got


def _echo_units(
    system_prompt: str,
    payload: str,
    want: set[int],
    model: str,
    endpoint: str,
    api_key: str,
    sampling: dict | None,
    output_cap_chars: int | None = None,
) -> tuple[dict[int, str], str | None]:
    """ONE batched 'N| ...' echo request; parse the answer.

    ``payload`` is prebuilt by the batch packer: indexed unit lines, per-unit
    NOTE hints, and one CONTEXT block per row-group. ``output_cap_chars`` is
    the FRAGMENT volume: the output token cap scales with it, not with the
    whole prompt (CONTEXT rows and NOTE hints inflate the prompt but not the
    expected output — a prompt-derived cap would give degenerate input-repeat
    more runway as batches grow). Retry rounds are managed by the scheduler,
    which requeues only the failed subset. Sampling is whatever the
    user/server configured (never overridden).

    Returns (got: {index: text}, finish_reason).
    """
    resp, finish = _call_llm(system_prompt, payload, model, endpoint, api_key,
                             sampling=sampling, output_cap_chars=output_cap_chars)
    resp = _strip_thinking(resp)
    return _parse_indexed_lines(resp, want), finish
