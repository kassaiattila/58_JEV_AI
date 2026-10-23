"""190 (plan 189 A2e): the quote request's registrations: its type pack, its detection type and its email intent.

A customer's request for a price quote is a type pack of the G path that reads an email's own text, a request form
(PDF) or a request list (Excel, CSV); its detection type and its family are new, and so is its email intent, whose
route is the quote request's data extraction. Its verification call site asks no invoice question, and asks each
requested item list about missing and extra rows. Synthetic texts and stand-in clients only; no paid call.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from typesafe_sdk import Noul

from jav import detect_detail, doc_types, extract_llm, flow, naming, policy, text_document, typepack
from jav.core import store
from jav.domains.email import intents
from jav.adapters import jev as jev_mod
from jav.domains.email.emails import Attachment
from jav.jev_verify import site_for
from jav.models import JevCall
from tests.test_no_jev_085 import _FakeAgent

KEY = "quote_request"
EMAIL = """From: Teszt Elek <teszt.elek@minta.hu>
Date: 2026-11-02T10:00:00+01:00
Subject: Ajanlatkeres irodai eszkozokre

Jo napot!

Arajanlatot kernenk az alabbiakra:
- 3 db 24 colos monitor
- 2 szett billentyuzet es eger

Az ajanlatot 2026. november 20-ig kernenk.

Udvozlettel:
Teszt Elek
Minta Szolgaltato Kft.
Adoszam: 12345676-2-41
"""
OUT = {"customer_name": "Minta Szolgaltato Kft.", "customer_tax_number": "12345676-2-41", "contact_name": "Teszt Elek",
       "contact_email": "teszt.elek@minta.hu", "contact_phone": None, "deadline": "2026-11-20", "reference": None,
       "requested_items": [{"description": "24 colos monitor", "quantity": 3, "unit": "db"},
                           {"description": "billentyuzet es eger", "quantity": 2, "unit": "szett"}]}


@pytest.fixture()
def db(tmp_path: Path):
    with store.use_store(tmp_path / "t190q.sqlite"):
        yield tmp_path


# --- the registrations ----------------------------------------------------------------------------------------------


def test_the_pack_reads_every_input_on_the_g_path():
    pack = typepack.get(KEY)
    assert pack.arms == ("G",) and pack.default_arm == "G" and pack.inputs == ("pdf", "text", "table")
    assert pack.parent == KEY and pack.source_prefix.startswith("SOURCE TEXT of the request")
    assert pack.header_fields == ("customer_name", "customer_tax_number", "contact_name", "contact_email", "contact_phone",
                                  "deadline", "reference")
    assert pack.list_fields == {"requested_items": {"description": "text", "quantity": "number", "unit": "text"}}
    assert KEY in typepack.extractable_keys()


def test_its_output_model_has_the_requested_items_as_rows():
    model = typepack.get(KEY).llm_model()
    out = model.model_validate(OUT)
    assert out.requested_items[1].unit == "szett" and out.requested_items[0].quantity == 3


def test_the_detection_type_is_its_own_family_and_needs_no_detail_question():
    t = doc_types.BY_KEY[KEY]
    assert t.parent == "request_like" and "request_like" in doc_types.PARENTS
    other = doc_types.BY_KEY["other"]
    assert "(quote_request)" in other.not_for
    result = detect_detail.resolve(KEY, "Ajanlatkero iv", jev=None, run_id="t")
    assert (result.key, result.method) == (KEY, "single")


def test_the_intent_routes_to_the_quote_requests_extraction():
    intent = intents.BY_KEY[KEY]
    assert intent.document_bearing and intent.parent == "human_correspondence"
    assert policy.INTENT_ROUTE[KEY] == f"m2:{KEY}" and KEY in policy.M2_TYPES
    assert policy.email_next_flow(KEY, 0.97, [], {KEY: 0.97, "business_correspondence": 0.02}) == f"m2:{KEY}"
    form = Attachment(filename="keroiv.pdf", path="keroiv.pdf", doc_type=KEY, status="done")
    assert policy.email_next_flow(KEY, 0.97, [form], {KEY: 0.97}) == f"m2:{KEY}"


def test_the_examples_are_not_the_invented_golden_emails():
    from jav.domains.quotes import invented_golden

    subjects = {c.message.subject.casefold() for c in invented_golden.load().cases}
    assert not {e.casefold() for e in intents.BY_KEY[KEY].examples} & subjects


def test_its_file_name_is_the_deadline_the_type_and_the_customer():
    pack = typepack.get(KEY)
    name = naming.name_for(KEY, {"customer_name": "Minta Szolgaltato Kft.", "deadline": date(2026, 11, 20)}, dict(pack.fields),
                           original="message.json", rules=naming.rules())
    assert name.stem == "2026-11-20_AJANLATKERES_Minta-Szolgaltato-Kft" and name.missing == ()


# --- its verification -----------------------------------------------------------------------------------------------


def test_the_verification_asks_no_invoice_question_and_asks_the_items_list():
    site = site_for(KEY)
    assert site.document_nouls == () and site.list_nouls == ("missing_rows", "extra_rows")
    questions = site.build_questions({f: None for f in typepack.get(KEY).header_fields}, {})
    assert not set(site_for("invoice_hu").document_nouls) & set(questions)
    assert {"requested_items__missing_rows", "requested_items__extra_rows"} <= set(questions)
    texts = " ".join(str(q.instructions) for q in questions.values()).casefold()
    assert "invoice" not in texts and "supplier" not in texts


# --- the extraction from an email's own text ------------------------------------------------------------------------


class _Jev:
    def __init__(self) -> None:
        self.questions: dict = {}

    def ask(self, request_id, state, questions, **_kw):
        self.questions = questions
        nouls = {q: SimpleNamespace(noul=0.03) for q, v in questions.items() if isinstance(v, Noul)}
        return SimpleNamespace(response=SimpleNamespace(nouls=nouls, model="jev-test"),
                               call=JevCall(request_id=request_id, n_questions=len(questions), state_chars=0))


def _run(*, jev: bool):
    with extract_llm.use_agent_factory(lambda pack: _FakeAgent(pack, OUT)):
        app = flow.build_app("inbox/box/m1/message.json", "c190q", "G", tracker=False, doc_type=KEY, source_text=EMAIL,
                             jev=jev)
        action, _, state = app.run(halt_after=flow.TERMINALS)
    return action.name, state.data


def test_a_request_in_an_emails_text_is_extracted_and_checked(db, monkeypatch):
    jev = _Jev()
    monkeypatch.setattr(jev_mod, "get_adapter", lambda: jev)
    terminal, state = _run(jev=True)
    assert state.doc_id == text_document.text_digest(EMAIL)
    record = state.record
    assert record.extra["customer_name"] == "Minta Szolgaltato Kft." and record.extra["deadline"] == date(2026, 11, 20)
    assert record.extra["requested_items"] == [{"description": "24 colos monitor", "quantity": Decimal("3"), "unit": "db"},
                                               {"description": "billentyuzet es eger", "quantity": Decimal("2"), "unit": "szett"}]
    assert {c.name: c.ok for c in state.validation} == {"tax_id:customer_tax_number": True, "list_rows:requested_items": True,
                                                         "list_values:requested_items": True, "list_positive:requested_items": True}
    assert "requested_items__missing_rows" in jev.questions
    assert state.verdicts.unsupported == []  # "2026. november 20-ig" is the deadline's evidence, read by the code
    assert terminal == "done" and state.review_reasons == []


def test_without_jev_the_code_checks_the_request(db, monkeypatch):
    monkeypatch.setattr(jev_mod, "get_adapter", lambda: pytest.fail("JEV was asked on the path without JEV"))
    _terminal, state = _run(jev=False)
    assert state.verdicts.source == "code"
    assert "customer_name" not in state.verdicts.unsupported and "contact_email" not in state.verdicts.unsupported
    assert all(c.ok for c in state.validation)
