"""121 (Q-szerepcsere): a pair of parties whose roles stand the other way round than on the earlier documents.

A model that swaps the supplier's and the buyer's tax numbers leaves two well-formed, check-digit-valid values: no
field check fails. The stored results showed it once (092) on one invoice of a supplier with twenty invoices; across
documents, the same pair of tax numbers stood the other way round on 4 of them and on no confirmed one. Here: when
the same two parties appear on earlier documents of the same type mostly the other way round, the current document
gets a to-do at its second role field. The check reads only the store's earlier results, so it runs in a worker run
only; measurements and the command line stay independent of the store. All tax numbers are made up.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from jav import fact_checks, party_history, policy, store, typepack, validators
from jav.models import FlowState, InvoiceHU
from jav.runtime import calls

A, A_EU, B, C = "12121216-2-42", "HU12121216", "13570008-1-13", "12345676-2-41"  # made up (data guard allow list)
CHECK = [{"check": "party_orientation", "fields": ["supplier_tax_id", "buyer_tax_id"]}]


@pytest.fixture
def history(tmp_path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield


def _earlier(doc_id: str, supplier: str, buyer: str, doc_type: str = "invoice_hu") -> None:
    store.insert_datapoints(run_id=f"run-earlier:{doc_id}", doc_id=doc_id, doc_type=doc_type, arm="S",
                            datapoints={"supplier_tax_id": supplier, "buyer_tax_id": buyer}, field_conf={}, validation=[],
                            route="auto", review_reasons=[], final_status="done")


def _check(supplier: str, buyer: str, *, doc_id: str = "doc-now", doc_type: str = "invoice_hu", in_run: bool = True):
    inv = InvoiceHU(supplier_tax_id=supplier, buyer_tax_id=buyer)
    if not in_run:
        return validators.run_checks(inv, CHECK, doc_id=doc_id, doc_type=doc_type)
    calls.set_budget("run-now", "jev", Decimal("0.01"))
    with calls.use_run(budget_scope="run-now"):
        return validators.run_checks(inv, CHECK, doc_id=doc_id, doc_type=doc_type)


def test_a_reversed_pair_against_a_clear_majority_opens_a_to_do(history):
    for n in range(4):
        _earlier(f"doc-{n}", A, B)
    (result,) = _check(B, A)
    assert not result.ok and result.code == "parties.orientation_reversed" and result.name == "party_orientation:buyer_tax_id"
    assert result.detail == "4 the other way, 0 alike"  # counts of earlier documents only, never the values
    state = FlowState(source_path="synthetic.pdf", case_id="synthetic", arm="G", doc_type="invoice_hu")
    state.validation = [result]
    policy.apply_validation_policy(state)
    assert "validator:parties.orientation_reversed:buyer_tax_id" in state.review_reasons


def test_the_usual_orientation_passes(history):
    for n in range(4):
        _earlier(f"doc-{n}", A, B)
    (result,) = _check(A, B)
    assert result.ok and result.code == "parties.orientation_ok"


def test_the_domestic_and_eu_forms_of_one_tax_number_are_one_party(history):
    for n in range(3):
        _earlier(f"doc-{n}", A_EU, B)
    (result,) = _check(B, A)
    assert not result.ok
    assert fact_checks.tax_party_key(A) == fact_checks.tax_party_key(A_EU) != fact_checks.tax_party_key(B)


@pytest.mark.parametrize("usual,reversed_,flagged", [
    (1, 0, False),  # a single earlier document is not a majority
    (2, 0, True),
    (3, 2, False),  # both orientations are common: two-way business, no to-do
    (4, 2, True),   # at least twice as many the usual way
])
def test_only_a_clear_majority_counts(history, usual, reversed_, flagged):
    for n in range(usual):
        _earlier(f"usual-{n}", A, B)
    for n in range(reversed_):
        _earlier(f"reversed-{n}", B, A)
    (result,) = _check(B, A)
    assert (not result.ok) == flagged


def test_only_documents_of_the_same_type_count(history):
    for n in range(4):
        _earlier(f"doc-{n}", A, B, doc_type="invoice_out")  # the owner's own outgoing invoices
    assert _check(B, A) == []


def test_the_document_itself_and_other_pairs_do_not_count(history):
    for n in range(4):
        _earlier("doc-now", A, B)  # earlier results of the very same document
        _earlier(f"other-{n}", A, C)
    assert _check(B, A) == []


def test_the_latest_result_of_each_earlier_document_counts_once(history):
    _earlier("doc-1", A, B)
    _earlier("doc-1", A, B)  # a second run of the same document
    _earlier("doc-2", A, B)
    with calls.use_run(budget_scope="run-now"):
        assert party_history.orientation("doc-now", "invoice_hu", ("supplier_tax_id", "buyer_tax_id"), (B, A)) == (2, 0)


def test_outside_a_worker_run_the_store_is_not_read(history):
    for n in range(4):
        _earlier(f"doc-{n}", A, B)
    assert _check(B, A, in_run=False) == []


def test_a_missing_or_unreadable_value_is_skipped(history):
    for n in range(4):
        _earlier(f"doc-{n}", A, B)
    assert _check(B, "") == [] and _check("n/a", A) == []


@pytest.mark.parametrize("key", ["invoice_hu", "invoice_foreign", "invoice_out"])
def test_invoice_packs_check_the_orientation_of_their_tax_numbers(key):
    pairs = [v["fields"] for v in typepack.get(key).validators if v["check"] == "party_orientation"]
    assert pairs == [["supplier_tax_id", "buyer_tax_id"]]
