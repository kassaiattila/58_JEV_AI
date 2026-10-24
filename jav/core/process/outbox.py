"""Outgoing handovers of the process core (213, P1a; rule 4 of plan 212 P0).

Plain-language summary: a message a case sends to another system is first recorded with the case, in the transaction
of the business change, and only then sent, always under the same id. A handover found already sent without an answer
(its sender stopped) or whose answer was lost becomes uncertain: it is never sent again by itself, and the step waits
for a person to settle it (after asking the other system) as acknowledged or failed.

States: recorded -> sent -> acknowledged | uncertain | failed; uncertain -> acknowledged | failed (by a person).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from jav.core import store
from jav.core.clock import utc_stamp as _now
from jav.core import access, observability
from jav.core.identity import Actor
from jav.core.process import cases

__all__ = [  # 229 (SZ1b): what code outside the process core may use; the rest is the core's own
    "RECORDED", "SENT", "ACKNOWLEDGED", "UNCERTAIN", "FAILED", "SETTLEMENT", "Uncertain", "Refused",
    "UnknownHandover", "NotUncertain", "get", "of_case", "record", "send", "settle",
]

log = logging.getLogger(__name__)

RECORDED, SENT, ACKNOWLEDGED, UNCERTAIN, FAILED = "recorded", "sent", "acknowledged", "uncertain", "failed"
SETTLEMENT = "settlement"  # what a step waits for while its handover is uncertain

store.register_schema("process.outbox", """
CREATE TABLE IF NOT EXISTS process_outbox (
    handover_id TEXT PRIMARY KEY,
    case_id     TEXT NOT NULL,
    step_id     TEXT NOT NULL,
    target      TEXT NOT NULL,                -- the receiving system
    payload     TEXT NOT NULL,                -- JSON
    status      TEXT NOT NULL,                -- recorded | sent | acknowledged | uncertain | failed
    attempts    INTEGER NOT NULL DEFAULT 0,
    receipt     TEXT,                         -- JSON: the receiver's answer
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_process_outbox_case ON process_outbox(case_id);
""")


class Uncertain(Exception):
    """The receiver may have the handover, but its answer is unknown (a timeout, a lost reply)."""


class Refused(Exception):
    """The receiver answered that it did not take the handover."""


class UnknownHandover(KeyError):
    """No handover with this id."""


class NotUncertain(ValueError):
    """Only an uncertain handover is settled by a person, as acknowledged or failed."""


def _row(c: sqlite3.Connection, handover_id: str) -> dict[str, Any]:
    row = c.execute("SELECT * FROM process_outbox WHERE handover_id=?", (handover_id,)).fetchone()
    if row is None:
        raise UnknownHandover(handover_id)
    return {**dict(row), "payload": json.loads(row["payload"])}


def get(handover_id: str) -> dict[str, Any] | None:
    with store.connect() as c:
        try:
            return _row(c, handover_id)
        except UnknownHandover:
            return None


def of_case(c: sqlite3.Connection, case_id: str) -> list[dict[str, Any]]:
    return [{k: r[k] for k in ("handover_id", "step_id", "target", "status", "attempts", "error")}
            for r in c.execute("SELECT * FROM process_outbox WHERE case_id=? ORDER BY created_at, handover_id", (case_id,))]


def record(c: sqlite3.Connection, case_id: str, step_id: str, target: str, payload: dict[str, Any], actor: Actor, *,
           handover_id: str | None = None) -> str:
    """Records a handover with the case, in the caller's transaction; returns its id, the same on every repeat."""
    handover_id = handover_id or f"{case_id}:{step_id}:{target}"
    if c.execute("SELECT 1 FROM process_outbox WHERE handover_id=?", (handover_id,)).fetchone():
        return handover_id
    cases.require_open(c, case_id)
    now = _now()
    c.execute("INSERT INTO process_outbox(handover_id, case_id, step_id, target, payload, status, created_at, updated_at)"
              " VALUES (?,?,?,?,?,?,?,?)",
              (handover_id, case_id, step_id, target, json.dumps(payload, sort_keys=True, ensure_ascii=False),
               RECORDED, now, now))
    cases.record(c, case_id, step_id, "handover_recorded", actor, {"handover_id": handover_id, "target": target})
    return handover_id


def _set(c: sqlite3.Connection, row: dict[str, Any], status: str, actor: Actor, *, error: str | None = None,
         receipt: Any = None) -> None:
    c.execute("UPDATE process_outbox SET status=?, error=?, receipt=?, updated_at=? WHERE handover_id=?",
              (status, error, json.dumps(receipt, sort_keys=True) if receipt is not None else None, _now(),
               row["handover_id"]))
    cases.record(c, row["case_id"], row["step_id"], f"handover_{status}", actor,
                 {"handover_id": row["handover_id"], **({"error": error} if error else {})})
    if cases.case_row(c, row["case_id"])["status"] != cases.OPEN:
        return
    step = cases.step_row(c, row["case_id"], row["step_id"])
    if status == UNCERTAIN and step["state"] == cases.RUNNING:
        cases.wait(c, row["case_id"], row["step_id"], SETTLEMENT, actor, detail={"handover_id": row["handover_id"]})
    elif status in (ACKNOWLEDGED, FAILED) and step["waiting_for"] == SETTLEMENT:
        cases.end_wait(c, row["case_id"], row["step_id"], actor, f"handover {status}")


def send(handover_id: str, deliver: Callable[[str, dict[str, Any]], Any], actor: Actor) -> str:
    """Sends a recorded handover once, under its id (`deliver(handover_id, payload)` returns the receipt), and returns
    its state. A handover already `sent` lost its sender before the answer: it becomes uncertain and is not sent again.
    `deliver` raising `Refused` makes it failed; any other error after the send began makes it uncertain."""
    with cases.transaction() as c:
        row = _row(c, handover_id)
        if row["status"] == SENT:
            _set(c, row, UNCERTAIN, actor, error="the earlier send has no answer")
            return UNCERTAIN
        if row["status"] != RECORDED:
            return str(row["status"])
        c.execute("UPDATE process_outbox SET status=?, attempts=attempts+1, updated_at=? WHERE handover_id=?",
                  (SENT, _now(), handover_id))
        cases.record(c, row["case_id"], row["step_id"], "handover_sent", actor, {"handover_id": handover_id})
    try:
        with observability.measured(f"handover:{row['target']}"):
            receipt = deliver(handover_id, row["payload"])
    except Refused as exc:
        return _finish(handover_id, FAILED, actor, error=str(exc)[:1000])
    except Exception as exc:  # noqa: BLE001 - the send began: whatever went wrong, the outcome is unknown
        log.warning("handover %s: no answer: %s", handover_id, exc)
        return _finish(handover_id, UNCERTAIN, actor, error=f"{type(exc).__name__}: {exc}"[:1000])
    return _finish(handover_id, ACKNOWLEDGED, actor, receipt=receipt)


def _finish(handover_id: str, status: str, actor: Actor, *, error: str | None = None, receipt: Any = None) -> str:
    """The send's outcome; a handover settled meanwhile keeps its settlement."""
    with cases.transaction() as c:
        row = _row(c, handover_id)
        if row["status"] != SENT:
            return str(row["status"])
        _set(c, row, status, actor, error=error, receipt=receipt)
        return status


def settle(handover_id: str, outcome: str, actor: Actor, *, note: str | None = None) -> str:
    """A person settles an uncertain handover as acknowledged or failed; the step waiting for it runs again."""
    if outcome not in (ACKNOWLEDGED, FAILED):
        raise NotUncertain(f"a handover is settled as acknowledged or failed, not {outcome!r}")
    with cases.transaction() as c:
        row = _row(c, handover_id)
        access.authorize(actor, "settle_handover", row["case_id"])
        if row["status"] != UNCERTAIN:
            raise NotUncertain(f"handover {handover_id} is {row['status']}, not uncertain")
        _set(c, row, outcome, actor, error=note or "settled by a person")
        return outcome
