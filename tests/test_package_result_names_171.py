"""171 (plan 170, L1): the item list's name comes from the same run as its counted result. Before, the name came from
the latest run in which the item finished (a later trial, or a stopped run), while the "Counting run" column showed the
approved or live run. Synthetic PDFs, a fake JEV client, no paid calls."""

from jav.app import naming, work, work_runs
from jav.core import store
from jav.runtime import worker
from tests import test_flexible_package_160c as fp
from tests.test_flexible_package_160c import _assign, _package, _start

env = fp.env  # the 160-C fixture: a store of its own, two synthetic invoices, a fake JEV client


def _runs_of(wp_id: str) -> tuple[set[str | None], set[str | None]]:
    wp = work.get(wp_id)
    names = naming.package_item_names(wp)
    states = work_runs.item_states(wp_id, wp["items"])
    return {n.run_id for n in names.values()}, {s["run_id"] for s in states.values()}


def test_a_later_trial_gives_neither_the_name_nor_the_counted_result(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    live = _start(c, wp["id"])["run_id"]
    worker.run_worker(once=True)
    _start(c, wp["id"], mode="shadow")
    worker.run_worker(once=True)
    assert _runs_of(wp["id"]) == ({live}, {live})


def test_a_stopped_run_gives_no_name(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    run_id = _start(c, wp["id"], mode="shadow")["run_id"]
    worker.run_worker(once=True)
    assert _runs_of(wp["id"]) == ({run_id}, {run_id})
    with store.connect() as conn:
        conn.execute("UPDATE runs SET status='cancelled' WHERE run_id=?", (run_id,))
    names = naming.package_item_names(work.get(wp["id"]))
    assert {n.state for n in names.values()} == {"pending"} and _runs_of(wp["id"]) == ({None}, {None})
