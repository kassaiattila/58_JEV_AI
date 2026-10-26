"""171 (plan 170 L1 = plan 160-E S4; DECISIONS 167, 171): Approve and release a package.

One step approves the package's open live runs together and records a released package version; its downloads are
the stored files, so they never change. The package reads not released, released, partly released (an item without
a released result) or changed since the release (a released item removed or replaced). A package approved before
gets its first version recorded afterwards. Synthetic PDFs, a fake JEV client, no paid calls."""

import hashlib

from jav.app import package_release, work, work_runs
from jav.core import store
from jav.runtime import worker
from tests import test_flexible_package_160c as fp
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_flexible_package_160c import HUMAN, _assign, _package, _start

env = fp.env  # the 160-C fixture: a store of its own, two synthetic invoices, a fake JEV client


def _result(c, wp_id: str) -> dict:
    r = c.get(f"/api/workpackages/{wp_id}/result")
    assert r.status_code == 200, r.text
    return r.json()


def _settle(c, wp_id: str) -> None:
    """A person settles every open to-do of the package."""
    for reason in (r for item in c.get(f"/api/workpackages/{wp_id}/reviews").json()["items"] for r in item["open_reasons"]):
        assert c.post(f"/api/review-reasons/{reason['id']}/resolve", json={"note": "checked"}, headers=HUMAN).status_code == 200


def _live(c, wp_id: str, **extra) -> str:
    run_id = _start(c, wp_id, **extra)["run_id"]
    worker.run_worker(once=True)
    _settle(c, wp_id)
    return run_id


def _release(c, wp_id: str, **body):
    mark = _result(c, wp_id)["mark"]
    return c.post(f"/api/workpackages/{wp_id}/release", headers=HUMAN, json={"expected_mark": mark, **body})


def test_release_approves_the_open_live_run_and_keeps_its_downloads(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    run_id = _live(c, wp["id"])
    before = _result(c, wp["id"])
    assert before["state"] == "not_released" and before["open_live_runs"] == [run_id] and before["blockers"] == []
    assert {i["tier"] for i in before["items"]} == {"live"}
    r = _release(c, wp["id"])
    assert r.status_code == 200, r.text
    version = r.json()["version"]
    assert version["version"] == 1 and version["runs"] == [run_id] and version["backfilled_at"] is None
    # 178: the utility cost's workbook only with utility bills (these are invoices); 180: not among the general files
    assert {name for f in version["files"] for name in [f["name"]]} == {n for n, _m in package_release.FILES}
    assert work_runs.get_run(run_id)["approval"] == "approved"
    after = r.json()["result"]
    assert after["state"] == "released" and {i["tier"] for i in after["items"]} == {"approved"}
    assert all(i["released"] for i in after["items"])
    assert {b["code"] for b in after["blockers"]} == {"nothing_to_release"}
    files = {f["name"]: f for f in version["files"]}
    for name in ("result.xlsx", "documents.csv", "result.json"):
        first = c.get(f"/api/workpackages/{wp['id']}/versions/1/files/{name}")
        second = c.get(f"/api/workpackages/{wp['id']}/versions/1/files/{name}")
        assert first.status_code == 200 and first.content == second.content
        assert hashlib.sha256(first.content).hexdigest() == files[name]["sha256"]
    assert files["documents.csv"]["rows"] == 2
    assert [e["action"] for e in work.workpackage_events(wp["id"])][-1] == "package_release"


def test_a_release_needs_the_shown_result_and_settled_to_dos(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    _start(c, wp["id"])
    worker.run_worker(once=True)
    view = _result(c, wp["id"])
    if any(b["code"] == "run_not_ready" for b in view["blockers"]):  # the fake model's answers raise to-dos
        r = _release(c, wp["id"])
        assert r.status_code == 409 and r.json()["error"] == "not_ready"
        _settle(c, wp["id"])
    r = c.post(f"/api/workpackages/{wp['id']}/release", headers=HUMAN, json={"expected_mark": "0" * 16})
    assert r.status_code == 409 and r.json()["error"] == "revision_conflict"
    assert _release(c, wp["id"]).status_code == 200
    again = _release(c, wp["id"])
    assert again.status_code == 422 and again.json()["error"] == "release_refused"


def test_a_new_item_makes_it_partly_released_and_the_next_release_takes_it(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    _live(c, wp["id"])
    assert _release(c, wp["id"]).status_code == 200
    third = env["folder"] / "invoice_3.pdf"
    write_text_pdf(third, [line.replace("MINTA-2026-001", "MINTA-2026-003") for line in INVOICE_LINES])
    work.add_documents(wp["id"], [third], expected_revision=work.get(wp["id"])["revision"])
    assert _result(c, wp["id"])["state"] == "partly_released"
    ready = c.get(f"/api/workpackages/{wp['id']}/workflow/readiness").json()
    r = c.post(f"/api/workpackages/{wp['id']}/workflow/start", headers=HUMAN,
               json={"mode": "apply", "scope": "pending", "expected_revision": ready["assignment_revision"],
                     "input_hash": ready["supplement"]["apply"]["input_hash"]})
    assert r.status_code in (200, 201), r.text
    run_id = r.json()["run_id"]
    worker.run_worker(once=True)
    _settle(c, wp["id"])
    r = _release(c, wp["id"])
    assert r.status_code == 200, r.text
    assert r.json()["version"]["version"] == 2 and r.json()["version"]["runs"] == [run_id]
    assert r.json()["result"]["state"] == "released" and len(r.json()["version"]["items"]) == 3
    old = {f["name"]: f["sha256"] for f in _result(c, wp["id"])["versions"][1]["files"]}
    assert hashlib.sha256(c.get(f"/api/workpackages/{wp['id']}/versions/1/files/documents.csv").content).hexdigest() == old["documents.csv"]


def test_removing_a_released_item_reads_changed_since_the_release(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    _live(c, wp["id"])
    assert _release(c, wp["id"]).status_code == 200
    item = wp["items"][0]["item_id"]
    r = c.post(f"/api/workpackages/{wp['id']}/items/{item}/remove", headers=HUMAN,
               json={"expected_revision": work.get(wp["id"])["revision"], "reason": "not this package's"})
    assert r.status_code == 200, r.text
    assert _result(c, wp["id"])["state"] == "changed_since_release"


def test_a_package_approved_before_gets_its_first_version_afterwards(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    run_id = _live(c, wp["id"])
    assert c.post(f"/api/runs/{run_id}/approve", json={}, headers=HUMAN).status_code == 200  # the way before v1.20.0
    assert _result(c, wp["id"])["state"] == "not_released"
    assert package_release.backfill(dry_run=True)[0]["workpackage_id"] == wp["id"]
    assert _result(c, wp["id"])["versions"] == []
    done = package_release.backfill()
    assert [(d["workpackage_id"], d["version"], d["items"]) for d in done] == [(wp["id"], 1, 2)]
    view = _result(c, wp["id"])
    assert view["state"] == "released"
    version = view["versions"][0]
    assert version["backfilled_at"] and version["runs"] == [] and version["released_by"] == HUMAN["X-Actor"]
    assert version["released_at"] == work_runs.get_run(run_id)["approved_at"]
    assert package_release.backfill() == []  # idempotent


def test_a_reconciliation_package_is_released_in_its_own_statement(env):
    wp_id = "wp-0000000000a1"
    with store.connect() as conn:
        conn.execute("INSERT INTO workpackages(id, name, source_kind, created_at, updated_at) VALUES (?,?,?,?,?)",
                     (wp_id, "Synthetic reconciliation", "case", "2026-10-18T08:00:00+00:00", "2026-10-18T08:00:00+00:00"))
    # 231 (C3a-2): a reconciliation is its process pack's case; a case's container is approved on its own page too
    view = package_release.view(wp_id)
    assert {b["code"] for b in view["blockers"]} == {"own_approval"} and view["state"] == "not_released"
    r = env["client"].post(f"/api/workpackages/{wp_id}/release", headers=HUMAN, json={"expected_mark": view["mark"]})
    assert r.status_code == 422 and r.json()["error"] == "release_refused"


def test_a_released_packages_page_carries_its_release_for_the_stage_bar(env):
    """181 (backlog J-szakaszsav-kiadott-proba): the package's page says its release state and latest version, so a
    trial run after a release no longer reads as only a trial result on the stage bar; a package never released has
    none."""
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    _live(c, wp["id"])
    assert "release" not in c.get(f"/api/workpackages/{wp['id']}").json()
    assert _release(c, wp["id"]).status_code == 200
    assert c.get(f"/api/workpackages/{wp['id']}").json()["release"] == {"state": "released", "version": 1}
    _start(c, wp["id"], mode="shadow")  # a trial after the release
    worker.run_worker(once=True)
    page = c.get(f"/api/workpackages/{wp['id']}").json()
    assert page["current_run"]["mode"] == "shadow" and page["release"] == {"state": "released", "version": 1}
