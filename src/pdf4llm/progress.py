"""Shared progress rendering for the long CLI stages (layout engine, LLM).

One line, rewritten in place at ~1 Hz when stdout is a TTY; a fresh line
every ~10 s otherwise (piped logs stay readable). Progress is independent
of --verbose.
"""
from __future__ import annotations

import shutil
import sys
import time


def _fmt_duration(seconds: float) -> str:
    """Human-readable duration: 42s, 6m05s, 1h02m."""
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m{sec:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


class LineProgress:
    """Throttled single-line progress renderer (see module docstring).

    ``update(text)`` rewrites the line; ``finish()`` clears it so the next
    plain print starts a fresh line. All output is flushed immediately.
    """

    def __init__(self, hz: float = 1.0, pipe_interval: float = 10.0) -> None:
        self.is_tty = sys.stdout.isatty()
        self.min_interval = 1.0 / hz
        self.pipe_interval = pipe_interval
        self._last = 0.0
        self._last_len = 0
        self._finished = False

    def update(self, text: str) -> None:
        if self._finished:
            return
        now = time.monotonic()
        interval = self.min_interval if self.is_tty else self.pipe_interval
        if now - self._last < interval:
            return
        self._last = now
        if self.is_tty:
            # a line wider than the terminal wraps, and the next '\r' would
            # only return to the start of the LAST wrapped segment — in-place
            # rewriting silently degrades into one printed line per update.
            # Truncate to the (current) terminal width; -1 avoids the
            # deferred-wrap quirk at the last column.
            width = shutil.get_terminal_size().columns
            text = text[:max(1, width - 1)]
            # leftover erasure goes AFTER the text: writing it before would
            # shift the new line right by len(pad) (visible as a jitter)
            pad = " " * max(0, self._last_len - len(text))
            sys.stdout.write(f"\r{text}{pad}")
            sys.stdout.flush()
            self._last_len = len(text)
        else:
            print(text, flush=True)

    def line_break(self) -> None:
        """Drop the cursor to a fresh line before a plain print.

        The next :meth:`update` rewrites the progress line again via ``\\r``.
        No-op off a TTY: piped progress is already plain lines.
        """
        if self.is_tty and not self._finished:
            sys.stdout.write("\n")
            sys.stdout.flush()

    def finish(self) -> None:
        """Clear the progress line (idempotent)."""
        if self._finished:
            return
        self._finished = True
        if self.is_tty:
            sys.stdout.write("\r" + " " * (self._last_len + 2) + "\r")
            sys.stdout.flush()
