"""231 (plan stage C, C2d): a process case whose scope names accounts is read and decided on as a reconciliation package.

A case container with the accounts part gets the same workspace as a reconciliation package of the same scope (the
decisions belong to the pairs, so both see them); its scope change keeps the case's party and period parts and its pack
reference; the decisions' conflict check counts its scope. The accounts are a scope part of the finance domain whose
default is the party's accounts and cards. Synthetic documents and made-up accounts only; no AI call, no network.
"""

from __future__ import annotations

import pytest

from jav.app import package_scope, process_runtime, scopes, work
from jav.core import store
from jav.domains.finance import reconcile_package as rp
from tests import test_reconcile_k2_129 as k2
from tests import test_reconcile_package_131 as p131

OWN_KEY = p131.OWN_KEY
PARTY = "party-0123456789ab"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "case.sqlite"):
        yield


def _container(*, accounts=(OWN_KEY,), start="2026-04-01", end="2026-04-30", party=None) -> str:
    wp = work.create_workpackage(name="April case", source_kind=process_runtime.CONTAINER, source_ref="pack:probe@1.0.0",
                                 owner="reviewer")
    parts = {**({scopes.PARTY: party} if party else {}), scopes.PERIOD: [start, end], rp.ACCOUNTS: list(accounts)}
    with store.connect() as c:
        store.begin_immediate(c)
        package_scope.save(c, wp["id"], party_id=party, period_start=start, period_end=end, parts=parts, actor="reviewer")
    return wp["id"]


def _same(ws: dict) -> dict:
    """A workspace without what names its own package."""
    return {k: v for k, v in ws.items() if k not in ("scope", "workpackage", "workpackage_id", "journal_state", "approval", "kept_at")}


def test_a_case_with_accounts_is_read_as_a_reconciliation_package(db):
    k2._save("inv", k2._invoice())
    p131._stmt("stmt", p131._line())
    case, package = _container(), p131._package()
    assert rp.holds_reconciliation(work.get(case)) and rp.holds_reconciliation(work.get(package))
    assert _same(rp.workspace(case)) == _same(rp.workspace(package))
    assert rp.scope(case)["accounts"] == [OWN_KEY] and rp.scope(case)["period_start"] == "2026-04-01"


def test_a_case_without_accounts_is_no_reconciliation_package(db):
    wp = work.create_workpackage(name="x", source_kind=process_runtime.CONTAINER, source_ref="pack:probe@1.0.0", owner="t")
    assert not rp.holds_reconciliation(work.get(wp["id"]))
    with pytest.raises(rp.PackageError):
        rp.workspace(wp["id"])


def test_a_case_keeps_its_party_period_parts_and_pack_reference_when_its_scope_changes(db):
    p131._stmt("stmt", p131._line())
    case = _container()
    rp.set_scope(case, accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-05-31", expected_revision=1, actor="t")
    stored = package_scope.stored(case)
    assert stored["parts"] == {scopes.PERIOD: ["2026-04-01", "2026-05-31"], rp.ACCOUNTS: [OWN_KEY]}
    assert (stored["period_end"], work.get(case)["source_ref"]) == ("2026-05-31", "pack:probe@1.0.0")


def test_the_conflict_check_counts_a_cases_scope(db):
    p131._stmt("stmt", p131._line())
    before = rp._decision_state()
    _container()
    assert rp._decision_state() != before


def test_the_accounts_default_to_the_partys_and_are_checked(db, monkeypatch):
    monkeypatch.setattr(rp, "accounts", lambda: [{"key": OWN_KEY, "party": {"id": PARTY}}, {"key": "OTHER", "party": None}])
    monkeypatch.setitem(scopes._PARTS, scopes.PARTY, scopes.Part(scopes.PARTY, "t", lambda v, e: v, str, lambda e: e("x")))
    got = scopes.check([scopes.PARTY, scopes.PERIOD, rp.ACCOUNTS], {"party": PARTY, "period": ["2026-04-01", "2026-04-30"]})
    assert got[rp.ACCOUNTS] == [OWN_KEY]
    assert scopes.check([rp.ACCOUNTS], {"accounts": ["OTHER", "OTHER"]})[rp.ACCOUNTS] == ["OTHER"]
    with pytest.raises(scopes.ScopeError, match="neither a statement nor a registered account"):
        scopes.check([rp.ACCOUNTS], {"accounts": ["NOWHERE"]})
    with pytest.raises(scopes.ScopeError, match="no account or card"):
        scopes.check([scopes.PARTY, rp.ACCOUNTS], {"party": "party-ffffffffffff"})
