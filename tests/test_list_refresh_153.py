"""153: the package list answers at once and says what the owner has to do.

Measured live on 2026-10-13: the package list took 5.2 s once every two minutes (and after changes) and 0.03 s
otherwise, because it builds every reconciliation package's workspace and those expire on a 120 s time slot; the UI
asks every 10 s. A `refresh_behind` dataset now serves its last rows at once when its fingerprint has changed, rebuilds
in one background thread and says so (`refreshing`). A download and a run's tables are never served outdated.

The owner also could not tell from the list where an older live run waited to be superseded (152 offers it on the
package's page only), and a package whose two latest runs had been stopped offered "rerun" while its earlier live run
had 169 open to-dos. The list now counts the older runs to supersede, and a later stopped run hides nothing.
Synthetic data, no paid calls.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from jav import datasets, store, work, work_views, workflows
from jav.tablequery import Column, Query
from tests.test_supersede_runs_151 import runs  # noqa: F401 - the shared fixture: one package, an older and a newer live run


@pytest.fixture(autouse=True)
def fresh_cache():
    datasets.clear_cache()
    yield
    datasets.clear_cache()


class _Source:
    """A dataset whose fingerprint and build the test controls; a build can be held until released."""

    def __init__(self) -> None:
        self.version = 1
        self.builds: list[int] = []
        self.paths: list[Path] = []
        self.release = threading.Event()
        self.release.set()
        self.fail = False

    def fingerprint(self, scope: dict[str, str]) -> str:
        return str(self.version)

    def build(self, scope: dict[str, str]):
        self.release.wait(10)
        self.paths.append(store.active_path())
        if self.fail:
            raise RuntimeError("synthetic build failure")
        self.builds.append(self.version)
        return [Column("v", "V", "number")], [{"_key": "1", "v": self.version}]


@pytest.fixture()
def source(monkeypatch, tmp_path):
    src = _Source()
    monkeypatch.setitem(datasets.REGISTRY, "probe", datasets.Dataset("probe", "Probe", (), src.build, src.fingerprint,
                                                                      refresh_behind=True))
    with store.use_store(tmp_path / "probe.sqlite"):
        yield src


def _value(page) -> int:
    return page["rows"][0]["v"]


def test_a_changed_list_answers_with_its_last_rows_and_rebuilds_behind(source):
    first = datasets.query("probe", None, Query())
    assert _value(first) == 1 and "refreshing" not in first
    source.version = 2
    source.release.clear()  # the rebuild is held: the answer must not wait for it
    stale = datasets.query("probe", None, Query())
    assert _value(stale) == 1 and stale["refreshing"] is True
    again = datasets.query("probe", None, Query())  # a second request while it runs starts no second rebuild
    assert _value(again) == 1 and again["refreshing"] is True
    source.release.set()
    datasets.wait_for_rebuilds()
    fresh = datasets.query("probe", None, Query())
    assert _value(fresh) == 2 and "refreshing" not in fresh
    assert source.builds == [1, 2]


def test_the_rebuild_reads_the_requests_store(source, tmp_path):
    datasets.query("probe", None, Query())
    source.version = 2
    datasets.query("probe", None, Query())
    datasets.wait_for_rebuilds()
    assert source.paths == [tmp_path / "probe.sqlite"] * 2


def test_a_failed_rebuild_keeps_the_last_rows_and_the_next_request_tries_again(source, caplog):
    datasets.query("probe", None, Query())
    source.version, source.fail = 2, True
    assert _value(datasets.query("probe", None, Query())) == 1
    datasets.wait_for_rebuilds()
    assert "background rebuild of dataset probe failed" in caplog.text
    source.fail = False
    assert datasets.query("probe", None, Query())["refreshing"] is True  # still the last rows; a new rebuild starts
    datasets.wait_for_rebuilds()
    assert _value(datasets.query("probe", None, Query())) == 2


def test_a_download_is_never_outdated(source):
    datasets.query("probe", None, Query())
    source.version = 2
    _cols, rows = datasets.rows("probe")
    assert rows[0]["v"] == 2


def test_only_the_package_list_is_served_outdated():
    """A run's tables carry the version of the reviewed result an approval names (086): never outdated."""
    assert [d.name for d in datasets.REGISTRY.values() if d.refresh_behind] == ["workpackages"]


# --- what the list says ----------------------------------------------------------------------------------------------------


def _row(wp_id: str) -> dict:
    datasets.query("workpackages", None, Query())
    datasets.wait_for_rebuilds()
    return next(r for r in datasets.query("workpackages", None, Query())["rows"] if r["id"] == wp_id)


def test_the_list_counts_the_older_runs_to_supersede(runs):  # noqa: F811
    with store.use_store(runs["db"]):
        column = next(c for c in datasets.query("workpackages", None, Query())["columns"] if c["key"] == "older_runs")
        assert column["link"] == "process" and column["alert"] is True and not column.get("hidden")
        assert _row(runs["wp"])["older_runs"] == 1
        work.supersede_run(runs["older"], actor="teszt.elek")
        assert _row(runs["wp"])["older_runs"] == 0


def test_a_later_stopped_run_does_not_hide_the_earlier_live_runs_to_dos(runs):  # noqa: F811
    with store.use_store(runs["db"]):
        work.cancel_run(runs["newer"], actor="teszt.elek")
        row = _row(runs["wp"])
        assert row["last_status"] == "cancelled"  # the list still says what happened last
        assert row["next_code"] == "review" and row["open_reasons"] == 2  # the older live run's to-dos
        view = work_views.workpackage_view(runs["wp"])
        assert view["last_run"]["run_id"] == runs["newer"] and view["current_run"]["run_id"] == runs["older"]
        assert view["next"]["code"] == "review" and view["next"]["params"] == {"n": 2}


def test_a_package_whose_runs_were_all_stopped_still_offers_a_rerun(runs):  # noqa: F811
    with store.use_store(runs["db"]):
        work.cancel_run(runs["older"], actor="teszt.elek")
        work.cancel_run(runs["newer"], actor="teszt.elek")
        assert work_views.workpackage_view(runs["wp"])["next"]["code"] == "rerun"
        assert _row(runs["wp"])["next_code"] == "rerun"


def test_the_current_run_passes_over_stopped_runs_only():
    runs_ = [{"run_id": "c", "status": "cancelled"}, {"run_id": "f", "status": "failed"},
             {"run_id": "r", "status": "needs_review"}]
    assert work_views.current_run(runs_)["run_id"] == "f"  # a failed run still asks for a rerun
    assert work_views.current_run(runs_[:1])["run_id"] == "c"
    assert work_views.current_run([]) is None


def test_a_workflow_step_stays_done_when_a_later_live_run_was_stopped(runs):  # noqa: F811
    with store.use_store(runs["db"]):
        with store.connect() as c:  # the older run approved: its to-dos closed first, as an approval requires
            c.execute("UPDATE review_reasons SET status='resolved' WHERE substr(run_id, 1, ?) = ?",
                      (len(runs["older"]) + 1, runs["older"] + ":"))
            c.execute("UPDATE runs SET status='done', approval='approved' WHERE run_id=?", (runs["older"],))
        work.cancel_run(runs["newer"], actor="teszt.elek")
        approved, nxt = workflows._package_state(runs["wp"])
        assert approved is True and nxt["code"] == "done"
