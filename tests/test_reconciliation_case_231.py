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


def test_the_pairing_element_gives_the_scope_counts_and_the_tab_of_the_next_step(db):
    from jav.domains.finance import capabilities as finance_capabilities

    k2._save("inv", k2._invoice())
    p131._stmt("stmt", p131._line())
    case = _container()
    shared: dict = {}
    data = finance_capabilities._view(case, "pair", shared)
    assert data["scope"]["accounts"] == [OWN_KEY] and data["counts"]["open_lines"] == 1
    assert (data["next"]["code"], data["next"]["element"], data["next"]["show"]) == ("reconcile_pair", "pairing", "decide")
    assert finance_capabilities._view(case, "pair", shared) is data  # read once per page view


def test_the_inputs_list_keeps_one_kind_when_asked(db):
    from jav.domains.finance import finance_datasets

    k2._save("inv", k2._invoice())
    p131._stmt("stmt", p131._line())
    case = _container()
    kinds = {name: {r["kind"] for r in finance_datasets.reconcile_inputs({"workpackage_id": case, **extra})[1]}
             for name, extra in (("all", {}), ("statement", {"kind": "statement"}), ("invoice", {"kind": "invoice"}))}
    assert kinds == {"all": {"statement", "incoming"}, "statement": {"statement"}, "invoice": {"incoming"}}


# --- the reconciliation's process pack (configs/processes/reconciliation.json) ------------------------------------------

env = p131.env


def _party_with_account() -> str:
    from jav.app import parties

    return parties.create("Example Home", identities=[("account", OWN_KEY, k2.OWN)], actor="t")["id"]


def test_a_case_starts_for_a_party_and_a_period_with_the_partys_accounts(db):
    from jav.app import case_views

    k2._save("inv", k2._invoice())
    p131._stmt("stmt", p131._line())
    party = _party_with_account()
    case = process_runtime.start_case("reconciliation", {"party": party, "period": ["2026-04-01", "2026-04-30"]},
                                      name="April", actor="reviewer")
    stored = package_scope.stored(case)
    assert (stored["party_id"], stored["period_start"], stored["parts"][rp.ACCOUNTS]) == (party, "2026-04-01", [OWN_KEY])
    package = rp.create(name="April package", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30",
                        actor="reviewer", party_id=party)["workpackage_id"]
    assert _same(rp.workspace(case)) == _same(rp.workspace(package))  # the same reconciliation as a package's
    page = case_views.view(case)
    assert [t["id"] for t in page["tabs"]] == ["invoices", "lines", "pairing", "result", "history"]
    assert (page["next"]["code"], page["next"]["tab"]) == ("reconcile_pair", "pairing")
    assert page["steps"]["pair"]["by_person"] is True


def test_the_pairing_step_is_done_with_the_approved_version_and_opens_again_when_it_is_reopened(db):
    from jav.app import package_release
    from jav.core.process import engine

    k2._save("inv", k2._invoice())
    p131._stmt("stmt", p131._line())
    case = process_runtime.start_case("reconciliation", {"party": _party_with_account(),
                                                         "period": ["2026-04-01", "2026-04-30"]}, name="April", actor="t")
    engine.turn(case, wake=True)
    assert engine.state(case)["steps"]["pair"]["waiting_for"] == "pairing"
    with store.connect() as c:
        store.begin_immediate(c)
        package_release.record_own(c, case, content={"invented": True}, fingerprint="f" * 16, locks=[], actor="anna")
    engine.turn(case, wake=True)
    state = engine.state(case)
    assert (state["status"], state["steps"]["pair"]["result"]) == ("closed", {"version": 1})
    with store.connect() as c:
        store.begin_immediate(c)
        package_release.reopen_own(c, case, note="a line was misread", actor="anna")
    state = engine.state(case)
    assert (state["status"], state["steps"]["pair"]["state"]) == ("open", "running")


def test_the_service_starts_a_case_for_a_party_and_a_period(env):
    from tests.test_api import HUMAN

    c = env["client"]
    k2._save("inv", k2._invoice())
    p131._stmt("stmt", p131._line())
    party = _party_with_account()
    listed = {p["id"]: p for p in c.get("/api/processes").json()["processes"]}
    assert listed["reconciliation"]["scope"] == ["party", "period", "accounts"]
    assert listed["reconciliation"]["asks"] == ["party", "period"]
    r = c.post("/api/cases", headers=HUMAN, json={"pack": "reconciliation", "name": "April", "party_id": party,
                                                  "period_start": "2026-04-01", "period_end": "2026-04-30"})
    assert r.status_code == 201, r.text
    case = r.json()["case_id"]
    assert c.get(f"/api/workpackages/{case}/reconcile").json()["lines"][0]["state"] == "proposed"
    bad = c.post("/api/cases", headers=HUMAN, json={"pack": "reconciliation", "name": "x", "party_id": party,
                                                    "period_start": "2026-04-01"})
    assert bad.status_code == 422
