"""The case, its steps, its history and its incoming events (213, P1a; rules 1, 2, 3, 4 and 5 of plan 212 P0).

Plain-language summary: a case starts under a stable id with a copy of its process definition and the data it was
started with; the same start again is answered "exists", the same id with other data is a conflict. Its steps move
waiting -> ready -> running -> done (or failed); a step waits for its `after` and `gates` steps, and a person may start
it out of order but never past a gate. Every change is written with its history row in one transaction. An incoming
event carries a stable id: a repeat is a duplicate, the same id with other content a conflict, and an event for a
closed case is kept but ignored. A step that is done gets a new result version; when a person reopens it, the steps
built on it become stale.

214 (P1b-2): work that ran before it was a case moves onto the core without starting again: the case is adopted with
each step in the state the work had reached (`adopt`). A whole case can be put on hold (a person put the work aside)
and resumed; nothing in it moves meanwhile, and its events wait for it.

215 (P2a): an event can be received inside the caller's transaction (`send_event_in`: a human task's closing sends it
with the closing), and what else must change when a step stops running or the case closes registers here
(`on_leave`: the human tasks withdraw the step's open tasks), so this module needs none of them.

227 (plan R3 R3d): a step also keeps its kind's own phase (`phase`, `set_phase`): where the kind's own work on the step
stands, in the kind's own words (e.g. a start under way, a download queued), which the step's state alone does not
say. The core keeps it through all of its own changes (a wait, a retry, a reopening, going stale) and never reads it,
so the kind's next run goes on from it; the kind changes it in the transaction of its own change, a claim with
`expect`. A step's whole state is in its row.

Tables:
- `process_cases`: the case: its definition (copy, id, version, fingerprint), its data, status (open | closed) and
  outcome, and a case-wide wait (`migration`: its definition names a step kind the running code does not have; or the
  reason it is on hold).
- `process_steps`: each step's state (waiting | ready | running | done | failed | stale), what a running step waits
  for, its result and result version, and its kind's own phase (227).
- `process_history`: the case's history, written in the transaction of the change it records; who acted (rule 8).
- `process_inbox`: incoming events by id, with their content's fingerprint (pending | applied | refused | ignored).

The functions that take a connection run inside the caller's write transaction; the others open their own.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from jav.core import rulebook, store, user_messages
from jav.core.clock import utc_stamp as _now
from jav.core.process import definition as definitions
from jav.core import access
from jav.core.identity import Actor
from jav.core.process import kinds, timers
from jav.core.process.definition import ProcessDef

__all__ = [  # 229 (SZ1b): what code outside the process core may use; the rest is the core's own
    "OPEN", "CLOSED", "WAITING", "READY", "RUNNING", "DONE", "FAILED", "STALE", "STATES", "MIGRATION", "PENDING",
    "IGNORED", "UnknownCase", "CaseConflict", "UnknownEvent", "CaseClosed", "StepStateError", "AdoptionError",
    "Event", "Adopted", "on_leave", "transaction", "definition_of", "find_case_in", "case_row", "find_step_in",
    "step_rows", "step_row", "without_case_in", "steps_in_phase_in", "get", "marks", "pending_events", "view", "record",
    "start", "send_event", "cancel", "override_order", "retry", "reopen", "start_in", "send_event_in",
    "override_order_in", "retry_in", "reopen_in", "adopt", "adopt_phases_in", "set_phase", "set_result", "end_wait",
    "fail", "close", "hold", "resume", "open_ids_in", "holding_in",
]

OPEN, CLOSED = "open", "closed"
WAITING, READY, RUNNING, DONE, FAILED, STALE = "waiting", "ready", "running", "done", "failed", "stale"
STATES = (WAITING, READY, RUNNING, DONE, FAILED, STALE)
MIGRATION = "migration"
PENDING, IGNORED = "pending", "ignored"

store.register_schema("process.cases", """
CREATE TABLE IF NOT EXISTS process_cases (
    case_id            TEXT PRIMARY KEY,
    definition_id      TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    definition_sha     TEXT NOT NULL,
    definition         TEXT NOT NULL,          -- the definition the case started with, canonical JSON (rule 1)
    data               TEXT NOT NULL,          -- JSON: what the case was started with
    start_sha          TEXT NOT NULL,          -- fingerprint of the definition and the data: a repeated start
    status             TEXT NOT NULL,          -- open | closed
    outcome            TEXT,                   -- how a closed case ended: done | cancelled | a step's outcome
    waiting_for        TEXT,                   -- the whole case waits: migration
    started_by         TEXT NOT NULL,          -- JSON actor
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_process_cases_status ON process_cases(status, updated_at);
CREATE TABLE IF NOT EXISTS process_steps (
    case_id        TEXT NOT NULL,
    step_id        TEXT NOT NULL,
    state          TEXT NOT NULL,              -- waiting | ready | running | done | failed | stale
    waiting_for    TEXT,                       -- while running: an event kind, budget, a settlement, ...
    result_version INTEGER NOT NULL DEFAULT 0, -- raised each time the step is done (rule 3)
    result         TEXT,                       -- JSON, as the step's kind records it
    note           TEXT,                       -- why it failed
    updated_at     TEXT NOT NULL,
    phase          TEXT,                       -- 227: the step kind's own phase, which the core keeps and never reads
    PRIMARY KEY (case_id, step_id)
);
CREATE TABLE IF NOT EXISTS process_history (
    id      INTEGER PRIMARY KEY,
    case_id TEXT NOT NULL,
    step_id TEXT,
    kind    TEXT NOT NULL,
    actor   TEXT NOT NULL,                     -- JSON actor (rule 8)
    detail  TEXT NOT NULL,                     -- JSON
    pid     INTEGER NOT NULL,                  -- the process that wrote it
    at      REAL NOT NULL                      -- epoch seconds
);
CREATE INDEX IF NOT EXISTS ix_process_history_case ON process_history(case_id, id);
CREATE TABLE IF NOT EXISTS process_inbox (
    event_id    TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    step_id     TEXT,                          -- the step it is for; NULL: the first running step waiting for its kind
    kind        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    payload_sha TEXT NOT NULL,
    status      TEXT NOT NULL,                 -- pending | applied | refused | ignored
    conflicts   INTEGER NOT NULL DEFAULT 0,    -- arrivals of the same id with other content
    sent_by     TEXT NOT NULL,                 -- JSON actor
    received_at TEXT NOT NULL,
    applied_at  TEXT
);
CREATE INDEX IF NOT EXISTS ix_process_inbox_case ON process_inbox(case_id, status);
""")
# 227: a store made before keeps its steps; their kinds' phase starts empty (a kind that had one moves it in itself)
store.register_migration("process.cases.phase", lambda conn: store.add_columns(conn, "process_steps", {"phase": "TEXT"}))


class UnknownCase(KeyError):
    """No case with this id."""


class CaseConflict(ValueError):
    """A case id started again with another definition or other data."""


class UnknownEvent(ValueError):
    """An event kind no step of the case takes, or a step the case does not have."""


class CaseClosed(ValueError):
    """The case is closed; only its history can be read."""


class StepStateError(ValueError):
    """The step is not in a state the operation can start from (e.g. a gate is not done)."""


class AdoptionError(ValueError):
    """An outside state the core cannot take: a step the definition lacks, an unknown state, a wait on a step not
    running."""


@dataclass(frozen=True)
class Event:
    event_id: str
    case_id: str
    step_id: str | None
    kind: str
    payload: dict[str, Any]
    sent_by: Actor


@dataclass(frozen=True)
class Adopted:
    """A step's state as its case is adopted (`adopt`): a running step may wait, with a timer (name, epoch seconds);
    227: with its kind's own phase."""

    state: str
    waiting_for: str | None = None
    note: str | None = None
    result: Any = None
    timer: tuple[str, float] | None = None
    phase: str | None = None


Leave = Callable[[sqlite3.Connection, str, str | None, Actor], None]
_leave_hooks: list[Leave] = []


def on_leave(fn: Leave) -> None:
    """215: `fn(c, case_id, step_id, actor)` runs in the transaction in which a step stops running (done, failed,
    stale) or, with `step_id` None, the case closes."""
    if fn not in _leave_hooks:
        _leave_hooks.append(fn)


def _left(c: sqlite3.Connection, case_id: str, step_id: str | None, actor: Actor) -> None:
    for fn in _leave_hooks:
        fn(c, case_id, step_id, actor)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """One write transaction, locked before its first read; inside an enclosing one, part of it (207)."""
    with store.connect() as c:
        store.begin_immediate(c)
        yield c


@functools.lru_cache(maxsize=256)
def _parsed(text: str) -> ProcessDef:
    return definitions.load(text)


def definition_of(row: dict[str, Any]) -> ProcessDef:
    """The definition a case started with (rule 1), from its stored copy."""
    return _parsed(row["definition"])


# --- reading --------------------------------------------------------------------------------------------------------


def find_case_in(c: sqlite3.Connection, case_id: str) -> dict[str, Any] | None:
    """229: the case, or None when there is none (e.g. a workflow an older process made, until it is adopted)."""
    row = c.execute("SELECT * FROM process_cases WHERE case_id=?", (case_id,)).fetchone()
    return None if row is None else {**dict(row), "data": json.loads(row["data"])}


def case_row(c: sqlite3.Connection, case_id: str) -> dict[str, Any]:
    row = find_case_in(c, case_id)
    if row is None:
        raise UnknownCase(case_id)
    return row


def _step(row: sqlite3.Row) -> dict[str, Any]:
    return {**dict(row), "result": json.loads(row["result"]) if row["result"] is not None else None}


def step_rows(c: sqlite3.Connection, case_id: str) -> dict[str, dict[str, Any]]:
    return {r["step_id"]: _step(r) for r in c.execute("SELECT * FROM process_steps WHERE case_id=?", (case_id,))}


def find_step_in(c: sqlite3.Connection, case_id: str, step_id: str) -> dict[str, Any] | None:
    """229: the step, or None when its case has no such step (or there is no case)."""
    row = c.execute("SELECT * FROM process_steps WHERE case_id=? AND step_id=?", (case_id, step_id)).fetchone()
    return None if row is None else _step(row)


def step_row(c: sqlite3.Connection, case_id: str, step_id: str) -> dict[str, Any]:
    row = find_step_in(c, case_id, step_id)
    if row is None:
        raise StepStateError(f"case {case_id} has no step {step_id!r}")
    return row


_CHUNK = 500  # ids per query of a lookup by many ids


def without_case_in(c: sqlite3.Connection, case_ids: Iterable[str]) -> list[str]:
    """229: those of the ids that have no case, in their given order."""
    ids = list(case_ids)
    known: set[str] = set()
    for i in range(0, len(ids), _CHUNK):
        part = ids[i:i + _CHUNK]
        known |= {r["case_id"] for r in c.execute(
            f"SELECT case_id FROM process_cases WHERE case_id IN ({','.join('?' * len(part))})", part)}
    return [i for i in ids if i not in known]


def steps_in_phase_in(c: sqlite3.Connection, phases: Iterable[str]) -> list[tuple[str, str]]:
    """229: the (case, step) pairs whose step kind's own phase (`set_phase`) is one of these, of any case."""
    wanted = list(phases)
    return [(r["case_id"], r["step_id"]) for r in c.execute(
        f"SELECT case_id, step_id FROM process_steps WHERE phase IN ({','.join('?' * len(wanted))})"
        " ORDER BY case_id, step_id", wanted)]


def adopt_phases_in(c: sqlite3.Connection, phases: Mapping[tuple[str, str], str]) -> int:
    """229 (227's store change): the phases a store of before kept elsewhere, for the steps that have none yet, in the
    caller's write transaction; nothing else of the step or its case changes (a migration, not a change of the case).
    Returns how many it set."""
    return sum(c.execute("UPDATE process_steps SET phase=? WHERE case_id=? AND step_id=? AND phase IS NULL",
                         (phase, case_id, step_id)).rowcount for (case_id, step_id), phase in phases.items())


def get(case_id: str) -> dict[str, Any]:
    with store.connect() as c:
        return case_row(c, case_id)


def open_ids_in(c: sqlite3.Connection) -> list[str]:
    """Stage D0 (D0-e): the open cases' ids, oldest first."""
    return [r["case_id"] for r in c.execute("SELECT case_id FROM process_cases WHERE status=? ORDER BY created_at, case_id",
                                            (OPEN,))]


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def holding_in(c: sqlite3.Connection, texts: list[str]) -> list[str]:
    """231 (stage U, U0): the cases, open or closed, whose start data holds any of `texts` as written (a version a case
    keeps from its start, `"<id>@`), oldest first."""
    found: dict[str, None] = {}
    for text in texts:
        for r in c.execute("SELECT case_id FROM process_cases WHERE data LIKE ? ESCAPE '\\' ORDER BY created_at, case_id",
                           (_like(text),)):
            found.setdefault(r["case_id"])
    return list(found)


def marks() -> list[Any]:
    """231 (A3d): a mark that changes whenever a case, a step or a human task changes (a list built from them is built
    again only then)."""
    with store.connect() as c:
        return [tuple(c.execute("SELECT COUNT(*), MAX(updated_at) FROM process_cases").fetchone()),
                tuple(c.execute("SELECT COUNT(*), MAX(updated_at) FROM process_steps").fetchone()),
                tuple(c.execute("SELECT SUM(status='open'), MAX(opened_at), MAX(closed_at) FROM process_tasks").fetchone())]


def pending_events(case_id: str) -> list[Event]:
    """The case's events not yet taken, in the order they arrived."""
    with store.connect() as c:
        rows = c.execute("SELECT * FROM process_inbox WHERE case_id=? AND status=? ORDER BY rowid", (case_id, PENDING))
        return [_event(r) for r in rows.fetchall()]


def _event(row: sqlite3.Row) -> Event:
    return Event(row["event_id"], row["case_id"], row["step_id"], row["kind"], json.loads(row["payload"]),
                 Actor.from_json(row["sent_by"]))


def view(case_id: str) -> dict[str, Any]:
    """The case as the core keeps it: the case, its steps, its events and its history."""
    with store.connect() as c:
        row = case_row(c, case_id)
        events = {r["event_id"]: {"kind": r["kind"], "status": r["status"], "conflicts": r["conflicts"]}
                  for r in c.execute("SELECT event_id, kind, status, conflicts FROM process_inbox WHERE case_id=?"
                                     " ORDER BY rowid", (case_id,))}
        history = [{"step_id": r["step_id"], "kind": r["kind"], "actor": json.loads(r["actor"])["id"],
                    "detail": json.loads(r["detail"]), "pid": r["pid"], "at": r["at"]}
                   for r in c.execute("SELECT * FROM process_history WHERE case_id=? ORDER BY id", (case_id,))]
        steps = {sid: {k: s[k] for k in ("state", "waiting_for", "result_version", "result", "note", "phase")}
                 for sid, s in step_rows(c, case_id).items()}
    return {"case_id": case_id, "definition": {"id": row["definition_id"], "version": row["definition_version"],
                                               "sha": row["definition_sha"]},
            "status": row["status"], "outcome": row["outcome"], "waiting_for": row["waiting_for"], "data": row["data"],
            "steps": steps, "events": events, "history": history}


# --- writing inside a transaction -----------------------------------------------------------------------------------


def record(c: sqlite3.Connection, case_id: str, step_id: str | None, kind: str, actor: Actor,
           detail: dict[str, Any] | None = None) -> None:
    """One history row, in the caller's transaction (rule 4)."""
    c.execute("INSERT INTO process_history(case_id, step_id, kind, actor, detail, pid, at) VALUES (?,?,?,?,?,?,?)",
              (case_id, step_id, kind, actor.as_json(), _json(detail or {}), os.getpid(), time.time()))


def _touch(c: sqlite3.Connection, case_id: str) -> None:
    c.execute("UPDATE process_cases SET updated_at=? WHERE case_id=?", (_now(), case_id))


def _set_step(c: sqlite3.Connection, case_id: str, step_id: str, **fields: Any) -> None:
    sets = ", ".join(f"{name}=?" for name in fields)
    c.execute(f"UPDATE process_steps SET {sets}, updated_at=? WHERE case_id=? AND step_id=?",
              (*fields.values(), _now(), case_id, step_id))
    _touch(c, case_id)


def require_open(c: sqlite3.Connection, case_id: str) -> dict[str, Any]:
    row = case_row(c, case_id)
    if row["status"] != OPEN:
        raise CaseClosed(f"case {case_id} is closed ({row['outcome']})")
    return row


def _require_running(c: sqlite3.Connection, case_id: str, step_id: str) -> dict[str, Any]:
    require_open(c, case_id)
    st = step_row(c, case_id, step_id)
    if st["state"] != RUNNING:
        raise StepStateError(f"step {step_id!r} of case {case_id} is {st['state']}, not running")
    return st


def promote(c: sqlite3.Connection, case_id: str) -> list[str]:
    """Steps whose order and gates are all done become ready; returns them."""
    defn = definition_of(case_row(c, case_id))
    steps = step_rows(c, case_id)
    ready = [s.id for s in defn.steps
             if steps[s.id]["state"] in (WAITING, STALE) and all(steps[n]["state"] == DONE for n in s.needs())]
    for sid in ready:
        _set_step(c, case_id, sid, state=READY)
    return ready


def begin(c: sqlite3.Connection, case_id: str, step_id: str, actor: Actor) -> bool:
    """A ready step starts running (its history row once); True when the step is running now."""
    if case_row(c, case_id)["status"] != OPEN:
        return False
    st = step_row(c, case_id, step_id)
    if st["state"] == READY:
        _set_step(c, case_id, step_id, state=RUNNING, waiting_for=None, note=None)
        record(c, case_id, step_id, "step_started", actor)
        return True
    return st["state"] == RUNNING


def wait(c: sqlite3.Connection, case_id: str, step_id: str, what: str, actor: Actor, *,
         timer: tuple[str, float] | None = None, detail: dict[str, Any] | None = None) -> None:
    """The running step waits for `what`; with `timer` (name, epoch seconds) its timer is armed in the same transaction,
    so a restart never finds the wait without it."""
    st = _require_running(c, case_id, step_id)
    if st["waiting_for"] != what:
        _set_step(c, case_id, step_id, waiting_for=what)
        record(c, case_id, step_id, "waiting", actor, {"for": what, **(detail or {})})
    if timer is not None:
        timers.arm(c, case_id, step_id, timer[0], timer[1])


def end_wait(c: sqlite3.Connection, case_id: str, step_id: str, actor: Actor, by: str) -> None:
    """The step's wait is over (an event, a timer, a person): the step runs again; its other timers are cancelled in
    the same transaction, so an event and a deadline never both win (rule 7)."""
    st = step_row(c, case_id, step_id)
    if st["state"] != RUNNING or st["waiting_for"] is None:
        return
    _set_step(c, case_id, step_id, waiting_for=None)
    timers.cancel(c, case_id, step_id=step_id, effect=f"wait ended: {by}")
    record(c, case_id, step_id, "wait_ended", actor, {"for": st["waiting_for"], "by": by})


def set_result(c: sqlite3.Connection, case_id: str, step_id: str, result: Any) -> None:
    """What the step has gathered so far (e.g. a decision it received); the result version is raised when it is done."""
    _set_step(c, case_id, step_id, result=_json(result))


def set_phase(c: sqlite3.Connection, case_id: str, step_id: str, phase: str, *,
              expect: tuple[str, ...] | None = None) -> bool:
    """227: the step kind's own phase, in the caller's write transaction, whatever the step's state; with `expect` only
    from one of those phases (a claim: False when another process got there first, and nothing is written). The kind
    records its own log of it; the core keeps it and never reads it."""
    sql = "UPDATE process_steps SET phase=?, updated_at=? WHERE case_id=? AND step_id=?"
    args: list[Any] = [phase, _now(), case_id, step_id]
    if expect is not None:
        sql += f" AND phase IN ({','.join('?' * len(expect))})"
        args += list(expect)
    if not c.execute(sql, args).rowcount:
        return False
    _touch(c, case_id)
    return True


def complete(c: sqlite3.Connection, case_id: str, step_id: str, actor: Actor, result: Any = None) -> int:
    """The running step is done under a new result version (rule 3); the steps it unblocks become ready, and a case
    whose steps are all done closes as done. Returns the result version. 218 (P3l): its history row names the result
    versions of the steps it waits for (`built_on`), as they were when it was done."""
    st = _require_running(c, case_id, step_id)
    version = int(st["result_version"]) + 1
    fields: dict[str, Any] = {"state": DONE, "waiting_for": None, "result_version": version, "note": None}
    if result is not None:
        fields["result"] = _json(result)
    needs = definition_of(case_row(c, case_id)).step(step_id).needs()
    steps = step_rows(c, case_id)
    _set_step(c, case_id, step_id, **fields)
    timers.cancel(c, case_id, step_id=step_id, effect="step done")
    record(c, case_id, step_id, "step_done", actor,
           {"result_version": version, "built_on": {n: int(steps[n]["result_version"]) for n in needs}})
    _left(c, case_id, step_id, actor)
    promote(c, case_id)
    if all(s["state"] == DONE for s in step_rows(c, case_id).values()):
        close(c, case_id, "done", actor)
    return version


def fail(c: sqlite3.Connection, case_id: str, step_id: str, actor: Actor, note: str, *,
         reasons: Iterable[Any] = ()) -> None:
    """The step failed; a person retries it (`retry`). U-A8: `reasons`, why in a person's words (`Said` sentences),
    kept in the failure's history row (`said_fields`) for the case's page."""
    st = step_row(c, case_id, step_id)
    if st["state"] not in (READY, RUNNING):
        return
    _set_step(c, case_id, step_id, state=FAILED, waiting_for=None, note=note[:1000])
    timers.cancel(c, case_id, step_id=step_id, effect="step failed")
    said = [user_messages.said_fields(r) for r in reasons]
    record(c, case_id, step_id, "step_failed", actor, {"note": note[:1000]} | ({"reasons": said} if said else {}))
    _left(c, case_id, step_id, actor)


def close(c: sqlite3.Connection, case_id: str, outcome: str, actor: Actor) -> None:
    """Closes an open case: its timers are cancelled and its pending events ignored, in this transaction."""
    if case_row(c, case_id)["status"] != OPEN:
        return
    c.execute("UPDATE process_cases SET status=?, outcome=?, waiting_for=NULL, updated_at=? WHERE case_id=?",
              (CLOSED, outcome, _now(), case_id))
    timers.cancel(c, case_id, effect=f"case {outcome}")
    c.execute("UPDATE process_inbox SET status=?, applied_at=? WHERE case_id=? AND status=?",
              (IGNORED, _now(), case_id, PENDING))
    record(c, case_id, None, "closed", actor, {"outcome": outcome})
    _left(c, case_id, None, actor)


def need_migration(c: sqlite3.Connection, case_id: str, missing: list[str], actor: Actor) -> None:
    """The case's definition names step kinds the running code lacks: the whole case waits for a migration (rule 1)."""
    row = case_row(c, case_id)
    if row["status"] == OPEN and row["waiting_for"] != MIGRATION:
        c.execute("UPDATE process_cases SET waiting_for=?, updated_at=? WHERE case_id=?", (MIGRATION, _now(), case_id))
        record(c, case_id, None, "migration_needed", actor, {"missing_kinds": missing})


def take_event(c: sqlite3.Connection, event_id: str, status: str) -> None:
    c.execute("UPDATE process_inbox SET status=?, applied_at=? WHERE event_id=?", (status, _now(), event_id))


def hold(c: sqlite3.Connection, case_id: str, reason: str, actor: Actor) -> bool:
    """The whole case waits for `reason` (214: a person put the work aside): none of its steps, events or timers moves
    until it is resumed; events still arrive and wait for it. False when the case is closed or waits already."""
    if reason == MIGRATION:
        raise ValueError("the migration wait is the engine's own (`need_migration`), not a hold")
    row = case_row(c, case_id)
    if row["status"] != OPEN or row["waiting_for"] is not None:
        return False
    c.execute("UPDATE process_cases SET waiting_for=?, updated_at=? WHERE case_id=?", (reason, _now(), case_id))
    record(c, case_id, None, "held", actor, {"for": reason})
    return True


def resume(c: sqlite3.Connection, case_id: str, reason: str, actor: Actor) -> bool:
    """The case's hold for `reason` is over and it moves on; False when it does not wait for that."""
    if reason == MIGRATION:
        raise ValueError("the migration wait ends with the migration, not with a resume")
    row = case_row(c, case_id)
    if row["status"] != OPEN or row["waiting_for"] != reason:
        return False
    c.execute("UPDATE process_cases SET waiting_for=NULL, updated_at=? WHERE case_id=?", (_now(), case_id))
    record(c, case_id, None, "resumed", actor, {"for": reason})
    return True


def _start_sha(definition: ProcessDef, data: dict[str, Any]) -> str:
    return _sha({"definition": definition.fingerprint(), "data": data})


def _prior_start(c: sqlite3.Connection, case_id: str, sha: str) -> bool:
    """Whether the case was started already with this definition and data; another start under its id is a conflict."""
    prior = c.execute("SELECT start_sha FROM process_cases WHERE case_id=?", (case_id,)).fetchone()
    if prior is not None and prior["start_sha"] != sha:
        raise CaseConflict(f"case {case_id} was started with another definition or other data")
    return prior is not None


def _insert_case(c: sqlite3.Connection, case_id: str, definition: ProcessDef, data: dict[str, Any], sha: str,
                 started_by: Actor) -> str:
    now = _now()
    c.execute("INSERT INTO process_cases(case_id, definition_id, definition_version, definition_sha, definition, data,"
              " start_sha, status, started_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (case_id, definition.id, definition.version, definition.fingerprint(), definition.canonical(),
               _json(data), sha, OPEN, started_by.as_json(), now, now))
    return now


def start_in(c: sqlite3.Connection, case_id: str, definition: ProcessDef, data: dict[str, Any], actor: Actor) -> str:
    """`start` inside the caller's write transaction (214: a case that starts with the caller's own rows, or neither)."""
    access.authorize(actor, "start", case_id)
    sha = _start_sha(definition, data)
    if _prior_start(c, case_id, sha):
        return "exists"
    now = _insert_case(c, case_id, definition, data, sha, actor)
    rulebook.link_in(c, rulebook.CASE, case_id)  # 218: the code and the rules the case started with
    for step in definition.steps:
        c.execute("INSERT INTO process_steps(case_id, step_id, state, updated_at) VALUES (?,?,?,?)",
                  (case_id, step.id, WAITING if step.needs() else READY, now))
    record(c, case_id, None, "started", actor, {"definition": definition.id, "version": definition.version,
                                                "sha": definition.fingerprint()})
    return "started"


def adopt(c: sqlite3.Connection, case_id: str, definition: ProcessDef, data: dict[str, Any], started_by: Actor,
          by: Actor, steps: Mapping[str, Adopted]) -> str:
    """214 (P1b-2): a case started from a state reached outside the core (work that ran before it moves onto it), in
    the caller's write transaction: each step in its given state (a step not given waits), a running step's wait with
    its timer, a done step under result version 1. Then the steps whose order and gates are done become ready, and a
    case whose steps are all done closes. One history row, by `by`, records the adoption and the states it took; the
    case is `started_by`'s. "adopted"; a case already there answers "exists" and keeps its own state (once adopted, the
    core's state counts); the same id with another definition or other data is a conflict, as for `start`."""
    access.authorize(by, "adopt", case_id)
    if unknown := sorted(set(steps) - {s.id for s in definition.steps}):
        raise AdoptionError(f"the definition {definition.id} has no step {unknown}")
    for sid, st in steps.items():
        if st.state not in STATES:
            raise AdoptionError(f"step {sid!r}: {st.state!r} is not a step state")
        if st.state != RUNNING and (st.waiting_for is not None or st.timer is not None):
            raise AdoptionError(f"step {sid!r} is {st.state}: only a running step waits")
    sha = _start_sha(definition, data)
    if _prior_start(c, case_id, sha):
        return "exists"
    now = _insert_case(c, case_id, definition, data, sha, started_by)
    taken = {s.id: steps.get(s.id, Adopted(WAITING)) for s in definition.steps}
    for sid, st in taken.items():
        c.execute("INSERT INTO process_steps(case_id, step_id, state, waiting_for, result_version, result, note, updated_at,"
                  " phase) VALUES (?,?,?,?,?,?,?,?,?)",
                  (case_id, sid, st.state, st.waiting_for, 1 if st.state == DONE else 0,
                   None if st.result is None else _json(st.result), st.note, now, st.phase))
    record(c, case_id, None, "adopted", by, {
        "definition": definition.id, "version": definition.version, "sha": definition.fingerprint(),
        "steps": {sid: st.state if st.waiting_for is None else f"{st.state}:{st.waiting_for}" for sid, st in taken.items()}})
    for sid, st in taken.items():
        if st.timer is not None:
            timers.arm(c, case_id, sid, st.timer[0], st.timer[1])
    promote(c, case_id)
    if all(st.state == DONE for st in taken.values()):
        close(c, case_id, "done", by)
    return "adopted"


# --- operations with their own transaction ----------------------------------------------------------------------------


def start(case_id: str, definition: ProcessDef, data: dict[str, Any], actor: Actor) -> str:
    """"started", or "exists" for a repeat of the same start; the same id with another definition or other data is a
    `CaseConflict` (rule 5 for the start). The steps that wait for nothing are ready at once."""
    with transaction() as c:
        return start_in(c, case_id, definition, data, actor)


def send_event_in(c: sqlite3.Connection, case_id: str, event_id: str, kind: str, payload: dict[str, Any], actor: Actor,
                  *, step_id: str | None = None) -> str:
    """`send_event` inside the caller's write transaction (215: a human task's closing sends its event with it)."""
    access.authorize(actor, "send_event", case_id)
    sha = _sha({"case_id": case_id, "step_id": step_id, "kind": kind, "payload": payload})
    row = case_row(c, case_id)
    defn = definition_of(row)
    if step_id is not None and step_id not in {s.id for s in defn.steps}:
        raise UnknownEvent(f"case {case_id} has no step {step_id!r}")
    if kind not in kinds.events_of(defn, [step_id] if step_id else None):
        raise UnknownEvent(f"no step of case {case_id} takes {kind!r} events")
    prior = c.execute("SELECT payload_sha FROM process_inbox WHERE event_id=?", (event_id,)).fetchone()
    if prior is not None:
        if prior["payload_sha"] == sha:
            return "duplicate"
        c.execute("UPDATE process_inbox SET conflicts=conflicts+1 WHERE event_id=?", (event_id,))
        return "conflict"
    c.execute("INSERT INTO process_inbox(event_id, case_id, step_id, kind, payload, payload_sha, status, sent_by,"
              " received_at, applied_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
              (event_id, case_id, step_id, kind, _json(payload), sha, PENDING if row["status"] == OPEN else IGNORED,
               actor.as_json(), _now(), None if row["status"] == OPEN else _now()))
    return "accepted"


def send_event(case_id: str, event_id: str, kind: str, payload: dict[str, Any], actor: Actor, *,
               step_id: str | None = None) -> str:
    """Receives an event (rule 5): "accepted" (new), "duplicate" (the same id and content again) or "conflict" (the
    same id with other content: nothing changes but its conflict count). An event for a closed case is kept as
    ignored. The kind must be one a step of the case takes."""
    with transaction() as c:
        return send_event_in(c, case_id, event_id, kind, payload, actor, step_id=step_id)


def cancel(case_id: str, actor: Actor) -> str:
    """Cancels an open case; returns its outcome."""
    access.authorize(actor, "cancel", case_id)
    with transaction() as c:
        close(c, case_id, "cancelled", actor)
        return str(case_row(c, case_id)["outcome"])


def override_order_in(c: sqlite3.Connection, case_id: str, step_id: str, actor: Actor, *,
                      reason: str | None = None) -> None:
    """`override_order` inside the caller's write transaction (214: with the caller's own change, or neither)."""
    access.authorize(actor, "override_order", case_id)
    defn = definition_of(require_open(c, case_id))
    step = defn.step(step_id)
    steps = step_rows(c, case_id)
    if steps[step_id]["state"] not in (WAITING, STALE):
        raise StepStateError(f"step {step_id!r} is {steps[step_id]['state']}, not waiting")
    closed = [g for g in step.gates if steps[g]["state"] != DONE]
    if closed:
        raise StepStateError(f"step {step_id!r} has gates not done: {closed}; a gate cannot be overridden")
    _set_step(c, case_id, step_id, state=READY)
    record(c, case_id, step_id, "order_overridden", actor,
           {"skipped": [a for a in step.after if steps[a]["state"] != DONE], "reason": reason})


def override_order(case_id: str, step_id: str, actor: Actor, *, reason: str | None = None) -> None:
    """A person starts a waiting step before the steps of its order are done (rule 2, recorded); its gates must be done:
    nothing overrides a gate."""
    with transaction() as c:
        override_order_in(c, case_id, step_id, actor, reason=reason)


def retry_in(c: sqlite3.Connection, case_id: str, step_id: str, actor: Actor) -> None:
    """`retry` inside the caller's write transaction."""
    access.authorize(actor, "retry", case_id)
    require_open(c, case_id)
    if step_row(c, case_id, step_id)["state"] != FAILED:
        raise StepStateError(f"step {step_id!r} has not failed")
    _set_step(c, case_id, step_id, state=READY, note=None)
    record(c, case_id, step_id, "step_retried", actor)


def retry(case_id: str, step_id: str, actor: Actor) -> None:
    """A person starts a failed step again."""
    with transaction() as c:
        retry_in(c, case_id, step_id, actor)


def reopen_in(c: sqlite3.Connection, case_id: str, step_id: str, actor: Actor, *, reason: str) -> list[str]:
    """`reopen` inside the caller's write transaction. 214: a step of a case closed as done reopens the case too (the
    work turned out not to be finished: a package of a done workflow was deleted); a case closed otherwise stays
    closed."""
    access.authorize(actor, "reopen", case_id)
    row = case_row(c, case_id)
    if row["status"] == CLOSED and row["outcome"] == "done":
        c.execute("UPDATE process_cases SET status=?, outcome=NULL, updated_at=? WHERE case_id=?", (OPEN, _now(), case_id))
        record(c, case_id, None, "case_reopened", actor, {"because": step_id, "reason": reason})
    defn = definition_of(require_open(c, case_id))
    if step_row(c, case_id, step_id)["state"] != DONE:
        raise StepStateError(f"step {step_id!r} is not done")
    _set_step(c, case_id, step_id, state=RUNNING, waiting_for=None)
    record(c, case_id, step_id, "reopened", actor, {"reason": reason})
    steps = step_rows(c, case_id)
    stale = [d for d in defn.dependants(step_id) if steps[d]["state"] != WAITING]
    for sid in stale:
        _set_step(c, case_id, sid, state=STALE, waiting_for=None)
        timers.cancel(c, case_id, step_id=sid, effect=f"stale: {step_id} reopened")
        record(c, case_id, sid, "stale", actor, {"because": step_id})
        _left(c, case_id, sid, actor)
    return stale


def reopen(case_id: str, step_id: str, actor: Actor, *, reason: str) -> list[str]:
    """A person reopens a done step (rule 3): it runs again, and the steps built on it that are not waiting become
    stale (their timers cancelled); they run again once it is done. Returns the stale steps."""
    with transaction() as c:
        return reopen_in(c, case_id, step_id, actor, reason=reason)
