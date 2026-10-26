"""231 (plan stage C, C3h): an email item on the review page (048 T2.3), split out of `mailbox.py`.

Plain-language summary: an email item's title and its attachments' parent labels, its result (the intent, the
proposed next step and the task proposals, with a person's correction of the intent), and a person's decisions on its
task proposals in the shared decision journal.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any


from jav.app import item_kinds, work, work_runs
from jav.core import decisions, identity, store
from jav.domains.email import email_store
from jav.core.user_messages import explained


EMAIL_FIELDS = ("intent",)  # 058 K5.1: an email's intent is correctable (the email is the source, not extracted)


def item_titles(items: list[dict[str, Any]]) -> dict[str, str]:
    """048 T2: an email's title in the item list is its subject and sender (the file name is always `message.json`);
    058 K5.2: an attachment's title names the email it came from. 185 (plan G-full-move T1e): the email kind's handler
    (until then in `jav/app/work_views.py` `item_titles`)."""
    from jav.domains.email.emails import message_version

    out, subjects = {}, {}
    for i in items:
        if i.get("kind") != item_kinds.EMAIL:
            continue
        m, status = message_version(i)  # 086 N04: the version the item was added with, not the latest
        if not m and status != "changed":
            continue  # unreadable: the file name stays the title
        subjects[i["item_id"]] = ("(a levél futáskori változata nem található)" if status == "changed"
                                  else m.get("subject") or "(tárgy nélkül)")[:100]
        out[i["item_id"]] = f"{subjects[i['item_id']]} — {m.get('sender_name') or m.get('sender') or '?'}"
    for i in items:  # 058 K5.2: the attachment's origin in its name (which email it came from)
        if i.get("parent_item_id") in subjects:
            out[i["item_id"]] = f"{Path(i['source_path']).name} (a levél csatolmánya: {subjects[i['parent_item_id']]})"
    return out


def parent_labels(items: list[dict[str, Any]]) -> dict[str, str]:
    """Subjects of the attachments' parent emails (only if the run has attachments), for the documents' source email
    column. 185 (plan G-full-move T1e): the email kind's handler (until then in `jav/app/export.py` `_email_subjects`)."""
    from jav.domains.email.emails import message_version

    parents = {i.get("parent_item_id") for i in items if i.get("parent_item_id")}
    out = {}
    for i in items:
        if i["item_id"] in parents:
            msg, status = message_version(i)  # 086 N04: the version the run processed
            # data (a cell of the download), not a label
            out[i["item_id"]] = ("(a levél futáskori változata nem található)" if status == "changed"
                                 else msg.get("subject") or ("(tárgy nélkül)" if msg else "(a levél nem olvasható)"))
    return out


def email_item_result(run: dict[str, Any], item: dict[str, Any], engine: str | None) -> dict[str, Any]:
    """048 T2: an email item's result on the review page: no extraction or page image; the email, its intent and its
    tasks. 185 (plan G-full-move T1e): the email kind's handler (`item_kinds.ItemHandler`; until then in
    `jav/app/corrections.py` `item_result`)."""
    from jav.app import corrections

    run_id, item_id = run["run_id"], item["item_id"]
    reasons = work_runs.item_reasons(run_id, item_id, item)
    corr = corrections.current(run_id, item_id)
    # 058 K5.2: the email's attachments that ran as documents in the run (the UI refers to them)
    attachment_items = [{"item_id": i["item_id"], "filename": Path(i["source_path"]).name}
                        for i in run["input"]["items"] if i.get("parent_item_id") == item_id]
    email = email_item_view(item, work_runs.flow_run_id(run_id, item_id), corr["fields"].get("intent"))
    own = bool(email["result"] and email["result"]["from_this_run"])
    return {"run_id": run_id, "item_id": item_id, "kind": "email", "extraction": None, "correction": corr,
            "effective": {}, "lists": {}, "checks": [], "provenance": {}, "source": None,
            "attachment_items": attachment_items, "email": email,
            # an intent taken from another run was not produced with this run's settings
            "engine": engine if own else None,
            "open_reasons": reasons["run"], "earlier_open_reasons": reasons["earlier"]}


@store.one_connection
def correct_email(run_id: str, item: dict[str, Any], *, fields: dict[str, Any], expected_revision: int, actor: identity.Who,
                  note: str | None, sources: dict[str, list[int]], confirm: list[str]) -> dict[str, Any]:
    """Manual correction of an email's intent (versioned, like a document's fields). The corrected intent settles the
    run's own intent to-dos (uncertain / unrecognised intent): the decision closes them; a to-do with another reason
    (e.g. suspicious content) stays open. 185 (plan G-full-move T1e): the email kind's handler (until then
    `jav/app/corrections.py` `_save_email`). 215 (plan G-process-core P2c): the new version and the to-dos it settles
    in one transaction, so a stop between the two keeps neither."""
    from jav.app import corrections
    from jav.domains.email import intents

    if confirm:
        raise explained(ValueError, "fields cannot be confirmed on an email; correct its intent instead")
    unknown = sorted(set(fields) - set(EMAIL_FIELDS))
    if unknown:
        raise explained(ValueError, "only {{email_fields}} can be corrected on an email: {{unknown}}",
                        email_fields=", ".join(EMAIL_FIELDS), unknown=unknown)
    if sources:
        raise explained(ValueError, "source selection is not supported for emails")
    key = fields.get("intent")
    if key is not None and key not in intents.BY_KEY:
        raise explained(ValueError, "unknown intent: {{key}}", key=key)
    item_id = item["item_id"]
    with store.connect() as c:
        store.begin_immediate(c)
        corrections.insert_revision(run_id, item_id, fields, expected_revision, actor, note, None)
        if key is not None:
            for r in work_runs.item_reasons(run_id, item_id, item)["run"]:
                if r["reason"].startswith("intent:"):
                    work_runs.resolve_reason(r["id"], actor=actor, resolution={"intent": key}, note="a szándék kézzel javítva")
    return corrections.current(run_id, item_id)


def intent_name(key: str | None) -> str | None:
    """The intent's Hungarian name from the registry (the key itself for an unknown key)."""
    from jav.domains.email import intents

    return (intents.BY_KEY[key].display_name if key in intents.BY_KEY else key) if key else None


def table_attachments(item: dict[str, Any]) -> int:
    """192 (B6c): how many table attachments (Excel, CSV) an email item has, each read as a part of a quote request in
    the email's follow-up (counted for the run's budget; cached by the message file and its time)."""
    path = Path(item["source_path"])
    try:
        return _message_tables(str(path), path.stat().st_mtime_ns)
    except OSError:
        return 0


@functools.lru_cache(maxsize=4096)
def _message_tables(message_json: str, _mtime_ns: int) -> int:
    from jav.domains.email import emails
    from jav.documents import text_document

    msg = emails.load_message_dir(Path(message_json).parent)
    return sum(1 for a in msg.attachments if a.path and text_document.input_kind(a.path) == "table")


def reads_text(next_flow: str | None) -> bool:
    """192 (backlog Q-m2-label-text): whether the email's next step extracts data from the email's own text too (its
    type pack reads text: the quote request), so its name says so."""
    from jav.ai import typepack

    if not next_flow or not next_flow.startswith("m2:"):
        return False
    key = next_flow.split(":", 1)[1]
    return key in typepack.keys() and "text" in typepack.get(key).inputs


def next_flow_labels() -> dict[str, str]:
    """Hungarian names of the proposed next steps (058 K5.1): the fixed codes from `configs/datasets.json`, and "data
    extraction from the attachment" per type, with the document type's name. The UI translates the same with its own
    dictionary."""
    from jav.core import cfg

    out = dict(cfg.load("datasets")["labels"]["next_flow"])
    for key, name in cfg.load("field_labels")["doc_types"].items():
        # 192 (backlog Q-m2-label-text): a type that reads the email's own text too says so (the quote request)
        out[f"m2:{key}"] = (f"Adatkinyerés a levélből és a csatolmányokból ({name})" if reads_text(f"m2:{key}")
                            else f"Adatkinyerés a csatolmányból ({name})")
    return out


def email_result_for(flow_run_id: str, message_id: str) -> tuple[dict[str, Any] | None, bool]:
    """The run's email result and whether it comes from this run. First the run's own row (058); for a pre-058 run the
    `emails` row if it comes from this run; otherwise the message's latest result (`from_this_run=False`, flagged in the
    UI)."""
    own = email_store.email_result(flow_run_id)
    if own is not None:
        return own, True
    with store.connect() as c:
        row = c.execute("SELECT * FROM emails WHERE message_id=?", (message_id,)).fetchone()
    if row is None:
        return None, False
    out = dict(row)
    out["signals"] = json.loads(out["signals"]) if out["signals"] else None
    out["attachments"] = json.loads(out["attachments"] or "[]")
    out["body"] = None
    return out, row["run_id"] == flow_run_id


def processed_types(doc_ids: list[str | None]) -> dict[str, str]:
    """126: the type each document was last processed as (`documents.doc_type`: the type pack's category once the data
    extraction saved it, else the recognised category)."""
    ids = sorted({d for d in doc_ids if d})
    if not ids:
        return {}
    with store.connect() as c:
        rows = c.execute(f"SELECT doc_id, doc_type FROM documents WHERE doc_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    return {r["doc_id"]: r["doc_type"] for r in rows if r["doc_type"]}


def effective_email_result(res: dict[str, Any], corrected_intent: str | None) -> dict[str, Any]:
    """The email result with the manual correction (058 K5.1): the corrected intent wins and the routing is recomputed
    from it in code (the machine signals - e.g. an injected instruction - still count). The machine intent is kept
    (`machine_intent`)."""
    from jav.domains.email import email_rules
    from jav.domains.email.emails import Attachment, is_bookkeeping_file

    signals = {k: v for k, v in (res.get("signals") or {}).items() if k != "scores"}
    # pre-048 runs also stored the message folder's bookkeeping file as an attachment: it is not one
    atts = [a for a in res.get("attachments") or [] if not is_bookkeeping_file(str(a.get("filename") or ""))]
    # 126 (Q-gpt-receipt-label): the type shown is the one the document was processed as (a foreign provider's receipt
    # recognised as a receipt goes to the foreign invoice pack); the recognised category stays in `doc_type`, and the
    # routing below still reads that
    processed = processed_types([a.get("doc_id") for a in atts])
    atts = [{**a, "shown_type": processed.get(a.get("doc_id") or "") or a.get("doc_type")} for a in atts]
    out = {"intent": res.get("intent"), "intent_label": intent_name(res.get("intent")), "confidence": res.get("intent_conf"),
           "next_flow": res.get("next_flow"), "attachments": atts, "signals": signals,
           "corrected": False, "machine_intent": res.get("intent"),
           "sent": res.get("folder") == "sent"}  # 149: a sent message is not asked about its intent
    if corrected_intent and corrected_intent != res.get("intent"):
        atts = [Attachment.model_validate(a) for a in out["attachments"]]
        out.update(intent=corrected_intent, intent_label=intent_name(corrected_intent), corrected=True,
                   next_flow=email_rules.email_next_flow(corrected_intent, 1.0, atts, {corrected_intent: 1.0}, signals))
    elif corrected_intent:
        out["corrected"] = True  # a person confirmed the machine intent
    out["next_flow_reads_text"] = reads_text(out["next_flow"])  # 192: its name says the email's text is read too
    return out


# 187 (plan G-full-move T2c): a person's decisions on an email's task proposals, in the shared decision journal
TASK_KIND = "email_task"


decisions.register(decisions.Kind(TASK_KIND, ("decide", "done", "undone"), __name__))


def _task_key(flow_run_id: str, index: int) -> str:
    return f"{flow_run_id}#{index}"


def task_view(flow_run_id: str, raw: dict[str, Any] | None, *, with_state: bool = True) -> dict[str, Any] | None:
    """058 K5.3: the task proposal with its decisions (None = the run did not ask for proposals). 187: each task's
    `decision_state`, which the page sends back with a change (`with_state=False`: a download, which has no page)."""
    tasks = (raw or {}).get("tasks")
    if not tasks:
        return None
    decided = email_store.email_task_decisions(flow_run_id)
    proposed = tasks.get("tasks") or []
    items = [{**t, "index": n, "decision": decided.get(n)} for n, t in enumerate(proposed)]
    if with_state:
        with store.connect() as c:
            state = decisions.states(c, TASK_KIND, [_task_key(flow_run_id, n) for n in range(len(proposed))])
        items = [{**t, "decision_state": state[_task_key(flow_run_id, t["index"])]} for t in items]
    return {"status": tasks.get("status"), "reason": tasks.get("reason"), "error": tasks.get("error"), "tasks": items,
            "rejected": tasks.get("rejected") or []}


@store.one_connection
def decide_task(run_id: str, item_id: str, index: int, *, decision: str, actor: identity.Who, note: str | None = None,
                expected_state: int | None = None) -> dict[str, Any]:
    """A human decision on a task proposal (accept / reject). Once every proposal of the message is decided, the run's
    own "proposal awaits decision" to-do is resolved (the decisions go into the resolution). Frozen on an approved
    run: 086 (audit of 2026-10-02, N02) the writing transaction checks the approval again, so a decision checked before
    a concurrent approval is refused instead of being written after it (the decisions are part of the approved result,
    `corrections.review_version`). 187: the change goes into the decision journal in the same transaction (before, a
    changed decision overwrote the earlier one with nothing kept), and a stale `expected_state` is refused. 215 (plan
    G-process-core P2c): the "proposal awaits decision" to-do closes in the decision's transaction too."""
    run = work_runs.get_run(run_id)
    if run["approval"]:
        raise explained(work.RevisionConflict, "run {{run_id}} is approved; task decisions are frozen", run_id=run_id)
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id and i.get("kind") == "email"), None)
    if item is None:
        raise KeyError(item_id)
    flow_id = work_runs.flow_run_id(run_id, item_id)
    view = task_view(flow_id, email_store.email_result(flow_id))
    if view is None or not 0 <= index < len(view["tasks"]):
        raise KeyError(f"task {index}")
    key = _task_key(flow_id, index)
    with store.connect() as c:
        store.begin_immediate(c)
        if decisions.run_approved(c, run_id):
            raise explained(work.RevisionConflict, "run {{run_id}} is approved; task decisions are frozen",
                            run_id=run_id)
        decisions.check(c, TASK_KIND, key, expected_state)
        email_store.email_task_decide(flow_id, index, decision=decision, actor=actor, note=note, c=c)
        decisions.record(c, TASK_KIND, key, "decide", actor=actor, value={"decision": decision}, note=note,
                         workpackage_id=run["workpackage_id"], run_id=run_id)
        view = task_view(flow_id, email_store.email_result(flow_id))
        if all(t["decision"] for t in view["tasks"]):
            summary = {"decisions": [{"index": t["index"], "decision": t["decision"]["decision"]} for t in view["tasks"]]}
            for r in work_runs.item_reasons(run_id, item_id, item)["run"]:
                if r["reason"].startswith("tasks:proposed"):
                    work_runs.resolve_reason(r["id"], actor=actor, resolution=summary, note="minden feladatjavaslatról döntöttek")
    return view


def mark_task_done(run_id: str, item_id: str, index: int, *, done: bool, actor: identity.Who,
                   expected_state: int | None = None) -> dict[str, Any]:
    """062 (decision of 2026-09-29): an accepted task can be marked done by hand, and the mark can be withdrawn. The
    task happens in the real world, so it can be marked even on an approved run; a rejected or undecided task cannot.
    187: in one transaction with its journal row, under the page's `expected_state`."""
    run = work_runs.get_run(run_id)
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id and i.get("kind") == "email"), None)
    if item is None:
        raise KeyError(item_id)
    flow_id = work_runs.flow_run_id(run_id, item_id)
    view = task_view(flow_id, email_store.email_result(flow_id))
    if view is None or not 0 <= index < len(view["tasks"]):
        raise KeyError(f"task {index}")
    key = _task_key(flow_id, index)
    with store.connect() as c:
        store.begin_immediate(c)
        decisions.check(c, TASK_KIND, key, expected_state)
        if not email_store.email_task_done(flow_id, index, actor=actor, done=done, c=c):
            raise explained(work.RevisionConflict, "task {{index}} is not accepted; only an accepted task can be marked done",
                            index=index)
        decisions.record(c, TASK_KIND, key, "done" if done else "undone", actor=actor,
                         workpackage_id=run["workpackage_id"], run_id=run_id)
    return task_view(flow_id, email_store.email_result(flow_id))  # type: ignore[return-value]


def email_item_view(item: dict[str, Any], flow_run_id: str, corrected_intent: str | None = None) -> dict[str, Any]:
    """The email item: the message (the version the item was added with, 086 N04: `emails.message_version`), the intent
    detection result with the manual correction, and how much of the message text the detection saw (`body_coverage`,
    058 K5.1). `source_status` says whether the email has changed since (`earlier`) or that version is gone
    (`changed`: no text is shown)."""
    from jav.domains.email.emails import EmailMessage, body_coverage, message_version

    path = Path(item["source_path"])
    msg, source_status = message_version(item)
    raw, from_this_run = email_result_for(flow_run_id, path.parent.name)
    res = {**effective_email_result(raw, corrected_intent), "from_this_run": from_this_run} if raw is not None else None
    body = msg.get("body") or ""
    coverage = (raw or {}).get("body") if from_this_run and (raw or {}).get("body") else body_coverage(
        EmailMessage(message_id=path.parent.name, body=body))
    return {"subject": msg.get("subject") or "", "sender": msg.get("sender"), "sender_name": msg.get("sender_name"),
            "to": msg.get("to") or [], "received_at": msg.get("received_at"), "mailbox": msg.get("mailbox"),
            "body": body[:20000], "attachments": [a.get("filename") for a in msg.get("attachments") or []],
            "body_coverage": coverage, "result": res, "tasks": task_view(flow_run_id, raw) if from_this_run else None,
            "source_status": source_status}
