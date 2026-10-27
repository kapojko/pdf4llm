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


class ReplyParse:
    """Structured result of parsing an indexed echo reply.

    ``got`` has exactly the semantics of :func:`_parse_indexed_lines`;
    the extra fields carry the information the dict loses and the
    deterministic missing-index inference (llm_batch) needs:

    - ``dup_want``: requested ordinals that appeared MORE THAN ONCE in the
      reply (the dict silently keeps the last occurrence — ambiguous, so
      inference must not run);
    - ``orphans``: text blocks that could not attach to any index — lines
      before the first index line, or after a CONTEXT/NOTE reset. A unit
      whose index prefix the model dropped lands here when it follows a
      reset (the common cell-batch shape: CONTEXT between row-groups).
    """

    __slots__ = ("got", "dup_want", "orphans", "order")

    def __init__(self) -> None:
        self.got: dict[int, str] = {}
        self.dup_want: set[int] = set()
        self.orphans: list[str] = []
        self.order: list[int] = []  # want-gids in first-occurrence order


def _parse_reply(resp: str, want: set[int]) -> ReplyParse:
    """Parse a 'N| text' echo answer, keeping reply structure.

    See :func:`_parse_indexed_lines` for the shared capture rules; this
    variant additionally records duplicate ordinals, orphan text blocks and
    reply order (see :class:`ReplyParse`).
    """
    info = ReplyParse()
    got = info.got
    counts: dict[int, int] = {}
    last: int | None = None
    orphan_buf: list[str] = []

    def flush_orphan() -> None:
        if orphan_buf:
            info.orphans.append("\n".join(orphan_buf))
            orphan_buf.clear()

    for raw in resp.split("\n"):
        stripped_line = raw.strip()
        if _CONTEXT_RE.match(stripped_line) or _NOTE_RE.match(stripped_line):
            last = None
            flush_orphan()
            continue
        m = _IDX_LINE_RE.match(raw)
        if m:
            flush_orphan()
            last = int(m.group(1))
            if last in want:
                counts[last] = counts.get(last, 0) + 1
                if last not in got:
                    info.order.append(last)
                got[last] = m.group(2)
        elif (stripped_line and last is not None and last in want
              and not stripped_line.startswith("|")):
            got[last] += "\n" + raw
        elif stripped_line and last is None and not stripped_line.startswith("|"):
            orphan_buf.append(raw)
    flush_orphan()
    info.dup_want = {g for g, c in counts.items() if c > 1}
    return info


def _parse_indexed_lines(resp: str, want: set[int]) -> dict[int, str]:
    """Parse a 'N| text' echo answer (dict-only view of :func:`_parse_reply`).

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
    output_cap_tokens: int | None = None,
    usage_sink: dict | None = None,
) -> tuple[dict[int, str], ReplyParse, str | None]:
    """ONE batched 'N| ...' echo request; parse the answer.

    ``payload`` is prebuilt by the batch packer: indexed unit lines, per-unit
    NOTE hints, and one CONTEXT block per row-group. ``output_cap_chars`` is
    the FRAGMENT volume: the output token cap scales with it, not with the
    whole prompt (CONTEXT rows and NOTE hints inflate the prompt but not the
    expected output — a prompt-derived cap would give degenerate input-repeat
    more runway as batches grow). Retry rounds are managed by the scheduler,
    which requeues only the failed subset. Sampling is whatever the
    user/server configured (never overridden).

    Returns (got: {index: text}, structured parse info, finish_reason).
    """
    resp, finish = _call_llm(system_prompt, payload, model, endpoint, api_key,
                             sampling=sampling, output_cap_chars=output_cap_chars,
                             output_cap_tokens=output_cap_tokens,
                             usage_sink=usage_sink)
    resp = _strip_thinking(resp)
    info = _parse_reply(resp, want)
    return info.got, info, finish
