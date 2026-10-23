"""160-C (plan F-flexible work package, S1-S3; decisions 163 D2, D3, D7): a package stays open after its first run.

S1: an item is removed by a named person with a reason, logged and restorable; a removed item stays out of new runs,
and a finished run keeps it. Synthetic PDFs, a fake JEV client, no paid calls.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav import api, work, work_runs
from jav.core import store
from jav.adapters import jev as jev_mod
from jav.runtime import worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_runtime_worker import FakeClient

BASE = "http://127.0.0.1:8930"
HUMAN = {"X-Actor": "teszt.elek"}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    folder = root / "incoming"
    folder.mkdir(parents=True)
    write_text_pdf(folder / "invoice_1.pdf", INVOICE_LINES)
    write_text_pdf(folder / "invoice_2.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-002") for line in INVOICE_LINES])
    monkeypatch.setenv("JAV_API_ROOTS", str(root))
    db = tmp_path / "w.sqlite"
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    client = TestClient(api.create_app(store_path=db), base_url=BASE)
    with store.use_store(db), jev_mod.use_adapter(adapter):
        yield {"client": client, "folder": folder, "root": root}


def _package(c: TestClient, folder: Path) -> dict:
    r = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(folder), "name": "Synthetic invoices"})
    assert r.status_code == 201, r.text
    return r.json()["workpackage"]


def _items(c: TestClient, wp_id: str, *, removed: bool = False) -> list[dict]:
    scope = {"workpackage_id": wp_id, **({"removed": "1"} if removed else {})}
    return c.post("/api/datasets/workpackage_items/query", json={"scope": scope, "query": {}}).json()["rows"]


# --- S1: removal by name, with a reason, restorable ---------------------------------------------------------------


def test_removal_records_who_why_and_when_and_stays_visible_behind_the_switch(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    item = wp["items"][0]["item_id"]
    r = c.post(f"/api/workpackages/{wp['id']}/items/{item}/remove", headers=HUMAN,
               json={"expected_revision": wp["revision"], "reason": "a duplicate scan"})
    assert r.status_code == 200, r.text
    assert [i["item_id"] for i in r.json()["workpackage"]["items"]] == [wp["items"][1]["item_id"]]
    assert [row["item_id"] for row in _items(c, wp["id"])] == [wp["items"][1]["item_id"]]  # hidden by default
    shown = {row["item_id"]: row for row in _items(c, wp["id"], removed=True)}
    assert set(shown) == {i["item_id"] for i in wp["items"]}
    assert shown[item]["removed_by"] == "teszt.elek" and shown[item]["removed_reason"] == "a duplicate scan"
    assert shown[item]["removed_at"] and shown[item]["_removed"] is True
    assert shown[wp["items"][1]["item_id"]]["_removed"] is False
    event = work.workpackage_events(wp["id"])[-1]
    assert (event["action"], event["actor"]) == ("item_remove", "teszt.elek")
    assert json.loads(event["detail"]) == {"item_id": item, "reason": "a duplicate scan"}


def test_removal_needs_a_reason_and_a_current_page(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    url = f"/api/workpackages/{wp['id']}/items/{wp['items'][0]['item_id']}/remove"
    assert c.post(url, headers=HUMAN, json={"expected_revision": wp["revision"]}).status_code == 422
    assert c.post(url, headers=HUMAN, json={"expected_revision": wp["revision"], "reason": "   "}).status_code == 422
    assert c.post(url, json={"expected_revision": wp["revision"], "reason": "no actor"}).status_code == 422
    assert c.post(url, headers=HUMAN, json={"expected_revision": wp["revision"] + 1, "reason": "stale"}).status_code == 409
    assert len(work.get(wp["id"])["items"]) == 2 and work.get(wp["id"])["revision"] == wp["revision"]


def test_restore_brings_the_item_back_and_is_logged(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    item = wp["items"][0]["item_id"]
    removed = c.post(f"/api/workpackages/{wp['id']}/items/{item}/remove", headers=HUMAN,
                     json={"expected_revision": wp["revision"], "reason": "wrong month"}).json()["workpackage"]
    r = c.post(f"/api/workpackages/{wp['id']}/items/{item}/restore", headers=HUMAN, json={"expected_revision": removed["revision"]})
    assert r.status_code == 200, r.text
    assert {i["item_id"] for i in r.json()["workpackage"]["items"]} == {i["item_id"] for i in wp["items"]}
    assert all(row["_removed"] is False for row in _items(c, wp["id"], removed=True))
    event = work.workpackage_events(wp["id"])[-1]
    assert (event["action"], event["actor"], json.loads(event["detail"])) == ("item_restore", "teszt.elek", {"item_id": item})
    again = c.post(f"/api/workpackages/{wp['id']}/items/{item}/restore", headers=HUMAN,
                   json={"expected_revision": r.json()["workpackage"]["revision"]})
    assert again.status_code == 404  # only a removed item can be restored


def _assign(c: TestClient, wp_id: str) -> None:
    r = c.post(f"/api/workpackages/{wp_id}/workflow", headers=HUMAN,
               json={"recipe_id": "invoice-extraction", "params": {"arm": "S"}, "expected_revision": 0, "note": "first"})
    assert r.status_code == 200, r.text


def _start(c: TestClient, wp_id: str, mode: str = "apply", **extra) -> dict:
    ready = c.get(f"/api/workpackages/{wp_id}/workflow/readiness").json()
    r = c.post(f"/api/workpackages/{wp_id}/workflow/start", headers=HUMAN,
               json={"mode": mode, "expected_revision": ready["assignment_revision"], "input_hash": ready["input_hash"], **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_a_removed_item_stays_out_of_the_next_run_and_a_finished_run_keeps_it(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    run_id = _start(c, wp["id"])["run_id"]
    worker.run_worker(once=True)
    removed = wp["items"][0]["item_id"]
    c.post(f"/api/workpackages/{wp['id']}/items/{removed}/remove", headers=HUMAN,
           json={"expected_revision": work.get(wp["id"])["revision"], "reason": "not ours"})
    ready = c.get(f"/api/workpackages/{wp['id']}/workflow/readiness").json()
    assert ready["counts"]["items"] == 1
    finished = work_runs.get_run(run_id)
    assert {i["item_id"] for i in finished["input"]["items"]} == {i["item_id"] for i in wp["items"]}
    assert {i["item_id"] for i in finished["items"]} == {i["item_id"] for i in wp["items"]}


def _finished_live_run(c: TestClient, wp: dict) -> str:
    """A live run of the package, processed, with its to-dos closed by a person: ready for approval."""
    _assign(c, wp["id"])
    run_id = _start(c, wp["id"])["run_id"]
    worker.run_worker(once=True)
    for reason in (r for item in c.get(f"/api/workpackages/{wp['id']}/reviews").json()["items"] for r in item["open_reasons"]):
        assert c.post(f"/api/review-reasons/{reason['id']}/resolve", json={"note": "checked"}, headers=HUMAN).status_code == 200
    return run_id


def _exported_items(c: TestClient, run_id: str) -> set[str]:
    data = c.get(f"/api/runs/{run_id}/export", params={"format": "json"}).json()
    return {d["item_id"] for d in data["documents"]}


def test_approval_with_a_removed_item_needs_a_confirmation_and_releases_without_it(env):
    """Decision 163 D7: a live run can be approved after one of its items was removed from the package, with a
    warning; the removed item's result is not part of the released result."""
    c = env["client"]
    wp = _package(c, env["folder"])
    run_id = _finished_live_run(c, wp)
    kept, removed = wp["items"][1]["item_id"], wp["items"][0]["item_id"]
    assert _exported_items(c, run_id) == {kept, removed}
    c.post(f"/api/workpackages/{wp['id']}/items/{removed}/remove", headers=HUMAN,
           json={"expected_revision": work.get(wp["id"])["revision"], "reason": "sent by mistake"})
    view = c.get(f"/api/runs/{run_id}").json()
    assert view["removed_items"] == [removed]
    refused = c.post(f"/api/runs/{run_id}/approve", json={}, headers=HUMAN)
    assert refused.status_code == 409 and refused.json()["blockers"][0]["code"] == "removed_items"
    assert c.post(f"/api/runs/{run_id}/approve", json={"confirm_removed": 2}, headers=HUMAN).status_code == 409  # a stale count
    approved = c.post(f"/api/runs/{run_id}/approve", json={"confirm_removed": 1}, headers=HUMAN)
    assert approved.status_code == 200, approved.text
    assert _exported_items(c, run_id) == {kept}
    c.post(f"/api/workpackages/{wp['id']}/items/{removed}/restore", headers=HUMAN,
           json={"expected_revision": work.get(wp["id"])["revision"]})
    assert _exported_items(c, run_id) == {kept}  # the released result does not change afterwards (decision 160 D1)


def test_a_removed_items_open_to_dos_do_not_block_the_approval(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    run_id = _start(c, wp["id"])["run_id"]
    worker.run_worker(once=True)
    reviews = c.get(f"/api/workpackages/{wp['id']}/reviews").json()["items"]
    open_by_item = {i["item_id"]: i["open_reasons"] for i in reviews if i["open_reasons"]}
    assert open_by_item, "the synthetic invoices leave to-dos (the precondition of this test)"
    blocked = next(iter(open_by_item))
    for item_id, reasons in open_by_item.items():
        if item_id != blocked:
            for reason in reasons:
                c.post(f"/api/review-reasons/{reason['id']}/resolve", json={"note": "checked"}, headers=HUMAN)
    assert c.post(f"/api/runs/{run_id}/approve", json={}, headers=HUMAN).status_code == 409  # its to-dos are open
    c.post(f"/api/workpackages/{wp['id']}/items/{blocked}/remove", headers=HUMAN,
           json={"expected_revision": work.get(wp["id"])["revision"], "reason": "not an invoice"})
    c.post(f"/api/workpackages/{wp['id']}/items/{blocked}/restore", headers=HUMAN,
           json={"expected_revision": work.get(wp["id"])["revision"]})
    assert c.post(f"/api/runs/{run_id}/approve", json={}, headers=HUMAN).status_code == 409  # restored: they count again
    assert work_runs.run_rows(wp["id"])[0]["open_reasons"] > 0
    c.post(f"/api/workpackages/{wp['id']}/items/{blocked}/remove", headers=HUMAN,
           json={"expected_revision": work.get(wp["id"])["revision"], "reason": "not an invoice"})
    assert work_runs.run_rows(wp["id"])[0]["open_reasons"] == 0  # the run list counts what the approval needs
    approved = c.post(f"/api/runs/{run_id}/approve", json={"confirm_removed": 1}, headers=HUMAN)
    assert approved.status_code == 200, approved.text
    assert work_runs.get_run(run_id)["excluded_items"] == [blocked]
    c.post(f"/api/workpackages/{wp['id']}/items/{blocked}/restore", headers=HUMAN,
           json={"expected_revision": work.get(wp["id"])["revision"]})
    assert work_runs.run_rows(wp["id"])[0]["open_reasons"] == 0  # approved: left out as recorded, not as the package is now


# --- S2: adding to an existing package ----------------------------------------------------------------------------


def _new_pdf(env, name: str, number: str) -> Path:
    path = env["root"] / "later" / name
    path.parent.mkdir(exist_ok=True)
    write_text_pdf(path, [line.replace("MINTA-2026-001", number) for line in INVOICE_LINES])
    return path


def test_adding_documents_reports_what_changed_and_is_logged(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    new = _new_pdf(env, "invoice_3.pdf", "MINTA-2026-003")
    r = c.post(f"/api/workpackages/{wp['id']}/items", headers=HUMAN,
               json={"paths": [str(new), str(env["folder"] / "invoice_1.pdf")], "expected_revision": wp["revision"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == {"added": 1, "already": 1, "restored": 0, "left_out": 0, "processed_elsewhere": []}
    assert len(body["workpackage"]["items"]) == 3
    event = work.workpackage_events(wp["id"])[-1]
    assert (event["action"], event["actor"]) == ("items_add", "teszt.elek")
    assert json.loads(event["detail"]) == {"added": 1, "already": 1, "restored": 0, "left_out": 0}
    again = c.post(f"/api/workpackages/{wp['id']}/items", headers=HUMAN,
                   json={"paths": [str(new)], "expected_revision": body["workpackage"]["revision"]}).json()
    assert again["added"]["already"] == 1 and again["workpackage"]["revision"] == body["workpackage"]["revision"]  # no step


def test_adding_a_removed_item_again_restores_it(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    item = next(i for i in wp["items"] if i["source_path"].endswith("invoice_1.pdf"))
    removed = c.post(f"/api/workpackages/{wp['id']}/items/{item['item_id']}/remove", headers=HUMAN,
                     json={"expected_revision": wp["revision"], "reason": "wrong month"}).json()["workpackage"]
    r = c.post(f"/api/workpackages/{wp['id']}/items", headers=HUMAN,
               json={"paths": [item["source_path"]], "expected_revision": removed["revision"]}).json()
    assert r["added"] == {"added": 0, "already": 0, "restored": 1, "left_out": 0, "processed_elsewhere": []}
    assert item["item_id"] in {i["item_id"] for i in r["workpackage"]["items"]}
    assert all(row["_removed"] is False for row in _items(c, wp["id"], removed=True))


def test_a_document_processed_live_in_another_package_is_named(env):
    c = env["client"]
    other = _package(c, env["folder"])
    _assign(c, other["id"])
    _start(c, other["id"])
    worker.run_worker(once=True)
    target = c.post("/api/workpackages", headers=HUMAN,
                    json={"paths": [str(_new_pdf(env, "invoice_9.pdf", "MINTA-2026-009"))], "name": "Second"}).json()["workpackage"]
    r = c.post(f"/api/workpackages/{target['id']}/items", headers=HUMAN,
               json={"paths": [str(env["folder"] / "invoice_2.pdf")], "expected_revision": target["revision"]}).json()
    assert r["added"]["added"] == 1 and r["added"]["processed_elsewhere"] == ["invoice_2.pdf"]  # a warning, not a refusal


def test_after_a_run_new_items_are_the_packages_next_step(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    _start(c, wp["id"])
    worker.run_worker(once=True)
    assert c.get(f"/api/workpackages/{wp['id']}").json()["next"]["code"] != "pending"
    c.post(f"/api/workpackages/{wp['id']}/items", headers=HUMAN,
           json={"paths": [str(_new_pdf(env, "invoice_4.pdf", "MINTA-2026-004"))], "expected_revision": work.get(wp["id"])["revision"]})
    view = c.get(f"/api/workpackages/{wp['id']}").json()
    assert (view["next"]["code"], view["next"]["stage"], view["next"]["params"]) == ("pending", "process", {"n": 1})
    listed = next(r for r in c.post("/api/datasets/workpackages/query", json={"scope": {}, "query": {}}).json()["rows"]
                  if r["_key"] == wp["id"])
    assert listed["next_code"] == "pending"
    assert work_runs.pending_items(wp["id"], "apply") == [i["item_id"] for i in work.get(wp["id"])["items"]
                                                     if i["source_path"].endswith("invoice_4.pdf")]


def test_an_item_removed_after_the_approval_stays_in_the_released_result(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    run_id = _finished_live_run(c, wp)
    assert c.post(f"/api/runs/{run_id}/approve", json={}, headers=HUMAN).status_code == 200
    removed = wp["items"][0]["item_id"]
    c.post(f"/api/workpackages/{wp['id']}/items/{removed}/remove", headers=HUMAN,
           json={"expected_revision": work.get(wp["id"])["revision"], "reason": "later"})
    assert _exported_items(c, run_id) == {i["item_id"] for i in wp["items"]}
    assert c.get(f"/api/runs/{run_id}").json()["removed_items"] == []


# --- S3: a run over only the pending items ------------------------------------------------------------------------


def _add(c: TestClient, env, wp_id: str, name: str, number: str) -> str:
    r = c.post(f"/api/workpackages/{wp_id}/items", headers=HUMAN,
               json={"paths": [str(_new_pdf(env, name, number))], "expected_revision": work.get(wp_id)["revision"]})
    assert r.status_code == 200, r.text
    return next(i["item_id"] for i in r.json()["workpackage"]["items"] if i["source_path"].endswith(name))


def test_a_run_over_the_pending_items_takes_only_them_with_their_own_budget(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    first = _start(c, wp["id"])["run_id"]
    worker.run_worker(once=True)
    assert "apply" not in c.get(f"/api/workpackages/{wp['id']}/workflow/readiness").json().get("supplement", {})
    new = _add(c, env, wp["id"], "invoice_5.pdf", "MINTA-2026-005")
    ready = c.get(f"/api/workpackages/{wp['id']}/workflow/readiness").json()
    sup = ready["supplement"]["apply"]
    assert sup["items"] == 1 and ready["counts"]["items"] == 3
    assert sup["input_hash"] != ready["input_hash"] and sup["ready"] is True
    full = {p: Decimal(v) for p, v in ready["budget"].items()}
    assert {p: Decimal(v) for p, v in sup["budget"].items()} == {p: v / 3 for p, v in full.items()}  # one item's of three
    assert sup["plan"]["documents"] == 1
    assert "shadow" not in ready["supplement"]  # no trial run yet: a trial takes the whole package
    r = c.post(f"/api/workpackages/{wp['id']}/workflow/start", headers=HUMAN,
               json={"mode": "apply", "scope": "pending", "expected_revision": ready["assignment_revision"],
                     "input_hash": sup["input_hash"]})
    assert r.status_code == 201, r.text
    run = work_runs.get_run(r.json()["run_id"])
    assert [i["item_id"] for i in run["input"]["items"]] == [new] and run["scope"] == "pending"
    worker.run_worker(once=True)
    assert [i["item_id"] for i in work_runs.get_run(run["run_id"])["items"]] == [new]
    assert len(work_runs.get_run(first)["items"]) == 2  # the first run is untouched
    assert work_runs.pending_items(wp["id"], "apply") == []
    assert "apply" not in c.get(f"/api/workpackages/{wp['id']}/workflow/readiness").json().get("supplement", {})


def _start_pending(c: TestClient, wp_id: str, mode: str = "apply"):
    ready = c.get(f"/api/workpackages/{wp_id}/workflow/readiness").json()
    return c.post(f"/api/workpackages/{wp_id}/workflow/start", headers=HUMAN,
                  json={"mode": mode, "scope": "pending", "expected_revision": ready["assignment_revision"],
                        "input_hash": ready["supplement"][mode]["input_hash"]})


def test_a_double_click_starts_one_run_over_the_pending_items_and_a_stopped_one_can_start_again(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    _start(c, wp["id"])
    worker.run_worker(once=True)
    _add(c, env, wp["id"], "invoice_6.pdf", "MINTA-2026-006")
    ready = c.get(f"/api/workpackages/{wp['id']}/workflow/readiness").json()
    body = {"mode": "apply", "scope": "pending", "expected_revision": ready["assignment_revision"],
            "input_hash": ready["supplement"]["apply"]["input_hash"]}
    first = c.post(f"/api/workpackages/{wp['id']}/workflow/start", headers=HUMAN, json=body)
    again = c.post(f"/api/workpackages/{wp['id']}/workflow/start", headers=HUMAN, json=body)
    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["run_id"] == first.json()["run_id"] and again.json()["deduped"] is True
    assert c.post(f"/api/runs/{first.json()['run_id']}/cancel", headers=HUMAN, json={}).status_code == 200
    restarted = _start_pending(c, wp["id"])
    assert restarted.status_code == 201 and restarted.json()["run_id"] != first.json()["run_id"]
    _add(c, env, wp["id"], "invoice_7.pdf", "MINTA-2026-007")  # while that run is queued
    refused = _start_pending(c, wp["id"])
    assert refused.status_code == 409 and refused.json()["blockers"][0]["code"] == "run_active"
    worker.run_worker(once=True)
    late = c.post(f"/api/workpackages/{wp['id']}/workflow/start", headers=HUMAN, json=body)
    assert late.status_code == 409  # the pending items changed since: a stale page starts nothing


def _resolve(c: TestClient, wp_id: str, run_id: str) -> None:
    """Close the open to-dos one run raised on the package."""
    for item in c.get(f"/api/workpackages/{wp_id}/reviews").json()["items"]:
        for reason in item["open_reasons"]:
            if str(reason["run_id"]).startswith(run_id + ":"):
                assert c.post(f"/api/review-reasons/{reason['id']}/resolve", json={"note": "checked"}, headers=HUMAN).status_code == 200


def test_the_oldest_open_live_run_is_the_packages_current_one_and_the_others_show(env):
    """160-C S3: a run over the pending items next to an earlier live run waiting for its review: the package's next
    step is about the earlier one first, the later one is listed with its to-dos, and neither hides the other."""
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    first = _start(c, wp["id"])["run_id"]
    worker.run_worker(once=True)
    _add(c, env, wp["id"], "invoice_8.pdf", "MINTA-2026-008")
    second = _start_pending(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    view = c.get(f"/api/workpackages/{wp['id']}").json()
    assert view["last_run"]["run_id"] == second and view["current_run"]["run_id"] == first
    assert view["next"]["code"] == "review" and view["next"]["params"]["n"] == view["current_run"]["open_reasons"]
    assert [(r["run_id"], r["items"]) for r in view["open_runs"]] == [(first, 2), (second, 1)]
    assert view["open_runs"][1]["open_reasons"] > 0 and view["open_runs"][1]["scope"] == "pending"
    _resolve(c, wp["id"], first)
    assert c.post(f"/api/runs/{first}/approve", json={}, headers=HUMAN).status_code == 200
    view = c.get(f"/api/workpackages/{wp['id']}").json()
    assert view["current_run"]["run_id"] == second and view["next"]["code"] == "review"
    assert [r["run_id"] for r in view["open_runs"]] == [second]
    _resolve(c, wp["id"], second)
    assert c.post(f"/api/runs/{second}/approve", json={}, headers=HUMAN).status_code == 200
    view = c.get(f"/api/workpackages/{wp['id']}").json()
    # 172: runs approved one by one (the way before v1.20.0) still need the package's release, which records a version
    assert view["next"]["code"] == "release" and view["open_runs"] == []
    mark = c.get(f"/api/workpackages/{wp['id']}/result").json()["mark"]
    assert c.post(f"/api/workpackages/{wp['id']}/release", headers=HUMAN, json={"expected_mark": mark}).status_code == 200
    assert c.get(f"/api/workpackages/{wp['id']}").json()["next"]["code"] == "done"
    approved = work_runs.get_run(first)
    assert approved["approval"] == "approved" and len(approved["input"]["items"]) == 2  # untouched by the later run
    assert _exported_items(c, first) == {i["item_id"] for i in wp["items"]}


def test_a_workflow_step_is_not_done_while_an_earlier_live_run_of_its_package_is_open(env):
    """160-C S3: an approved run over the pending items next to an earlier open live run does not make the step done
    (it looked only at the latest live run)."""
    from jav import parties, workflows

    c = env["client"]
    wp = _package(c, env["folder"])
    party = parties.create("Example Kft.", identities=[], actor="tester")["id"]
    made = workflows.create(template_id="monthly_reconciliation", party_id=party, period_start="2026-06-01",
                            period_end="2026-06-30", actor="tester", auto=False,
                            steps={"invoices": {"source": {"kind": "package", "workpackage_id": wp["id"]}},
                                   "statements": {"source": {"kind": "folder", "folder": str(env["root"])}},
                                   "reconcile": {"source": {"kind": "none"}}})

    def status() -> str:
        return next(s["status"] for s in workflows.view(made["workflow"]["id"])["steps"] if s["id"] == "invoices")

    _assign(c, wp["id"])
    first = _start(c, wp["id"])["run_id"]
    worker.run_worker(once=True)
    _add(c, env, wp["id"], "invoice_9.pdf", "MINTA-2026-009")
    second = _start_pending(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    _resolve(c, wp["id"], second)
    assert c.post(f"/api/runs/{second}/approve", json={}, headers=HUMAN).status_code == 200
    assert status() == "review"  # the first run's to-dos are still open
    _resolve(c, wp["id"], first)
    assert status() == "approve"
    assert c.post(f"/api/runs/{first}/approve", json={}, headers=HUMAN).status_code == 200
    assert status() == "approved"
