"""153 (review B1, B2, B4): the package's page, the run's page and the run list read through one connection.

Measured live on 2026-10-13: a package of 468 documents opened in 4.0-4.2 s, because its readiness check opened two
connections per document (944 in all); the run page of such a run took 1.6 s on every poll for the same reason (one
connection per item's native check); the run list opened one per run. A run's open to-dos are counted by a range on
the item flow ids, which an index on the to-dos serves. Synthetic data, no paid calls.
"""

from __future__ import annotations

import sqlite3

import pytest

from jav import work_readiness, work_runs, work_views
from jav.core import store
from tests.test_supersede_runs_151 import runs  # noqa: F401 - the shared fixture: one package, an older and a newer live run


@pytest.fixture()
def connections(monkeypatch):
    opened: list[str] = []
    real = sqlite3.connect

    def counting(*args, **kwargs):
        opened.append(str(args[0]) if args else "")
        return real(*args, **kwargs)

    monkeypatch.setattr(store.sqlite3, "connect", counting)
    return opened


@pytest.mark.parametrize("view", ["package", "run", "run_list", "readiness"])
def test_a_view_opens_one_connection(runs, connections, view):  # noqa: F811
    with store.use_store(runs["db"]):
        with store.connect():
            pass  # the store's structure is checked once per process; the views below find it ready
        connections.clear()
        if view == "package":
            work_views.workpackage_view(runs["wp"])
        elif view == "run":
            work_views.run_view(runs["newer"])
        elif view == "run_list":
            work_views.run_list(None)
            work_views.run_list(runs["wp"])
        else:
            work_readiness.readiness(runs["wp"])
    assert len(connections) <= (2 if view == "run_list" else 1), connections


def test_a_runs_open_to_dos_count_only_its_own_items(runs):  # noqa: F811
    """The range `<run>:` .. `<run>;` takes the run's item flow ids only, not a run whose id starts the same."""
    with store.use_store(runs["db"]):
        longer = runs["older"] + "0"  # an id that extends the older run's id
        store.review_enqueue(subject_kind="document", subject_id="x", run_id=work_runs.flow_run_id(longer, "abc"),
                             reasons=["pick:seller_name"], producer="m2")
        rows = {r["run_id"]: r["open_reasons"] for r in work_runs.run_rows(runs["wp"])}
        assert rows == {runs["older"]: 2, runs["newer"]: 1}
        with store.connect() as c:
            plan = " ".join(r["detail"] for r in c.execute(
                "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM review_reasons x WHERE x.status='open'"
                " AND x.run_id >= ? AND x.run_id < ?", (runs["older"] + ":", runs["older"] + ";")))
        assert "ix_review_reasons_status_run" in plan
