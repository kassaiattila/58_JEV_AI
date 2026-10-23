"""218 (plan G-process-core P3b): the decision trace - which rule decided, with what, in which version.

Plain-language summary: a machine decision (this document is an invoice, this field waits for a person, this step's
estimate is over its budget) is recorded in one shared trace, in the same transaction as the decision's result: the
decision point, what it was about, what the rule read (probabilities, differences, amounts), what it decided, and which
rule files and keys it used, each with its version and content fingerprint, together with the process's calculation
snapshot (`jav.core.rulebook`). So years later it can be told which rule of which version decided, with what input, and
a changed rule can be tried on the stored inputs without processing anything again (plan P3d).

- `register(point)`: a decision point: its code, what it decides and what it is not for, its owner module, the rule
  files it reads and its rule: a pure function of the stored inputs that gives the stored outcome (`replay`).
- `record_in(c, point, subject=, inputs=, outcome=, keys=, ...)`: one trace row in the caller's write transaction.
- `rows(...)`, `replay(row)`: reading the trace back, and the rule run again on a row's inputs.

A person's decision has its own journal (`jav.core.decisions`); this trace is the machine's. Measurements and replays
write into their own copy of the store, so they never grow the live trace.

Layer: shared core; it imports only the store and the calculation snapshot. The owners register their points.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from jav.core import rulebook, store
from jav.core.clock import utc_stamp as _now

store.register_schema("trace", """
CREATE TABLE IF NOT EXISTS decision_trace (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    point        TEXT NOT NULL,     -- a registered decision point (`register`)
    subject_kind TEXT NOT NULL,     -- what it decided about: a document, a datapoint, an email, a workflow step ...
    subject_id   TEXT NOT NULL,
    run_id       TEXT,              -- the run it was made in
    case_id      TEXT,              -- the case it was made in
    inputs       TEXT NOT NULL,     -- JSON: what the rule read
    inputs_sha   TEXT NOT NULL,
    outcome      TEXT NOT NULL,     -- JSON: what it decided (the rule's value for the inputs)
    rules        TEXT NOT NULL,     -- JSON: [{file, version, sha256, keys}] the rule files and keys it used
    snapshot_id  TEXT NOT NULL,     -- the calculation snapshot of the process that decided
    at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_decision_trace_subject ON decision_trace(subject_kind, subject_id, id);
CREATE INDEX IF NOT EXISTS ix_decision_trace_point ON decision_trace(point, id);
CREATE INDEX IF NOT EXISTS ix_decision_trace_run ON decision_trace(run_id);
""")


class UnknownPoint(ValueError):
    """No module registered this decision point, or it names a rule file the point does not read."""


@dataclass(frozen=True)
class Point:
    """A machine decision point. `rule(inputs)` is the pure function whose value for the stored inputs is the stored
    outcome; `files` are the rule files under `configs/` it may read."""

    code: str
    what: str
    not_for: str
    owner: str
    files: tuple[str, ...]
    rule: Callable[[Mapping[str, Any]], Any]


_POINTS: dict[str, Point] = {}


def register(point: Point) -> None:
    """The same point again adds nothing; another one of the same code is an error."""
    known = _POINTS.get(point.code)
    if known is not None and known != point:
        raise ValueError(f"decision point {point.code!r} is registered already by {known.owner}")
    _POINTS[point.code] = point


def points() -> list[Point]:
    """In the order they were registered."""
    return list(_POINTS.values())


def point(code: str) -> Point:
    try:
        return _POINTS[code]
    except KeyError:
        raise UnknownPoint(f"no module registered the decision point {code!r}") from None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _rules(p: Point, keys: Mapping[str, Iterable[str]], snapshot: rulebook.Snapshot) -> list[dict[str, Any]]:
    if unknown := sorted(set(keys) - set(p.files)):
        raise UnknownPoint(f"the decision point {p.code} reads no rule file {unknown}")
    out = []
    for name in sorted(keys):
        found = snapshot.files.get(name)
        out.append({"file": name, "version": found.version if found else None, "sha256": found.sha256 if found else None,
                    "keys": sorted(set(keys[name]))})
    return out


def record_in(c: sqlite3.Connection, code: str, *, subject: tuple[str, str], inputs: Mapping[str, Any], outcome: Any,
              keys: Mapping[str, Iterable[str]], run_id: str | None = None, case_id: str | None = None) -> int:
    """One trace row in the caller's write transaction, so the decision's result and its trace are written together or
    not at all. `keys`: the rule keys it used, by rule file (each one the point reads). Returns the row's id."""
    p = point(code)
    snapshot = rulebook.current()
    text = _json(dict(inputs))
    cur = c.execute(
        "INSERT INTO decision_trace(point, subject_kind, subject_id, run_id, case_id, inputs, inputs_sha, outcome, rules,"
        " snapshot_id, at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (code, subject[0], subject[1], run_id, case_id, text, hashlib.sha256(text.encode("utf-8")).hexdigest(),
         _json(outcome), _json(_rules(p, keys, snapshot)), rulebook.store_in(c, snapshot), _now()))
    return int(cur.lastrowid)


def _row(r: sqlite3.Row) -> dict[str, Any]:
    out = dict(r)
    for name in ("inputs", "outcome", "rules"):
        out[name] = json.loads(out[name])
    return out


def rows(*, point: str | None = None, subject: tuple[str, str] | None = None, run_id: str | None = None,
         case_id: str | None = None, last: int | None = None) -> list[dict[str, Any]]:
    """The trace rows matching every filter given, oldest first (with `last`: only the latest that many)."""
    where, args = [], []
    for column, value in (("point", point), ("run_id", run_id), ("case_id", case_id)):
        if value is not None:
            where.append(f"{column}=?")
            args.append(value)
    if subject is not None:
        where.append("subject_kind=? AND subject_id=?")
        args += list(subject)
    sql = "SELECT * FROM decision_trace" + (f" WHERE {' AND '.join(where)}" if where else "") + " ORDER BY id DESC"
    if last is not None:
        sql += f" LIMIT {int(last)}"
    with store.connect() as c:
        return [_row(r) for r in reversed(c.execute(sql, args).fetchall())]


def replay(row: Mapping[str, Any]) -> Any:
    """The point's rule run again on the row's stored inputs (its value equals the stored outcome while the rule's code
    is the same)."""
    return json.loads(_json(point(row["point"]).rule(row["inputs"])))
