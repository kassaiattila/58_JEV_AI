"""The email domain's part of a result's downloads (185, plan G-full-move T1e; until then in `jav/export.py`).

Plain-language summary: a run's or a package's result holds its emails beside its documents. This module reads a run's
email items as the downloads show them (058 K5.1: the email's data, the recognised intent with the manual correction,
the suggested next step, the attachments' recognition and how much of the email's text the recognition saw), their
task proposals one per row (058 K5.3, with the person's decision), and builds the two sheets of the result's workbook,
the emails and the tasks, with their Hungarian headers. The email domain registers it as an item kind's part of a
result (`jav/outputs/parts.py` `ItemPart`), so the shared export writes it before the documents as it always did.

Layer: application operation (a read view) → `jav.emails`, `jav.mailbox`, `jav.corrections`, `jav.work`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jav import cfg, corrections, item_kinds, work
from jav.outputs import contract


def email_records(run_id: str) -> list[dict[str, Any]]:
    """058 K5.1: the run's email items: the email's data, the recognised intent with the manual correction, the
    suggested next step (computed in code from the corrected intent), the recognition of the attachments, and how much
    of the email text the recognition saw. For an old run without its own result row, the email's latest result
    (`from_this_run=False`)."""
    from jav import emails, mailbox

    out = []
    items = work.released_items(work.get_run(run_id))  # 160-C: not the items removed from the package (decision 163 D7)
    split = work.items_reasons(run_id, [i for i in items if i.get("kind") == item_kinds.EMAIL])  # 153 (review B3): one query
    for item in items:
        if item.get("kind") != item_kinds.EMAIL:
            continue
        path = Path(item["source_path"])
        msg, source_status = emails.message_version(item)  # 086 N04: the version the run processed, not the latest
        raw, own = mailbox.email_result_for(work.flow_run_id(run_id, item["item_id"]), path.parent.name)
        corr = corrections.current(run_id, item["item_id"])
        res = mailbox.effective_email_result(raw, corr["fields"].get("intent")) if raw is not None else {}
        body = (raw or {}).get("body") if own else None
        if not body:
            body = emails.body_coverage(emails.EmailMessage(message_id=path.parent.name, body=msg.get("body") or ""))
        sender = msg.get("sender_name") or ""
        if msg.get("sender"):
            sender = f"{sender} <{msg['sender']}>" if sender else msg["sender"]
        out.append({"item_id": item["item_id"], "message_id": path.parent.name, "subject": msg.get("subject") or "",
                    "sender": sender, "received_at": msg.get("received_at"), "mailbox": msg.get("mailbox"),
                    "intent": res.get("intent"), "machine_intent": res.get("machine_intent"), "confidence": res.get("confidence"),
                    "corrected": bool(res.get("corrected")), "next_flow": res.get("next_flow"),
                    "attachments": res.get("attachments") or [], "from_this_run": own, "body": body,
                    "open_reasons": [r["reason"] for r in split[item["item_id"]]["run"]],
                    "tasks": mailbox.task_view(work.flow_run_id(run_id, item["item_id"]), raw) if own else None,
                    "source_status": source_status})
    return out


def task_rows(mails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """058 K5.3: the task proposals, one per row (with the email, the evidence and the human decision)."""
    out = []
    for m in mails:
        for t in (m.get("tasks") or {}).get("tasks") or []:
            d = t.get("decision") or {}
            out.append({"item_id": m["item_id"], "subject": m["subject"], "index": t["index"], "action": t["action"], "title": t["title"],
                        "due_date": t.get("due_date"), "assignee_hint": t.get("assignee_hint"),
                        "evidence": " | ".join(e["quote"] for e in t.get("evidence") or []),
                        "decision": d.get("decision"), "decided_by": d.get("actor"), "decided_at": d.get("decided_at"),
                        "done_by": d.get("done_by"), "done_at": d.get("done_at")})  # 062: manual "done" mark
    return out


EMAIL_HEAD = ["Tárgy", "Feladó", "Érkezett", "Postafiók", "Szándék", "Gépi szándék", "Valószínűség", "Javítva",
              "Javasolt következő lépés", "Csatolmányok", "Levél szövege", "Levél hossza (karakter)", "Nyitott teendők", "Tétel-azonosító"]
# 178 (plan 170 L4): the column keys of the email sheets (`configs/outputs.json` `package_result`), in header order
EMAIL_COLUMNS = ("subject", "sender", "received_at", "mailbox", "intent", "machine_intent", "confidence", "corrected", "next_flow",
                 "attachments", "body_status", "body_chars", "open_reasons", "item_id")
TASK_COLUMNS = ("subject", "action", "title", "due_date", "assignee_hint", "evidence", "decision", "decided_by", "done_at", "done_by",
                "item_id")
TASK_HEAD = ("Levél", "Akció", "Feladat", "Határidő", "Felelős", "Bizonyíték", "Döntés", "Döntött", "Elvégezve", "Elvégezte",
             "Tétel-azonosító")


def emails_table(records: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    """The email table with Hungarian captions (intent, next step, the part of the text seen, attachment type)."""
    from jav import mailbox

    flows = mailbox.next_flow_labels()
    body = cfg.load("datasets")["labels"]["body_status"]
    doc_types = cfg.load("field_labels")["doc_types"]
    shown = lambda a: a.get("shown_type") or a.get("doc_type")  # noqa: E731 - 126: the type the document was processed as
    att = lambda a: f"{a.get('filename')} ({doc_types.get(shown(a), shown(a)) or a.get('status') or '–'})"  # noqa: E731
    rows = [[r["subject"], r["sender"], r["received_at"], r["mailbox"], mailbox.intent_name(r["intent"]),
             mailbox.intent_name(r["machine_intent"]), r["confidence"], "igen" if r["corrected"] else "",
             flows.get(r["next_flow"] or "", r["next_flow"]), ", ".join(att(a) for a in r["attachments"]),
             body.get(r["body"]["status"], r["body"]["status"]), r["body"]["chars"], "; ".join(r["open_reasons"]), r["item_id"]]
            for r in records]
    return EMAIL_HEAD, rows


def result_tables(mails: list[dict[str, Any]]) -> tuple[contract.Table, ...]:
    """058 K5.1: the email items on their own sheet; 058 K5.3: the task proposals on a separate sheet, with the
    decision, when there is one."""
    head, rows = emails_table(mails)
    tables = [contract.table("emails", "Levelek", EMAIL_COLUMNS, head, rows)]
    tasks = task_rows(mails)
    if tasks:
        actions = cfg.load("email_tasks")["actions"]
        decisions = {"accepted": "elfogadva", "rejected": "elvetve"}
        tables.append(contract.table("tasks", "Feladatok", TASK_COLUMNS, TASK_HEAD,
                                     [[t["subject"], actions.get(t["action"], t["action"]), t["title"], t["due_date"], t["assignee_hint"],
                                       t["evidence"], decisions.get(t["decision"] or "", "vár döntésre"), t["decided_by"], t["done_at"],
                                       t["done_by"], t["item_id"]] for t in tasks]))
    return tuple(tables)


def shown_tables(mails: list[dict[str, Any]]) -> list[str]:
    """The result views of the interface the emails add (058 K5.1): the emails, and the task proposals when a run asked
    for them (058 K5.3)."""
    return ["emails", "tasks"] if task_rows(mails) else ["emails"]


HEADS = {"emails": dict(zip(EMAIL_COLUMNS, EMAIL_HEAD)), "tasks": dict(zip(TASK_COLUMNS, TASK_HEAD))}


__all__ = ["EMAIL_COLUMNS", "EMAIL_HEAD", "HEADS", "TASK_COLUMNS", "TASK_HEAD", "email_records", "emails_table",
           "result_tables", "shown_tables", "task_rows"]
