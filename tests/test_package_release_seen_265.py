"""265 (code review APPW-01): Approve and release releases only the result the page showed.

The release page shows each item's counted result. A live run started after an approved one is not counted until it
is approved (an approved run outranks it), yet Approve and release approved it with no reviewed version and released
its results, which the page never showed; a native item then failed half way, after earlier runs were approved. Now
every open live run has its reviewed version, the mark covers the open runs, and when approving them would change
which run counts for an item, the release names that run (`run_result_not_shown`) and approves nothing: the person
checks and approves it on its own page first. Synthetic PDFs, a fake JEV client, no paid calls.
"""

from jav.app import package_release, work_runs
from jav.runtime import worker
from tests import test_flexible_package_160c as fp
from tests.test_flexible_package_160c import _assign, _package, _start
from tests.test_package_release_171 import _live, _release, _result, _settle

env = fp.env  # the 160-C fixture: a store of its own, two synthetic invoices, a fake JEV client


def _rerun(c, wp_id: str, of: str) -> str:
    run_id = _start(c, wp_id, rerun_of=of)["run_id"]
    worker.run_worker(once=True)
    _settle(c, wp_id)
    return run_id


def test_a_run_whose_result_the_page_does_not_show_is_named_and_nothing_is_approved(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    first = _live(c, wp["id"])
    assert _release(c, wp["id"]).status_code == 200
    shown = _result(c, wp["id"])  # the page as the person loaded it: everything released
    rerun = _rerun(c, wp["id"], first)
    view = _result(c, wp["id"])
    assert view["open_live_runs"] == [rerun]
    assert {i["run_id"] for i in view["items"]} == {first}  # the approved run still counts
    assert {"code": "run_result_not_shown", "run_id": rerun} in view["blockers"]
    assert view["mark"] != shown["mark"]  # the open run is part of what the page shows
    r = c.post(f"/api/workpackages/{wp['id']}/release", headers=fp.HUMAN, json={"expected_mark": shown["mark"]})
    assert r.status_code == 409 and r.json()["error"] == "revision_conflict"
    r = _release(c, wp["id"])
    assert r.status_code == 409 and r.json()["error"] == "not_ready", r.text
    assert work_runs.get_run(rerun)["approval"] is None


def test_every_open_live_run_has_its_reviewed_version(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    first = _live(c, wp["id"])
    assert _release(c, wp["id"]).status_code == 200
    rerun = _rerun(c, wp["id"], first)
    view = package_release.view(wp["id"])
    assert view["open_live_runs"] == [rerun] and view["reviewed"].get(rerun)


def test_once_approved_on_its_own_page_the_run_s_result_is_released(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    first = _live(c, wp["id"])
    assert _release(c, wp["id"]).status_code == 200
    rerun = _rerun(c, wp["id"], first)
    from jav.app import corrections

    work_runs.approve_run(rerun, actor="reviewer", review_version=corrections.review_version(rerun))
    view = _result(c, wp["id"])
    assert {i["run_id"] for i in view["items"]} == {rerun} and not any(
        b["code"] == "run_result_not_shown" for b in view["blockers"])
    r = _release(c, wp["id"])
    assert r.status_code == 200, r.text
    assert r.json()["version"]["version"] == 2
