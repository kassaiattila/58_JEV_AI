"""167 (review T-2): the Excel file of an email run, which no test opened.

The email items go on their own sheet, the task proposals with a person's decision on another, and a run of emails only
gets no empty document sheets. The captions are the export's Hungarian vocabulary. Synthetic emails and a stand-in
task proposer; no paid call.
"""

from __future__ import annotations

import io

from openpyxl import load_workbook

from jav.domains.email import email_export, mailbox
from jav.app import export
from tests.test_audit_fixes_1002 import _reviewed_email
from tests.test_mailbox import env  # noqa: F401 - `env` is a fixture


def _sheets(run_id: str) -> dict[str, list[list]]:
    wb = load_workbook(io.BytesIO(export.xlsx_bytes(run_id)), read_only=True)
    return {ws.title: [list(row) for row in ws.iter_rows(values_only=True)] for ws in wb.worksheets}


def test_an_email_run_has_its_emails_and_its_decided_tasks_on_their_own_sheets(env, monkeypatch):  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)  # the question's task proposal is accepted by "t"
    sheets = _sheets(run_id)
    assert list(sheets) == ["Levelek", "Feladatok"]  # emails only: no document, datapoint or utility sheet

    head, *mails = sheets["Levelek"]
    assert head == email_export.EMAIL_HEAD
    by_subject = {row[0]: dict(zip(head, row)) for row in mails}
    assert sorted(by_subject) == ["Kérdés", "Számla 2026/09"]
    question = by_subject["Kérdés"]
    assert question["Feladó"] == "Minta Ügyfél <ugyfel@pelda.hu>" and question["Tétel-azonosító"] == item["item_id"]
    assert question["Nyitott teendők"] in (None, "")  # every to-do of the run was closed by the review

    head, *tasks = sheets["Feladatok"]
    assert head[:3] == ["Levél", "Akció", "Feladat"] and head[-1] == "Tétel-azonosító"
    [task] = [dict(zip(head, row)) for row in tasks]
    assert (task["Levél"], task["Feladat"], task["Döntés"], task["Döntött"], task["Tétel-azonosító"]) == (
        "Kérdés", "Válasz a szerződés érkezéséről", "elfogadva", "t", item["item_id"])


def test_an_undecided_task_is_shown_as_waiting_and_a_rejected_one_as_rejected(env, monkeypatch):  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)
    mailbox.decide_task(run_id, item["item_id"], 0, decision="rejected", actor="second reviewer")
    [task] = _sheets(run_id)["Feladatok"][1:]
    assert "elvetve" in task and "second reviewer" in task
    rows = email_export.task_rows(email_export.email_records(run_id))
    assert [(r["subject"], r["decision"], r["decided_by"]) for r in rows] == [("Kérdés", "rejected", "second reviewer")]
