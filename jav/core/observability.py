"""The observability sink (213, P1a; the plug-in points of plan 212 P0).

Plain-language summary: how long an operation took and how it ended can be sent to one sink, switched off by default;
the sink receives only the operation's kind, its duration, its outcome category and its attempt count, never a case
id, document content, file name or address, and a sink that fails never stops the work.

229 (plan structure stage 1, SZ2a): moved from the process core to the shared core, so every layer measures through
the same place.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Measurement:
    """What the observability sink receives, and nothing else."""

    operation: str
    seconds: float
    outcome: str
    attempts: int = 1


Observer = Callable[[Measurement], None]

_observer: Observer | None = None


def set_observer(fn: Observer | None) -> None:
    """Installs the observability sink (None: switched off, the default)."""
    global _observer
    _observer = fn


def observe(measurement: Measurement) -> None:
    if _observer is None:
        return
    try:
        _observer(measurement)
    except Exception:  # noqa: BLE001 - observability never stops the work; the failure is logged
        log.exception("the observability sink failed on %s", measurement.operation)


@contextmanager
def measured(operation: str, *, attempts: int = 1) -> Iterator[None]:
    """Measures the block: its duration and "ok", or "error" when it raises (the error goes on)."""
    started = time.perf_counter()
    outcome = "error"
    try:
        yield
        outcome = "ok"
    finally:
        observe(Measurement(operation, time.perf_counter() - started, outcome, attempts))
