"""231 (plan stage C, C2e, C3a-2; DECISIONS 231): the reconciliation packages made before are taken over as the
reconciliation process's cases.

A reconciliation package (its own kind of package until C2d) becomes a case of the reconciliation pack under its own id
(`adopts` in the pack file), so its decisions and approved statements stay where they are; its party is optional (C3a-2),
so a package made without one is taken over as it was. The scopes' general rule that the given parts may imply a needed
part (the one own party every account is registered to) is checked here too. A package whose scope the pack refuses is
named and the others go on. Synthetic statements and invoices; no AI call.
"""

from __future__ import annotations

import pytest

from jav.app import parties, process_runtime, scopes, work
from jav.core import store
from jav.core.process import cases, engine
from jav.domains.finance import reconcile, reconcile_package
from tests import legacy_reconcile
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
    return legacy_reconcile.old_package(name="April", accounts=[reconcile.account_key(k2.OWN)], period_start="2026-04-01",
                                        period_end="2026-04-30", actor=PERSON, party_id=party)


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


def test_a_package_made_without_a_party_is_taken_over_as_it_was(db):
    wp = _old_package(party=None)
    _party("Example Home", k2.OWN)  # its accounts have a party now: the case still reconciles them alone, as the package did
    assert [r["result"] for r in process_runtime.adopt_all(actor="tester", write=True)] == ["adopted"]
    assert engine.state(wp)["status"] == "open" and process_runtime.pack_of(wp)[0] == "reconciliation"
    assert "party" not in cases.get(wp)["data"]["scope"] and reconcile_package.scope(wp)["party_id"] is None


def test_a_package_whose_accounts_imply_no_party_is_taken_over_without_one(db):
    wp = _old_package(party=None)  # its account belongs to no party: the party is optional, as it was for the package
    assert [r["result"] for r in process_runtime.adopt_all(actor="tester", write=True)] == ["adopted"]
    assert "party" not in cases.get(wp)["data"]["scope"]


def test_a_package_whose_scope_its_pack_refuses_is_named_and_the_others_go_on(db):
    home = _party("Example Home", k2.OWN)
    broken = _old_package(party=home)
    with store.connect() as c:  # its stored scope lost its accounts and its party (nothing gives them)
        c.execute("UPDATE workpackage_scopes SET parts = '{}', party_id = NULL WHERE workpackage_id = ?", (broken,))
    good = legacy_reconcile.old_package(name="May", accounts=[reconcile.account_key(k2.OWN)], period_start="2026-05-01",
                                        period_end="2026-05-31", actor=PERSON, party_id=home)
    rows = {r["workpackage_id"]: r for r in process_runtime.adopt_all(actor="tester", write=True)}
    assert rows[broken]["result"] == "refused" and rows[broken]["error"]
    assert rows[good]["result"] == "adopted"
    assert work.get(broken)["source_kind"] == reconcile_package.KIND  # nothing changed
