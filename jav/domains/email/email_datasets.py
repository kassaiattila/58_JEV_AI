"""The email domain's tables on the interface (185, plan G-full-move T1b; until then in `jav/app/datasets.py`).

Plain-language summary: three tables of the shared data view are the email domain's: a run's or a package's emails
(058 K5.1: the intent with its correction, the suggested next step, the attachments, how much of the email's text the
recognition saw), their task proposals (058 K5.3: one per row, with the evidence and the person's decision), and the
mailbox downloads (048 T2). Two label sets are the domain's too: the intents' names and the suggested next steps'.
They moved here from `jav/app/datasets.py` as they were: the same columns, rows and order. The email domain module
registers them (`jav/domains/email/__init__.py`), and the data view asks its registry.

Layer: application operation (a read view) → `jav.domains.email.email_export`, `jav.domains.email.mailbox`, `jav.domains.email.intents`.
"""

from __future__ import annotations

from typing import Any

from jav.app import datasets
from jav.core import cfg, display, field_names
from jav.app.datasets import Rows, col


def emails(scope: dict[str, str]) -> Rows:
    """058 K5.1: the run's emails — intent (with the manual correction), suggested next step, attachments, and how much
    of the email's text the recognition saw."""
    from jav.domains.email import email_export, mailbox

    records, run_of = datasets.merged(scope, email_export.email_records)
    link = datasets.linker(scope, run_of)
    cols = [
        col("subject", "Subject", link="item"),
        col("sender", "From (column)"),
        col("received_at", "Received", "datetime"),
        col("mailbox", "Mailbox", hidden=True),
        col("intent", "Intent", "enum", labels="intent"),
        col("confidence", "Probability", "number", percent=True),
        col("corrected", "Corrected (column)", "enum", labels="yes"),
        col("machine_intent", "Machine intent", "enum", labels="intent", hidden=True),
        col("next_flow", "Suggested next step", "enum", labels="next_flow"),
        col("attachments", "Attachment", "number"),
        col("attachment_types", "Attachment types"),
        col("body_status", "Email text", "enum", labels="body_status"),
        col("body_chars", "Email length (characters)", "number", hidden=True),
        col("tasks", "Task proposal", "number", hidden=not any(r.get("tasks") for r in records)),
        col("open_reasons", "Open to-dos (column)", "number", link="item", alert=True),
        col("message_id", "Email ID", "id", hidden=True),
        col("item_id", "Item ID", "id", hidden=True),
    ]
    rows = []
    for r in records:
        # 126: the type each attachment was processed as (`shown_type`), else the recognised one
        shown = [a.get("shown_type") or a.get("doc_type") for a in r["attachments"]]
        types = sorted({field_names.type_name(x) for x in shown if x})  # 231 (D4): in the request's language
        rows.append({"_key": r["item_id"], **link(r["item_id"]), "item_id": r["item_id"],
                     "message_id": r["message_id"], "subject": r["subject"] or display.text("(without subject)"), "sender": r["sender"],
                     "received_at": r["received_at"], "mailbox": r["mailbox"], "intent": r["intent"],
                     "machine_intent": r["machine_intent"], "confidence": r["confidence"],
                     "corrected": "igen" if r["corrected"] else None, "next_flow": r["next_flow"],
                     # 192: no column of its own; the interface names such a next step by it
                     "next_flow_reads_text": mailbox.reads_text(r["next_flow"]),
                     "attachments": len(r["attachments"]), "attachment_types": ", ".join(types) or None,
                     "body_status": r["body"]["status"], "body_chars": r["body"]["chars"], "open_reasons": len(r["open_reasons"]),
                     "tasks": len((r.get("tasks") or {}).get("tasks") or []) or None})
    return cols, rows


def email_tasks(scope: dict[str, str]) -> Rows:
    """058 K5.3: the task proposals, one per row, with the evidence and the human decision (only a person accepts)."""
    from jav.domains.email import email_export

    records, run_of = datasets.merged(scope, email_export.email_records)
    link = datasets.linker(scope, run_of)
    cols = [
        col("subject", "Email (column)", link="item"),
        col("action", "Action (column)", "enum", labels="task_action"),
        col("title", "Task"),
        col("due_date", "Deadline", "date"),
        col("assignee_hint", "Assignee"),
        col("evidence", "Evidence"),
        col("decision", "Decision", "enum", labels="task_decision"),
        col("decided_by", "Decided by", hidden=True),
        col("decided_at", "Decided at", "datetime", hidden=True),
        col("done_at", "Done (column)", "datetime"),  # 062: manual "done" on an accepted task
        col("done_by", "Done by", hidden=True),
        col("item_id", "Item ID", "id", hidden=True),
    ]
    rows = [{**t, "_key": f"{t['item_id']}:{t['index']}", **link(t["item_id"])} for t in email_export.task_rows(records)]
    return cols, rows


def mailbox_pulls(scope: dict[str, str]) -> Rows:
    """The mailbox downloads, newest first; 264 (F6): a schedule's own (`schedule_id`, its page), grouped by their state
    or by who started them."""
    from jav.domains.email import mailbox

    cols = [
        col("created_at", "Started (column)", "datetime"),
        col("label", "Mailbox / period"),
        col("status", "Status", "enum", labels="pull_status", badge=True, group=True),
        col("new", "New emails", "number"),
        col("changed", "Changed (column)", "number", hidden=True),
        col("duplicate", "Already fetched", "number", hidden=True),
        col("workpackage", "Work package (column)", "id", link="workpackage"),
        col("actor", "Started by", group=True),
        col("error", "Error"),
        col("finished_at", "Finished", "datetime", hidden=True),
    ]
    rows = []
    for p in mailbox.pulls(limit=cfg.load("datasets")["export_max_rows"], schedule_id=scope.get("schedule_id") or None):
        res = p.get("result") or {}
        rows.append({"_key": p["id"], "_wp": res.get("workpackage"), "created_at": p["created_at"], "label": p["label"],
                     "status": p["status"], "new": res.get("new"), "changed": res.get("changed"), "duplicate": res.get("duplicate"),
                     "workpackage": res.get("workpackage"), "actor": p["actor"], "error": res.get("error"),
                     "finished_at": p.get("finished_at"),
                     "_request": p["request"]})  # 183: the interface writes the label in its own language from it
    return cols, rows


def mailbox_schedules(_scope: dict[str, str]) -> Rows:
    """264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): the mailbox schedules -
    what each reads, how often, whether it is on, when it runs next and how its last download ended - each opening its
    own page (Settings › Mailboxes)."""
    from jav.domains.email import mailbox

    cols = [
        col("label", "Reads", link="settings", section="mailboxes"),
        col("interval_min", "Frequency", "enum", labels="mailbox_interval", group=True),
        col("state", "State", "enum", labels="schedule_state", badge=True, group=True, marks={"on": "done", "off": "muted"}),
        col("next_at", "Next", "datetime"),
        col("last_at", "Most recently", "datetime"),
        col("last_status", "Last download", "enum", labels="pull_status", badge=True, group=True),
        col("last_new", "New emails", "number"),
        col("actor", "Saved by", group=True, hidden=True),
        col("changed_at", "Changed", "datetime", hidden=True),
    ]
    rows = []
    for s in mailbox.schedules():
        last = s.get("last_result") or {}
        rows.append({"_key": s["id"], "label": s["label"], "interval_min": str(s["interval_min"]),
                     "state": "on" if s["enabled"] else "off", "next_at": s["next_at"] if s["enabled"] else None,
                     "last_at": s.get("last_at"), "last_status": s.get("last_status"),
                     "last_new": (last.get("new") or 0) + (last.get("changed") or 0) if s.get("last_status") == "ok" else None,
                     "actor": s.get("actor"), "changed_at": s.get("changed_at") or s.get("created_at"),
                     "_request": s["request"]})  # the interface writes the label in its own language from it
    return cols, rows


def mailbox_intervals() -> dict[str, str]:
    """264 (F6): a schedule's frequencies (the interface's own words)."""
    return {"15": "every 15 minutes", "30": "every 30 minutes", "60": "hourly", "240": "every 4 hours", "1440": "daily"}


def schedule_states() -> dict[str, str]:
    return {"on": "On (value)", "off": "Off (value)"}


def intent_labels() -> dict[str, str]:
    """058 K5.1: the names of the email intents, from the registry."""
    from jav.domains.email import intents

    return {k: v.display_name for k, v in intents.BY_KEY.items()}


def task_action_labels() -> dict[str, str]:
    """058 K5.3: the Hungarian names of the task actions."""
    return dict(cfg.load("email_tasks")["actions"])


def next_flow_labels() -> dict[str, Any]:
    from jav.domains.email import mailbox

    return mailbox.next_flow_labels()


# the tables, each with the table it follows in the catalogue (the order they always had), and the label sets;
# registered by `jav/domains/email/__init__.py`
DATASETS = (
    (datasets.Dataset("emails", "Emails", (), emails, datasets.result_fingerprint, one_of=datasets.RESULT_SCOPE), "package_costs"),
    (datasets.Dataset("email_tasks", "Task proposals", (), email_tasks, datasets.result_fingerprint,
                      one_of=datasets.RESULT_SCOPE), "emails"),
    (datasets.Dataset("mailbox_pulls", "Mailbox downloads", (), mailbox_pulls, optional_scope=("schedule_id",)), "calls"),
    (datasets.Dataset("mailbox_schedules", "Mailbox schedules", (), mailbox_schedules,
                      natural_sort=(("label", False),)), "mailbox_pulls"),  # 264 (F6)
)
LABELS = (
    datasets.LabelSet("intent", __name__, intent_labels),
    datasets.LabelSet("task_action", __name__, task_action_labels),
    datasets.LabelSet("next_flow", __name__, next_flow_labels),
    datasets.LabelSet("mailbox_interval", __name__, mailbox_intervals),  # 264 (F6)
    datasets.LabelSet("schedule_state", __name__, schedule_states),
)


__all__ = ["DATASETS", "LABELS", "email_tasks", "emails", "intent_labels", "mailbox_intervals", "mailbox_pulls",
           "mailbox_schedules", "next_flow_labels", "schedule_states", "task_action_labels"]
