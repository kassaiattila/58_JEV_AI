"""The authorisation check and the observability sink (213, P1a; rule 9 and the plug-in points of plan 212 P0).

Plain-language summary: every operation on a case asks one function whether the actor may do it. Today there is one
local user and the answer is always yes; a company's rules will answer here later, at the moment of the operation.
How long an operation took and how it ended can be sent to one sink, switched off by default; the sink receives only
the operation's kind, its duration, its outcome category and its attempt count, never a case id, document content,
file name or address, and a sink that fails never stops the work.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from jav.core.process.actor import Actor

__all__ = [  # 229 (SZ1b): what code outside the process core may use; the rest is the core's own
    "NotAuthorised", "Measurement", "Authorizer", "Observer", "set_authorizer", "authorize", "set_observer",
    "observe", "measured",
]

log = logging.getLogger(__name__)

Authorizer = Callable[[Actor, str, str | None], bool]


class NotAuthorised(PermissionError):
    """The actor may not do this operation on this case."""


@dataclass(frozen=True)
class Measurement:
    """What the observability sink receives, and nothing else."""

    operation: str
    seconds: float
    outcome: str
    attempts: int = 1


Observer = Callable[[Measurement], None]

_authorizer: Authorizer | None = None
_observer: Observer | None = None


def set_authorizer(fn: Authorizer | None) -> None:
    """Installs the authorisation rule (None: everything is allowed, the local default)."""
    global _authorizer
    _authorizer = fn


def authorize(actor: Actor, action: str, case_id: str | None = None) -> None:
    """Raises `NotAuthorised` when the installed rule says no."""
    if _authorizer is not None and not _authorizer(actor, action, case_id):
        raise NotAuthorised(f"{actor.id} may not {action}" + (f" on case {case_id}" if case_id else ""))


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
