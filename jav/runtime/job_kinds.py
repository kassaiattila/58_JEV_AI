"""The kinds of job the worker runs besides a run's items, and the ticks it calls (185, plan G-full-move T1c).

Plain-language summary: the worker takes jobs from the durable queue. A run's item (`work.JOB_KIND`) is the worker's
own; a domain may add a kind of its own with what processes it and what settles it when it ends without being
processed (an interrupted claim, an unexpected error): the email domain adds the mailbox download. A domain may also
add a tick, a step the worker calls before each claim: the email domain's starts the due mailbox schedules. The worker
asks this registry instead of naming them. Each is registered once by its domain module (`registrations.load_all`),
and the registry completes itself the first time it is read, as the check registry does.

Layer: runtime (the registry; no rule of its own). It imports no domain module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JobKind:
    """One kind of job (`jobs.kind`): `process(job)` carries it through and returns the job's end state;
    `abandon(job, error)` settles its owner when it ended without processing."""

    kind: str
    module: str
    process: Callable[[Any], str]
    abandon: Callable[[Any, str], None]


@dataclass(frozen=True)
class Tick:
    """A step the worker calls before each claim (`name` in its log on an error)."""

    name: str
    module: str
    run: Callable[[], Any]


_KINDS: dict[str, JobKind] = {}
_TICKS: dict[str, Tick] = {}


def _complete() -> None:
    from jav.app import registrations
    from jav.runtime import app_jobs

    registrations.load_all()
    app_jobs.register()  # 231 (D-c7e): the application's own jobs, which its layer cannot name here


def register(kind: JobKind) -> None:
    """Registers a kind of job; the same one again adds nothing, another one of the same kind is an error."""
    known = _KINDS.get(kind.kind)
    if known is not None and known != kind:
        raise ValueError(f"job kind {kind.kind!r} is registered already by {known.module}")
    _KINDS[kind.kind] = kind


def register_tick(tick: Tick) -> None:
    known = _TICKS.get(tick.name)
    if known is not None and known != tick:
        raise ValueError(f"tick {tick.name!r} is registered already by {known.module}")
    _TICKS[tick.name] = tick


def kinds() -> list[JobKind]:
    """Every registered kind of job, in the order they were registered."""
    _complete()
    return list(_KINDS.values())


def of(kind: str) -> JobKind | None:
    """The registered kind of a job; None for one no domain registered (a run's item is the worker's own)."""
    _complete()
    return _KINDS.get(kind)


def ticks() -> list[Tick]:
    """Every registered tick, in the order they were registered."""
    _complete()
    return list(_TICKS.values())


__all__ = ["JobKind", "Tick", "kinds", "of", "register", "register_tick", "ticks"]
