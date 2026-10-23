"""Indexed echo protocol ('N| text') for unit-level model requests.

One batched echo request per round; the caller re-requests only the
subset that fails parsing or verification, with a rejection-reason hint.
"""
from __future__ import annotations

import re

from .llm_client import _call_llm, _strip_thinking


_IDX_LINE_RE = re.compile(r"^\s*(\d+)\s*\|\s?(.*)$")


def _parse_indexed_lines(resp: str, want: set[int]) -> dict[int, str]:
    """Parse a 'N| text' echo answer.

    Continuation lines (no index) are appended to the previous index, so a
    long wrapped line is not lost. The appended continuation must never
    capture the CONTEXT block (measured failure mode: the model echoes
    'CONTEXT: ...' after the cells, which used to poison the last cell), so
    parsing stops at the context marker and never captures raw table rows.
    Indices outside `want` are ignored.
    """
    got: dict[int, str] = {}
    last: int | None = None
    for raw in resp.split("\n"):
        stripped_line = raw.strip()
        if stripped_line.startswith(("CONTEXT", "context", "row:", "Row:")):
            break
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
    context: str | None,
    want: set[int],
    model: str,
    endpoint: str,
    api_key: str,
    sampling: dict | None,
    hint: str | None = None,
) -> tuple[dict[int, str], str | None]:
    """ONE batched 'N| ...' echo request; parse the answer.

    Retry rounds — for malformed replies and for units that fail verification
    — are managed by the caller, which re-requests only the failed subset
    with a rejection-reason hint. Sampling is whatever the user/server
    configured (never overridden), so a failed attempt may simply recover on
    the next one.

    Returns (got: {index: text}, finish_reason).
    """
    user = payload + ("\n\nCONTEXT:\n" + context if context else "")
    if hint:
        user += ("\n\nNOTE: your previous output was REJECTED (" + hint + "). "
                 "Return the corrected lines exactly as instructed.")
    resp, finish = _call_llm(system_prompt, user, model, endpoint, api_key,
                             sampling=sampling)
    resp = _strip_thinking(resp)
    return _parse_indexed_lines(resp, want), finish


def _verified_rounds(
    system_prompt: str,
    units: dict[int, str],
    context: str | None,
    verify,
    model: str,
    endpoint: str,
    api_key: str,
    sampling: dict | None,
    retries: int,
    state: dict,
    strip: bool = False,
) -> tuple[dict[int, str], list[int], dict[int, str], str | None]:
    """Send 'N|' echo requests for `units` and verify each returned text.

    Retries (up to `retries` extra rounds) target only the subset that fails
    parsing (malformed reply) or verification, with a rejection-reason hint.
    Sampling is never overridden — a failed attempt may simply recover on the
    next round, since the verifier, not sampling, is the safety gate.

    verify(idx, new_text) -> None when the replacement is accepted.
    Returns (accepted {idx: text}, still_failing [idx], last_fail_reasons,
    last_finish_reason); request counters accumulate into ``state``.
    """
    pending = sorted(units)
    fail_reasons: dict[int, str] = {}
    accepted: dict[int, str] = {}
    fin: str | None = None
    for round_no in range(1 + max(0, retries)):
        payload = "\n".join(f"{k}| {units[k]}" for k in pending)
        hint = None
        if round_no:
            uniq = list(dict.fromkeys(fail_reasons.values()))
            hint = "; ".join(uniq)[:150] or "malformed reply"
        got, fin = _echo_units(system_prompt, payload, context, set(pending),
                               model, endpoint, api_key, sampling, hint=hint)
        state["n_calls"] += 1
        state["retries_used"] += 1 if round_no else 0
        state["truncated"] += 1 if fin == "length" else 0
        if set(got) != set(pending):
            fail_reasons = {k: "malformed reply" for k in pending}
            continue
        new_pending: list[int] = []
        for k in pending:
            new = got[k].strip() if strip else got[k]
            if not new.strip() or new.strip() == units[k].strip():
                continue
            reason = verify(k, new)
            if reason is None:
                accepted[k] = new
            else:
                fail_reasons[k] = reason
                new_pending.append(k)
        pending = new_pending
        if not pending:
            break
    return accepted, pending, fail_reasons, fin
