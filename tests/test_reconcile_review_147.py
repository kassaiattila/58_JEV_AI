"""147 (backlog F-quick-review; DECISIONS 147): the quick review of a reconciliation package.

The owner's decisions of 2026-10-12: the lines whose pair or reason is known with high probability are shown in groups
(a sure pair, the partner's earlier reason, the bank's own category, salary, the AI's sure kind …), each accepted with
one click; the AI counts as sure when both engines give the same kind and JEV's probability is at least the policy's
threshold (0.95); the rest of the AI's suggestions are a group of their own, to look at. The saved reason records the
suggestion it came from.

Synthetic documents and made-up accounts only; the AI's answers are stored by hand (no call).
"""

from __future__ import annotations

import pytest

from jav import work
from jav.ai import policy
from jav.core import cfg, store
from jav.domains.finance import reconcile, reconcile_ai, reconcile_package as rp, reconcile_review as rr
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_package_131 import _line, _package, _stmt


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield


LINES = {
    "pair": _line(),  # INV-0001, exact: a sure pair
    "earlier_old": _line(amount="11.00", day="2026-03-20", memo="", counterparty_name="Example Bakery", counterparty_account=None),
    "earlier": _line(amount="12.00", day="2026-04-11", memo="", counterparty_name="Example Bakery", counterparty_account=None),
    "atm": _line(amount="20000.00", day="2026-04-12", memo="", description="ATM", counterparty_name=None, counterparty_account=None),
    "salary": _line(amount="300000.00", day="2026-04-13", memo="Szeptemberi munkabér", counterparty_name="Jane Example",
                    counterparty_account=None),
    "ai_sure": _line(amount="13.00", day="2026-04-14", memo="", counterparty_name="Example Market", counterparty_account=None),
    "ai_low": _line(amount="14.00", day="2026-04-15", memo="", counterparty_name="Example Kiosk", counterparty_account=None),
    "ai_one": _line(amount="15.00", day="2026-04-16", memo="", counterparty_name="Example Cash Point", counterparty_account=None),
    "expects": _line(amount="16.00", day="2026-04-17", memo="", counterparty_name="Example Cloud", counterparty_account=None),
    "rest": _line(amount="17.00", day="2026-04-18", memo="", counterparty_name="Example Somebody", counterparty_account=None),
    "repayment": _line(amount="18.00", day="2026-04-19", memo="Hitelkártya törlesztés", counterparty_name=None, counterparty_account=None),
    "income": _line(amount="19.00", day="2026-04-20", memo="", direction="credit", counterparty_name="Example Customer",
                    counterparty_account=None),
}


def _answer(kind: str, p: float) -> dict:
    return {"options": [], "pays": None, "pays_probability": None, "pays_distribution": None, "kind": kind,
            "kind_probability": p, "kind_distribution": {kind: p}, "measured": True, "model": "synthetic", "error": None}


def _setup() -> tuple[str, dict[str, str], str]:
    inv = k2._save("inv", k2._invoice())
    stmt = _stmt("stmt", *LINES.values())
    ids = dict(zip(LINES, (ln["id"] for ln in reconcile.with_line_ids(stmt, list(LINES.values())))))
    old = _package(start="2026-03-01", end="2026-03-31", name="March")
    rp.mark(old, [ids["earlier_old"]], category="private", note=None, actor="reviewer")  # a person's earlier reason
    wp_id = _package()
    line = lambda name: {"id": ids[name], "statement_id": stmt}  # noqa: E731
    for name, answers in (("ai_sure", {"jev": ("retail_purchase", 0.97), "gpt": ("retail_purchase", 0.9999)}),
                          ("ai_low", {"jev": ("retail_purchase", 0.80), "gpt": ("retail_purchase", 0.9999)}),
                          ("ai_one", {"jev": ("cash", 0.99)}),
                          ("expects", {"jev": ("subscription", 0.99), "gpt": ("subscription", 1.0)}),
                          ("rest", {"jev": ("other", 0.6), "gpt": ("person_transfer", 0.9)})):
        for engine, (kind, p) in answers.items():
            reconcile_ai._save(wp_id, line(name), engine, _answer(kind, p), "synthetic")
    return wp_id, ids, inv


def _groups(view: dict) -> dict[str, dict]:
    return {g["id"]: g for g in view["groups"]}


def _members(view: dict, ids: dict[str, str]) -> dict[str, list[str]]:
    names = {v: k for k, v in ids.items()}
    return {g["id"]: [names[ln["id"]] for ln in g["lines"]] for g in view["groups"]}


# --- the groups --------------------------------------------------------------------------------------------------------


def test_each_line_to_decide_is_in_the_first_group_that_fits(db):
    wp_id, ids, inv = _setup()
    view = rr.review(wp_id)
    assert _members(view, ids) == {
        "sure_pairs": ["pair"], "earlier": ["earlier"], "bank_category": ["atm"], "salary_rule": ["salary"],
        "ai_sure": ["ai_sure"], "ai_review": ["ai_low", "ai_one"], "expects_invoice": ["expects"], "rest": ["rest"]}
    g = _groups(view)
    assert [g[k]["action"] for k in rr.GROUPS] == ["pair", "mark", "mark", "mark", "mark", "mark", "none", "none"]
    assert g["sure_pairs"]["lines"][0]["invoices"][0]["id"] == inv
    assert [(ln["category"]) for k in ("earlier", "bank_category", "salary_rule", "ai_sure") for ln in g[k]["lines"]] == [
        "private", "cash", "salary", "private"]
    assert [ln["category"] for ln in g["ai_review"]["lines"]] == ["private", "cash"]
    assert g["ai_sure"]["lines"][0]["ai"] == {"jev": {"kind": "retail_purchase", "probability": 0.97},
                                              "gpt": {"kind": "retail_purchase", "probability": 0.9999}}
    assert g["salary_rule"]["totals"] == {"HUF": "300000.00"} and g["sure_pairs"]["count"] == 1
    # what the code left out, by its reason, for information
    assert {k: v["count"] for k, v in view["excluded"].items()} == {"payment_kind_review": 1, "not_outgoing_payment": 1}
    assert view["threshold"] == policy.RECONCILE["ai_sure"]["min_jev_probability"] == 0.95


def test_the_ai_threshold_comes_from_the_policy(db, monkeypatch):
    wp_id, ids, _inv = _setup()
    monkeypatch.setitem(policy.RECONCILE, "ai_sure", {"min_jev_probability": 0.99})
    members = _members(rr.review(wp_id), ids)
    assert members["ai_sure"] == [] and members["ai_review"] == ["ai_sure", "ai_low", "ai_one"]


def test_a_decided_line_leaves_the_review(db):
    wp_id, ids, _inv = _setup()
    rp.mark(wp_id, [ids["rest"]], category="other", note="a gift", actor="reviewer")
    members = _members(rr.review(wp_id), ids)
    assert "rest" not in sum(members.values(), [])


# --- the salary rule and the AI's salary kind ---------------------------------------------------------------------------


@pytest.mark.parametrize("memo, description, mark", [
    ("Szeptemberi munkabér", None, "salary"),
    ("BÉR 2026/09", None, "salary"),
    (None, "Payroll", "salary"),
    ("Kártyás fizetés", "Vásárlás", None),  # paying is no salary
    ("Berlin trip", None, None),
])
def test_the_salary_rule_reads_the_memo_and_the_description(memo, description, mark):
    assert reconcile.salary_mark({"memo": memo, "description": description}) == mark


def test_the_ais_kind_of_payment_knows_salary():
    site = cfg.load("callsite:reconcile_line")
    assert "salary" in site["questions"]["line_kind"]["criteria"] and site["kind_marks"]["salary"] == "salary"
    assert site["meta"]["version"] == "1.2.0"  # 158: incoming money got its own kind question


# --- accepting a group -------------------------------------------------------------------------------------------------


def test_accepting_a_reason_group_marks_its_lines_with_the_suggestions_source(db):
    wp_id, ids, _inv = _setup()
    assert rr.accept(wp_id, "ai_review", [ids["ai_low"], ids["ai_one"]], actor="reviewer") == 2
    with store.connect() as c:
        rows = {r["line_id"]: (r["category"], r["basis"], r["actor"]) for r in c.execute(
            "SELECT line_id, category, basis, actor FROM reconcile_line_marks WHERE revoked_at IS NULL AND workpackage_id=?", (wp_id,))}
    assert rows == {ids["ai_low"]: ("private", "ai_review", "reviewer"), ids["ai_one"]: ("cash", "ai_review", "reviewer")}
    assert _members(rr.review(wp_id), ids)["ai_review"] == []
    assert [e["action"] for e in work.workpackage_events(wp_id)][-1] == "reconcile_mark"


def test_accepting_the_sure_pairs_allocates_them(db):
    wp_id, ids, inv = _setup()
    assert rr.accept(wp_id, "sure_pairs", [ids["pair"]], actor="reviewer") == 1
    line = next(ln for ln in rp.workspace(wp_id)["lines"] if ln["id"] == ids["pair"])
    assert line["state"] == "allocated" and line["allocations"][0]["invoice_id"] == inv


def test_a_line_no_longer_in_the_group_stops_the_whole_acceptance(db):
    wp_id, ids, _inv = _setup()
    with pytest.raises(work.RevisionConflict, match="no longer"):
        rr.accept(wp_id, "ai_sure", [ids["ai_sure"], ids["ai_low"]], actor="reviewer")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM reconcile_line_marks WHERE workpackage_id=?", (wp_id,)).fetchone()[0] == 0
    for group, message in (("expects_invoice", "nothing to accept"), ("nothing", "unknown group")):
        with pytest.raises(rr.ReviewError, match=message):
            rr.accept(wp_id, group, [ids["expects"]], actor="reviewer")
    with pytest.raises(rr.ReviewError, match="no line"):
        rr.accept(wp_id, "ai_sure", [], actor="reviewer")


def test_marking_several_reasons_at_once_is_all_or_none(db):
    wp_id, ids, _inv = _setup()
    with pytest.raises(rp.PackageError, match="unknown reason"):
        rp.mark_each(wp_id, {ids["ai_low"]: "private", ids["ai_one"]: "lottery"}, note=None, actor="reviewer", basis="ai_review")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM reconcile_line_marks WHERE workpackage_id=?", (wp_id,)).fetchone()[0] == 0
    rp.mark(wp_id, [ids["ai_low"]], category="private", note=None, actor="reviewer")  # a person's own mark: no basis
    with store.connect() as c:
        assert c.execute("SELECT basis FROM reconcile_line_marks WHERE line_id=?", (ids["ai_low"],)).fetchone()[0] is None


# --- the service ---------------------------------------------------------------------------------------------------------


def test_the_service_shows_the_review_and_accepts_a_group(db):
    from fastapi.testclient import TestClient

    from jav import api
    from tests.test_api import BASE, HUMAN

    wp_id, ids, _inv = _setup()
    client = TestClient(api.create_app(store_path=store.current_path()), base_url=BASE)
    got = client.get(f"/api/workpackages/{wp_id}/reconcile/quick-review")
    assert got.status_code == 200, got.text
    assert [g["id"] for g in got.json()["groups"]] == list(rr.GROUPS)
    body = {"group": "bank_category", "line_ids": [ids["atm"]]}
    assert client.post(f"/api/workpackages/{wp_id}/reconcile/quick-review/accept", json=body).status_code == 422  # unnamed
    done = client.post(f"/api/workpackages/{wp_id}/reconcile/quick-review/accept", headers=HUMAN, json=body)
    assert done.status_code == 200, done.text
    assert done.json()["accepted"] == 1 and _members(done.json()["review"], ids)["bank_category"] == []
    stale = client.post(f"/api/workpackages/{wp_id}/reconcile/quick-review/accept", headers=HUMAN, json=body)
    assert stale.status_code == 409
