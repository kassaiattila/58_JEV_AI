"""149 (backlog F-type-uncertainty-outgoing; DECISIONS 149): the parties confirm an outgoing invoice's detailed type.

The 43 outgoing invoices of an own company were recognised as outgoing invoices, 21 of them with a JEV confidence of only
0.46-0.59 against the incoming Hungarian invoice (a to-do each). The text cannot say which side is "us"; the code can,
once the data is extracted: the own parties' tax numbers and names give the invoice's direction (147, 148). So when
the detailed type was uncertain between an outgoing and an incoming pack (`policy.json`
`detect_detail.direction_sides`), the extraction compares it with the direction the parties alone give (not the type,
which would confirm itself): a match closes the uncertainty to-do, a contradiction is a to-do of its own. Any other
uncertainty (a gas bill against an invoice, say) is left as it was.

Synthetic parties, invoices and probabilities only; no AI call.
"""

from __future__ import annotations

import pytest

from jav import flow, parties, policy, store
from jav.models import FlowState, InvoiceHU

OWN_TAX = "28642099-2-42"
SURE = {"invoice_hu": 0.29, "invoice_out": 0.70, "none": 0.01}


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        parties.create("Sample Own Company", identities=[("tax", parties.tax_key(OWN_TAX), OWN_TAX),
                                                         ("name", "sample own company", "Sample Own Company Kft.")], actor="t")
        yield


@pytest.mark.parametrize("key, probabilities, direction, verdict", [
    ("invoice_out", SURE, "outgoing", "confirmed"),
    ("invoice_out", SURE, "incoming", "contradicted"),
    ("invoice_out", SURE, "unclear", None),
    ("invoice_out", SURE, "not_own", None),
    ("invoice_hu", {"invoice_hu": 0.6, "invoice_out": 0.39}, "incoming", "confirmed"),
    ("invoice_hu", {"invoice_hu": 0.6, "invoice_out": 0.39}, "outgoing", "contradicted"),
    ("invoice_hu", {"invoice_hu": 0.6, "foldgaz_szamla": 0.39, "invoice_out": 0.01}, "incoming", None),  # not about direction
    ("invoice_out", {}, "outgoing", None),
    ("foldgaz_szamla", {"foldgaz_szamla": 0.6, "invoice_out": 0.4}, "incoming", None),  # no side of its own
])
def test_the_direction_settles_only_an_uncertainty_about_direction(key, probabilities, direction, verdict):
    assert policy.detail_direction(key, probabilities, direction) == verdict


def _uncertain(doc_id: str = "d1") -> None:
    store.review_enqueue(subject_kind="document", subject_id=doc_id, run_id="run-a:item-1-doc_detect", producer="detect_detail",
                         reasons=["detect_detail:low_conf:invoice_out:0.55"], payload={"detail": {"probabilities": SURE}})


def _state(**invoice) -> FlowState:
    return FlowState(source_path="invoice.pdf", case_id="c", arm="G", run_id="run-a:item-1", doc_id="d1", doc_type="invoice_out",
                     detail_probabilities=SURE, invoice=InvoiceHU(**invoice))


def _open() -> list[str]:
    return [r["reason"] for r in store.review_open_reasons("document", "d1")]


def test_the_own_party_as_supplier_closes_the_uncertainty(db):
    _uncertain()
    flow.confirm_detail_by_direction(_state(supplier_name="Sample Own Company Kft.", supplier_tax_id=OWN_TAX,
                                            buyer_name="Northwind Trading Ltd."))
    assert _open() == []


def test_the_own_party_as_buyer_is_a_to_do_and_the_uncertainty_stays(db):
    _uncertain()
    flow.confirm_detail_by_direction(_state(supplier_name="Northwind Trading Ltd.", buyer_name="Sample Own Company Kft.",
                                            buyer_tax_id=OWN_TAX))
    assert _open() == ["detect_detail:low_conf:invoice_out:0.55", "detect_detail:direction_mismatch:invoice_out:incoming"]


def test_the_type_alone_is_no_evidence(db):
    # neither side is an own party: the outgoing type would make it outgoing, but that would confirm itself
    _uncertain()
    flow.confirm_detail_by_direction(_state(supplier_name="Somebody Kft.", buyer_name="Northwind Trading Ltd."))
    assert _open() == ["detect_detail:low_conf:invoice_out:0.55"]


def test_without_the_detection_probabilities_nothing_changes(db):
    _uncertain()
    state = _state(supplier_name="Sample Own Company Kft.", supplier_tax_id=OWN_TAX, buyer_name="Northwind Trading Ltd.")
    state.detail_probabilities = {}
    flow.confirm_detail_by_direction(state)
    assert _open() == ["detect_detail:low_conf:invoice_out:0.55"]


def test_the_worker_passes_the_detection_probabilities_to_the_extraction():
    from jav.runtime import worker

    detected = {"final_status": "done", "detail": {"key": "invoice_out", "probabilities": SURE}}
    params = worker._next_params({"arm": "auto"}, detected)
    assert params["doc_type"] == "invoice_out" and params["detail_probabilities"] == SURE
