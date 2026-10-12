"""148 (backlog F-outgoing-reconciliation, K4; DECISIONS 148): incoming money paired with an own party's outgoing invoices.

Until now the pairing compared only an outgoing payment (a debit line) with an incoming invoice: every credit line was
left out as "not an outgoing payment", and every outgoing invoice as "outgoing invoice". The owner's decisions of
2026-10-12: a customer's payment (a credit line) is paired with the outgoing invoice it pays, by the same rules (amount,
currency, the payment window, the invoice number in the memo, combined payments, credit notes); the partner of an
outgoing invoice is its buyer, not the own party that issued it. A credit line with no outgoing invoice as a candidate
stays informational, as before ("Only the ones with a candidate are to decide"), so the packages without outgoing
invoices do not get new lines to decide.

Synthetic data and made-up parties only; no AI call.
"""

from __future__ import annotations

import copy

import pytest

from jav import cfg, parties, reconcile, store
from jav import reconcile_package as rp
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_package_131 import _line as _pkg_line
from tests.test_reconcile_package_131 import OWN_KEY, _stmt

CLUB_TAX = "13570008-1-13"  # a sample number on the data guard's allow list

D = cfg.load("golden_reconcile")["defaults"]
OWN = "Sample Own Company Kft."


def _invoice(iid: str, **over) -> dict:
    return {**D["invoice"], "id": iid, "number": f"INV-{iid}", **over}


def _outgoing(iid: str, **over) -> dict:
    return _invoice(iid, **{"direction": "outgoing", "supplier_name": OWN, "buyer_name": "Northwind Trading Ltd.",
                            "payment_account": "11112223-33334444-55556666", **over})


def _line(lid: str, **over) -> dict:
    return {**D["line"], "id": lid, **over}


def _credit(lid: str, **over) -> dict:
    return _line(lid, **{"direction": "credit", "counterparty_name": "Northwind Trading",
                         "counterparty_account": "12121212-34343434-56565656", **over})


def _snap(invoices: list[dict], lines: list[dict], **extra) -> dict:
    return {"invoices": invoices, "statements": [{**D["statement"], "id": "s1", "lines": lines}], "decisions": [],
            "fx_rates": {}, "allocations": [], "marks": [], "own_accounts": [], **extra}


def _pairs(result: dict) -> list[tuple[str, str, bool]]:
    return sorted((c["line_id"], c["invoice_id"], c["proposed"]) for c in result["candidates"])


def _status(result: dict) -> dict[str, str]:
    return {s["invoice_id"]: s["status"] for s in result["invoices"]}


def test_a_customers_payment_is_proposed_for_the_outgoing_invoice_it_names():
    result = reconcile.propose(_snap([_outgoing("o1")], [_credit("t1", memo="Payment INV-o1")]))
    assert _pairs(result) == [("t1", "o1", True)]
    cand = result["candidates"][0]
    assert "invoice_number" in cand["signals"] and "supplier_name" in cand["signals"]  # the buyer is the partner
    assert _status(result) == {"o1": "proposed"}
    assert not result["excluded"]


def test_the_own_company_on_the_invoice_is_not_the_partner():
    # the line names the own company (a transfer between the company's accounts would): no name signal from it
    line = _credit("t1", counterparty_name="Sample Own Company", memo="")
    result = reconcile.propose(_snap([_outgoing("o1")], [line]))
    assert all("supplier_name" not in c["signals"] and "supplier_name_fuzzy" not in c["signals"] for c in result["candidates"])


def test_a_debit_never_pays_an_outgoing_invoice_and_a_credit_never_an_incoming_one():
    snap = _snap([_outgoing("o1"), _invoice("i1")],
                 [_line("d1", memo="INV-o1"), _credit("c1", memo="INV-i1", counterparty_name="Example Supplier", amount="70.00")])
    result = reconcile.propose(snap)
    assert ("d1", "o1") not in {(c["line_id"], c["invoice_id"]) for c in result["candidates"]}
    assert ("c1", "i1") not in {(c["line_id"], c["invoice_id"]) for c in result["candidates"]}
    assert _status(result)["o1"] == "no_payment_found"  # an outgoing invoice is no longer left out


def test_a_credit_without_a_candidate_stays_informational():
    result = reconcile.propose(_snap([_invoice("i1")], [_line("d1", memo="INV-i1"), _credit("c1", memo="Salary")]))
    assert ["line", "c1", "not_outgoing_payment"] in [[e["kind"], e["id"], e["reason"]] for e in result["excluded"]]
    assert "c1" not in result["unpaired_line_ids"]


def test_the_payment_kind_pattern_is_for_outgoing_payments_only():
    # interest credited (kamat) is incoming money without an outgoing invoice: informational as before, not "look at it"
    result = reconcile.propose(_snap([_invoice("i1")], [_credit("c1", memo="Kamat jovairas", counterparty_name="Bank")]))
    assert [["line", "c1", "not_outgoing_payment"]] == [[e["kind"], e["id"], e["reason"]] for e in result["excluded"]]


def test_a_credit_from_an_own_account_is_a_transfer():
    snap = _snap([_outgoing("o1")], [_credit("c1", memo="INV-o1", counterparty_account="10000001-20000002-00000000")],
                 own_accounts=[{"key": "10000001-20000002-00000000", "kind": "bank", "currencies": ["HUF"]}])
    snap["statements"].append({**D["statement"], "id": "s2", "account": "10000001-20000002-00000000", "lines": []})
    result = reconcile.propose(snap)
    assert ["line", "c1", "own_account_transfer"] in [[e["kind"], e["id"], e["reason"]] for e in result["excluded"]]
    assert not result["candidates"]


def test_one_credit_paying_two_outgoing_invoices_is_combined():
    snap = _snap([_outgoing("o1", amount="60.00"), _outgoing("o2", amount="40.00")],
                 [_credit("c1", memo="INV-o1 INV-o2")])
    result = reconcile.propose(snap)
    assert {c["invoice_id"] for c in result["candidates"] if c["proposed"]} == {"o1", "o2"}
    assert all(c.get("combined") for c in result["candidates"] if c["proposed"])


def test_an_outgoing_credit_note_cancels_the_invoice_of_the_same_buyer():
    snap = _snap([_outgoing("o1", issue_date="2026-04-01"),
                  _outgoing("n1", amount="-100.00", issue_date="2026-04-05"),
                  _outgoing("o2", buyer_name="Another Customer Zrt.", issue_date="2026-04-02")], [])
    result = reconcile.propose(snap)
    assert {s["invoice_id"]: s.get("credited_by") for s in result["invoices"] if s.get("credited_by")} == {"o1": "n1"}


def test_the_golden_set_has_the_outgoing_cases():
    ids = {c["id"] for c in reconcile.golden_cases()}
    assert {"outgoing_paid_by_credit", "credit_never_pays_incoming", "credit_without_candidate", "outgoing_unpaid"} <= ids
    for case in reconcile.golden_cases():
        if case["id"] in ("outgoing_invoice", "own_supplier_outgoing"):
            assert case["expected"]["status"]["i1"] == "no_payment_found"  # 148: no longer left out


def test_the_snapshot_order_does_not_decide():
    snap = _snap([_outgoing("o1", amount="60.00"), _outgoing("o2", amount="40.00"), _invoice("i1")],
                 [_credit("c1", memo="INV-o1 INV-o2"), _line("d1", memo="INV-i1")])
    first = reconcile.propose(copy.deepcopy(snap))
    snap["invoices"].reverse()
    snap["statements"][0]["lines"].reverse()
    assert reconcile.propose(snap)["candidates"] == first["candidates"]


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def test_the_package_of_the_issuing_party_pairs_its_outgoing_invoice(db):
    club = parties.create("Sporting Club", identities=[("tax", parties.tax_key(CLUB_TAX), CLUB_TAX),
                                                       ("name", "sporting club", "Sporting Club")], actor="t")["id"]
    parties.create("Example Home", identities=[("name", "jane example", "Jane Example")], actor="t")
    out = k2._save("out", k2._invoice(number="OUT-1", supplier_name="Sporting Club", supplier_tax_id=CLUB_TAX,
                                       buyer_name="Northwind Trading Ltd."))
    home_out = k2._save("home-out", k2._invoice(number="HOME-1", amount="80.00", supplier_name="Jane Example",
                                     buyer_name="Northwind Trading Ltd."))  # another own party's outgoing invoice
    _stmt("stmt", _pkg_line(memo="OUT-1", direction="credit", counterparty_name="Northwind Trading"))
    wp = rp.create(name="April", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="reviewer",
                   party_id=club)["workpackage_id"]
    ws = rp.workspace(wp)
    own = {i["id"]: i["own"] for i in ws["invoices"]}
    assert own == {out: True, home_out: False}  # an outgoing invoice belongs to its issuer's package
    row = next(i for i in ws["invoices"] if i["id"] == out)
    assert row["outgoing"] is True and row["partner_name"] == "Northwind Trading Ltd."  # shown as the invoice's partner
    (line,) = ws["lines"]
    assert line["direction"] == "credit" and line["state"] == "proposed"


def test_the_engine_version_marks_the_change():
    assert reconcile.ENGINE_VERSION == "1.14.0"
