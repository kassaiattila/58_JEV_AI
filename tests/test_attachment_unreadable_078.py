"""078: an unreadable PDF attachment does not fail the whole email.

Before 078 a corrupt or over-limit PDF attachment raised out of the attachment recognition, and the email item failed
without an intent. Now the attachment is marked unreadable, the email gets a to-do, and the intent is still recognised.
Synthetic email and PDFs, a fake JEV client, no paid calls.
"""

import json

import pytest

from jav import flow_detect, flow_email, isolated_pdf, pdf, store
from jav.adapters import jev as jev_mod
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_email_signals import FakeClient  # answers the intent question (Choice + Noul + Score)


@pytest.fixture()
def env(tmp_path):
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        yield {"tmp": tmp_path}

CORRUPT = b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >>\nendobj\ntrailer << /Root 1 0 R >>\n%%EOF garbage"


def _email_dir(env, *, corrupt: bool = True):
    d = env["tmp"] / "box" / "m1"
    d.mkdir(parents=True)
    (d / "message.json").write_text(json.dumps({"sender": "a@b.hu", "subject": "Számla", "body": "Mellékelten küldöm a számlát."}),
                                    encoding="utf-8")
    if corrupt:
        (d / "01_serult.pdf").write_bytes(CORRUPT)
    write_text_pdf(d / "02_szamla.pdf", INVOICE_LINES)
    return d


def test_a_corrupt_attachment_is_marked_and_the_email_still_gets_its_intent(env):
    st = flow_email.run_email(str(_email_dir(env)))
    status = {a.filename: a.status for a in st.message.attachments}
    assert status["01_serult.pdf"] == "unreadable" and status["02_szamla.pdf"] not in (None, "unreadable")  # the good one ran
    assert st.result is not None and st.result.intent  # the intent was recognised
    assert "attachment:unreadable:PdfReaderError" in st.review_reasons and st.final_status == "needs_review"
    open_reasons = [r["reason"] for r in store.review_open_reasons("email", "m1")]
    assert "attachment:unreadable:PdfReaderError" in open_reasons  # a person sees it among the email's to-dos


@pytest.mark.parametrize("exc, code", [
    (isolated_pdf.PdfReaderLimit("over the time limit", reason="timeout"), "attachment:unreadable:timeout"),
    (pdf.DocumentTooLarge("too many pages"), "attachment:unreadable:DocumentTooLarge"),
])
def test_an_attachment_over_a_reading_limit_is_marked_too(env, monkeypatch, exc, code):
    def refuse(*_a, **_k):
        raise exc

    monkeypatch.setattr(flow_detect, "run_detect", refuse)
    st = flow_email.run_email(str(_email_dir(env, corrupt=False)))
    assert [a.status for a in st.message.attachments] == ["unreadable"] and st.result is not None
    assert st.review_reasons.count(code) == 1


def test_any_other_error_still_fails_the_email(env, monkeypatch):
    """Only the named reading errors are absorbed; a programming error must not be hidden."""
    def broken(*_a, **_k):
        raise KeyError("bug")

    monkeypatch.setattr(flow_detect, "run_detect", broken)
    with pytest.raises(KeyError):
        flow_email.run_email(str(_email_dir(env, corrupt=False)))
