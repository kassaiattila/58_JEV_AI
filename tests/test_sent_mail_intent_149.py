"""149 (backlog F-sent-mail-processing; DECISIONS 149): a sent message gets no intent question.

The intent question asks what the sender wants from us. For a message we sent ourselves the answer means nothing, and
the call is paid. A sent message (`folder = 'sent'` in its `message.json`, 148) now skips that question. Its
attachments are still recognised and decide the suggested next step, as for a document-bearing intent; without a
document attachment it is archived. Neither JEV nor GPT is asked about the message itself, no task proposal is made
for it, and a sent message without a problem leaves no to-do. The run's email result records the folder, so the UI can
say why there is no intent. An Inbox message is unchanged.

Synthetic email and PDF, a fake JEV client, no paid calls.
"""

from __future__ import annotations

import json

import pytest

from jav import email_tasks, flow_email, intent_gpt, mailbox, policy, store
from jav.adapters import jev as jev_mod
from jav.emails import Attachment, load_message_dir
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_email_signals import FakeClient


@pytest.fixture()
def env(tmp_path):
    client = FakeClient()
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        yield {"tmp": tmp_path, "client": client}


def _email_dir(env, *, folder: str | None = "sent", attachment: bool = False, name: str = "m1"):
    d = env["tmp"] / "box" / name
    d.mkdir(parents=True)
    record = {"sender": "box@example.com", "subject": "Invoice INV-0001", "body": "Please find the invoice attached.",
              **({"folder": folder} if folder else {})}
    (d / "message.json").write_text(json.dumps(record), encoding="utf-8")
    if attachment:
        write_text_pdf(d / "invoice.pdf", INVOICE_LINES)
    return d


def _intent_questions(client: FakeClient) -> int:
    return sum(1 for r in client.requests for q in r["questions"] if q.startswith("intent"))


def test_the_folder_comes_from_the_message_record(env):
    assert load_message_dir(_email_dir(env)).folder == "sent"
    assert load_message_dir(_email_dir(env, folder=None, name="m2")).folder == "inbox"  # a record without a folder


def test_a_sent_message_is_not_asked_about_and_leaves_no_to_do(env):
    st = flow_email.run_email(str(_email_dir(env)))
    assert env["client"].requests == []  # nothing asked about the message
    assert st.result is None and not st.uncertain and st.final_status == "done"
    assert st.next_flow == policy.EMAIL_SENT_ROUTE == "archive:sent"
    assert store.review_open_reasons("email", "m1") == []


def test_a_sent_message_attachment_is_still_recognised(env):
    st = flow_email.run_email(str(_email_dir(env, attachment=True)))
    [att] = st.message.attachments
    assert att.status not in (None, "skipped") and att.doc_id  # the attachment recognition ran
    assert _intent_questions(env["client"]) == 0 and st.result is None
    assert st.next_flow == policy.email_sent_route(st.message.attachments)


def test_without_jev_gpt_is_not_asked_either(env, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("GPT asked about a sent message")

    monkeypatch.setattr(intent_gpt, "classify", refuse)
    st = flow_email.run_email(str(_email_dir(env)), jev=False)
    assert st.result is None and st.final_status == "done"


def test_no_task_proposal_is_made_for_a_sent_message(env, monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("a task proposal asked for a sent message")

    monkeypatch.setattr(email_tasks, "extract", refuse)
    app = flow_email.build_app(source_dir=str(_email_dir(env)), propose_tasks=True)
    *_, state = app.run(halt_after=flow_email.TERMINALS)
    assert state.data.tasks == {"status": "skipped", "reason": "sent_message", "tasks": [], "rejected": []}


def test_the_email_result_records_the_folder_and_says_why_there_is_no_intent(env):
    app = flow_email.build_app(source_dir=str(_email_dir(env)), run_id="run-x:item-1")
    app.run(halt_after=flow_email.TERMINALS)
    res = store.email_result("run-x:item-1")
    assert res["folder"] == "sent" and res["intent"] is None
    view = mailbox.effective_email_result(res, None)
    assert view["sent"] is True and view["intent_label"] is None  # the UI names the reason


def test_an_inbox_message_is_still_asked(env):
    st = flow_email.run_email(str(_email_dir(env, folder=None)))
    assert _intent_questions(env["client"]) == 1 and st.result is not None and st.result.intent == "szamlakuldes"


@pytest.mark.parametrize("atts, route", [
    ([], "archive:sent"),
    ([Attachment(filename="a.pdf", path="a.pdf", status="done", doc_type="invoice_hu")], "m2:invoice_hu"),
    ([Attachment(filename="a.pdf", path="a.pdf", status="needs_ocr")], "m2:needs_ocr"),
    ([Attachment(filename="a.pdf", path="a.pdf", status="skipped")], "m1:detect"),
    ([Attachment(filename="a.png", path="a.png", status="unsupported")], "archive:sent"),
])
def test_the_attachments_decide_a_sent_message_route(atts, route):
    assert policy.email_sent_route(atts) == route
