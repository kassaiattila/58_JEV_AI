"""147 (backlog F-invoice-direction; DECISIONS 147): an invoice's direction, from the own parties' identities.

The owner's decision of 2026-10-12: incoming and outgoing invoices are told apart. An invoice whose buyer is an own
party is that party's incoming invoice; one whose supplier is an own party is that party's outgoing invoice (as is an
invoice typed as outgoing); one with own parties on both sides is between own parties (incoming for the buyer, outgoing
for the supplier); one with none is not an own party's. The store showed 54 invoices with an own party as the supplier,
2 of them typed as outgoing: the others were taken as incoming invoices and could be proposed as a payment's invoice.
Now such an invoice is left out of the pairing of payments (as an outgoing invoice), and the run's documents show the
direction.

Synthetic documents and made-up parties only; no AI call.
"""

from __future__ import annotations

import pytest

from jav.app import export, parties
from jav.core import store
from jav.domains.finance import reconcile
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_package_131 import _line, _stmt

CLUB_TAX = "13570008-1-13"  # a sample number on the data guard's allow list


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _parties() -> tuple[str, str]:
    home = parties.create("Example Home", identities=[("name", "jane example", "Jane Example")], actor="t")["id"]
    club = parties.create("Sporting Club", identities=[("tax", parties.tax_key(CLUB_TAX), CLUB_TAX),
                                                       ("name", "sporting club", "Sporting Club")], actor="t")["id"]
    return home, club


def _direction(**values) -> tuple[str, str | None]:
    return parties.direction(parties.resolver(), values.pop("doc_type", "invoice_hu"), values)


# --- the direction --------------------------------------------------------------------------------------------------------


def test_the_direction_comes_from_the_own_parties_on_the_two_sides(db):
    home, club = _parties()
    assert _direction(buyer_name="Jane Example", supplier_name="Example Supplier Kft.") == ("incoming", home)
    assert _direction(supplier_name="Sporting Club", supplier_tax_id=CLUB_TAX, buyer_name="A Customer Bt.") == ("outgoing", club)
    assert _direction(supplier_tax_id=CLUB_TAX, buyer_name="Jane Example") == ("internal", None)
    assert _direction(supplier_name="Example Supplier Kft.", buyer_name="Someone Else") == ("not_own", None)
    assert _direction(supplier_tax_id=CLUB_TAX, buyer_tax_id=CLUB_TAX) == ("unclear", None)  # the same party twice
    # an invoice typed as outgoing is outgoing, with its supplier's party when it is known
    assert _direction(doc_type="invoice_out", buyer_name="A Customer Bt.") == ("outgoing", None)
    assert _direction(doc_type="invoice_out", supplier_tax_id=CLUB_TAX, buyer_name="A Customer Bt.") == ("outgoing", club)


def test_the_buyer_fields_are_read_by_the_reconciliations_field_names(db):
    home, _club = _parties()
    assert _direction(customer_name="Jane Example") == ("incoming", home)  # the utility packs' buyer name


# --- the pairing of payments ---------------------------------------------------------------------------------------------


def test_an_own_partys_outgoing_invoice_is_no_payments_candidate(db):
    # 148: no longer left out of the pairing; incoming money pays it (tests/test_reconcile_outgoing_148.py), a payment never
    _home, _club = _parties()
    out = k2._save("out", k2._invoice(number="OUT-1", supplier_name="Sporting Club", supplier_tax_id=CLUB_TAX,
                                       buyer_name="A Customer Bt."))
    internal = k2._save("internal", k2._invoice(number="INT-1", amount="55.00", supplier_name="Sporting Club",
                                                supplier_tax_id=CLUB_TAX, buyer_name="Jane Example"))
    _stmt("stmt", _line(memo="OUT-1"), _line(amount="55.00", memo="INT-1"))
    snap = reconcile.snapshot()
    directions = {i["id"]: i["direction"] for i in snap["invoices"]}
    assert directions == {out: "outgoing", internal: "internal"}
    result = reconcile.propose(snap)
    assert not [e for e in result["excluded"] if e["kind"] == "invoice"]
    assert {c["invoice_id"] for c in result["candidates"]} == {internal}  # the buyer's incoming invoice is still paid


def test_the_golden_case_of_an_invoice_whose_supplier_is_an_own_party():
    case = next(c for c in reconcile.golden_cases() if c["id"] == "own_supplier_outgoing")
    assert reconcile.check_case(case) == []


# --- the run's documents --------------------------------------------------------------------------------------------------


def test_the_documents_table_shows_an_invoices_direction(db):
    _home, club = _parties()
    rec = {"file": "a.pdf", "item_id": "x", "doc_type": "invoice_hu", "arm": "S", "final_status": "done", "open_reasons": [],
           "fields": {"supplier_name": "Sporting Club", "supplier_tax_id": CLUB_TAX, "buyer_name": "A Customer Bt."}}
    other = {**rec, "item_id": "y", "doc_type": "certificate", "fields": {"title": "A certificate"}}
    head, rows = export.documents_table([rec, other])
    at = head.index("Direction")
    assert [r[at] for r in rows] == ["outgoing", None]  # only an invoice has a direction
    assert club
