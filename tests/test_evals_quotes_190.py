"""190 (plan 189 A2g): the quote request's golden runs and their place in the shared measurement command.

The intent part counts the 13 invented emails' intents; the request part reads the 10 requests from each email's own
text and its attachments and counts the judgements: each header field, each request's number of items and each item's
quantity (the units only as information: the expected unit is the price list's). A stand-in reader that returns the
expected request must score every judgement right, and one that misses an item must lose its row count and its
quantity. Stand-ins only; no model call.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from jav.evals import evals_quotes, goldens
from jav.ai import typepack
from jav.domains.quotes import invented_golden
from jav.ai.models import record_from_llm

GOLDEN = invented_golden.load()
CASES = {c.id: c for c in GOLDEN.cases}


# --- the comparison ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("field", "got", "expected", "right"), [
    ("contact_phone", "+36 30 123 4567", "06-30-123-4567", True),
    ("contact_phone", "06 30 123 4567", "06-30-123-4567", True),
    ("contact_phone", "+36 20 000 1234", "06-30-123-4567", False),
    ("contact_email", "Kovacs.Anna@Pelda.hu", "kovacs.anna@pelda.hu", True),
    ("customer_name", "Példa Könyvelő Bt", "Példa Könyvelő Bt.", True),
    ("customer_tax_number", "12345676241", "12345676-2-41", True),
    ("deadline", "2026.10.16.", "2026-10-16", True),
    ("reference", None, None, True),
    ("reference", "BSZ-2026-118", None, False),
    ("deadline", None, "2026-10-16", False),
])
def test_a_field_is_compared_by_its_kind(field, got, expected, right):
    assert evals_quotes.field_right(field, got, expected) is right


def test_the_text_comes_first_and_the_items_from_an_attachment_with_rows():
    text = {"customer_name": "Minta Kft.", "deadline": None, "requested_items": [{"description": "a", "quantity": 1}]}
    form = {"customer_name": "Minta Korlátolt", "deadline": "2026-10-22", "requested_items": [{"description": "b", "quantity": 2}]}
    got = evals_quotes.merged([text, form])
    assert got["customer_name"] == "Minta Kft." and got["deadline"] == "2026-10-22"
    assert got["requested_items"] == form["requested_items"]
    assert evals_quotes.merged([text, {"requested_items": []}])["requested_items"] == text["requested_items"]


def test_a_missing_item_loses_its_row_count_and_its_quantity():
    request = CASES["q01_hu_office_body"].expected.request
    got = {**request.model_dump(mode="json"), "requested_items": [
        {"description": i.written, "quantity": str(i.quantity), "unit": i.unit} for i in request.items[:-1]]}
    s = evals_quotes.score(got, request)
    assert all(s["fields"].values()) and s["row_count"] is False and s["quantities"] == [True] * 4 + [False]
    right, scored = evals_quotes.judgements([{"score": s}])
    assert (right, scored) == (7 + 4, 7 + 1 + 5)


# --- the shared measurement command --------------------------------------------------------------------------------------


def test_both_parts_are_golden_sets_of_the_shared_command():
    intents, requests = goldens.get("quotes:intents"), goldens.get("quotes:requests")
    assert (intents.layer, intents.owner, intents.count()) == ("intent", "email_intent", 13)
    assert (requests.layer, requests.owner, requests.count()) == ("datapoints", "quote_request", 10)
    assert intents.engines == requests.engines == goldens.ENGINES
    assert [g.key for g in goldens.select(["quotes"])] == ["quotes:requests", "quotes:intents"]  # the layers' order


# --- a stand-in reader -------------------------------------------------------------------------------------------------


def _record(values: dict):
    pack = typepack.get(evals_quotes.TYPE)
    record, _ = record_from_llm(values, pack.fields, list_fields=pack.list_fields)
    return record


def _perfect(source_path, case_id, arm, *, use_cache, doc_type, jev, source_text=None):
    """The expected request from the email's text; nothing from an attachment."""
    case = CASES[case_id.split("-", 1)[0]]
    if source_text is None:
        return SimpleNamespace(record=_record({}), final_status="done", review_reasons=[])
    request = case.expected.request.model_dump(mode="json")
    items = [{"description": i["written"], "quantity": i["quantity"], "unit": i["unit"]} for i in request.pop("items")]
    return SimpleNamespace(record=_record({**request, "requested_items": items}), final_status="done", review_reasons=[])


def test_a_perfect_reader_scores_every_judgement(tmp_path, monkeypatch):
    from jav.flows import flow_detect

    monkeypatch.setattr(evals_quotes, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(flow_detect, "run_detect", lambda *a, **k: SimpleNamespace(result=SimpleNamespace(doc_type="quote_request")))
    rows = evals_quotes.quote_requests(run_one=_perfect)
    assert len(rows) == 10 and all(r["score"] for r in rows)
    right, scored = evals_quotes.judgements(rows)
    assert right == scored == 10 * 7 + 10 + sum(len(c.expected.request.items) for c in GOLDEN.cases if c.expected.request)
    pdfs = [s for r in rows for s in r["sources"] if "detected" in s]
    assert [s["source"] for s in pdfs] == ["keroiv_halozat.pdf", "igenyek.pdf"]  # the Excel lists are not recognised
    assert len(list(tmp_path.glob("*_quote_requests.jsonl"))) == 1


def test_the_intents_are_counted_against_the_expected_ones(tmp_path, monkeypatch):
    from jav.domains.email import flow_email

    def run_email(source_dir, **_kw):
        case = CASES[source_dir.replace("\\", "/").rsplit("/", 1)[-1]]
        got = "business_correspondence" if case.id == "q06_hu_support_reply" else case.expected.intent
        return SimpleNamespace(result=SimpleNamespace(intent=got, confidence=0.9, probabilities={}), next_flow="x",
                               review_reasons=[])

    monkeypatch.setattr(evals_quotes, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(flow_email, "run_email", run_email)
    rows = evals_quotes.quote_intents()
    assert len(rows) == 13 and sum(r["got"] == r["expected"] for r in rows) == 12
    outcome = goldens._case_outcome(rows)
    assert (outcome.cases, outcome.answered, outcome.right) == (13, 13, 12)


def test_the_expected_dates_are_dates():
    assert CASES["q01_hu_office_body"].expected.request.deadline == date(2026, 10, 16)
    assert CASES["q01_hu_office_body"].expected.request.items[0].quantity == Decimal("5")


def test_the_legacy_intent_golden_set_counts_an_unanswered_email_without_a_result(tmp_path, monkeypatch):
    """190: with a new intent every question is new; a round without a budget has no earlier answer, and an email
    without one is a row without a result (it stopped the whole set with an assertion before)."""
    from jav.evals import evals_email
    from jav.core import store
    from jav.ai import jev as jev_mod
    from jav.domains.email.emails import EmailMessage, GoldenEmail
    from tests.test_email_signals import FakeClient

    case = GoldenEmail(case_id="c1", expected="other", source="t", message=EmailMessage(message_id="golden:c1", subject="s", body="b"))
    monkeypatch.setattr(evals_email, "_cases", lambda limit=None: [case])
    monkeypatch.setattr(evals_email, "RUNS_DIR", tmp_path)
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "e.sqlite"), jev_mod.use_adapter(adapter):
        rows = evals_email.email_golden()
    assert [(r["got"], r["engine"]) for r in rows] == [(None, "jev")]
    assert goldens._case_outcome(rows).without_result == 1
