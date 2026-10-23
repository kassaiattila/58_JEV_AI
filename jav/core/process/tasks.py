"""Human tasks of the process core (215, plan G-process-core P2a; rules 3, 4, 5, 7, 8 and 9 of plan 212 P0).

Plain-language summary: a human task is a piece of work waiting for a person: check a document's to-dos, approve a
run, decide a budget. Its id comes from what it is about (its kind and subject), so opening it again while it is open
changes nothing, and opening it after it was closed starts a new round. It names its assignee (a person or a group;
nobody named: anyone), may have a deadline and may need a reason, and it records the result version the decision is
about (rule 3). It ends decided by a person, expired by its deadline, or withdrawn (what it was about went away or
moved on). Every change is written with its history row in the caller's transaction, and the authorisation check is
asked before anyone acts on it.

A task may belong to a running step of a case: then it is that step's wait, its deadline is a timer of the case (the
engine expires it when due; a woken turn never does so early), and its closing sends the case an event in the same
transaction, so the step moves on at the case's next turn. When the case closes or the step stops running, its open
tasks are withdrawn without an event (nothing waits for one any more).

Tables:
- `process_tasks`: one row per task in its current round: what it is about, its case and step, its assignee, deadline,
  whether a decision needs a reason (the rule as it was when the task opened), the result version, its state and how
  it ended.
- `process_task_history`: every change, by round (who, what, when); a task in a case also writes the case's history.

The functions that take a connection run inside the caller's write transaction; `decide` opens its own.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from jav.core import store
from jav.core.clock import utc_stamp as _now
from jav.core.process import cases, hooks, kinds, timers
from jav.core.process.actor import Actor

OPEN, DECIDED, EXPIRED, WITHDRAWN = "open", "decided", "expired", "withdrawn"
EVENT = "task_closed"  # the event a task's closing sends its case, unless the opener names the step's own wait
TIMER = "task:"  # a task's deadline timer is named `task:<task id>`

store.register_schema("process.tasks", """
CREATE TABLE IF NOT EXISTS process_tasks (
    task_id         TEXT PRIMARY KEY,          -- <kind>:<subject>
    kind            TEXT NOT NULL,
    subject         TEXT NOT NULL,             -- what it is about, within its kind (a to-do item, a run, a step)
    case_id         TEXT,                      -- the case it belongs to (NULL: none)
    step_id         TEXT,
    event_kind      TEXT,                      -- the event its closing sends the case
    assignee        TEXT,                      -- a person's or a group's id (`local:<name>`); NULL: anyone
    due_at          REAL,                      -- epoch seconds; NULL: no deadline
    reason_required INTEGER NOT NULL,          -- a decision needs a reason (its kind's rule when it opened)
    result_ref      TEXT,                      -- the result version the decision is about (rule 3)
    detail          TEXT NOT NULL,             -- JSON: what the opener keeps with it (e.g. where it came from)
    status          TEXT NOT NULL,             -- open | decided | expired | withdrawn
    outcome         TEXT,                      -- JSON: the decision
    note            TEXT,                      -- the reason given
    round           INTEGER NOT NULL,          -- raised each time a closed task opens again
    opened_by       TEXT NOT NULL,             -- JSON actor
    closed_by       TEXT,                      -- JSON actor
    opened_at       TEXT NOT NULL,
    closed_at       TEXT
);
CREATE INDEX IF NOT EXISTS ix_process_tasks_open ON process_tasks(status, assignee);
CREATE INDEX IF NOT EXISTS ix_process_tasks_case ON process_tasks(case_id, status);
CREATE TABLE IF NOT EXISTS process_task_history (
    id      INTEGER PRIMARY KEY,
    task_id TEXT NOT NULL,
    round   INTEGER NOT NULL,
    kind    TEXT NOT NULL,                     -- opened | reopened | assigned | due_set | decided | expired | withdrawn
    actor   TEXT NOT NULL,                     -- JSON actor (rule 8)
    detail  TEXT NOT NULL,                     -- JSON
    at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_process_task_history_task ON process_task_history(task_id, id);
""")


class UnknownTask(KeyError):
    """No task with this id."""


class UnknownTaskKind(KeyError):
    """No task kind is registered under this name."""


class TaskClosed(ValueError):
    """The task is no longer open (decided, expired or withdrawn): a page that showed it open is out of date."""


class ReasonRequired(ValueError):
    """The task's kind asks for a reason with every decision."""


class StaleResult(ValueError):
    """The decision names another result version than the one the task is about (rule 3)."""


@dataclass(frozen=True)
class TaskKind:
    """A kind of human task: its `name` (the first part of its tasks' ids), the module that owns it, and whether a
    decision needs a reason."""

    name: str
    owner: str
    reason_required: bool = False


_KINDS: dict[str, TaskKind] = {}


def register_kind(kind: TaskKind) -> None:
    """Registers a task kind; its owner may register it again (a module loaded twice), another owner may not."""
    if ":" in kind.name:
        raise ValueError(f"a task kind's name has no ':' ({kind.name!r})")
    prior = _KINDS.get(kind.name)
    if prior is not None and prior.owner != kind.owner:
        raise ValueError(f"task kind {kind.name!r} is registered by {prior.owner}, not by {kind.owner}")
    _KINDS[kind.name] = kind


def kind_of(name: str) -> TaskKind:
    try:
        return _KINDS[name]
    except KeyError:
        raise UnknownTaskKind(name) from None


@dataclass(frozen=True)
class Task:
    task_id: str
    kind: str
    subject: str
    case_id: str | None
    step_id: str | None
    event_kind: str | None
    assignee: str | None
    due_at: float | None
    reason_required: bool
    result_ref: str | None
    detail: dict[str, Any]
    status: str
    outcome: Any
    note: str | None
    round: int
    opened_by: Actor
    closed_by: Actor | None
    opened_at: str
    closed_at: str | None


def task_id(kind: str, subject: str) -> str:
    return f"{kind}:{subject}"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _task(row: sqlite3.Row) -> Task:
    return Task(
        task_id=row["task_id"], kind=row["kind"], subject=row["subject"], case_id=row["case_id"],
        step_id=row["step_id"], event_kind=row["event_kind"], assignee=row["assignee"],
        due_at=None if row["due_at"] is None else float(row["due_at"]), reason_required=bool(row["reason_required"]),
        result_ref=row["result_ref"], detail=json.loads(row["detail"]), status=row["status"],
        outcome=None if row["outcome"] is None else json.loads(row["outcome"]), note=row["note"],
        round=int(row["round"]), opened_by=Actor.from_json(row["opened_by"]),
        closed_by=None if row["closed_by"] is None else Actor.from_json(row["closed_by"]),
        opened_at=row["opened_at"], closed_at=row["closed_at"])


# --- reading ----------------------------------------------------------------------------------------------------------


def task_in(c: sqlite3.Connection, tid: str) -> Task | None:
    row = c.execute("SELECT * FROM process_tasks WHERE task_id=?", (tid,)).fetchone()
    return None if row is None else _task(row)


def get(tid: str) -> Task | None:
    with store.connect() as c:
        return task_in(c, tid)


def open_tasks(assignee: str | None = None, *, kind: str | None = None) -> list[Task]:
    """The open tasks, oldest first; with `assignee` only that person's or group's, with `kind` only that kind's."""
    sql, args = "SELECT * FROM process_tasks WHERE status=?", [OPEN]
    if assignee is not None:
        sql, args = sql + " AND assignee=?", [*args, assignee]
    if kind is not None:
        sql, args = sql + " AND kind=?", [*args, kind]
    with store.connect() as c:
        return [_task(r) for r in c.execute(sql + " ORDER BY opened_at, task_id", args)]


def of_case(c: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    """The case's tasks (each in its current round), for the case's state."""
    return [{k: r[k] for k in ("task_id", "step_id", "status", "assignee", "due_at", "round")}
            for r in c.execute("SELECT * FROM process_tasks WHERE case_id=? ORDER BY opened_at, task_id", (case_id,))]


def history(tid: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        return [{"round": r["round"], "kind": r["kind"], "actor": json.loads(r["actor"])["id"],
                 "detail": json.loads(r["detail"]), "at": r["at"]}
                for r in c.execute("SELECT * FROM process_task_history WHERE task_id=? ORDER BY id", (tid,))]


# --- writing inside a transaction -------------------------------------------------------------------------------------


def _record(c: sqlite3.Connection, task: Task, rnd: int, kind: str, actor: Actor, detail: dict[str, Any]) -> None:
    """The task's history row, and the case's when the task is in one (rule 4)."""
    c.execute("INSERT INTO process_task_history(task_id, round, kind, actor, detail, at) VALUES (?,?,?,?,?,?)",
              (task.task_id, rnd, kind, actor.as_json(), _json(detail), _now()))
    if task.case_id is not None:
        cases.record(c, task.case_id, task.step_id, f"task_{kind}", actor, {"task": task.task_id, "round": rnd, **detail})


def _require(c: sqlite3.Connection, tid: str) -> Task:
    task = task_in(c, tid)
    if task is None:
        raise UnknownTask(tid)
    return task


def _require_open(c: sqlite3.Connection, tid: str) -> Task:
    task = _require(c, tid)
    if task.status != OPEN:
        raise TaskClosed(f"task {tid} is {task.status}")
    return task


def _check_assignee(assignee: str | None) -> None:
    if assignee is not None and ":" not in assignee:
        raise ValueError(f"an assignee is a person's or a group's id with its namespace, not {assignee!r}")


def _check_step(c: sqlite3.Connection, case_id: str, step_id: str, waits: str) -> None:
    """A task in a case is a running step's wait, and the step's kind takes the event its closing sends."""
    row = cases.require_open(c, case_id)
    state = cases.step_row(c, case_id, step_id)["state"]
    if state != cases.RUNNING:
        raise cases.StepStateError(f"step {step_id!r} of case {case_id} is {state}: a task is a running step's wait")
    kind = cases.definition_of(row).step(step_id).kind
    if waits not in kinds.of(kind).events:
        raise cases.UnknownEvent(f"step kind {kind!r} takes no {waits!r} events")


def _timer_id(task: Task) -> str:
    return timers.timer_id(str(task.case_id), str(task.step_id), TIMER + task.task_id)


def open_in(c: sqlite3.Connection, kind: str, subject: str, opened_by: Actor, *, assignee: str | None = None,
            due_at: float | None = None, case_id: str | None = None, step_id: str | None = None, waits: str = EVENT,
            result_ref: str | None = None, detail: dict[str, Any] | None = None) -> str:
    """Opens the task of `kind` about `subject`: "opened"; "exists" when it is open (nothing changes); "reopened" when
    it was closed: a new round, with what this call gives. In a case, the running step `step_id` waits for it (for the
    event `waits`, which the step's kind must take), and its deadline is armed as the case's timer."""
    registered = kind_of(kind)
    _check_assignee(assignee)
    if (case_id is None) != (step_id is None):
        raise ValueError("a task in a case names its step, and only a task in a case does")
    tid = task_id(kind, subject)
    hooks.authorize(opened_by, "open_task", case_id)
    prior = task_in(c, tid)
    if prior is not None and prior.status == OPEN:
        return "exists"
    if case_id is not None and step_id is not None:
        _check_step(c, case_id, step_id, waits)
    rnd = 1 if prior is None else prior.round + 1
    values = (kind, subject, case_id, step_id, waits if case_id else None, assignee, due_at,
              int(registered.reason_required), result_ref, _json(detail or {}), OPEN, rnd, opened_by.as_json(), _now())
    c.execute("INSERT INTO process_tasks(task_id, kind, subject, case_id, step_id, event_kind, assignee, due_at,"
              " reason_required, result_ref, detail, status, round, opened_by, opened_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
              " ON CONFLICT(task_id) DO UPDATE SET kind=excluded.kind, subject=excluded.subject, case_id=excluded.case_id,"
              " step_id=excluded.step_id, event_kind=excluded.event_kind, assignee=excluded.assignee,"
              " due_at=excluded.due_at, reason_required=excluded.reason_required, result_ref=excluded.result_ref,"
              " detail=excluded.detail, status=excluded.status, outcome=NULL, note=NULL, round=excluded.round,"
              " opened_by=excluded.opened_by, closed_by=NULL, opened_at=excluded.opened_at, closed_at=NULL",
              (tid, *values))
    task = _require(c, tid)
    what = "opened" if prior is None else "reopened"
    _record(c, task, rnd, what, opened_by, {"assignee": assignee, "due_at": due_at, "result_ref": result_ref})
    if case_id is not None and step_id is not None:
        cases.wait(c, case_id, step_id, waits, opened_by, detail={"task": tid})
        if due_at is not None:
            timers.arm(c, case_id, step_id, TIMER + tid, due_at)
    return what


def _close(c: sqlite3.Connection, task: Task, status: str, actor: Actor, detail: dict[str, Any], *,
           outcome: Any = None, note: str | None = None, notify: bool = True) -> None:
    """Closes the open task; in a case its deadline timer is cancelled, and (with `notify`, while the case is open) the
    case receives the closing event, all in the caller's transaction."""
    c.execute("UPDATE process_tasks SET status=?, outcome=?, note=?, closed_by=?, closed_at=? WHERE task_id=? AND status=?",
              (status, None if outcome is None else _json(outcome), note, actor.as_json(), _now(), task.task_id, OPEN))
    _record(c, task, task.round, status, actor, detail)
    if task.case_id is None or task.step_id is None:
        return
    if status != EXPIRED:  # an expired task's timer is the one firing
        timers.close(c, _timer_id(task), timers.CANCELLED, f"task {status}")
    if notify and cases.case_row(c, task.case_id)["status"] == cases.OPEN:
        cases.send_event_in(c, task.case_id, f"{task.task_id}#{task.round}", str(task.event_kind),
                            {"task": task.task_id, "round": task.round, "status": status}, actor, step_id=task.step_id)


def decide_in(c: sqlite3.Connection, tid: str, actor: Actor, *, outcome: Any = None, note: str | None = None,
              result_ref: str | None = None) -> int:
    """A person decides the open task (once; `TaskClosed` after that), with a reason where its kind asks for one, on the
    result version it is about (`StaleResult` for another). Returns the task's round."""
    task = _require(c, tid)
    hooks.authorize(actor, "decide_task", task.case_id)
    task = _require_open(c, tid)
    note = note.strip() if note and note.strip() else None
    if task.reason_required and note is None:
        raise ReasonRequired(f"a decision on task {tid} needs a reason")
    if result_ref is not None and task.result_ref is not None and result_ref != task.result_ref:
        raise StaleResult(f"task {tid} is about {task.result_ref}, not {result_ref}")
    _close(c, task, DECIDED, actor, {"outcome": outcome, "note": note, "result_ref": result_ref or task.result_ref},
           outcome=outcome, note=note)
    return task.round


def withdraw_in(c: sqlite3.Connection, tid: str, actor: Actor, *, note: str | None = None, notify: bool = True) -> bool:
    """What the open task was about went away (or a machine settled it): withdrawn; False when it was not open."""
    task = _require(c, tid)
    hooks.authorize(actor, "withdraw_task", task.case_id)
    if task.status != OPEN:
        return False
    _close(c, task, WITHDRAWN, actor, {"note": note} if note else {}, note=note, notify=notify)
    return True


def expire_in(c: sqlite3.Connection, tid: str, actor: Actor) -> bool:
    """The open task's deadline passed (the engine, when its timer fires): expired; False when it was not open."""
    task = _require(c, tid)
    if task.status != OPEN:
        return False
    _close(c, task, EXPIRED, actor, {"due_at": task.due_at})
    return True


def assign_in(c: sqlite3.Connection, tid: str, assignee: str | None, actor: Actor) -> bool:
    """The open task goes to `assignee` (None: anyone); False when it was assigned so already."""
    _check_assignee(assignee)
    task = _require(c, tid)
    hooks.authorize(actor, "assign_task", task.case_id)
    task = _require_open(c, tid)
    if task.assignee == assignee:
        return False
    c.execute("UPDATE process_tasks SET assignee=? WHERE task_id=?", (assignee, tid))
    _record(c, task, task.round, "assigned", actor, {"from": task.assignee, "to": assignee})
    return True


def set_due_in(c: sqlite3.Connection, tid: str, due_at: float | None, actor: Actor) -> None:
    """The open task's deadline (None: none); in a case its timer is armed again or cancelled with it (rule 7)."""
    task = _require(c, tid)
    hooks.authorize(actor, "set_task_due", task.case_id)
    task = _require_open(c, tid)
    c.execute("UPDATE process_tasks SET due_at=? WHERE task_id=?", (due_at, tid))
    _record(c, task, task.round, "due_set", actor, {"from": task.due_at, "to": due_at})
    if task.case_id is not None and task.step_id is not None:
        if due_at is None:
            timers.close(c, _timer_id(task), timers.CANCELLED, "deadline removed")
        else:
            timers.arm(c, task.case_id, task.step_id, TIMER + tid, due_at)


def decide(tid: str, actor: Actor, *, outcome: Any = None, note: str | None = None,
           result_ref: str | None = None) -> int:
    """`decide_in` in a transaction of its own."""
    with cases.transaction() as c:
        return decide_in(c, tid, actor, outcome=outcome, note=note, result_ref=result_ref)


# --- the engine's side ------------------------------------------------------------------------------------------------


def is_timer(timer: timers.Timer) -> bool:
    """Whether the timer is a task's deadline."""
    return timer.name.startswith(TIMER)


def of_timer(timer: timers.Timer) -> str:
    """The id of the task whose deadline the timer is."""
    return timer.name[len(TIMER):]


def _withdraw_left(c: sqlite3.Connection, case_id: str, step_id: str | None, actor: Actor) -> None:
    """The case closed (`step_id` None) or the step stopped running: its open tasks are withdrawn, without an event."""
    sql, args = "SELECT * FROM process_tasks WHERE case_id=? AND status=?", [case_id, OPEN]
    if step_id is not None:
        sql, args = sql + " AND step_id=?", [*args, step_id]
    because = "the case closed" if step_id is None else "the step moved on"
    for row in c.execute(sql, args).fetchall():
        _close(c, _task(row), WITHDRAWN, actor, {"note": because}, note=because, notify=False)


cases.on_leave(_withdraw_left)
