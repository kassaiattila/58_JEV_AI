"""134 (backlog F-pre-matching P1): looser supplier names, reference numbers and a strength for every candidate.

The owner's request of 2026-10-10 (DECISIONS 134): pair the statement lines and the invoices in advance by the supplier's
name, the invoice numbers and the periods, with code and later with AI, and let a person check and narrow them. A card
line glues the merchant's name to a suffix or misreads a letter, so the whole-word name signal missed it. The loose name
is a weak signal: alone it ties only an equal amount, a word common to many suppliers or lines ties nothing, and a whole
word counts only when it leads the supplier's name. Synthetic documents and made-up accounts only; no AI call.
"""

from __future__ import annotations

import copy

import pytest

from jav import reconcile, reconcile_package, store
from tests import test_reconcile_k2_129 as k2

CASES = {c["id"]: c for c in reconcile.golden_cases()}
NEW = ("fuzzy_glued_name", "fuzzy_misread_letter", "fuzzy_name_other_amount", "fuzzy_ignores_a_word_on_many_lines",
       "fuzzy_brand_word_leads", "fuzzy_shared_trade_word", "supplier_name_without_the_address", "reference_in_memo",
       "short_reference_is_no_signal", "fuzzy_card_conversion")


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _conf_with(monkeypatch, **fuzzy):
    conf = copy.deepcopy(reconcile._conf())
    conf["signals"]["fuzzy_name"].update(fuzzy)
    monkeypatch.setattr(reconcile, "_conf", lambda: conf)


# --- the pure core -------------------------------------------------------------------------------------------------


def test_the_golden_set_has_the_new_cases_and_every_case_passes():
    assert set(NEW) <= set(CASES) and len(CASES) >= 60
    assert reconcile.golden_score() == {"passed": len(CASES), "total": len(CASES), "failures": {}}
    assert {"reference", "supplier_name_fuzzy"} <= set(reconcile.SIGNALS) and reconcile.ENGINE_VERSION == "1.6.0"  # 137


def test_the_supplier_name_is_compared_without_its_address_numbers_and_legal_form():
    name = "Example Telecom Nyrt. 1097 Example City, Main Street 1."
    assert reconcile.name_words(name) == ["example", "telecom"]
    assert reconcile.name_words("Example 2000 Shop Kft.") == ["example", "shop"]
    assert reconcile.supplier_words("Example Bt. of Arts") == ["example"]  # filler words and short words drop
    assert reconcile.line_words({"counterparty_name": "EXAMPLETEL*12345 EX BUDAPEST"}) == ["exampletel", "budapest"]
    assert reconcile.line_words({"counterparty_name": None, "description": "SIMPLEP*Shop"}) == ["simplep", "shop"]


def test_common_words_come_from_many_suppliers_or_many_line_names():
    invoices = [{"supplier_name": f"{w} Waterworks Zrt."} for w in ("Northside", "Southside", "Eastside")]
    invoices.append({"supplier_name": "NORTHSIDE WATERWORKS ZRT."})  # one supplier, however spelt
    lines = [{"counterparty_name": f"{shop} NORTHTOWN"} for shop in ("BAKERY", "PHARMACY", "CORNER SHOP")]
    assert reconcile.common_words(invoices, lines) == frozenset({"waterworks", "northtown"})
    assert reconcile.common_words(invoices[:2], lines[:2]) == frozenset()  # fewer than common_min


def test_the_word_on_many_lines_is_what_keeps_the_city_case_only_listed(monkeypatch):
    snap = CASES["fuzzy_ignores_a_word_on_many_lines"]["snapshot"]
    assert [c["signals"] for c in reconcile.propose(snap)["candidates"]] == [[]]
    _conf_with(monkeypatch, common_min=99)
    [cand] = reconcile.propose(snap)["candidates"]
    assert (cand["signals"], cand["proposed"]) == (["supplier_name_fuzzy"], True)


@pytest.mark.parametrize("line, tied", [
    ("SIMPLEP*EXAMPLEINSURE BUDAPEST", True),   # the same whole word leading the supplier's name (its brand)
    ("EXAMPLEINSUREHU*778", True),             # glued to a suffix
    ("EXAMPLEINSURF", True),                   # one letter off
    ("EXAMPLEINSU", True),                     # cut short on a card terminal
    ("HUNGARIA SHOP", False),                  # a whole word that does not lead the name
    ("EXAMPLE", False),                        # begins the brand but holds too little of it
    ("OTHERINSURE", False),
])
def test_the_loose_name_signal(line, tied):
    invoice = {"supplier_name": "Exampleinsure Hungaria Zrt."}
    found = reconcile.signals(invoice, {"counterparty_name": line})
    assert ("supplier_name_fuzzy" in found) is tied and "supplier_name" not in found


def test_the_whole_name_is_the_stronger_signal_and_excludes_the_loose_one():
    invoice = {"supplier_name": "Example Telecom Nyrt."}
    assert reconcile.signals(invoice, {"counterparty_name": "EXAMPLE TELECOM BUDAPEST"}) == ["supplier_name"]


def test_a_common_word_ties_nothing_even_when_it_leads_the_name():
    invoice = {"supplier_name": "Northtown Waterworks Zrt."}
    line = {"counterparty_name": "NORTHTOWN BAKERY"}
    assert reconcile.signals(invoice, line) == ["supplier_name_fuzzy"]
    assert reconcile.signals(invoice, line, common=frozenset({"northtown"})) == []


def test_a_reference_number_is_matched_like_the_invoice_number():
    invoice = {"number": "W-77", "supplier_name": "Unrelated Name Kft.", "references": ["CUST-1234567", "12"]}
    assert reconcile.signals(invoice, {"memo": "Customer: CUST 1234567", "counterparty_name": "Payee"}) == ["reference"]
    assert reconcile.signals(invoice, {"memo": "cust1234567", "counterparty_name": "Payee"}) == ["reference"]
    assert reconcile.signals(invoice, {"memo": "Customer 12", "counterparty_name": "Payee"}) == []
    assert reconcile.signals({**invoice, "references": []}, {"memo": "CUST-1234567"}) == []


def test_the_strength_orders_the_candidates_and_says_when_the_line_was_booked():
    invoice = {"issue_date": "2026-04-01", "due_date": "2026-04-15"}
    on_time = {"booking_date": "2026-04-10"}
    late = {"booking_date": "2026-05-30"}
    number = reconcile.strength(invoice, on_time, ["invoice_number"], "equal")
    loose = reconcile.strength(invoice, on_time, ["supplier_name_fuzzy"], "equal")
    only = reconcile.strength(invoice, on_time, [], "equal")
    assert number == {"strength": 90, "days_after_issue": 9, "by_due": True}
    assert number["strength"] > loose["strength"] > only["strength"] == 50
    assert reconcile.strength(invoice, late, [], "equal") == {"strength": 40, "days_after_issue": 59, "by_due": False}
    capped = reconcile.strength(invoice, on_time, ["invoice_number", "supplier_account", "supplier_name"], "equal")
    assert capped["strength"] == 100
    assert reconcile.strength({"issue_date": None}, on_time, [], "different")["days_after_issue"] is None


def test_every_candidate_of_the_proposal_carries_its_strength():
    for case_id in ("one_payment", "fuzzy_glued_name", "amount_alone", "fx_card_within"):
        for cand in reconcile.propose(CASES[case_id]["snapshot"])["candidates"]:
            assert 0 <= cand["strength"] <= 100 and isinstance(cand["by_due"], bool)


def test_the_signal_context_holds_the_learnt_names_and_the_common_words():
    ctx = reconcile.signal_context(CASES["learned_name_from_a_confirmation"]["snapshot"])
    assert ctx["learned"] == {("extel budapest", "example telecom")} and ctx["common"] == frozenset()
    assert reconcile.signal_context(CASES["fuzzy_ignores_a_word_on_many_lines"]["snapshot"])["common"] == frozenset({"northtown"})


# --- through the store -----------------------------------------------------------------------------------------------


def test_the_snapshot_reads_the_utility_bills_account_and_the_reference_numbers(db):
    bill = {"invoice_number": "W-77", "supplier_name": "Example Water Zrt.", "supplier_bank_account": k2.SUPPLIER,
            "customer_id": "1234567890", "customer_code": None, "gross_total": "100.00", "currency": "HUF",
            "issue_date": "2026-04-01", "due_date": "2026-04-15"}
    doc = k2._save("bill", bill, doc_type="viz_szamla")
    k2._save("hu", k2._invoice(order_number="PO-998877"))
    by_id = {i["id"]: i for i in reconcile.snapshot()["invoices"]}
    assert (by_id[doc]["payment_account"], by_id[doc]["references"]) == (k2.SUPPLIER, ["1234567890"])
    assert by_id[k2._id("hu")]["payment_account"] == k2.SUPPLIER and by_id[k2._id("hu")]["references"] == ["PO-998877"]


def test_the_package_shows_the_strength_of_a_candidate(db):
    k2._save_statement("stmt", k2._line())
    k2._save("inv", k2._invoice())
    wp = reconcile_package.create(name="Example", accounts=[reconcile.account_key(k2.OWN)], period_start="2026-04-01",
                                  period_end="2026-04-30", actor="tester")
    ws = reconcile_package.workspace(wp["workpackage_id"])
    [line] = ws["lines"]
    [cand] = line["candidates"]
    assert cand["strength"] == 100 and cand["by_due"] is True and cand["days_after_issue"] == 9
