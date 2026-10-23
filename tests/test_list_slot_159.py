"""159 (the list's two-minute rebuild): the package list no longer rebuilds every reconciliation workspace every two
minutes when nothing has changed.

The workspace's safety bound (`KEEP_SECONDS`, 120 s: a change the marks miss shows within this time) also ended the
list's rows, so the list built all six live reconciliation workspaces again every two minutes (5-6 s on one core,
slowing every other request). The list's next step now has its own, longer bound (`LIST_KEEP_SECONDS`); the pairing
page keeps the short one, and a change the marks see still shows at once. Synthetic data only; no AI call.
"""

from __future__ import annotations

import pytest

from jav import datasets
from jav.domains.finance import reconcile, reconcile_package as rp
from jav.tablequery import Query
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


def _list() -> dict:
    page = datasets.query("workpackages", None, Query())
    datasets.wait_for_rebuilds()
    return page


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
    page = _list()
    assert "refreshing" not in page and len(built) == 1


def test_the_list_rebuilds_its_workspaces_after_its_own_bound(db, clock, built):
    _package(built)
    _list()
    clock["t"] += rp.LIST_KEEP_SECONDS
    assert _list()["refreshing"] is True
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
    before = next(r for r in _list()["rows"] if r["id"] == wp)
    for line in rp.workspace(wp)["lines"]:
        rp.mark(wp, [line["id"]], category="private", note=None, actor="reviewer")
    _list()
    after = next(r for r in _list()["rows"] if r["id"] == wp)
    assert before["next_code"] == "reconcile_pair" and after["next_code"] == "reconcile_result"
