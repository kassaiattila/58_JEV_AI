"""231 (plan stage C, C2e; DECISIONS 231): the reconciliation packages made before are taken over as the reconciliation
process's cases.

A reconciliation package (its own kind of package until C2d) becomes a case of the reconciliation pack under its own id
(`adopts` in the pack file), so its decisions and approved statements stay where they are. A package made before its
accounts had a party takes the party its accounts imply: the one own party every one of them is registered to; accounts
of no party or of two parties imply none, and a case then needs its party given. Synthetic statements and invoices; no
AI call.
"""

from __future__ import annotations

import pytest

from jav.app import parties, process_runtime, scopes, work
from jav.core import store
from jav.core.process import cases, engine
from jav.domains.finance import reconcile, reconcile_package
from tests import test_reconcile_ai_134 as ai134
from tests import test_reconcile_k2_129 as k2

PERSON = "anna"
OTHER = "99990001-00000002-00000003"  # made up, a second own account


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "adopt.sqlite"):
        yield


def _party(name: str, *accounts: str) -> str:
    return parties.create(name, identities=[("account", reconcile.account_key(a), a) for a in accounts], actor="t")["id"]


def _old_package(*, party: str | None) -> str:
    k2._save_statement("stmt", *ai134.LINES)
    k2._save("tel", ai134.TELECOM)
    return reconcile_package.create(name="April", accounts=[reconcile.account_key(k2.OWN)], period_start="2026-04-01",
                                    period_end="2026-04-30", actor=PERSON, party_id=party)["workpackage_id"]


def test_the_accounts_of_one_party_imply_it_and_others_imply_none(db):
    home = _party("Example Home", k2.OWN)
    period = ["2026-04-01", "2026-04-30"]
    k2._save_statement("stmt", *ai134.LINES)
    scope = scopes.check(["party", "period", "accounts"], {"period": period, "accounts": [reconcile.account_key(k2.OWN)]})
    assert scope["party"] == home
    assert reconcile_package.party_of_accounts({"accounts": []}) is None
    assert reconcile_package.party_of_accounts({"accounts": [reconcile.account_key(k2.OWN), "unknown-account"]}) is None
    _party("Example Club", OTHER)
    both = {"accounts": [reconcile.account_key(k2.OWN), reconcile.account_key(OTHER)]}
    assert reconcile_package.party_of_accounts(both) is None
    with pytest.raises(scopes.ScopeError):
        scopes.check(["party", "period", "accounts"], {"period": period, **both})


def test_a_reconciliation_package_is_taken_over_as_the_process_case(db):
    home = _party("Example Home", k2.OWN)
    wp = _old_package(party=home)
    listed = process_runtime.adopt_all(actor="tester")  # without write: only listed
    assert [(r["pack"], r["workpackage_id"], r["result"]) for r in listed] == [("reconciliation", wp, "to adopt")]
    assert listed[0]["scope"] == {"party": home, "period": ["2026-04-01", "2026-04-30"],
                                  "accounts": [reconcile.account_key(k2.OWN)]}
    assert work.get(wp)["source_kind"] == reconcile_package.KIND
    assert [r["result"] for r in process_runtime.adopt_all(actor="tester", write=True)] == ["adopted"]
    assert work.get(wp)["source_kind"] == process_runtime.CONTAINER
    assert process_runtime.adopt_all(actor="tester", write=True) == []
    state = engine.state(wp)
    assert state["steps"]["pair"]["state"] == "running" and state["steps"]["propose"]["state"] != "done"
    assert reconcile_package.workspace(wp)["scope"]["party_id"] == home  # read and decided on as before


def test_a_package_made_before_its_accounts_had_a_party_takes_the_party_they_imply(db):
    wp = _old_package(party=None)
    home = _party("Example Home", k2.OWN)
    listed = process_runtime.adopt_all(actor="tester")
    assert listed[0]["scope"]["party"] is None  # the stored scope has none
    assert [r["result"] for r in process_runtime.adopt_all(actor="tester", write=True)] == ["adopted"]
    assert engine.state(wp)["status"] == "open" and process_runtime.pack_of(wp)[0] == "reconciliation"
    assert cases.get(wp)["data"]["scope"]["party"] == home


def test_a_package_whose_accounts_imply_no_party_is_refused_and_the_others_go_on(db):
    wp = _old_package(party=None)  # its account belongs to no party
    rows = process_runtime.adopt_all(actor="tester")
    assert [(r["workpackage_id"], r["result"]) for r in rows] == [(wp, "refused")] and "party" in rows[0]["error"]
    assert process_runtime.adopt_all(actor="tester", write=True)[0]["result"] == "refused"
    assert work.get(wp)["source_kind"] == reconcile_package.KIND  # nothing changed
