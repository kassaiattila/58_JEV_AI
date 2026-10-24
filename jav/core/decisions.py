"""The shared decision handler (187, plan G-full-move T2c): one way to record a person's decision, of any kind.

Plain-language summary: people decide many kinds of things: which task of an email to accept, whether two invoices
are copies, which of two statements stays valid, where an emailed document goes, which template a package's workbook
uses, how a bank line is reconciled. Each kind keeps its current decisions in its own table, as before. What they share
comes from here. Every change goes into one decision journal in the same transaction, so no earlier decision is lost.
Each decision has a state that a page sends back with a change, so a change made on a stale page is refused. And the
checks every kind needs (an approved run's decisions are frozen, and so are those made in another approved run) are in
one place.

- `register(kind)`: a decision kind (its name, the actions it records, its owner module); `kinds()`.
- `record(c, kind, key, action, ...)`: one journal row, written inside the owner's write transaction; returns the
  decision's new state.
- `state(c, kind, key)`, `states(c, kind, keys)`: a decision's state, the id of its latest journal row (0 before
  any); `check(c, kind, key, expected)`: a state other than the one the page read is `RevisionConflict` (227: here, the
  work package's `work.RevisionConflict` is the same class).
- `run_state(c, run_id)`: the latest journal row of any decision made on a run (0: none), for the run's cache marks.
- `package_state(c, workpackage_id, kinds)`, `check_package(...)`: the same for every decision of the given kinds in a
  package, for a page that changes many decisions of one package (a reconciliation).
- `history(kind, key)`: every journal row of a decision, oldest first.
- `run_approved(c, run_id)`, `decided_in_approved_run(c, earlier_run_id, run_id)`: the shared checks inside the write
  transaction; the caller raises its own message.
- `one_at_a_time(kind, scope)`: within the service, one change of a scope at a time, for a kind whose change does part
  of its work in transactions of its own (the email routing adds documents to packages and makes new ones).

The kinds' own tables keep their structure, so the reviewed version of a run (`corrections.review_version`) and every
stored approval stay the same. A decision recorded before 187 has no journal row; its state is 0 until it changes.

Layer: shared service (business module). It reads the runs' approvals; the owners register their kinds, so this
module imports no domain module.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from jav.core import store
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now

class RevisionConflict(RuntimeError):
    """The request was based on an earlier revision; the caller should reload the state (in the UI: 409, the working
    copy is kept). 227 (plan R3c): the shared core's, so this module needs no application module; the work package
    names it `work.RevisionConflict`."""


store.register_schema("decisions", """
CREATE TABLE IF NOT EXISTS decision_journal (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL,     -- a registered decision kind (`register`)
    key            TEXT NOT NULL,     -- the decision within its kind (a pair, a task of an email, a bank line ...)
    action         TEXT NOT NULL,     -- one of the kind's actions
    value          TEXT,              -- JSON: what the action recorded (NULL: nothing beyond the action)
    workpackage_id TEXT,              -- the package it was made in
    run_id         TEXT,              -- the run it was made on (NULL: a logic pack's decision)
    actor          TEXT NOT NULL,
    note           TEXT,
    at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS decision_journal_key ON decision_journal(kind, key, id);
CREATE INDEX IF NOT EXISTS decision_journal_run ON decision_journal(run_id, id);
""")


@dataclass(frozen=True)
class Kind:
    """A kind of decision: its `name` in the journal, the `actions` it records and the module that owns it."""
    name: str
    actions: tuple[str, ...]
    owner: str


_KINDS: dict[str, Kind] = {}
_CHUNK = 500  # stays under the SQLite parameter limit


def register(kind: Kind) -> None:
    """The same kind again adds nothing; another one of the same name is an error."""
    if not kind.actions:
        raise ValueError(f"decision kind {kind.name} records no action")
    if kind.name in _KINDS and _KINDS[kind.name] != kind:
        raise ValueError(f"decision kind {kind.name} is registered twice")
    _KINDS[kind.name] = kind


def kinds() -> list[Kind]:
    """In the order they were registered."""
    return list(_KINDS.values())


def record(c: sqlite3.Connection, kind: str, key: str, action: str, *, actor: str, value: Any = None,
           note: str | None = None, workpackage_id: str | None = None, run_id: str | None = None,
           at: str | None = None) -> int:
    """One journal row for a change of a decision, in the caller's write transaction (so the change and its journal
    row are written together or not at all). An unknown kind or action is a programming error (`ValueError`)."""
    registered = _KINDS.get(kind)
    if registered is None:
        raise ValueError(f"no module registered the decision kind {kind!r}")
    if action not in registered.actions:
        raise ValueError(f"the decision kind {kind} records no action {action!r}")
    cur = c.execute(
        "INSERT INTO decision_journal(kind, key, action, value, workpackage_id, run_id, actor, note, at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (kind, key, action, None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True),
         workpackage_id, run_id, actor, note, at or _now()))
    return int(cur.lastrowid)


def state(c: sqlite3.Connection, kind: str, key: str) -> int:
    row = c.execute("SELECT MAX(id) FROM decision_journal WHERE kind=? AND key=?", (kind, key)).fetchone()
    return int(row[0] or 0)


def states(c: sqlite3.Connection, kind: str, keys: Iterable[str]) -> dict[str, int]:
    """The state of each key (0 for a key without a journal row), read at once for a view."""
    wanted = sorted(set(keys))
    out = dict.fromkeys(wanted, 0)
    for start in range(0, len(wanted), _CHUNK):
        chunk = wanted[start:start + _CHUNK]
        for r in c.execute(f"SELECT key, MAX(id) FROM decision_journal WHERE kind=? AND key IN ({','.join('?' * len(chunk))})"
                           " GROUP BY key", (kind, *chunk)):
            out[r[0]] = int(r[1])
    return out


def check(c: sqlite3.Connection, kind: str, key: str, expected: int | None) -> None:
    """The page's state of the decision must still hold (None: the caller sent none, so nothing is compared)."""
    if expected is not None and state(c, kind, key) != expected:
        raise explained(RevisionConflict, "the decision was changed meanwhile; reload the page")


def package_state(c: sqlite3.Connection, workpackage_id: str, kinds: Iterable[str]) -> int:
    wanted = sorted(set(kinds))
    row = c.execute(f"SELECT MAX(id) FROM decision_journal WHERE workpackage_id=? AND kind IN ({','.join('?' * len(wanted))})",
                    (workpackage_id, *wanted)).fetchone()
    return int(row[0] or 0)


def check_package(c: sqlite3.Connection, workpackage_id: str, kinds: Iterable[str], expected: int | None) -> None:
    """The page's state of the package's decisions must still hold (None: nothing is compared)."""
    if expected is not None and package_state(c, workpackage_id, kinds) != expected:
        raise explained(RevisionConflict, "the decision was changed meanwhile; reload the page")


def run_state(c: sqlite3.Connection, run_id: str) -> int:
    row = c.execute("SELECT MAX(id) FROM decision_journal WHERE run_id=?", (run_id,)).fetchone()
    return int(row[0] or 0)


def history(kind: str, key: str, c: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    if c is None:
        with store.connect() as own:
            return history(kind, key, own)
    rows = [dict(r) for r in c.execute("SELECT * FROM decision_journal WHERE kind=? AND key=? ORDER BY id", (kind, key))]
    for r in rows:
        r["value"] = None if r["value"] is None else json.loads(r["value"])
    return rows


def run_approved(c: sqlite3.Connection, run_id: str | None) -> bool:
    """Whether the run is approved (a run that does not exist is not)."""
    if run_id is None:
        return False
    row = c.execute("SELECT approval FROM runs WHERE run_id=?", (run_id,)).fetchone()
    return row is not None and bool(row["approval"])


def decided_in_approved_run(c: sqlite3.Connection, earlier_run_id: str | None, run_id: str) -> bool:
    """Whether the decision's earlier state was recorded in another run that is approved by now: a later change would
    alter that run's reviewed version, so the decision is frozen."""
    return earlier_run_id is not None and earlier_run_id != run_id and run_approved(c, earlier_run_id)


_locks: dict[tuple[str, str], threading.Lock] = {}
_locks_guard = threading.Lock()


@contextmanager
def one_at_a_time(kind: str, scope: str) -> Iterator[None]:
    """The service runs one change of a kind's scope at a time; a second request waits for the first, then reads what
    it recorded."""
    with _locks_guard:
        lock = _locks.setdefault((kind, scope), threading.Lock())
    with lock:
        yield


__all__ = ["Kind", "check", "check_package", "decided_in_approved_run", "history", "kinds", "one_at_a_time",
           "package_state", "record", "register", "run_approved", "run_state", "state", "states"]
