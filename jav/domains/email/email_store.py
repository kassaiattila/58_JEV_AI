"""The email domain's tables, with their writers and readers (209, plan G-process-core R2c; until then in `jav/core/store.py`).

Plain-language summary: what the email flow stores of a message lives here: one row per message with its latest result
(`emails`), the result of each run that read it (`email_results`) and a person's decision on each task it proposed
(`email_task_decisions`). The tables are created with the domain's other tables when this module is loaded, and the shared
code reaches them only through the domain's registrations (`jav/domains/email/__init__.py`): "My work today", the
reviewed version of a run, the store summary and another domain's reading of an email item.

The columns, the writers' SQL and the readers' results are the ones the shared store had; a store written before 209
has the same tables.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from jav.core import store
from jav.core.clock import utc_stamp as _now

store.register_schema("emails", """
CREATE TABLE IF NOT EXISTS emails (
    message_id    TEXT PRIMARY KEY,
    mailbox       TEXT,
    sender        TEXT,
    subject       TEXT,
    received_at   TEXT,
    body_excerpt  TEXT,
    attachments   TEXT NOT NULL,             -- JSON: list of doc_ids
    intent        TEXT,
    intent_conf   REAL,
    signals       TEXT,                      -- JSON: the Noul signals
    next_flow     TEXT,
    run_id        TEXT,
    created_at    TEXT NOT NULL
);

-- 058 K5.1: the email result per run (by its flow id), as datapoints for the documents; the `emails` row stays the
-- message's latest result
CREATE TABLE IF NOT EXISTS email_results (
    run_id        TEXT PRIMARY KEY,          -- the item's flow id (<run>:<item>)
    message_id    TEXT NOT NULL,
    intent        TEXT,
    intent_conf   REAL,
    signals       TEXT,                      -- JSON
    next_flow     TEXT,
    attachments   TEXT NOT NULL,             -- JSON: the attachments with their detection (doc_id, doc_type, status)
    body          TEXT,                      -- JSON: the part of the email's text that was seen (emails.body_coverage)
    tasks         TEXT,                      -- JSON: 058 K5.3 the task proposal after the gate (NULL = not asked for)
    created_at    TEXT NOT NULL,
    folder        TEXT                       -- 149: 'sent' for a message read from the Sent Items folder, else NULL
);

-- 058 K5.3: a person's decision on a task proposal (one per proposal, the latest counts; 187: every change is also
-- in the decision journal, jav/core/decisions.py)
CREATE TABLE IF NOT EXISTS email_task_decisions (
    run_id        TEXT NOT NULL,             -- the email's flow id (email_results.run_id)
    task_index    INTEGER NOT NULL,
    decision      TEXT NOT NULL,             -- accepted | rejected
    actor         TEXT NOT NULL,
    note          TEXT,
    decided_at    TEXT NOT NULL,
    done_by       TEXT,                      -- 062: who marked the accepted task as done
    done_at       TEXT,
    PRIMARY KEY (run_id, task_index)
);
""")


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive columns on a store made before them."""
    # 062: manual "done" mark on an accepted task
    store.add_columns(conn, "email_task_decisions", {"done_by": "TEXT", "done_at": "TEXT"})
    store.add_columns(conn, "email_results", {
        "tasks": "TEXT",  # 058 K5.3: the task proposal next to the email result
        "folder": "TEXT",  # 149: a sent message has no intent; the result says why
    })


store.register_migration("emails", _migrate)


def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, default=str)


# --- writers ------------------------------------------------------------------------------


def upsert_email(
    *,
    message_id: str,
    mailbox: str | None,
    sender: str | None,
    subject: str | None,
    received_at: str | None,
    body_excerpt: str | None,
    attachments: list[dict[str, Any]],
    intent: str | None,
    intent_conf: float | None,
    signals: dict[str, float] | None,
    next_flow: str | None,
    run_id: str | None,
) -> None:
    """M3: one row per email; overwritten on a re-run (run_id shows which run it came from)."""
    with store.connect() as c:
        c.execute(
            "INSERT INTO emails(message_id, mailbox, sender, subject, received_at, body_excerpt, attachments, intent, intent_conf,"
            " signals, next_flow, run_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(message_id) DO UPDATE SET"
            "  mailbox=excluded.mailbox, sender=excluded.sender, subject=excluded.subject, received_at=excluded.received_at,"
            "  body_excerpt=excluded.body_excerpt, attachments=excluded.attachments, intent=excluded.intent,"
            "  intent_conf=excluded.intent_conf, signals=excluded.signals, next_flow=excluded.next_flow, run_id=excluded.run_id,"
            "  created_at=excluded.created_at",
            (message_id, mailbox, sender, subject, received_at, body_excerpt, _json(attachments), intent, intent_conf,
             _json(signals) if signals is not None else None, next_flow, run_id, _now()),
        )


def upsert_email_result(*, run_id: str, message_id: str, intent: str | None, intent_conf: float | None,
                        signals: dict[str, Any] | None, next_flow: str | None, attachments: list[dict[str, Any]],
                        body: dict[str, Any] | None, tasks: dict[str, Any] | None = None, folder: str = "inbox") -> None:
    """058 K5.1: the email result as the run's own row (a repeated run does not overwrite the earlier one); K5.3: the
    task proposal; 149: the mail folder, stored only for a sent message."""
    with store.connect() as c:
        c.execute("INSERT INTO email_results(run_id, message_id, intent, intent_conf, signals, next_flow, attachments, body, tasks, created_at, folder)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET message_id=excluded.message_id,"
                  " intent=excluded.intent, intent_conf=excluded.intent_conf, signals=excluded.signals, next_flow=excluded.next_flow,"
                  " attachments=excluded.attachments, body=excluded.body, tasks=excluded.tasks, created_at=excluded.created_at,"
                  " folder=excluded.folder",
                  (run_id, message_id, intent, intent_conf, _json(signals) if signals is not None else None, next_flow,
                   _json(attachments), _json(body) if body is not None else None, _json(tasks) if tasks is not None else None, _now(),
                   folder if folder == "sent" else None))


TASK_DECISIONS = ("accepted", "rejected")  # a person's decisions on an email's task proposal (175: the one list)


def email_task_decide(run_id: str, index: int, *, decision: str, actor: str, note: str | None,
                      c: sqlite3.Connection | None = None) -> None:
    """`c` (086, audit N02): write inside the caller's transaction (which checks the approval first)."""
    if decision not in TASK_DECISIONS:
        raise ValueError(f"unknown decision: {decision}")
    if c is None:
        with store.connect() as own:
            _email_task_decide(own, run_id, index, decision=decision, actor=actor, note=note)
    else:
        _email_task_decide(c, run_id, index, decision=decision, actor=actor, note=note)


def _email_task_decide(c: sqlite3.Connection, run_id: str, index: int, *, decision: str, actor: str, note: str | None) -> None:
    c.execute("INSERT INTO email_task_decisions(run_id, task_index, decision, actor, note, decided_at) VALUES (?,?,?,?,?,?)"
              " ON CONFLICT(run_id, task_index) DO UPDATE SET decision=excluded.decision, actor=excluded.actor,"
              " note=excluded.note, decided_at=excluded.decided_at,"
              # 062: rejecting also clears the done mark (only an accepted task can be done)
              " done_by=CASE WHEN excluded.decision='accepted' THEN done_by END,"
              " done_at=CASE WHEN excluded.decision='accepted' THEN done_at END", (run_id, index, decision, actor, note, _now()))


def email_task_done(run_id: str, index: int, *, actor: str, done: bool, c: sqlite3.Connection | None = None) -> bool:
    """062: marks an accepted task as done (or undoes it); False if the task is not accepted. `c` (187): inside the
    caller's transaction, with its journal row."""
    if c is None:
        with store.connect() as own:
            return email_task_done(run_id, index, actor=actor, done=done, c=own)
    cur = c.execute("UPDATE email_task_decisions SET done_by=?, done_at=? WHERE run_id=? AND task_index=? AND decision='accepted'",
                    (actor if done else None, _now() if done else None, run_id, index))
    return cur.rowcount == 1


# --- readers ------------------------------------------------------------------------------


def email_task_decisions(run_id: str) -> dict[int, dict[str, Any]]:
    with store.connect() as c:
        return {r["task_index"]: dict(r) for r in c.execute("SELECT * FROM email_task_decisions WHERE run_id=?", (run_id,))}


def email_result(run_id: str) -> dict[str, Any] | None:
    """The email result of one flow run (None if the run has not saved it yet, or it predates 058)."""
    with store.connect() as c:
        row = c.execute("SELECT * FROM email_results WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    for k in ("signals", "attachments", "body", "tasks"):
        out[k] = json.loads(out[k]) if out.get(k) is not None else None
    return out


# --- what the shared code reads through the domain's registrations ----------------------------------------------------

def task_rows(run_id: str, items: list[str], c: sqlite3.Connection) -> list[Any]:
    """086: the decisions on an email's task proposals (the flow runs of a run are `<run_id>:<item_id>`): the reviewed
    version's part (`jav/core/activity_kinds.py`; until 209 in `jav/app/corrections.py`)."""
    prefix = f"{run_id}:"
    return [[d["run_id"], d["task_index"], d["decision"]] for d in c.execute(
        "SELECT run_id, task_index, decision FROM email_task_decisions WHERE substr(run_id, 1, ?) = ?"
        " ORDER BY run_id, task_index", (len(prefix), prefix))]


def task_fingerprint(run_id: str, c: sqlite3.Connection) -> list[Any]:
    """The task decisions' part of a run's result fingerprint: their count and a digest of each decision with its time
    (until 209 in `jav/app/datasets.py`). An email's flow id is `<run>:<item>`; a range condition, so that the key index
    can be used."""
    dec = c.execute("SELECT COUNT(*), GROUP_CONCAT(k) FROM (SELECT run_id || '#' || task_index || '=' || decision || '@' || decided_at AS k"
                    " FROM email_task_decisions WHERE run_id >= ? AND run_id < ? ORDER BY k)", (run_id + ":", run_id + ";")).fetchone()
    return [dec[0], hashlib.sha256(str(dec[1]).encode("utf-8")).hexdigest()[:16]]


def reading(flow_run_id: str, c: sqlite3.Connection) -> dict[str, Any] | None:
    """What another domain reads of an email item's stored result (`item_kinds.ItemHandler.reading`): the intent it
    was read as, and the message's subject, sender and arrival; None before the run saved it."""
    row = c.execute("SELECT e.message_id, e.intent, m.subject, m.sender, m.received_at FROM email_results e"
                    " LEFT JOIN emails m ON m.message_id = e.message_id WHERE e.run_id=?", (flow_run_id,)).fetchone()
    if row is None:
        return None
    return {"read_as": row["intent"], "title": row["subject"], "sender": row["sender"], "received_at": row["received_at"]}


def found_as(intent: str, c: sqlite3.Connection) -> list[tuple[str, str]]:
    """(package, item) of every email item a run read as `intent` (`item_kinds.ItemHandler.found_as`)."""
    return [(r[0], r[1]) for r in c.execute(
        "SELECT DISTINCT r.workpackage_id, ri.item_id FROM email_results e JOIN run_items ri ON ri.flow_run_id = e.run_id"
        " JOIN runs r ON r.run_id = ri.run_id WHERE e.intent = ?", (intent,))]


def _has_emails(c: sqlite3.Connection) -> bool:
    """Whether the store has the emails table: a fresh store looked at read-only (the state snapshot) has only what an
    earlier process created, and until 209 the shared store always created it."""
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='emails'").fetchone() is not None


def summary_counts(c: sqlite3.Connection) -> dict[str, Any]:
    """The emails' line of the store summary (`store.stats`); 0 without the table, as an empty one counted."""
    return {"emails": c.execute("SELECT COUNT(*) FROM emails").fetchone()[0] if _has_emails(c) else 0}


def summary_intents(c: sqlite3.Connection) -> dict[str, Any]:
    """The intents' breakdown in the store summary (`store.stats`); empty without the table."""
    if not _has_emails(c):
        return {"intents": []}
    return {"intents": [dict(r) for r in c.execute("SELECT intent, COUNT(*) n FROM emails GROUP BY intent ORDER BY n DESC").fetchall()]}


store.register_summary("emails", summary_counts, after="datapoints")
store.register_summary("intents", summary_intents, after="doc_types")


__all__ = ["TASK_DECISIONS", "email_result", "email_task_decide", "email_task_decisions", "email_task_done", "found_as",
           "reading", "summary_counts", "summary_intents", "task_fingerprint", "task_rows", "upsert_email",
           "upsert_email_result"]
