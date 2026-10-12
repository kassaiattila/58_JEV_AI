"""143 (DECISIONS 143): the finder of the pairing page's two lists.

The owner found the invoice list beside a selected statement line hard to read: nothing said which invoice is the
line's payment and why. The finder compares the line with every invoice on the page in code - name, invoice number,
account, amount and timing - and says which ones fit (`jav/reconcile.py` `compare`, `jav/reconcile_package.py`
`matches`). It decides nothing. Synthetic documents and made-up accounts only; no AI call.
"""

from __future__ import annotations

from jav import reconcile, reconcile_package as rp
from tests import test_reconcile_k2_129 as k2
from tests import test_reconcile_package_131 as p131

db = p131.db
env = p131.env
ELSEWHERE = "12345678-12345678-12345678"  # made up

INVOICE = {"id": "i1", "number": "INV-0001", "supplier_name": "Example Supplier Kft.", "payment_account": k2.SUPPLIER,
           "amount": "100.00", "currency": "HUF", "issue_date": "2026-04-01", "due_date": "2026-04-15"}
LINE = {"id": "t1", "booking_date": "2026-04-10", "amount": "100.00", "currency": "HUF", "direction": "debit",
        "counterparty_name": "Example Supplier", "counterparty_account": k2.SUPPLIER, "memo": "INV-0001",
        "description": "Transfer", "statement_type": "bank_account"}


# --- one line against one invoice ------------------------------------------------------------------------------------------


def test_a_line_naming_the_invoice_at_its_amount_fits_in_every_respect():
    m = reconcile.compare(INVOICE, LINE)
    assert {"invoice_number", "supplier_account", "supplier_name"} <= set(m["signals"])
    assert (m["amount_relation"], m["account_differs"], m["in_window"], m["by_due"]) == ("equal", False, True, True)
    assert m["difference"] == {"amount": "0.00", "currency": "HUF"} and m["strength"] == 100


def test_another_account_and_another_amount_are_told_not_dropped():
    m = reconcile.compare(INVOICE, {**LINE, "counterparty_account": ELSEWHERE, "memo": "rent", "amount": "130.00"})
    assert m["signals"] == ["supplier_name"] and m["account_differs"]
    assert m["amount_relation"] == "different" and m["difference"] == {"amount": "-30.00", "currency": "HUF"}


def test_a_line_through_a_payment_app_or_without_an_account_is_never_another_account():
    assert not reconcile.compare(INVOICE, {**LINE, "counterparty_account": None})["account_differs"]
    app = {**LINE, "counterparty_account": ELSEWHERE, "description": "Postacsekk befizetes"}
    assert not reconcile.compare(INVOICE, app)["account_differs"]


def test_a_line_outside_the_payment_window_still_compares_with_less_strength():
    named = {**LINE, "counterparty_name": "Someone", "counterparty_account": None}  # the number alone ties them
    m = reconcile.compare(INVOICE, {**named, "booking_date": "2026-09-30"})
    assert not m["in_window"] and not m["by_due"] and m["signals"] == ["invoice_number"]
    assert (m["strength"], reconcile.compare(INVOICE, named)["strength"]) == (75, 90)  # no timing weight outside it


def test_currencies_that_cannot_meet_have_no_amount_to_compare():
    # 149: a forint bank line meets a euro invoice through the MNB rate, a dollar account's line does not
    m = reconcile.compare({**INVOICE, "currency": "EUR"}, {**LINE, "currency": "USD"})
    assert (m["amount_relation"], m["difference"], m["in_window"]) == (None, None, False)


def test_a_card_purchase_compares_on_its_original_amount():
    card = {**LINE, "amount": "39500.00", "original_amount": "101.50", "original_currency": "EUR", "memo": "", "counterparty_account": None}
    m = reconcile.compare({**INVOICE, "currency": "EUR"}, card)
    assert m["amount_relation"] == "different" and m["difference"] == {"amount": "-1.50", "currency": "EUR"}


# --- every invoice of the page against the selected line ------------------------------------------------------------------


def _page():
    """April: t1 names INV-0001; t2 paid INV-0006 (allocated); t3 names INV-0004, an invoice of January."""
    ids = {
        "a": k2._save("a", k2._invoice()),  # INV-0001: named, same amount -> proposed for t1
        "d": k2._save("d", k2._invoice(number="INV-0003", amount="300.00", issue_date="2026-04-05", due_date="2026-04-20")),
        "f": k2._save("f", k2._invoice(number="INV-0006", issue_date="2026-04-03", due_date="2026-04-17")),
        "b": k2._save("b", k2._invoice(number="INV-0777", supplier_name="Other Vendor Bt.", payment_iban=ELSEWHERE,
                                       issue_date="2026-04-02", due_date="2026-04-16")),
        "c": k2._save("c", k2._invoice(number="INV-0778", supplier_name="Other Vendor Bt.", payment_iban=ELSEWHERE,
                                       amount="95.00", issue_date="2026-04-02", due_date="2026-04-16")),
        "e": k2._save("e", k2._invoice(number="INV-0004", supplier_name="Someone Else Kft.", payment_iban=ELSEWHERE,
                                       amount="50.00", issue_date="2026-01-20", due_date="2026-02-01")),
    }
    lines = [p131._line(), p131._line(memo="INV-0006", day="2026-04-12"),
             p131._line(memo="INV-0004", amount="50.00", day="2026-04-28", counterparty_name="Someone Else",
                        counterparty_account=ELSEWHERE)]
    stmt = p131._stmt("stmt", *lines)
    t1, t2, t3 = p131._ids(stmt, *lines)
    wp_id = p131._package()
    rp.allocate(wp_id, [{"invoice_doc_id": ids["f"], "line_id": t2, "line_amount": "100.00"}], note=None, actor="reviewer")
    return wp_id, ids, (t1, t2, t3)


def test_the_finder_compares_every_invoice_of_the_page_and_puts_the_fitting_ones_first(db):
    wp_id, ids, (t1, _t2, _t3) = _page()
    found = rp.matches(wp_id, t1)
    assert found["line_id"] == t1
    by = {m["invoice_id"]: m for m in found["matches"]}
    assert set(by) == {i["id"] for i in rp.workspace(wp_id)["invoices"]}
    order = [m["invoice_id"] for m in found["matches"]]
    # the proposal; the other fitting ones by strength (the allocation of t2 taught the name), on a tie the nearer
    # amount first; then the rest by the nearest amount
    assert order[:6] == [ids[k] for k in ("a", "f", "d", "b", "c", "e")]
    assert [(by[ids[k]]["fit"], by[ids[k]]["strength"]) for k in ("a", "f", "d", "b")] == [
        ("proposed", 100), ("tied", 100), ("candidate", 100), ("same_amount", 50)]
    assert by[ids["c"]]["fit"] is None and by[ids["e"]]["fit"] is None
    # the invoice another line paid is compared on its whole amount: a possible second payment shows
    assert by[ids["f"]]["amount_relation"] == "equal" and {"supplier_name", "supplier_account"} <= set(by[ids["f"]]["signals"])
    assert by[ids["b"]]["account_differs"] and by[ids["c"]]["difference"] == {"amount": "-5.00", "currency": "HUF"}
    assert (by[ids["a"]]["days_from_due"], by[ids["d"]]["days_from_due"]) == (-5, -10)


def test_a_line_naming_an_invoice_outside_its_window_still_finds_it(db):
    wp_id, ids, (_t1, _t2, t3) = _page()
    first, second, third, *_rest = rp.matches(wp_id, t3)["matches"]
    assert (first["invoice_id"], first["fit"], first["in_window"], first["days_from_due"]) == (ids["e"], "named", False, 86)
    # the other vendor's two invoices go to the same account: listed by the engine, at a different amount
    assert {second["invoice_id"], third["invoice_id"]} == {ids["b"], ids["c"]} and second["fit"] == third["fit"] == "candidate"


def test_the_service_returns_the_comparison_and_refuses_an_unknown_line(env):
    wp_id, ids, (t1, _t2, _t3) = _page()
    c = env["client"]
    r = c.get(f"/api/workpackages/{wp_id}/reconcile/matches", params={"line_id": t1})
    assert r.status_code == 200, r.text
    assert r.json()["matches"][0]["invoice_id"] == ids["a"]
    assert c.get(f"/api/workpackages/{wp_id}/reconcile/matches", params={"line_id": "nope"}).status_code == 422
    assert c.get(f"/api/workpackages/{wp_id}/reconcile/matches", params={"line_id": "abcd:000000000000:0"}).status_code == 404
