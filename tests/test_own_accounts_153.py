"""153 (decision of 2026-10-13, review A4): a payment is a transfer between own accounts only to a registered account.

Any stored bank statement made its account "own": a statement from a trial run or an email attachment printing an
account turned every payment to that account into a transfer between own accounts, left out of the pairing without a
blocker. An own account is now one an own party holds (a person assigned it, or an approved live run of a statement
package did); a payment to an account that only a statement prints stays in the pairing, marked for a person. A
measurement snapshot without registrations keeps the old rule. Synthetic data, no paid calls.
"""

from __future__ import annotations

import pytest

from jav import parties
from jav.core import store
from jav.domains.finance import reconcile, reconcile_package as rp
from tests import test_reconcile_k2_129 as k2

ELSEWHERE = "12121212-34343434-56565656"  # made up: the account another stored statement prints


def _case() -> dict:
    return next(c for c in reconcile.golden_cases() if c["id"] == "own_transfer")["snapshot"]


def _excluded(prepared: dict) -> dict[str, str]:
    return {e["id"]: e["reason"] for e in prepared["excluded"] if e["kind"] == "line"}


def test_a_measurement_case_without_registrations_keeps_the_statements_accounts():
    prepared = reconcile.prepare(_case())
    assert _excluded(prepared) == {"t1": "own_account_transfer"} and prepared["unregistered_own"] == []


def test_a_payment_to_an_account_only_a_statement_prints_stays_in_the_pairing():
    snap = {**_case(), "registered_accounts": []}
    prepared = reconcile.prepare(snap)
    assert "t1" not in _excluded(prepared) and prepared["unregistered_own"] == ["t1"]
    assert reconcile.propose(snap)["unregistered_own"] == ["t1"]


def test_a_payment_to_a_registered_account_is_a_transfer():
    elsewhere = next(reconcile.statement_account(st) for st in _case()["statements"] if st["id"] == "s2")
    prepared = reconcile.prepare({**_case(), "registered_accounts": [elsewhere]})
    assert _excluded(prepared) == {"t1": "own_account_transfer"} and prepared["unregistered_own"] == []


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        rp.clear_cache()
        yield
        rp.clear_cache()


def test_the_store_snapshot_carries_the_accounts_a_party_holds(db):
    party = parties.create("Example Home", identities=[("account", "K1", "first")], actor="tester")["id"]
    parties.assign("account", "K2", "second", None, actor="tester")  # dismissed: no own party's
    assert parties.registered_accounts() == {"K1"}
    assert reconcile.snapshot()["registered_accounts"] == ["K1"]
    assert party


def test_the_package_marks_a_line_to_an_unregistered_account_until_a_party_holds_it(db):
    line = k2._line(memo="savings", counterparty_name="Example Home", counterparty_account=ELSEWHERE)
    own = k2._save("stmt", k2._statement(line), doc_type="statement_cib", validation=k2.VERIFIED)
    k2._save("other", {**k2._statement(k2._line()), "account_no": ELSEWHERE}, doc_type="statement_cib",
             validation=k2.VERIFIED)  # e.g. from a trial run or an email attachment
    [lid] = [ln["id"] for ln in reconcile.with_line_ids(own, [line])]
    wp = rp.create(name="April", accounts=[reconcile.account_key(k2.OWN)], period_start="2026-04-01",
                   period_end="2026-04-30", actor="tester")["workpackage_id"]
    row = next(ln for ln in rp.workspace(wp)["lines"] if ln["id"] == lid)
    assert row["own_account_unregistered"] is True and row["excluded_reason"] is None and row["state"] != "excluded"
    key = next(reconcile.statement_account(st) for st in reconcile.statements() if st["account"] == ELSEWHERE)
    parties.create("Example Home", identities=[("account", key, ELSEWHERE)], actor="tester")
    row = next(ln for ln in rp.workspace(wp)["lines"] if ln["id"] == lid)
    assert row["own_account_unregistered"] is False and row["excluded_reason"] == "own_account_transfer"
