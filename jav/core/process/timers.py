"""Durable timers of the process core (213, P1a; rule 7 of plan 212 P0).

Plain-language summary: a step that waits until a time (a deadline, a reminder, a retry) arms a timer in the store, in
the same transaction as its wait, so a restart never loses it. A timer has a stable id (its case, step and name):
arming it again moves the same timer. It fires once, under its case's claim; it is cancelled in the transaction of the
event that ends the wait first, so an event and a deadline never both win. A timer that fires on a step that is no
longer waiting changes nothing but leaves a history row (the engine's `_fire`).

Every function here takes the caller's connection inside its write transaction.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from jav.core import store
from jav.core.clock import utc_stamp as _now

ARMED, FIRED, CANCELLED = "armed", "fired", "cancelled"

store.register_schema("process.timers", """
CREATE TABLE IF NOT EXISTS process_timers (
    timer_id  TEXT PRIMARY KEY,               -- <case>:<step>:<name>; arming it again moves the same timer
    case_id   TEXT NOT NULL,
    step_id   TEXT NOT NULL,
    name      TEXT NOT NULL,
    due_at    REAL NOT NULL,                  -- epoch seconds
    status    TEXT NOT NULL,                  -- armed | fired | cancelled
    effect    TEXT,                           -- what firing or cancelling it did
    armed_at  TEXT NOT NULL,
    closed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_process_timers_due ON process_timers(status, due_at);
CREATE INDEX IF NOT EXISTS ix_process_timers_case ON process_timers(case_id, status);
""")


@dataclass(frozen=True)
class Timer:
    timer_id: str
    case_id: str
    step_id: str
    name: str
    due_at: float


def timer_id(case_id: str, step_id: str, name: str) -> str:
    return f"{case_id}:{step_id}:{name}"


def _timer(row: sqlite3.Row) -> Timer:
    return Timer(row["timer_id"], row["case_id"], row["step_id"], row["name"], float(row["due_at"]))


def arm(c: sqlite3.Connection, case_id: str, step_id: str, name: str, due_at: float) -> Timer:
    tid = timer_id(case_id, step_id, name)
    c.execute("INSERT INTO process_timers(timer_id, case_id, step_id, name, due_at, status, armed_at)"
              " VALUES (?,?,?,?,?,?,?) ON CONFLICT(timer_id) DO UPDATE SET due_at=excluded.due_at, status=excluded.status,"
              " effect=NULL, armed_at=excluded.armed_at, closed_at=NULL",
              (tid, case_id, step_id, name, due_at, ARMED, _now()))
    return Timer(tid, case_id, step_id, name, due_at)


def close(c: sqlite3.Connection, tid: str, status: str, effect: str | None) -> bool:
    """Fires or cancels an armed timer; False when it was no longer armed."""
    return bool(c.execute("UPDATE process_timers SET status=?, effect=?, closed_at=? WHERE timer_id=? AND status=?",
                          (status, effect, _now(), tid, ARMED)).rowcount)


def set_effect(c: sqlite3.Connection, tid: str, effect: str) -> None:
    c.execute("UPDATE process_timers SET effect=? WHERE timer_id=?", (effect, tid))


def cancel(c: sqlite3.Connection, case_id: str, *, effect: str, step_id: str | None = None) -> int:
    """Cancels the case's armed timers (or one step's); returns how many."""
    sql = "UPDATE process_timers SET status=?, effect=?, closed_at=? WHERE case_id=? AND status=?"
    args: list[Any] = [CANCELLED, effect, _now(), case_id, ARMED]
    if step_id is not None:
        sql += " AND step_id=?"
        args.append(step_id)
    return c.execute(sql, args).rowcount


def due(c: sqlite3.Connection, case_id: str, now: float) -> list[Timer]:
    return [_timer(r) for r in c.execute(
        "SELECT * FROM process_timers WHERE case_id=? AND status=? AND due_at<=? ORDER BY due_at, timer_id",
        (case_id, ARMED, now))]


def is_armed(c: sqlite3.Connection, tid: str) -> bool:
    return c.execute("SELECT 1 FROM process_timers WHERE timer_id=? AND status=?", (tid, ARMED)).fetchone() is not None


def of_case(c: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(
        "SELECT timer_id, step_id, name, due_at, status, effect FROM process_timers WHERE case_id=? ORDER BY timer_id",
        (case_id,))]
