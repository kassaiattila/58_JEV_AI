"""138 (backlog F-master-data; DECISIONS 137, 138): own accounts and cards registered in advance with their party, and
the monthly data status of a party.

An account registered without a statement still has to be covered, so an invoice it may have paid is never "no
payment found"; the monthly status says per account and month whether a statement is there, checks out, is approved
and continues the previous one, and how many invoices the month has.

Synthetic documents, made-up accounts and names only; no AI call, no network.
"""

from __future__ import annotations

from datetime import date

import pytest

from jav import parties, party_views, reconcile, reconcile_package as rp, store
from tests import test_api
from tests import test_reconcile_k2_129 as k2
from tests import test_reconcile_package_131 as p131

CASES = {c["id"]: c for c in reconcile.golden_cases()}
NEW = ("registered_account_without_statement", "registered_account_closed_before", "registered_account_opened_in_window",
       "registered_card_without_statement")
OWN_KEY = p131.OWN_KEY
OTHER = p131.OTHER  # a second own account, made up
OTHER_KEY = reconcile.account_key(OTHER)
APPROVED, OPEN = "run-0000000000a1", "run-0000000000b2"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


def _home(*identities):
    return parties.create("Example Home", identities=list(identities), actor="t")["id"]


# --- the core: a registered account counts in the coverage ---------------------------------------------------------------


def test_the_golden_cases_of_registered_accounts_pass():
    assert set(NEW) <= set(CASES)
    for case_id in NEW:
        assert reconcile.check_case(CASES[case_id]) == [], case_id
    assert reconcile.golden_score() == {"passed": len(CASES), "total": len(CASES), "failures": {}}


def test_without_the_registration_the_same_cases_say_no_payment_found():
    for case_id in ("registered_account_without_statement", "registered_card_without_statement"):
        snap = {**CASES[case_id]["snapshot"], "own_accounts": []}
        assert {s["status"] for s in reconcile.propose(snap)["invoices"]} == {"no_payment_found"}, case_id
    snap = {**CASES["registered_account_opened_in_window"]["snapshot"], "own_accounts": []}
    assert {s["status"] for s in reconcile.propose(snap)["invoices"]} == {"partly_covered"}


# --- registering an account with its party --------------------------------------------------------------------------------


def test_an_account_is_registered_by_its_number_and_shown_without_a_statement(db):
    home = _home()
    view = party_views.register_account(home, "HU42 2222 3334 4444 5555 6666 7777", kind="account", currencies=["huf", "EUR"],
                                        bank="Example Bank", valid_from="2026-01-01", actor="t")
    [party] = view["parties"]
    [acct] = party["accounts"]
    assert acct["key"] == OTHER_KEY  # the IBAN and the domestic number are one account
    assert (acct["statements"], acct["label"], acct["currencies"]) == (0, "HU42 2222 3334 4444 5555 6666 7777", ["EUR", "HUF"])
    assert {k: acct["registered"][k] for k in ("kind", "bank", "valid_from", "valid_to")} == {
        "kind": "account", "bank": "Example Bank", "valid_from": "2026-01-01", "valid_to": None}
    assert parties.resolver().account(OTHER_KEY) == home


@pytest.mark.parametrize("over", [{"kind": "loan"}, {"currencies": []}, {"currencies": ["HUFX"]}, {"bank": "x" * 101},
                                  {"valid_from": "2026-05-01", "valid_to": "2026-04-30"}, {"valid_from": "May 2026"}])
def test_wrong_details_are_refused(db, over):
    home = _home()
    with pytest.raises(parties.PartyError):
        party_views.register_account(home, OTHER, **{"kind": "account", "currencies": ["HUF"], **over}, actor="t")
    assert parties.accounts() == {}


def test_a_short_number_and_another_partys_account_are_refused_a_dismissed_one_is_taken(db):
    home = _home()
    parties.create("Sporting Club", identities=[("account", OTHER_KEY, OTHER)], actor="t")
    with pytest.raises(parties.PartyError):
        party_views.register_account(home, "1234-5678", kind="account", currencies=["HUF"], actor="t")
    with pytest.raises(parties.PartyError, match="Sporting Club"):
        party_views.register_account(home, OTHER, kind="account", currencies=["HUF"], actor="t")
    parties.assign("account", OTHER_KEY, OTHER, None, actor="t")  # dismissed: no own party's
    party_views.register_account(home, OTHER, kind="account", currencies=["HUF"], actor="t")
    assert parties.resolver().account(OTHER_KEY) == home


def test_the_details_of_an_account_found_on_statements_can_be_set(db):
    p131._stmt("stmt", p131._line())
    _home(("account", OWN_KEY, k2.OWN))
    parties.set_account(OWN_KEY, kind="card", currencies=["HUF"], bank="Example Bank", actor="t")
    [acct] = party_views.overview()["parties"][0]["accounts"]
    assert (acct["statements"], acct["registered"]["kind"], acct["currencies"]) == (1, "card", ["HUF"])
    with pytest.raises(KeyError):
        parties.set_account(OTHER_KEY, kind="account", currencies=["HUF"], actor="t")


# --- a registered account in a reconciliation package -------------------------------------------------------------------


def test_a_registered_account_in_a_package_keeps_its_invoice_from_no_payment_found(db):
    inv = k2._save("inv", k2._invoice())
    p131._stmt("stmt", p131._line(amount="555.00", memo="OTHER", counterparty_name="Somebody", counterparty_account=None))
    home = _home(("account", OWN_KEY, k2.OWN))
    alone = rp.create(name="Own only", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t", party_id=home)
    assert p131._invoice_row(rp.workspace(alone["workpackage_id"]), inv)["state"] == "no_payment_found"
    with pytest.raises(rp.PackageError):
        rp.create(name="X", accounts=[OWN_KEY, OTHER_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t")
    party_views.register_account(home, OTHER, kind="account", currencies=["HUF"], actor="t")
    listed = {a["key"]: a for a in rp.accounts()}
    assert (listed[OTHER_KEY]["statements"], listed[OTHER_KEY]["party"]["id"], listed[OTHER_KEY]["currencies"]) == (0, home, ["HUF"])
    both = rp.create(name="Both", accounts=[OWN_KEY, OTHER_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="t",
                     party_id=home)
    ws = rp.workspace(both["workpackage_id"])
    assert p131._invoice_row(ws, inv)["state"] == "partly_covered"
    assert {(c["account"], c["statements"]) for c in ws["coverage"]} == {(OWN_KEY, 1), (OTHER_KEY, 0)}
    # the first package does not ask the second account: its invoice is still no_payment_found
    assert p131._invoice_row(rp.workspace(alone["workpackage_id"]), inv)["state"] == "no_payment_found"


# --- the monthly data status ---------------------------------------------------------------------------------------------


def _month_stmt(name, start, end, opening, closing, *, run_id=APPROVED, verified=True):
    values = {**k2._statement(p131._line(day=start)), "period_start": start, "period_end": end,
              "opening_balance": opening, "closing_balance": closing}
    return k2._save(name, values, run_id=run_id, doc_type="statement_cib", validation=k2.VERIFIED if verified else [])


def _status_store():
    k2._run(APPROVED, ["jan", "jun-a", "jun-b", "inv-jan", "inv-feb"], approved=True)
    k2._run(OPEN, ["feb", "mar", "may", "inv-mar"])
    _month_stmt("jan", "2026-01-01", "2026-01-31", "100.00", "150.00")
    _month_stmt("feb", "2026-02-01", "2026-02-28", "150.00", "120.00", run_id=OPEN)
    _month_stmt("mar", "2026-03-01", "2026-03-31", "130.00", "90.00", run_id=OPEN, verified=False)  # 130 does not continue 120
    _month_stmt("may", "2026-05-01", "2026-05-20", "90.00", "80.00", run_id=OPEN)
    _month_stmt("jun-a", "2026-06-01", "2026-06-30", "80.00", "70.00")
    _month_stmt("jun-b", "2026-06-01", "2026-06-30", "80.00", "70.00")  # the same month loaded twice
    for name, day, run in (("inv-jan", "2026-01-05", APPROVED), ("inv-feb", "2026-02-05", APPROVED), ("inv-mar", "2026-03-05", OPEN)):
        k2._save(name, k2._invoice(number=name.upper(), issue_date=day, buyer_name="Jane Example"), run_id=run)
    k2._save("inv-cli", k2._invoice(number="CLI-1", issue_date="2026-03-09", buyer_name="Jane Example"))  # an evaluation's
    k2._save("inv-else", k2._invoice(number="ELSE-1", issue_date="2026-03-09", buyer_name="Somebody Else"))
    return _home(("account", OWN_KEY, k2.OWN), ("name", "example jane", "Jane Example"))


def test_the_monthly_status_shows_each_months_statements_and_invoices(db):
    home = _status_store()
    out = party_views.months(home, "2026-01", "2026-08", today=date(2026, 8, 15))
    assert out["months"][0] == "2026-01" and len(out["months"]) == 8
    [col] = out["columns"]
    assert (col["key"], col["currency"], col["kind"], col["registered"], col["opened"], col["statements"]) == (
        OWN_KEY, "HUF", "account", False, "2026-01-01", 6)
    cells = {c["month"]: (c["state"], c["statements"], c["flags"]) for c in col["months"]}
    assert cells == {"2026-01": ("ok", 1, []), "2026-02": ("unapproved", 1, []), "2026-03": ("unverified", 1, ["break"]),
                     "2026-04": ("missing", 0, []), "2026-05": ("partial", 1, []), "2026-06": ("ok", 2, ["overlap"]),
                     "2026-07": ("missing", 0, []), "2026-08": ("none", 0, [])}
    invoices = {i["month"]: (i["total"], i["approved"], i["not_approved"], i["no_run"]) for i in out["invoices"]}
    assert invoices["2026-01"] == (1, 1, 0, 0) and invoices["2026-02"] == (1, 1, 0, 0)
    assert invoices["2026-03"] == (2, 0, 1, 1) and invoices["2026-04"] == (0, 0, 0, 0)  # another party's invoice is not counted
    assert out["summary"] == {"ok": 2, "unapproved": 1, "unverified": 1, "partial": 1, "missing": 2, "overlap": 1, "break": 1}


def test_a_card_cycle_that_starts_on_the_previous_closing_day_is_no_overlap(db):
    # a credit card statement prints its closing day as the next cycle's first day (the store's card statements do)
    k2._run(APPROVED, ["c1", "c2", "c3"], approved=True)
    _month_stmt("c1", "2026-03-25", "2026-04-24", "-100.00", "-200.00")
    _month_stmt("c2", "2026-04-24", "2026-05-22", "-200.00", "-50.00")
    _month_stmt("c3", "2026-05-22", "2026-06-25", "-60.00", "-10.00")  # does not continue -50.00
    home = _home(("account", OWN_KEY, k2.OWN))
    [col] = party_views.months(home, "2026-04", "2026-06", today=date(2026, 8, 15))["columns"]
    assert [(c["state"], c["flags"]) for c in col["months"]] == [("ok", []), ("ok", ["break"]), ("partial", [])]


def test_a_registered_account_is_expected_from_its_opening_to_its_closing(db):
    home = _home()
    party_views.register_account(home, OTHER, kind="card", currencies=["HUF"], valid_from="2026-02-15", valid_to="2026-04-10", actor="t")
    out = party_views.months(home, "2026-01", "2026-05", today=date(2026, 8, 15))
    [col] = out["columns"]
    assert (col["kind"], col["registered"], col["opened"], col["closed"]) == ("card", True, "2026-02-15", "2026-04-10")
    assert [c["state"] for c in col["months"]] == ["none", "missing", "missing", "missing", "none"]


def test_the_default_period_is_this_year_to_the_last_closed_month(db):
    home = _home()
    assert party_views.period(None, None, date(2026, 10, 10)) == ("2026-01", "2026-09")
    assert party_views.period(None, None, date(2027, 1, 5)) == ("2026-01", "2026-12")
    for start, end in (("2026-13", "2026-12"), ("2026-05", "2026-04"), ("2010-01", "2026-12")):
        with pytest.raises(parties.PartyError):
            party_views.period(start, end, date(2026, 10, 10))
    with pytest.raises(KeyError):
        party_views.months("party-000000000000", today=date(2026, 10, 10))
    assert party_views.months(home, today=date(2026, 10, 10))["columns"] == []


# --- the service ---------------------------------------------------------------------------------------------------------

env = test_api.env


def test_the_service_registers_an_account_sets_its_details_and_shows_the_months(env):
    c, human = env["client"], test_api.HUMAN
    home = _home()
    body = {"number": OTHER, "kind": "account", "currencies": ["HUF"], "bank": "Example Bank", "valid_from": "2026-01-01"}
    assert c.post(f"/api/parties/{home}/accounts", json=body).status_code == 422  # a person registers it
    r = c.post(f"/api/parties/{home}/accounts", headers=human, json=body)
    assert r.status_code == 200, r.text
    [acct] = r.json()["parties"][0]["accounts"]
    assert (acct["key"], acct["registered"]["bank"]) == (OTHER_KEY, "Example Bank")
    r = c.post(f"/api/parties/{home}/accounts", headers=human, json={**body, "number": "123"})
    assert r.status_code == 422 and "16 characters" in r.text
    r = c.post("/api/parties/accounts/details", headers=human, json={"key": OTHER_KEY, "kind": "card", "currencies": ["huf"]})
    assert r.status_code == 200 and r.json()["parties"][0]["accounts"][0]["registered"]["kind"] == "card"
    assert c.post("/api/parties/accounts/details", headers=human,
                  json={"key": OWN_KEY, "kind": "card", "currencies": ["HUF"]}).status_code == 404
    r = c.get(f"/api/parties/{home}/months", params={"start": "2026-01", "end": "2026-03"})
    assert r.status_code == 200, r.text
    assert r.json()["months"] == ["2026-01", "2026-02", "2026-03"] and r.json()["columns"][0]["key"] == OTHER_KEY
    assert c.get(f"/api/parties/{home}/months", params={"start": "2026-1"}).status_code == 422
    assert c.get(f"/api/parties/{home}/months", params={"start": "2026-05", "end": "2026-04"}).status_code == 422
    assert c.get("/api/parties/party-000000000000/months").status_code == 404
