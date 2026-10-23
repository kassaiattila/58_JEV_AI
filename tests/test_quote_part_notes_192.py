"""192 (plan F-quote-package B6b, the owner's decision of 2026-10-21, DECISIONS 192): a quote request's part gaps are
notes, not to-dos. A quote request arrives in parts (the email's own text, an attached form or list), each read on its
own; one part often lacks what another has. So when a part lacks the customer or names no item, that is shown as a
note and does not hold back its package's approval; the quote package judges the gaps on the whole request. A doubt
about a value that is there (a tax number that fails its check, a JEV flag) stays a to-do. Every other type pack keeps
its to-dos as before. Synthetic emails, a stand-in JEV and GPT; no paid call.
"""

from __future__ import annotations

from jav.app import work_runs
from jav.ai import typepack
from jav.ai.models import DocumentRecord, FlowState, JevVerdicts
from jav.ai.policy import apply_validation_policy, apply_verdict_policy
from tests import test_email_text_follow_up_190 as follow
from tests.test_email_text_follow_up_190 import OUT, _package, _run

env = follow.env  # the 190 fixture: a mailbox package of one quote request email, a stand-in JEV and GPT


def test_only_the_quote_request_turns_its_gaps_into_notes():
    pack = typepack.get("quote_request")
    assert pack.required_review is False
    assert {v["check"]: v.get("review", True) for v in pack.validators} == {
        "tax_id": True, "list_rows": False, "list_values": False, "list_positive": False}
    assert [k for k in typepack.keys() if not typepack.get(k).required_review] == ["quote_request"]


def test_a_missing_required_field_is_a_note_that_opens_no_to_do():
    state = FlowState(source_path="x.txt", case_id="c", arm="G", doc_type="quote_request", record=DocumentRecord(),
                      verdicts=JevVerdicts())
    apply_verdict_policy(state)
    apply_validation_policy(state)
    assert not any(r.startswith("llm:required_missing") for r in state.review_reasons)
    note = next(c for c in state.validation if c.code == "required_missing")
    assert (note.name, note.ok, note.advisory) == ("required:customer_name", False, True)


def test_a_pack_that_reviews_its_required_fields_still_opens_the_to_do():
    state = FlowState(source_path="x.pdf", case_id="c", arm="G", doc_type="invoice_foreign", record=DocumentRecord(),
                      verdicts=JevVerdicts())
    apply_verdict_policy(state)
    assert any(r.startswith("llm:required_missing:") for r in state.review_reasons)
    assert not any(c.code == "required_missing" for c in state.validation)


def test_an_email_whose_text_names_no_item_is_not_held_back(env, monkeypatch):
    monkeypatch.setitem(OUT, "requested_items", [])  # the items would be in an attachment
    wp_id = _package(env)
    run_id, item = _run(wp_id)
    assert work_runs.item_reasons(run_id, item["item_id"], item)["run"] == []
    assert work_runs.approve_run(run_id, actor="t")["approval"] == "approved"


def test_a_doubt_about_a_value_the_text_has_stays_a_to_do_of_the_email(env, monkeypatch):
    monkeypatch.setitem(OUT, "customer_tax_number", "12345678-1-12")  # fails the tax number's check digit
    wp_id = _package(env)
    run_id, item = _run(wp_id)
    reasons = [r["reason"] for r in work_runs.item_reasons(run_id, item["item_id"], item)["run"]]
    assert any(r.startswith("validator:") and r.endswith(":customer_tax_number") for r in reasons)
