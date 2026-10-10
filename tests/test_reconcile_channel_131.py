"""131 (backlog F-reconciliation K4, first step): the payment method signal, the pairs listed only for their exactly
equal amount, and the card names learnt from a person's confirmations.

The owner's decisions of 2026-10-09 (DECISIONS 131): an invoice payable by postal cheque and a line through a cheque
payment app are tied by the payment method; an equal amount without any signal is never proposed but listed for a person
to decide (one currency only, never beside a proposed pair); a confirmed pair teaches the line's name for the invoice's
supplier, except through a payment app. Synthetic documents and made-up accounts only; no AI call, no network.
"""

from __future__ import annotations

import copy

import pytest

from jav import reconcile, store
from tests import test_reconcile_k2_129 as k2

CASES = {c["id"]: c for c in reconcile.golden_cases()}
NEW = ("cheque_app_pays_cheque_invoice", "cheque_app_other_amount", "cheque_app_but_transfer_invoice", "amount_only_two_invoices",
       "amount_only_gives_way_to_a_proposal", "learned_name_from_a_confirmation", "no_learning_from_a_payment_app",
       "learned_name_needs_the_same_supplier", "learned_name_for_a_card_conversion")
CARD = "4444555566667777"
CHEQUE = "Postai sz\u00e1mlabefizet\u00e9si megb\u00edz\u00e1s"  # document vocabulary as printed, in codepoints for the language guard
TRANSFER = "\u00c1tutal\u00e1s"
PURCHASE = "V\u00c1S\u00c1RL\u00c1S"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


# --- the pure core -------------------------------------------------------------------------------------------------


def test_the_golden_set_has_the_new_cases_and_every_case_passes():
    assert set(NEW) <= set(CASES)
    assert reconcile.golden_score() == {"passed": len(CASES), "total": len(CASES), "failures": {}}
    assert len(CASES) >= 44


def test_the_line_name_key_drops_reference_numbers():
    assert reconcile.name_key("EXAMPLETEL*12345 BUDAPEST") == reconcile.name_key("EXAMPLETEL*67890 BUDAPEST") == "exampletel budapest"
    assert reconcile.name_key("PAYPAL *EXAMPLESTREAM 1234567890") == "paypal examplestream"
    assert reconcile.name_key(None) is None and reconcile.name_key("12345 / 678") is None


def test_the_payment_method_signal_needs_both_sides():
    invoice = {"supplier_name": "Example Energy Zrt.", "payment_method": CHEQUE}
    assert reconcile.signals(invoice, {"counterparty_name": "SIMPLEP*PostaCsekk Budapest"}) == ["payment_channel"]
    assert reconcile.signals(invoice, {"counterparty_name": None, "description": "SIMPLEP*iCsekk app"}) == ["payment_channel"]
    assert reconcile.signals(invoice, {"counterparty_name": "Tesco HU Online"}) == []
    assert reconcile.signals({**invoice, "payment_method": TRANSFER}, {"counterparty_name": "SIMPLEP*PostaCsekk"}) == []
    assert reconcile.signals({**invoice, "payment_method": None}, {"counterparty_name": "SIMPLEP*PostaCsekk"}) == []


def test_a_converted_amount_alone_is_not_listed():
    """The card band is wide enough for chance matches (a dollar invoice against an unrelated subscription), so only an
    exactly equal amount in one currency lists a pair without a signal."""
    result = reconcile.propose(CASES["fx_card_no_signal"]["snapshot"])
    assert result["candidates"] == []


def test_a_rejected_equal_amount_pair_is_not_listed_again_and_a_confirmed_one_settles_the_invoice():
    snap = copy.deepcopy(CASES["amount_alone"]["snapshot"])
    snap["decisions"] = [{"invoice_id": "i1", "line_id": "t1", "decision": "not_this"}]
    rejected = reconcile.propose(snap)
    assert rejected["candidates"] == [] and rejected["invoices"][0]["status"] == "no_payment_found"
    snap["decisions"] = [{"invoice_id": "i1", "line_id": "t1", "decision": "paid_by"}]
    confirmed = reconcile.propose(snap)
    assert confirmed["candidates"] == [] and confirmed["invoices"][0]["status"] == "confirmed"


def test_an_equal_amount_pair_is_marked_and_never_proposed():
    [cand] = reconcile.propose(CASES["amount_alone"]["snapshot"])["candidates"]
    assert (cand["amount_only"], cand["proposed"], cand["signals"], cand["amount_relation"]) == (True, False, [], "equal")
    [signed] = reconcile.propose(CASES["one_payment"]["snapshot"])["candidates"]
    assert signed["amount_only"] is False


def test_the_checker_notices_a_wrong_equal_amount_or_signal_expectation():
    case = copy.deepcopy(CASES["amount_alone"])
    case["expected"]["amount_only"] = []
    assert [p for p in reconcile.check_case(case) if p.startswith("amount_only")]
    case = copy.deepcopy(CASES["cheque_app_pays_cheque_invoice"])
    case["expected"]["signals"] = {"t1|i1": ["supplier_name"]}
    assert [p for p in reconcile.check_case(case) if p.startswith("signals")]


def test_names_are_learnt_only_from_confirmations_and_not_through_a_payment_app():
    assert reconcile.learned_names(CASES["learned_name_from_a_confirmation"]["snapshot"]) == {("extel budapest", "example telecom")}
    assert reconcile.learned_names(CASES["no_learning_from_a_payment_app"]["snapshot"]) == set()
    assert reconcile.learned_names(CASES["one_payment"]["snapshot"]) == set()
    snap = copy.deepcopy(CASES["learned_name_from_a_confirmation"]["snapshot"])
    snap["decisions"][0]["decision"] = "not_this"
    assert reconcile.learned_names(snap) == set()


def test_the_learnt_name_counts_only_from_the_configured_number_of_confirmations(monkeypatch):
    conf = {**reconcile._conf(), "learning": {**reconcile._conf()["learning"], "min_confirmations": 2}}
    monkeypatch.setattr(reconcile, "_conf", lambda: conf)
    assert reconcile.learned_names(CASES["learned_name_from_a_confirmation"]["snapshot"]) == set()


# --- through the store -----------------------------------------------------------------------------------------------


def _card_line(name: str, amount: str = "100.00", booking: str = "2026-04-10") -> dict:
    return {"booking_date": booking, "value_date": None, "direction": "debit", "amount": amount, "running_balance": None,
            "description": PURCHASE, "counterparty_name": name, "counterparty_account": None, "memo": None}


def _card(*lines) -> dict:
    return {"statement_type": "credit_card", "account_no": CARD, "account_iban": None, "period_start": "2026-03-01",
            "period_end": "2026-06-30", "currency": "HUF", "opening_balance": None, "closing_balance": None,
            "total_debit": None, "total_credit": None, "transactions": list(lines)}


def _telecom(number: str, amount: str = "100.00", issue: str = "2026-04-01", due: str = "2026-04-15") -> dict:
    return {"invoice_number": number, "supplier_name": "Example Telecom Nyrt.", "gross_total": amount, "currency": "HUF",
            "issue_date": issue, "due_date": due}


# 134: a shortened card name the code cannot tie to Example Telecom (EXAMPLETEL* now carries the loose name signal)
APRIL = _card_line("EXTEL*111 BUDAPEST")
MAY = _card_line("EXTEL*222 BUDAPEST", amount="120.00", booking="2026-05-10")


def _telecom_run() -> tuple[str, str, str]:
    k2._run(k2.RUN, ["card", "tel-04", "tel-05"])
    stmt = k2._save("card", _card(APRIL, MAY), run_id=k2.RUN, doc_type="statement_cib", validation=k2.VERIFIED)
    inv = k2._save("tel-04", _telecom("TEL-04"), run_id=k2.RUN)
    return stmt, inv, reconcile.with_line_ids(stmt, [APRIL, MAY])[0]["id"]


def _candidate(invoice: str, line: str) -> dict:
    return next(c for c in reconcile.propose(reconcile.snapshot())["candidates"]
                if (c["invoice_id"], c["line_id"]) == (invoice, line))


def test_an_equal_amount_pair_is_listed_for_a_person_not_proposed(db):
    stmt = k2._save("card", _card(APRIL), doc_type="statement_cib", validation=k2.VERIFIED)
    inv = k2._save("tel-04", _telecom("TEL-04"))
    line = reconcile.with_line_ids(stmt, [APRIL])[0]["id"]
    pair = _candidate(inv, line)
    assert (pair["amount_only"], pair["proposed"], pair["signals"], pair["amount_relation"]) == (True, False, [], "equal")


def test_a_confirmed_equal_amount_pair_teaches_the_name_for_the_next_month(db):
    stmt, inv, april = _telecom_run()
    k2._decide(inv, stmt, april, run_id=k2.RUN)  # a decision of the retired review page panel (129-136)
    may_line = reconcile.with_line_ids(stmt, [APRIL, MAY])[1]["id"]
    may = k2._save("tel-05", _telecom("TEL-05", "120.00", "2026-05-01", "2026-05-15"), run_id=k2.RUN)
    pair = _candidate(may, may_line)
    assert (pair["signals"], pair["amount_only"], pair["proposed"]) == (["learned_name"], False, True)


def test_scan_counts_the_equal_amount_pairs(db):
    stmt, inv, april = _telecom_run()
    dry = reconcile.scan()
    assert (dry["proposed_pairs"], dry["amount_only_pairs"]) == (0, 1)
    assert stmt and inv and april


def test_the_labels_name_the_new_status_and_the_config_names_the_channel():
    assert "amount_only" in reconcile.STATUSES and {"payment_channel", "learned_name"} <= set(reconcile.SIGNALS)
    [channel] = reconcile._conf()["payment_channels"]
    assert channel["name"] == "postal_cheque"
