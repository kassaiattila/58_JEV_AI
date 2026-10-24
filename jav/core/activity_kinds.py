"""The kinds of what people do and what the logs record, in one registry (175, plan 170 E4, decision K18).

Plain-language summary: four lists that were written out by hand in several places now come from here.
- Log events: every action a package's log or a workflow's log records ("renamed", "statements added", "version
  approved", "its live run started"). Each module names the actions it records, and a log refuses an action no module
  named, so a test can check that every action has a label in the interface.
- The sources of "My work today": where a person's actions of the day are read from (package events, runs started
  and approved, corrections, closed to-dos, task decisions, mailbox downloads), in their order; 209 (plan
  G-process-core R2c): a domain registers the sources that read its tables, in the place they always had.
- The decisions a person makes on a run's results (corrections, decisions on an email's task proposals, a native
  result's publication, duplicate, reconciliation and statement decisions). Together they make the run's reviewed
  version: each part present wraps the earlier ones, in the order registered.
- The task kinds an email's task proposal may name (`configs/email_tasks.json` `actions`) and the decisions a person
  makes on a proposal.
A logic pack (`jav/app/logic_packs.py`) adds its own kinds the same way. The built-in ones are registered by the modules that own them;
229 (plan structure stage 1, MD1): the application loads those modules and every domain's registrations
(`registrations.load_all`), and the registry asks for that call (`jav.core.completion`) the first time a full list is
read, so it names no module above the shared core. A domain's kinds come from its domain module: the finance domain's
duplicate, reconciliation and statement decisions, each placed after the part it follows (`after`), so the reviewed
version nests them as before whichever registers first.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from jav.core import cfg, completion

Log = Literal["package", "workflow"]
LOGS: tuple[Log, ...] = ("package", "workflow")

# the modules that register the built-in kinds: the package log's writers, the workflow log, "My work today", the
# reviewed version's parts

class UnknownEvent(ValueError):
    """A log was asked to record an action no module registered."""


@dataclass(frozen=True)
class Source:
    """Where "My work today" reads one kind of action: `sql` returns the columns (at, actor, workpackage_id, run_id,
    detail) of the rows between two times; `flow_run`: the run column holds an item's flow id (`<run>:<item>`);
    `action_prefix`: the action is the detail column after this prefix (a log's own action, labelled as such), else the
    source's code; `detail`: 209 (plan G-process-core R2c): the row's short detail made from its detail column (without
    personal data), for a source whose detail column is not shown as it is."""
    code: str
    sql: str
    flow_run: bool = True
    action_prefix: str | None = None
    detail: Callable[[Any], str | None] | None = None


@dataclass(frozen=True)
class DecisionKind:
    """A kind of decision on a run's results. `rows(run_id, items, c)`: the run's decisions of this kind in the form
    the reviewed version digests (empty: none); `wraps`: the key the earlier parts go under when this part is present
    (None only for the first part, which is the payload itself). `fingerprint(run_id, c)`: 209 (plan G-process-core
    R2c): the kind's own part of a run's result fingerprint, for a kind the fingerprint read in its own form before
    the registry (the email domain's task decisions); a kind without one is fingerprinted by its rows."""
    name: str
    rows: Callable[[str, list[str], sqlite3.Connection], list[Any]]
    wraps: str | None = None
    fingerprint: Callable[[str, sqlite3.Connection], list[Any]] | None = None


_EVENTS: dict[str, dict[str, str]] = {log: {} for log in LOGS}
_SOURCES: dict[str, Source] = {}
_DECISIONS: dict[str, DecisionKind] = {}
_loaded = False


def _load() -> None:
    """The shared modules' kinds, then the domains' (229: the application's registrations, `jav.core.completion`)."""
    global _loaded
    if not _loaded:
        completion.complete("log events and decisions")
        _loaded = True


# --- log events ------------------------------------------------------------------------------------------------------

def register_events(log: Log, codes: Iterable[str], owner: str) -> None:
    """The actions a module records in a log. A code another module already registered is an error."""
    if log not in _EVENTS:
        raise ValueError(f"unknown log {log!r}")
    for code in codes:
        if _EVENTS[log].get(code, owner) != owner:
            raise ValueError(f"{log} event {code} is registered by {_EVENTS[log][code]} already")
        _EVENTS[log][code] = owner


def check_event(log: Log, code: str) -> None:
    """Raises `UnknownEvent` for an action no module registered in the log (its writer registers it on import)."""
    if code not in _EVENTS[log]:
        raise UnknownEvent(f"no module registered the {log} event {code!r}")


def events(log: Log) -> dict[str, str]:
    """Every action of a log: code -> the module that records it."""
    _load()
    return dict(_EVENTS[log])


# --- the sources of "My work today" ------------------------------------------------------------------------------------

def register_source(source: Source, *, after: str | None = None, before: str | None = None) -> None:
    """A source, last or (209, plan G-process-core R2c) right after the source `after` or right before the source
    `before`: a domain's sources keep the place they always had among the shared ones (the shared modules' sources are
    loaded first), whichever domain registers first. The same source again adds nothing; another one of the same code
    is an error."""
    anchor = after or before
    if anchor is not None and anchor not in _SOURCES:
        completion.complete("sources of the day's work")
    known = _SOURCES.get(source.code)
    if known is not None:
        if known == source:
            return
        raise ValueError(f"activity source {source.code} is registered twice")
    if anchor is None:
        _SOURCES[source.code] = source
        return
    if anchor not in _SOURCES:
        raise ValueError(f"activity source {source.code}: no source {anchor!r} to place it by")
    items = list(_SOURCES.items())
    items.insert([code for code, _s in items].index(anchor) + (1 if after else 0), (source.code, source))
    _SOURCES.clear()
    _SOURCES.update(items)


def sources() -> list[Source]:
    """In the order they were registered (rows of the same time keep it)."""
    _load()
    return list(_SOURCES.values())


# --- the decisions on a run's results ----------------------------------------------------------------------------------

def register_decision(kind: DecisionKind, *, after: str | None = None) -> None:
    """A decision kind, last or (185) right after the part `after` (the shared modules' parts are loaded first, so a
    domain's kind finds the part it follows). The same kind again adds nothing; another one of the same name is an
    error."""
    if after is not None and after not in _DECISIONS:
        completion.complete("decisions on a run's results")
    if kind.name in _DECISIONS:
        if _DECISIONS[kind.name] == kind:
            return
        raise ValueError(f"decision kind {kind.name} is registered twice")
    if (kind.wraps is None) != (not _DECISIONS):
        raise ValueError(f"decision kind {kind.name}: only the first part has no wrapping key")
    if after is None:
        _DECISIONS[kind.name] = kind
        return
    if after not in _DECISIONS:
        raise ValueError(f"decision kind {kind.name}: no part {after!r} to follow")
    items = list(_DECISIONS.items())
    items.insert([name for name, _k in items].index(after) + 1, (kind.name, kind))
    _DECISIONS.clear()
    _DECISIONS.update(items)


def decisions() -> list[DecisionKind]:
    """In the order they were registered: the order the reviewed version nests them."""
    _load()
    return list(_DECISIONS.values())


# --- the task proposals ---------------------------------------------------------------------------------------------

def task_kinds() -> tuple[str, ...]:
    """The task kinds an email's task proposal may name, in the order of `configs/email_tasks.json` `actions` (the
    order of the answer's schema)."""
    return tuple(cfg.load("email_tasks")["actions"])


__all__ = ["DecisionKind", "LOGS", "Log", "Source", "UnknownEvent", "check_event", "decisions", "events",
           "register_decision", "register_events", "register_source", "sources", "task_kinds"]
