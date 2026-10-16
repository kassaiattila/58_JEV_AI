"""158: the package list is ready when the service starts, and it stays in the cache.

Reported on 2026-10-16: the package list was slow the first time it was opened, then fast. Measured: after a service
start the list is not cached yet, so the first request builds it while the person waits; that build is the six
reconciliation packages' workspaces (5.2-6.2 s on a copy of the store, 7-8 s on a fresh start). The same wait came back
whenever the result tables of a few runs pushed the list out of the 24-entry cache. Now the service builds the list in
the background when it starts, a request that arrives meanwhile waits for that build instead of starting a second one,
and the result tables no longer push a refresh-behind dataset out of the cache. Synthetic data, no paid calls.
"""

from __future__ import annotations

import contextvars
import threading

import pytest

from jav import api, datasets, store
from jav.tablequery import Column, Query


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
        self.release = threading.Event()
        self.release.set()

    def fingerprint(self, scope: dict[str, str]) -> str:
        return f"{self.version}:{scope.get('run_id', '')}"

    def build(self, scope: dict[str, str]):
        self.release.wait(10)
        self.builds.append(self.version)
        return [Column("v", "V", "number")], [{"_key": "1", "v": self.version}]


@pytest.fixture()
def lists(monkeypatch, tmp_path):
    """`probe`: a refresh-behind list; `table`: a run's table, one cache entry per run."""
    listing, table = _Source(), _Source()
    monkeypatch.setitem(datasets.REGISTRY, "probe", datasets.Dataset("probe", "Probe", (), listing.build,
                                                                      listing.fingerprint, refresh_behind=True))
    monkeypatch.setitem(datasets.REGISTRY, "table", datasets.Dataset("table", "Table", ("run_id",), table.build,
                                                                      table.fingerprint))
    monkeypatch.setattr(datasets, "_warm_names", lambda: ["probe"])
    with store.use_store(tmp_path / "probe.sqlite"):
        yield listing, table


def _value(page) -> int:
    return page["rows"][0]["v"]


def test_the_warm_up_builds_the_list_before_anyone_asks(lists):
    listing, _ = lists
    datasets.warm_up()
    datasets.wait_for_rebuilds()
    assert listing.builds == [1]
    page = datasets.query("probe", None, Query())
    assert _value(page) == 1 and "refreshing" not in page
    assert listing.builds == [1]  # the request found it ready


def test_a_request_during_the_warm_up_waits_for_it_instead_of_building_again(lists):
    listing, _ = lists
    listing.release.clear()  # the warm-up build is held
    datasets.warm_up()
    answers: list[dict] = []
    context = contextvars.copy_context()  # the request's store, as the service's middleware sets it
    asker = threading.Thread(target=lambda: answers.append(context.run(datasets.query, "probe", None, Query())))
    asker.start()
    asker.join(0.3)
    assert asker.is_alive()  # it waits for the running build
    listing.release.set()
    asker.join(10)
    assert _value(answers[0]) == 1 and "refreshing" not in answers[0]
    assert listing.builds == [1]  # one build, not two


def test_the_warm_up_leaves_a_list_already_cached_alone(lists):
    listing, _ = lists
    datasets.query("probe", None, Query())
    datasets.warm_up()
    datasets.wait_for_rebuilds()
    assert listing.builds == [1]


def test_the_result_tables_of_many_runs_do_not_push_the_list_out(lists):
    listing, table = lists
    datasets.query("probe", None, Query())
    for i in range(datasets.cfg.load("datasets")["cache_entries"] + 6):
        datasets.query("table", {"run_id": f"run-{i}"}, Query())
    page = datasets.query("probe", None, Query())
    assert _value(page) == 1 and "refreshing" not in page
    assert listing.builds == [1]  # served from the cache, not built again while the person waits
    datasets.query("table", {"run_id": "run-0"}, Query())  # the tables themselves still take turns
    assert table.builds.count(1) == datasets.cfg.load("datasets")["cache_entries"] + 7


def test_only_the_package_list_is_warmed_up():
    assert datasets._warm_names() == ["workpackages"]


def test_the_service_warms_the_list_up_when_it_starts(monkeypatch):
    import uvicorn

    from jav.runtime import preload

    order: list[str] = []
    monkeypatch.setattr(preload, "preload", lambda: order.append("preload"))
    monkeypatch.setattr(datasets, "warm_up", lambda: order.append("warm_up"))
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: order.append("run"))
    api.serve()
    assert order == ["preload", "warm_up", "run"]
