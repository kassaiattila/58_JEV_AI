"""159 (the list's two-minute rebuild): the package list no longer rebuilds every reconciliation workspace every two
minutes when nothing has changed.

The workspace's safety bound (`KEEP_SECONDS`, 120 s: a change the marks miss shows within this time) also ended the
list's rows, so the list built all six live reconciliation workspaces again every two minutes (5-6 s on one core,
slowing every other request). The list's next step now has its own, longer bound (`LIST_KEEP_SECONDS`); the pairing
page keeps the short one, and a change the marks see still shows at once. 231 (U2a; the owner's decision of 2026-10-28:
one work list, the cases): a reconciliation is a case, so the list of every document batch leaves it out and builds no
workspace at all; the list of every package (the service's full list, the command line's) still reads its container's
next step by the list's bound. Synthetic data only; no AI call.
"""

from __future__ import annotations

import pytest

from jav.app import datasets, work_views
from jav.domains.finance import reconcile, reconcile_package as rp
from jav.app.tablequery import Query
from tests import test_list_speed_140 as l140
from tests import test_reconcile_package_131 as p131

db = p131.db
fresh_caches = l140.fresh_caches

# the start of a list slot, so that one workspace slot later is still the same list slot
START = 1_800_000_000 - 1_800_000_000 % rp.LIST_KEEP_SECONDS + 1


@pytest.fixture
def clock(monkeypatch):
    now = {"t": float(START)}
    monkeypatch.setattr(rp.time, "time", lambda: now["t"])
    return now


@pytest.fixture
def built(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = reconcile.propose

    def propose(snap):
        calls.append(1)
        return real(snap)

    monkeypatch.setattr(reconcile, "propose", propose)
    return calls


def _list() -> list[dict]:
    """231 (U2a): the list of every package, where a reconciliation's container still shows its next step."""
    return work_views.workpackage_list()


def _code(wp: str) -> str:
    return next(r for r in _list() if r["id"] == wp)["next"]["code"]


def _package(built: list[int]) -> str:
    """A reconciliation package; its first build creates the tables a fresh test store lacks (a real store has them),
    which would change the marks once."""
    wp, _statement, _invoice = l140._workspace_package()
    rp.workspace(wp)
    datasets.clear_cache()
    rp.clear_cache()
    built.clear()
    return wp


def test_the_list_keeps_its_workspaces_past_the_pairing_pages_bound(db, clock, built):
    _package(built)
    _list()
    assert len(built) == 1
    clock["t"] += rp.KEEP_SECONDS
    _list()
    assert len(built) == 1


def test_the_list_rebuilds_its_workspaces_after_its_own_bound(db, clock, built):
    _package(built)
    _list()
    clock["t"] += rp.LIST_KEEP_SECONDS
    _list()
    assert len(built) == 2


def test_the_pairing_page_keeps_the_short_bound_after_the_list_built_it(db, clock, built):
    wp = _package(built)
    _list()
    rp.workspace(wp)
    assert len(built) == 1  # the list's workspace is fresh enough for the pairing page
    clock["t"] += rp.KEEP_SECONDS
    rp.workspace(wp)
    assert len(built) == 2


def test_a_workspace_the_pairing_page_built_serves_the_list(db, clock, built):
    wp = _package(built)
    rp.workspace(wp)
    _list()
    assert len(built) == 1


def test_a_change_still_shows_in_the_list_at_once(db, clock, built):
    wp = _package(built)
    before = _code(wp)
    for line in rp.workspace(wp)["lines"]:
        rp.mark(wp, [line["id"]], category="private", note=None, actor="reviewer")
    assert before == "reconcile_pair" and _code(wp) == "reconcile_result"


def test_the_list_of_every_batch_leaves_the_reconciliation_out_and_builds_none(db, clock, built):
    wp = _package(built)
    page = datasets.query("workpackages", None, Query())
    datasets.wait_for_rebuilds()
    assert all(r["id"] != wp for r in page["rows"]) and not built
