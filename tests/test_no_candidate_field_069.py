"""069 (066 Á11, decision of 2026-09-29): a field without candidates.

- The field's confidence is None (until then 1.0, and the UI showed the empty field as "Magabiztos", i.e. confident).
- For the band-checked optional fields the presence question goes into a request even without a candidate, but only
  into a request that is sent anyway (no new call needed). If JEV says the value is on the document: a to-do (the code
  did not find it).
- The stored field confidence is the weaker of the Choice and the presence judgement (until then the raw Choice).
Offline, with a fake client; the lines and the candidates are made up."""

from __future__ import annotations

from pathlib import Path

from typesafe_sdk import Noul

from jav import policy, store
from jav.adapters.jev import JevAdapter
from jav.jev_select import field_confidence, select_fields
from jav.models import FieldPick, FlowState
from tests.test_select_presence import LINES, FakeClient, _cands


def test_no_candidate_field_gets_a_presence_question_in_an_existing_request(tmp_path: Path):
    client = FakeClient(nouls={"payment_iban__present": 0.93})
    jev = JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "t.sqlite"):  # the call log goes into the test's own store
        picks, calls = select_fields(jev, LINES, _cands(), run_id="r")

    money = next(r for r in client.requests if "gross_total" in r["questions"])
    assert isinstance(money["questions"]["payment_iban__present"], Noul) and "payment_iban" not in money["questions"]
    p = picks["payment_iban"]
    assert p.n_options == 0 and p.confidence is None and p.present_p == 0.93
    assert len(calls) == 3  # the same three requests, no new call
    asked = {q for r in client.requests for q in r["questions"]}
    assert "invoice_number__present" not in asked  # required field: the old "no candidate" to-do stays, no question
    assert "supplier_address__present" not in asked  # informative-only field: no check


def test_present_but_no_candidate_opens_a_task():
    def pick(field: str, p: float) -> FieldPick:
        return FieldPick(field=field, label=None, confidence=None, present_p=p, n_options=0, request_id="money")

    st = FlowState(source_path="x.pdf", case_id="c", arm="S",
                   picks={"payment_iban": pick("payment_iban", 0.93), "vat_total": pick("vat_total", 0.08), "net_total": pick("net_total", 0.5)})
    policy.apply_pick_policy(st)
    assert st.review_reasons == ["pick:present_no_candidates:payment_iban:0.93"]  # absent and uncertain: no reason


def test_stored_confidence_is_none_without_candidates_and_the_weaker_judgment_otherwise():
    picks = {
        "a": FieldPick(field="a", label="x", confidence=0.9, present_p=0.2, n_options=2, request_id="r"),
        "b": FieldPick(field="b", label="y", confidence=0.8, n_options=3, request_id="r"),
        "f": FieldPick(field="f", label=None, confidence=None, present_p=0.9, n_options=0, request_id="r"),
    }
    assert field_confidence(picks) == {"a": 0.2, "b": 0.8, "f": None}
