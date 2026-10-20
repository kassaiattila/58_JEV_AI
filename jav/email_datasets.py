"""The email domain's tables on the interface (185, plan G-full-move T1b; until then in `jav/datasets.py`).

Plain-language summary: three tables of the shared data view are the email domain's: a run's or a package's emails
(058 K5.1: the intent with its correction, the suggested next step, the attachments, how much of the email's text the
recognition saw), their task proposals (058 K5.3: one per row, with the evidence and the person's decision), and the
mailbox downloads (048 T2). Two label sets are the domain's too: the intents' names and the suggested next steps'.
They moved here from `jav/datasets.py` as they were: the same columns, rows and order. The email domain module
registers them (`jav/domains/email.py`), and the data view asks its registry.

Layer: application operation (a read view) → `jav.export`, `jav.mailbox`, `jav.intents`.
"""

from __future__ import annotations

from typing import Any

from jav import cfg, datasets
from jav.datasets import Rows, col


def emails(scope: dict[str, str]) -> Rows:
    """058 K5.1: the run's emails — intent (with the manual correction), suggested next step, attachments, and how much
    of the email's text the recognition saw."""
    from jav import export

    doc_types = datasets.label_set("doc_type")
    records, run_of = datasets.merged(scope, export.email_records)
    link = datasets.linker(scope, run_of)
    cols = [
        col("subject", "Tárgy", link="item"),
        col("sender", "Feladó"),
        col("received_at", "Érkezett", "datetime"),
        col("mailbox", "Postafiók", hidden=True),
        col("intent", "Szándék", "enum", labels="intent"),
        col("confidence", "Valószínűség", "number", percent=True),
        col("corrected", "Javítva", "enum", labels="yes"),
        col("machine_intent", "Gépi szándék", "enum", labels="intent", hidden=True),
        col("next_flow", "Javasolt következő lépés", "enum", labels="next_flow"),
        col("attachments", "Csatolmány", "number"),
        col("attachment_types", "Csatolmányok típusa"),
        col("body_status", "Levél szövege", "enum", labels="body_status"),
        col("body_chars", "Levél hossza (karakter)", "number", hidden=True),
        col("tasks", "Feladatjavaslat", "number", hidden=not any(r.get("tasks") for r in records)),
        col("open_reasons", "Nyitott teendő", "number", link="item", alert=True),
        col("message_id", "Levél-azonosító", "id", hidden=True),
        col("item_id", "Tétel-azonosító", "id", hidden=True),
    ]
    rows = []
    for r in records:
        # 126: the type each attachment was processed as (`shown_type`), else the recognised one
        shown = [a.get("shown_type") or a.get("doc_type") for a in r["attachments"]]
        types = sorted({doc_types.get(x, x) for x in shown if x})
        rows.append({"_key": r["item_id"], **link(r["item_id"]), "item_id": r["item_id"],
                     "message_id": r["message_id"], "subject": r["subject"] or "(tárgy nélkül)", "sender": r["sender"],
                     "received_at": r["received_at"], "mailbox": r["mailbox"], "intent": r["intent"],
                     "machine_intent": r["machine_intent"], "confidence": r["confidence"],
                     "corrected": "igen" if r["corrected"] else None, "next_flow": r["next_flow"],
                     "attachments": len(r["attachments"]), "attachment_types": ", ".join(types) or None,
                     "body_status": r["body"]["status"], "body_chars": r["body"]["chars"], "open_reasons": len(r["open_reasons"]),
                     "tasks": len((r.get("tasks") or {}).get("tasks") or []) or None})
    return cols, rows


def email_tasks(scope: dict[str, str]) -> Rows:
    """058 K5.3: the task proposals, one per row, with the evidence and the human decision (only a person accepts)."""
    from jav import export

    records, run_of = datasets.merged(scope, export.email_records)
    link = datasets.linker(scope, run_of)
    cols = [
        col("subject", "Levél", link="item"),
        col("action", "Akció", "enum", labels="task_action"),
        col("title", "Feladat"),
        col("due_date", "Határidő", "date"),
        col("assignee_hint", "Felelős"),
        col("evidence", "Bizonyíték"),
        col("decision", "Döntés", "enum", labels="task_decision"),
        col("decided_by", "Döntött", hidden=True),
        col("decided_at", "Döntés ideje", "datetime", hidden=True),
        col("done_at", "Elvégezve", "datetime"),  # 062: manual "done" on an accepted task
        col("done_by", "Elvégezte", hidden=True),
        col("item_id", "Tétel-azonosító", "id", hidden=True),
    ]
    rows = [{**t, "_key": f"{t['item_id']}:{t['index']}", **link(t["item_id"])} for t in export.task_rows(records)]
    return cols, rows


def mailbox_pulls(_scope: dict[str, str]) -> Rows:
    from jav import mailbox

    cols = [
        col("created_at", "Indítva", "datetime"),
        col("label", "Postafiók / időszak"),
        col("status", "Állapot", "enum", labels="pull_status", badge=True),
        col("new", "Új levél", "number"),
        col("changed", "Változott", "number", hidden=True),
        col("duplicate", "Már megvolt", "number", hidden=True),
        col("workpackage", "Munkacsomag", "id", link="workpackage"),
        col("actor", "Indította"),
        col("error", "Hiba"),
        col("finished_at", "Befejeződött", "datetime", hidden=True),
    ]
    rows = []
    for p in mailbox.pulls(limit=cfg.load("datasets")["export_max_rows"]):
        res = p.get("result") or {}
        rows.append({"_key": p["id"], "_wp": res.get("workpackage"), "created_at": p["created_at"], "label": p["label"],
                     "status": p["status"], "new": res.get("new"), "changed": res.get("changed"), "duplicate": res.get("duplicate"),
                     "workpackage": res.get("workpackage"), "actor": p["actor"], "error": res.get("error"),
                     "finished_at": p.get("finished_at"),
                     "_request": p["request"]})  # 183: the interface writes the label in its own language from it
    return cols, rows


def intent_labels() -> dict[str, str]:
    """058 K5.1: the names of the email intents, from the registry."""
    from jav import intents

    return {k: v.display_name for k, v in intents.BY_KEY.items()}


def task_action_labels() -> dict[str, str]:
    """058 K5.3: the Hungarian names of the task actions."""
    return dict(cfg.load("email_tasks")["actions"])


def next_flow_labels() -> dict[str, Any]:
    from jav import mailbox

    return mailbox.next_flow_labels()


# the tables, each with the table it follows in the catalogue (the order they always had), and the label sets;
# registered by `jav/domains/email.py`
DATASETS = (
    (datasets.Dataset("emails", "Levelek", (), emails, datasets.result_fingerprint, one_of=datasets.RESULT_SCOPE), "package_costs"),
    (datasets.Dataset("email_tasks", "Feladatjavaslatok", (), email_tasks, datasets.result_fingerprint,
                      one_of=datasets.RESULT_SCOPE), "emails"),
    (datasets.Dataset("mailbox_pulls", "Postafiók-letöltések", (), mailbox_pulls), "calls"),
)
LABELS = (
    datasets.LabelSet("intent", __name__, intent_labels),
    datasets.LabelSet("task_action", __name__, task_action_labels),
    datasets.LabelSet("next_flow", __name__, next_flow_labels),
)


__all__ = ["DATASETS", "LABELS", "email_tasks", "emails", "intent_labels", "mailbox_pulls", "next_flow_labels",
           "task_action_labels"]
