"""The step kinds of the process core (213, P1a): what each kind of step does, registered by the layers above.

Plain-language summary: a process definition names its steps' kinds; each kind is registered here once, with the
function that runs the step and, when the step waits, the events it takes and what its timer does. The core calls
them; it knows no kind itself.

- `run(ctx)` returns `Done(result)` (the step is done; its result gets a new version), `WAIT` (the step has said what
  it waits for: an event, a timer, a person), `Close(outcome)` (the case ends here) or `Fail(note)` (a person retries
  the step). It runs outside any transaction, so it may call another system, and it must be repeatable: when its work
  is already recorded it returns at once without doing it again (a worker may stop at any point).
- `events` are the event kinds the step takes while it waits for them; `on_event(ctx, c, event)` takes one inside the
  engine's transaction and returns `APPLIED` or `REFUSED` (default: applied). An applied event ends the step's wait.
- `on_timer(ctx, c, timer)` acts on the step's timer inside the engine's transaction and returns what it did (e.g. a
  deadline closes the case). Without it the timer is a retry: the step runs again while it keeps its wait.

A kind's behaviour belongs to its name: a case keeps the definition it started with, so a change that would make an
older case go another way is a new kind (`approval_v2`), not a change of the old one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jav.core.process.cases import Event
    from jav.core.process.definition import ProcessDef
    from jav.core.process.engine import StepContext
    from jav.core.process.timers import Timer

__all__ = [  # 229 (SZ1b): what code outside the process core may use; the rest is the core's own
    "APPLIED", "REFUSED", "Done", "Wait", "Close", "Fail", "DONE", "WAIT", "StepOutcome", "StepKind", "UnknownKind",
    "register", "of", "known", "unknown", "events_of",
]

APPLIED, REFUSED = "applied", "refused"


@dataclass(frozen=True)
class Done:
    """The step is done; `result` (JSON) is its result, under a new result version."""

    result: Any = None


@dataclass(frozen=True)
class Wait:
    """The step waits for what it has named (`cases.wait`)."""


@dataclass(frozen=True)
class Close:
    """The case ends with this outcome (e.g. rejected, expired)."""

    outcome: str


@dataclass(frozen=True)
class Fail:
    """The step failed; the note says why, and a person may retry it."""

    note: str


DONE, WAIT = Done(), Wait()
StepOutcome = Done | Wait | Close | Fail


@dataclass(frozen=True)
class StepKind:
    name: str
    owner: str
    run: Callable[[StepContext], StepOutcome]
    events: tuple[str, ...] = ()
    on_event: Callable[[StepContext, sqlite3.Connection, Event], str] | None = None
    on_timer: Callable[[StepContext, sqlite3.Connection, Timer], str] | None = None
    described: dict[str, Any] = field(default_factory=dict)


class UnknownKind(KeyError):
    """No step kind is registered under this name."""


_KINDS: dict[str, StepKind] = {}


def register(kind: StepKind) -> None:
    """Registers a step kind; its owner may register it again (a module loaded twice), another owner may not."""
    prior = _KINDS.get(kind.name)
    if prior is not None and prior.owner != kind.owner:
        raise ValueError(f"step kind {kind.name!r} is registered by {prior.owner}, not by {kind.owner}")
    _KINDS[kind.name] = kind


def of(name: str) -> StepKind:
    try:
        return _KINDS[name]
    except KeyError:
        raise UnknownKind(name) from None


def known(name: str) -> bool:
    return name in _KINDS


def unknown(definition: ProcessDef) -> list[str]:
    """The step kinds the definition names that the running code has not registered."""
    return sorted({s.kind for s in definition.steps if s.kind not in _KINDS})


def events_of(definition: ProcessDef, steps: Iterable[str] | None = None) -> frozenset[str]:
    """The event kinds the definition's steps (or the named ones) take."""
    wanted = set(steps) if steps is not None else None
    return frozenset(e for s in definition.steps if (wanted is None or s.id in wanted) and s.kind in _KINDS
                     for e in _KINDS[s.kind].events)
