"""130 (backlog F-reconciliation, K3): a forint card line and an invoice in another currency, through the MNB rate.

The owner's decisions (DECISIONS 128 variant C, DECISIONS 130): a card line is compared with the invoice amount converted
at the MNB rate of the issue date; the pair is proposed within -2% ... +5% (`policy.json` `reconcile.fx_tolerance`), and
a person decides on it as on any other pair. The processing fetches a missing rate, a view only reads the stored ones.
Synthetic documents, made-up accounts and invented rates only; no AI call, no network.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest

from jav import fx, reconcile, store
from tests import test_reconcile_k2_129 as k2
from tests.test_fx_130 import Service

CASES = {c["id"]: c for c in reconcile.golden_cases()}
RATES = {"2026-03-27": {"USD": (1, "325,50")}, "2026-03-30": {"USD": (1, "325,90")}, "2026-03-31": {"USD": (1, "326,00")},
         "2026-04-01": {"USD": (1, "326,18")}, "2026-04-02": {"USD": (1, "326,94")}}
CARD = "4444555566667777"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(fx, "_now", lambda: datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc))
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _card_line(amount="6700.00", **over):
    return {"booking_date": "2026-04-03", "value_date": None, "direction": "debit", "amount": amount, "running_balance": None,
            "description": "EXAMPLE CLOUD SUBSCRIPTION", "counterparty_name": "EXAMPLE CLOUD", "counterparty_account": None,
            "memo": None, **over}


def _card_statement(*lines):
    return {"statement_type": "credit_card", "account_no": CARD, "account_iban": None, "period_start": "2026-03-01",
            "period_end": "2026-04-30", "currency": "HUF", "opening_balance": None, "closing_balance": None,
            "total_debit": None, "total_credit": None, "transactions": list(lines) or [_card_line()]}


def _usd_invoice(**over):
    return {"invoice_number": "EC-1001", "supplier_name": "Example Cloud Inc.", "gross_total": "20.00", "currency": "USD",
            "issue_date": "2026-04-01", **over}


def _line_id(statement: str) -> str:
    return reconcile.with_line_ids(statement, [_card_line()])[0]["id"]


# --- the pure core -------------------------------------------------------------------------------------------------


def _within(amount: str) -> str:
    snap = copy.deepcopy(CASES["fx_card_within"]["snapshot"])
    snap["statements"][0]["lines"][0]["amount"] = amount
    [cand] = reconcile.propose(snap)["candidates"]
    return cand["amount_relation"]


@pytest.mark.parametrize("amount, relation", [
    ("6849.78", "fx_within"),   # +4.99998%: inside the +5% edge
    ("6849.79", "fx_outside"),  # +5.00015%
    ("6393.13", "fx_within"),   # -1.99997%
    ("6393.12", "fx_outside"),  # -2.00012%
])
def test_the_band_edges_come_from_the_policy(amount, relation):
    assert _within(amount) == relation


def test_a_card_pair_shows_its_conversion():
    result = reconcile.propose(CASES["fx_card_within"]["snapshot"])
    [cand] = result["candidates"]
    assert cand["fx"] == {"rate": "326.18", "rate_day": "2026-04-01", "source": "mnb", "converted": "6523.60",
                          "deviation": "0.0270"}
    assert (cand["currency"], cand["line_currency"]) == ("USD", "HUF")
    assert result["fx_tolerance"] == ["0.02", "0.05"]


def test_the_checker_notices_a_wrong_relation():
    case = copy.deepcopy(CASES["fx_card_within"])
    case["expected"]["relations"] = {"t1|i1": "fx_outside"}
    assert [p for p in reconcile.check_case(case) if p.startswith("relations")]


def test_the_golden_set_has_the_card_cases():
    card = {k for k in CASES if k.startswith("fx_")}
    assert len(card) == 8 and all(reconcile.check_case(CASES[k]) == [] for k in card)


# --- through the store -----------------------------------------------------------------------------------------------


def _documents(run_id=k2.RUN):
    k2._run(run_id, ["card", "inv"])
    stmt = k2._save("card", _card_statement(), run_id=run_id, doc_type="statement_cib", validation=k2.VERIFIED)
    return stmt


def _pair(stmt: str) -> dict:
    [pair] = reconcile.propose(reconcile.snapshot())["candidates"]
    assert pair["line_id"] == _line_id(stmt)
    return pair


def test_the_command_line_fetches_the_rate_once(db):
    stmt = _documents()
    k2._save("inv", _usd_invoice(), run_id=k2.RUN, doc_type="invoice_foreign")
    service = Service(RATES)
    with fx.use_transport(service):
        [pair] = reconcile.propose(reconcile.snapshot(fetch_rates=True))["candidates"]
    assert (pair["proposed"], pair["amount_relation"], pair["line_id"]) == (True, "fx_within", _line_id(stmt))
    assert len(service.calls) == 1 and service.calls[0]["codes"] == ["USD"]
    with fx.use_transport(service):
        reconcile.snapshot(fetch_rates=True)
    assert len(service.calls) == 1  # stored: not asked again


def test_without_a_rate_nothing_is_proposed_and_the_failure_is_logged(db):
    stmt = _documents()
    k2._save("inv", _usd_invoice(), run_id=k2.RUN, doc_type="invoice_foreign")
    with fx.use_transport(Service(RATES, fail=OSError("down"))):
        [pair] = reconcile.propose(reconcile.snapshot(fetch_rates=True))["candidates"]
    assert (pair["proposed"], pair["amount_relation"]) == (False, "no_rate")
    with store.connect() as c:
        assert [r["status"] for r in c.execute("SELECT status FROM fx_fetches")] == ["failed"]
    assert stmt


def test_a_view_reads_the_stored_rates_and_never_fetches(db):
    stmt = _documents()
    k2._save("inv", _usd_invoice(), run_id=k2.RUN, doc_type="invoice_foreign")
    pair = _pair(stmt)  # the test setup refuses any request: nothing was fetched
    assert (pair["amount_relation"], pair.get("fx")) == ("no_rate", None)
    with fx.use_transport(Service(RATES)):
        fx.ensure([("USD", reconcile._date("2026-04-01"))])
    pair = _pair(stmt)
    assert pair["amount_relation"] == "fx_within" and pair["fx"]["converted"] == "6523.60"


def test_an_earlier_confirmation_settles_a_card_pair(db):
    stmt = _documents()
    inv = k2._save("inv", _usd_invoice(), run_id=k2.RUN, doc_type="invoice_foreign")
    with fx.use_transport(Service(RATES)):
        fx.ensure([("USD", reconcile._date("2026-04-01"))])
    k2._decide(inv, stmt, _line_id(stmt), run_id=k2.RUN)  # a decision of the retired review page panel (129-136)
    result = reconcile.propose(reconcile.snapshot())
    assert {s["invoice_id"]: s["status"] for s in result["invoices"]} == {inv: "confirmed"} and result["candidates"] == []
