"""134 (backlog Q-supplier-tax): a supplier's tax number read on the buyer's side, and an own party's number as the
supplier's.

The store showed it (DECISIONS 134): on some invoices the supplier's and the buyer's tax numbers were swapped, or the
supplier's number was read as the buyer's too, and the own-party proposal of 133 then gave a rail company's and a
service provider's numbers to the buyer company. Now such a number teaches nothing about the buyer, and an incoming
invoice whose supplier number is an own party's gets a to-do. Made-up tax numbers (the data guard's allowed ones)."""

from __future__ import annotations

import pytest

from jav import parties, store
from jav.runtime import calls

BUYER, RAIL, SECOND, OTHER = "12121216-2-42", "13570008-1-13", "21357912-1-13", "12345676-2-41"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "p.sqlite"):
        yield


def _inv(tax, supplier_tax, name="Example Buyer Kft.", supplier="Example Rail Zrt."):
    return {"name": name, "tax_id": tax, "supplier_name": supplier, "supplier_tax_id": supplier_tax}


def _invoices():
    return ([_inv(BUYER, RAIL)] * 6          # read right
            + [_inv(RAIL, RAIL)] * 3         # the supplier's number on both sides (left out since 133)
            + [_inv(RAIL, BUYER)] * 2        # swapped
            + [_inv(RAIL, None)] * 2         # the supplier's number on the buyer's side, no supplier number read
            + [_inv(SECOND, OTHER, supplier="Example Shop Kft.")] * 3)  # a genuine second number of the buyer


def _taxes(result):
    found = {i["key"] for s in result["suggestions"] for i in s["identities"] if i["kind"] == "tax"}
    return found | {u["key"] for u in result["unassigned"] if u["kind"] == "tax"}


def test_a_suppliers_number_read_on_the_buyers_side_is_not_proposed(db):
    result = parties.suggest(_invoices(), [])
    assert parties.tax_key(RAIL) not in _taxes(result)
    [group] = result["suggestions"]
    keys = {(i["kind"], i["key"]) for i in group["identities"]}
    assert {("tax", parties.tax_key(BUYER)), ("tax", parties.tax_key(SECOND))} <= keys
    assert ("name", parties.name_key("Example Buyer Kft.")) in keys
    assert group["invoices"] == 13 and result["buyer_is_supplier"] == 3  # the swapped ones still count by their name


def test_the_swapped_and_the_foreign_numbers_are_found_by_position():
    invoices = _invoices()
    found = parties._supplier_tax_numbers(invoices)
    assert found == set(range(9, 13))  # the two swapped and the two without a supplier number


def test_a_buyer_number_printed_more_often_as_the_buyers_stays():
    invoices = [_inv(BUYER, RAIL)] * 3 + [_inv(RAIL, BUYER)]  # one swapped invoice cannot take the buyer's number away
    assert parties._supplier_tax_numbers(invoices) == {3}


# --- the to-do -------------------------------------------------------------------------------------------------------


def _own():
    return parties.create("Example Buyer Kft.", identities=[("tax", parties.tax_key(BUYER), BUYER)], actor="tester")


@pytest.mark.parametrize("doc_type, supplier_tax, buyer_tax, wanted", [
    ("invoice_hu", BUYER, None, ["parties:own_tax_as_supplier"]),
    ("invoice_hu", BUYER, RAIL, ["parties:own_tax_as_supplier"]),
    ("viz_szamla", BUYER, None, ["parties:own_tax_as_supplier"]),
    ("invoice_hu", BUYER, BUYER, []),       # the role-pair check's (validator:parties.same_entity)
    ("invoice_hu", RAIL, BUYER, []),
    ("invoice_out", BUYER, RAIL, []),       # an outgoing invoice is the own party's
    ("invoice_hu", None, BUYER, []),
])
def test_an_own_partys_number_as_the_suppliers_opens_a_to_do_in_a_worker_run(db, doc_type, supplier_tax, buyer_tax, wanted):
    _own()
    values = {"supplier_tax_id": supplier_tax, "buyer_tax_id": buyer_tax}
    assert parties.review_reasons(doc_type, values) == []  # outside a worker run the store is not read
    with calls.use_run(budget_scope="run-000000000001"):
        assert parties.review_reasons(doc_type, values) == wanted
    with calls.measurement("measure-x", {}):
        assert parties.review_reasons(doc_type, values) == []


def test_a_dismissed_number_opens_no_to_do(db):
    parties.assign("tax", parties.tax_key(BUYER), BUYER, None, actor="tester")
    with calls.use_run(budget_scope="run-000000000001"):
        assert parties.review_reasons("invoice_hu", {"supplier_tax_id": BUYER}) == []


def test_the_flow_asks_the_check_for_incoming_invoice_types():
    from jav import policy

    assert "invoice_hu" in parties.supplier_check_types() and "invoice_out" not in parties.supplier_check_types()
    assert "apply_party_policy(state)" in open(policy.__file__, encoding="utf-8").read()
