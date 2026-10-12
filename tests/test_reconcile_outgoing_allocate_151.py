"""151: allocating a customer's payment to an outgoing invoice.

148 taught the engine to propose incoming money for an own party's outgoing invoice, but the package's allocation still
refused every invoice of the outgoing type ("an outgoing invoice is not paid from an own account"), so accepting the
sure pairs failed for a whole package as soon as one of them was a customer's payment. The allocation now follows the
engine's side rule (`reconcile.pays`): incoming money pays an outgoing invoice, a payment an incoming one. Synthetic
data, no paid calls.
"""

from __future__ import annotations

import pytest

from jav import parties, store
from jav import reconcile_package as rp
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_outgoing_148 import CLUB_TAX
from tests.test_reconcile_package_131 import OWN_KEY, _stmt
from tests.test_reconcile_package_131 import _line as _pkg_line


@pytest.fixture
def package(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        club = parties.create("Sporting Club", identities=[("tax", parties.tax_key(CLUB_TAX), CLUB_TAX),
                                                           ("name", "sporting club", "Sporting Club")], actor="t")["id"]
        out = k2._save("out", k2._invoice(number="OUT-1", supplier_name="Sporting Club", supplier_tax_id=CLUB_TAX,
                                           buyer_name="Northwind Trading Ltd."), doc_type="invoice_out")
        inc = k2._save("in", k2._invoice(number="INV-7", amount="40.00"))
        stmt = _stmt("stmt", _pkg_line(memo="OUT-1", direction="credit", counterparty_name="Northwind Trading"),
                     _pkg_line(memo="INV-7", amount="40.00"))
        wp = rp.create(name="April", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="reviewer",
                       party_id=club)["workpackage_id"]
        lines = {ln["direction"]: ln["id"] for ln in rp.workspace(wp)["lines"]}
        yield {"wp": wp, "out": out, "in": inc, "stmt": stmt, "credit": lines["credit"], "debit": lines["debit"]}


def test_the_sure_pairs_with_a_customers_payment_can_be_accepted(package):
    assert {(p["invoice_doc_id"], p["line_id"]) for p in rp.proposed_pairs(package["wp"])} == {
        (package["out"], package["credit"]), (package["in"], package["debit"])}
    assert rp.accept_proposed(package["wp"], actor="reviewer") == 2
    states = {i["id"]: i["state"] for i in rp.workspace(package["wp"])["invoices"]}
    assert states[package["out"]] == states[package["in"]] == "confirmed"


def test_a_payment_never_settles_an_outgoing_invoice_nor_incoming_money_an_incoming_one(package):
    with pytest.raises(rp.PackageError, match="side"):
        rp.allocate(package["wp"], [{"invoice_doc_id": package["out"], "line_id": package["debit"]}], note="x", actor="reviewer")
    with pytest.raises(rp.PackageError, match="side"):
        rp.allocate(package["wp"], [{"invoice_doc_id": package["in"], "line_id": package["credit"]}], note="x", actor="reviewer")
