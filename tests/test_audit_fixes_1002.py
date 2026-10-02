"""086: fixes of the 2026-10-02 backend and frontend audit (N02, N04). Synthetic emails and stand-in models only; no
paid call. The audit's witnesses (`runs/20261002_full_audit/probes.py`) are turned round: they proved the faults,
these tests require the protected behaviour.

- N02: a task decision is part of the approved result. Changing a decision changes the review version, so an approval
  of the version seen before the change is refused; and the decision's write checks the approval again in its own
  transaction, so a decision cannot be written after a concurrent approval.
- N04: an email item always shows the email as it was when it was added (the version whose fingerprint the item
  recorded), even after the same email was received again with a changed text; if that version is gone, the view
  says so instead of showing another text.
"""

import hashlib
import json

import pytest

from jav import corrections, email_tasks, emails, export, ingest_server, mailbox, store, work, work_views
from jav.runtime import worker
from tests.test_email_results import _fake_tasks
from tests.test_mailbox import MAILS, REQ, FakeBridge, env  # noqa: F401 - `env` is a fixture


def _reviewed_email(env, monkeypatch):  # noqa: F811 - the fixture's value
    monkeypatch.setattr(email_tasks, "extract", _fake_tasks)
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge(MAILS), inbox_root=env["inbox"])
    wp_id = res["workpackage"]
    work.assign_recipe(wp_id, "processing", params={"tasks": "propose"}, expected_revision=1, actor="t")
    ready = work.readiness(wp_id)
    run_id = work.start_run(wp_id, mode="apply", expected_assignment_revision=2, input_hash=ready["input_hash"], actor="t")["run_id"]
    worker.run_worker(once=True)
    item = next(i for i in work.get_run(run_id)["input"]["items"]
                if corrections.item_result(run_id, i["item_id"])["email"]["subject"] == "Kérdés")
    mailbox.decide_task(run_id, item["item_id"], 0, decision="accepted", actor="t")
    for i in work.get_run(run_id)["input"]["items"]:
        for reason in work.item_reasons(run_id, i["item_id"], i)["run"]:
            work.resolve_reason(reason["id"], actor="t", resolution=None, note="Synthetic review")
    return run_id, item


# --- N02: the task decisions are part of the approved result -------------------------------------------------


def test_a_changed_task_decision_changes_the_review_version(env, monkeypatch):  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)
    seen = corrections.review_version(run_id)
    mailbox.decide_task(run_id, item["item_id"], 0, decision="rejected", actor="second reviewer")
    assert corrections.review_version(run_id) != seen
    with pytest.raises(work.RevisionConflict):
        work.approve_run(run_id, actor="first reviewer", review_version=seen)
    assert work.get_run(run_id)["approval"] is None


def test_a_run_without_task_decisions_keeps_its_review_version(env, monkeypatch):  # noqa: F811
    """The version of a run without task decisions is computed exactly as before, so an approval page opened before the
    change does not get a needless conflict."""
    run_id, _item = _reviewed_email(env, monkeypatch)
    with store.connect() as c:
        c.execute("DELETE FROM email_task_decisions")
        rows = c.execute("SELECT item_id, MAX(revision) r FROM run_item_corrections WHERE run_id=? GROUP BY item_id"
                         " ORDER BY item_id", (run_id,)).fetchall()
    before = hashlib.sha256(json.dumps([[r["item_id"], r["r"]] for r in rows]).encode("utf-8")).hexdigest()[:16]
    assert corrections.review_version(run_id) == before


def test_a_task_decision_cannot_be_written_after_a_concurrent_approval(env, monkeypatch):  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)
    real = mailbox.task_view
    approved = []

    def approve_after_the_check(*args, **kwargs):  # the approval lands between the first check and the write
        if not approved:
            approved.append(work.approve_run(run_id, actor="other reviewer")["approval"])
        return real(*args, **kwargs)

    monkeypatch.setattr(mailbox, "task_view", approve_after_the_check)
    with pytest.raises(work.RevisionConflict):
        mailbox.decide_task(run_id, item["item_id"], 0, decision="rejected", actor="t")
    assert approved == ["approved"]
    flow_id = work.flow_run_id(run_id, item["item_id"])
    assert store.email_task_decisions(flow_id)[0]["decision"] == "accepted"  # the approved decision stands


# --- N01: a run's table names the version of the result it shows ------------------------------------------------


def test_a_result_table_carries_the_version_it_shows(env, monkeypatch):  # noqa: F811
    from jav import datasets
    from jav.tablequery import Query

    run_id, item = _reviewed_email(env, monkeypatch)
    page = datasets.query("emails", {"run_id": run_id}, Query())
    assert page["review_version"] == corrections.review_version(run_id)
    mailbox.decide_task(run_id, item["item_id"], 0, decision="rejected", actor="second reviewer")
    newer = datasets.query("emails", {"run_id": run_id}, Query())
    assert newer["review_version"] == corrections.review_version(run_id) != page["review_version"]
    with pytest.raises(work.RevisionConflict):  # the version of the table seen before the change is not approved
        work.approve_run(run_id, actor="t", review_version=page["review_version"])
    assert "review_version" not in datasets.query("workpackages", None, Query())


# --- N04: an email item shows the email as it was added ----------------------------------------------------------


def _reingest_changed(env):  # noqa: F811
    receipt = ingest_server.ingest_message({**MAILS[1], "subject": "CHANGED AFTER APPROVAL",
                                            "body_preview": "This is a different source text."}, env["inbox"])
    assert receipt["status"] == "changed" and receipt["version"] == 2
    return receipt


def test_an_approved_email_run_keeps_showing_the_email_it_processed(env, monkeypatch):  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)
    original = corrections.item_result(run_id, item["item_id"])["email"]
    work.approve_run(run_id, actor="t", review_version=corrections.review_version(run_id))
    _reingest_changed(env)
    shown = corrections.item_result(run_id, item["item_id"])["email"]
    assert (shown["subject"], shown["body"]) == (original["subject"], original["body"]) == ("Kérdés", "Mikor érkezik a szerződés?")
    assert shown["source_status"] == "earlier"  # the email changed later; this is the version the run processed
    record = next(r for r in export.email_records(run_id) if r["item_id"] == item["item_id"])
    assert record["subject"] == "Kérdés" and record["source_status"] == "earlier"
    assert work_views.item_titles(work.get_run(run_id)["input"]["items"])[item["item_id"]].startswith("Kérdés")


def test_a_missing_email_version_is_reported_not_replaced(env, monkeypatch):  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)
    _reingest_changed(env)
    for old in (env["inbox"].rglob("message.v*.json")):
        old.unlink()  # synthetic data: the version the run processed is gone
    shown = corrections.item_result(run_id, item["item_id"])["email"]
    assert shown["source_status"] == "changed"
    assert shown["subject"] == "" and shown["body"] == ""  # never the other version's text
    assert emails.message_version(item)[1] == "changed"


def test_an_unchanged_email_is_read_as_before(env, monkeypatch):  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)
    msg, status = emails.message_version(item)
    assert status == "current" and msg["subject"] == "Kérdés"
    assert corrections.item_result(run_id, item["item_id"])["email"]["source_status"] == "current"
