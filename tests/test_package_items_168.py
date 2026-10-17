"""168 (plan F-item-list-and-adding; DECISIONS 168): the package's item list and adding in three steps.

Adding to an existing package is previewed before anything is written: each file of the given files or of a folder
(with or without its subfolders) is new, already in the package, removed (restored only when ticked), repeated in the
selection, or processed live in another package. Several items are removed with one reason and restored in one revision
step. The item list says per item whether a run has processed it and which run's result counts now (approved live >
live > trial; a stopped or superseded run does not count). Synthetic PDFs, a fake JEV client, no paid calls.
"""

import json
from pathlib import Path

from jav import store, work
from jav.runtime import worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests import test_flexible_package_160c as fp
from tests.test_flexible_package_160c import HUMAN, _assign, _items, _new_pdf, _package, _start

env = fp.env  # the 160-C fixture: a store of its own, two synthetic invoices, a fake JEV client


def _preview(c, wp_id: str, **body) -> dict:
    r = c.post(f"/api/workpackages/{wp_id}/items/preview", headers=HUMAN, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _by_name(preview: dict) -> dict[str, dict]:
    return {f["name"]: f for f in preview["files"]}


# --- the preview ----------------------------------------------------------------------------------------------------


def test_the_preview_marks_each_file_and_writes_nothing(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    removed = next(i for i in wp["items"] if i["source_path"].endswith("invoice_1.pdf"))
    wp = c.post(f"/api/workpackages/{wp['id']}/items/{removed['item_id']}/remove", headers=HUMAN,
                json={"expected_revision": wp["revision"], "reason": "wrong month"}).json()["workpackage"]
    new = _new_pdf(env, "invoice_3.pdf", "MINTA-2026-003")
    copy = new.with_name("invoice_3_copy.pdf")
    copy.write_bytes(new.read_bytes())
    note = new.with_name("scan.jpg")
    note.write_bytes(b"not a document")
    paths = [str(p) for p in (new, copy, env["folder"] / "invoice_1.pdf", env["folder"] / "invoice_2.pdf", note)]
    events = len(work.workpackage_events(wp["id"]))
    out = _preview(c, wp["id"], paths=paths)
    files = _by_name(out)
    assert {n: f["state"] for n, f in files.items()} == {
        "invoice_3.pdf": "new", "invoice_3_copy.pdf": "repeated", "invoice_1.pdf": "removed", "invoice_2.pdf": "already"}
    assert files["invoice_3.pdf"]["item_id"] == files["invoice_3_copy.pdf"]["item_id"]
    assert out["counts"] == {"new": 1, "already": 1, "removed": 1, "repeated": 1, "elsewhere": 0}
    assert out["others"] == {"count": 1, "names": ["scan.jpg"]}  # not a document: left out, named
    assert work.get(wp["id"])["revision"] == wp["revision"] and len(work.workpackage_events(wp["id"])) == events


def test_the_preview_names_a_file_processed_live_in_another_package(env):
    c = env["client"]
    other = _package(c, env["folder"])
    _assign(c, other["id"])
    _start(c, other["id"])
    worker.run_worker(once=True)
    target = c.post("/api/workpackages", headers=HUMAN,
                    json={"paths": [str(_new_pdf(env, "invoice_9.pdf", "MINTA-2026-009"))], "name": "Second"}).json()["workpackage"]
    files = _by_name(_preview(c, target["id"], paths=[str(env["folder"] / "invoice_2.pdf")]))
    assert files["invoice_2.pdf"]["state"] == "new" and files["invoice_2.pdf"]["elsewhere"] is True


def _tree(env) -> Path:
    """A folder with a document of its own, one in a subfolder, and the output folder of the named copies inside it."""
    top = env["root"] / "supplement"
    for sub in ("march", "named"):
        (top / sub).mkdir(parents=True)
    write_text_pdf(top / "top.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-011") for line in INVOICE_LINES])
    write_text_pdf(top / "march" / "deep.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-012") for line in INVOICE_LINES])
    write_text_pdf(top / "named" / "copy.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-013") for line in INVOICE_LINES])
    return top


def test_a_folder_is_previewed_with_or_without_its_subfolders_and_without_the_output_folder(env, monkeypatch):
    from jav import app_settings

    c = env["client"]
    wp = _package(c, env["folder"])
    top = _tree(env)
    monkeypatch.setattr(app_settings, "output_folder", lambda: str(top / "named"))
    flat = _preview(c, wp["id"], folder=str(top))
    assert sorted(_by_name(flat)) == ["top.pdf"]
    deep = _preview(c, wp["id"], folder=str(top), recursive=True)
    assert sorted(_by_name(deep)) == ["deep.pdf", "top.pdf"]  # the named copies are not new documents
    assert _by_name(deep)["deep.pdf"]["folder"] == "march"
    r = c.post(f"/api/workpackages/{wp['id']}/items/preview", headers=HUMAN, json={"folder": str(top), "paths": [str(top / "top.pdf")]})
    assert r.status_code == 422  # exactly one of the two


# --- adding what the preview showed ------------------------------------------------------------------------------------


def test_adding_a_folder_takes_its_new_documents_and_leaves_out_what_was_unticked(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    top = _tree(env)
    preview = _by_name(_preview(c, wp["id"], folder=str(top), recursive=True))
    r = c.post(f"/api/workpackages/{wp['id']}/items", headers=HUMAN,
               json={"folder": str(top), "recursive": True, "exclude": [preview["copy.pdf"]["item_id"]], "expected_revision": wp["revision"]})
    assert r.status_code == 200, r.text
    assert r.json()["added"] == {"added": 2, "already": 0, "restored": 0, "left_out": 1, "processed_elsewhere": []}
    names = {Path(i["source_path"]).name for i in r.json()["workpackage"]["items"]}
    assert names == {"invoice_1.pdf", "invoice_2.pdf", "top.pdf", "deep.pdf"}
    event = work.workpackage_events(wp["id"])[-1]
    assert (event["action"], json.loads(event["detail"])) == ("items_add", {"added": 2, "already": 0, "restored": 0, "left_out": 1})


def test_a_removed_document_comes_back_only_when_ticked(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    item = next(i for i in wp["items"] if i["source_path"].endswith("invoice_1.pdf"))
    wp = c.post(f"/api/workpackages/{wp['id']}/items/{item['item_id']}/remove", headers=HUMAN,
                json={"expected_revision": wp["revision"], "reason": "a duplicate scan"}).json()["workpackage"]
    kept_out = c.post(f"/api/workpackages/{wp['id']}/items", headers=HUMAN,
                      json={"folder": str(env["folder"]), "restore": [], "expected_revision": wp["revision"]}).json()
    assert kept_out["added"] == {"added": 0, "already": 1, "restored": 0, "left_out": 1, "processed_elsewhere": []}
    assert kept_out["workpackage"]["revision"] == wp["revision"]  # nothing changed: no revision step
    back = c.post(f"/api/workpackages/{wp['id']}/items", headers=HUMAN,
                  json={"folder": str(env["folder"]), "restore": [item["item_id"]], "expected_revision": wp["revision"]}).json()
    assert back["added"]["restored"] == 1 and item["item_id"] in {i["item_id"] for i in back["workpackage"]["items"]}


# --- removing and restoring several items --------------------------------------------------------------------------------


def test_several_items_are_removed_with_one_reason_in_one_step_and_restored_together(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    ids = [i["item_id"] for i in wp["items"]]
    r = c.post(f"/api/workpackages/{wp['id']}/items/remove", headers=HUMAN,
               json={"item_ids": ids, "reason": "the wrong folder", "expected_revision": wp["revision"]})
    assert r.status_code == 200, r.text
    after = r.json()["workpackage"]
    assert after["items"] == [] and after["revision"] == wp["revision"] + 1
    rows = {row["item_id"]: row for row in _items(c, wp["id"], removed=True)}
    assert all(rows[i]["removed_reason"] == "the wrong folder" and rows[i]["removed_by"] == "teszt.elek" for i in ids)
    event = work.workpackage_events(wp["id"])[-1]
    assert (event["action"], json.loads(event["detail"])) == ("items_remove", {"item_ids": ids, "reason": "the wrong folder"})
    back = c.post(f"/api/workpackages/{wp['id']}/items/restore", headers=HUMAN, json={"item_ids": ids, "expected_revision": after["revision"]})
    assert back.status_code == 200, back.text
    assert {i["item_id"] for i in back.json()["workpackage"]["items"]} == set(ids)
    assert work.workpackage_events(wp["id"])[-1]["action"] == "items_restore"


def test_removing_several_needs_a_reason_a_current_page_and_items_in_use(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    ids = [i["item_id"] for i in wp["items"]]
    url = f"/api/workpackages/{wp['id']}/items/remove"
    assert c.post(url, headers=HUMAN, json={"item_ids": ids, "reason": " ", "expected_revision": wp["revision"]}).status_code == 422
    assert c.post(url, headers=HUMAN, json={"item_ids": [], "reason": "x", "expected_revision": wp["revision"]}).status_code == 422
    assert c.post(url, headers=HUMAN, json={"item_ids": ids, "reason": "x", "expected_revision": wp["revision"] + 1}).status_code == 409
    assert c.post(url, headers=HUMAN, json={"item_ids": [*ids, "0" * 64], "reason": "x", "expected_revision": wp["revision"]}).status_code == 404
    assert len(work.get(wp["id"])["items"]) == 2 and work.get(wp["id"])["revision"] == wp["revision"]  # all or nothing


# --- each item's state and the run whose result counts ---------------------------------------------------------------------


def _states(c, wp_id: str, *, removed: bool = False) -> dict[str, dict]:
    return {Path(row["source_path"]).name: row for row in _items(c, wp_id, removed=removed)}


def test_a_package_before_any_run_has_only_pending_items(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    rows = _states(c, wp["id"])
    assert {n: r["state"] for n, r in rows.items()} == {"invoice_1.pdf": "pending", "invoice_2.pdf": "pending"}
    assert all(r["run_mode"] is None and r["_run"] is None for r in rows.values())


def test_the_counted_result_is_approved_live_then_live_then_trial(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    trial = _start(c, wp["id"], mode="shadow")["run_id"]
    worker.run_worker(once=True)
    rows = _states(c, wp["id"])
    assert {r["state"] for r in rows.values()} == {"trial"} and {r["_run"] for r in rows.values()} == {trial}
    live = _start(c, wp["id"])["run_id"]
    worker.run_worker(once=True)
    for reason in (r for item in c.get(f"/api/workpackages/{wp['id']}/reviews").json()["items"] for r in item["open_reasons"]):
        assert c.post(f"/api/review-reasons/{reason['id']}/resolve", json={"note": "checked"}, headers=HUMAN).status_code == 200
    rows = _states(c, wp["id"])
    assert {(r["state"], r["run_mode"], r["_run"]) for r in rows.values()} == {("live", "apply", live)}
    assert c.post(f"/api/runs/{live}/approve", json={}, headers=HUMAN).status_code == 200
    _start(c, wp["id"], mode="shadow", rerun_of=trial)  # a later trial does not hide the approved result
    worker.run_worker(once=True)
    rows = _states(c, wp["id"])
    assert {(r["state"], r["_run"]) for r in rows.values()} == {("approved", live)}
    assert all(r["final_status"] for r in rows.values())


def test_a_stopped_run_does_not_count_and_a_running_or_failed_item_says_so(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    _assign(c, wp["id"])
    run_id = _start(c, wp["id"])["run_id"]
    assert {r["state"] for r in _states(c, wp["id"]).values()} == {"running"}
    first, second = (i["item_id"] for i in wp["items"])
    work.record_item_result(run_id, first, status="failed", error="synthetic")
    work.record_item_result(run_id, second, status="done", final_status="auto_approved")
    with store.connect() as conn:
        conn.execute("UPDATE runs SET status='failed' WHERE run_id=?", (run_id,))
    by_id = {r["item_id"]: r for r in _items(c, wp["id"])}
    assert (by_id[first]["state"], by_id[second]["state"]) == ("failed", "live")
    with store.connect() as conn:
        conn.execute("UPDATE runs SET status='cancelled' WHERE run_id=?", (run_id,))
    assert {r["state"] for r in _items(c, wp["id"])} == {"pending"}  # a stopped run's results do not count


def test_a_removed_item_reads_removed_behind_the_switch(env):
    c = env["client"]
    wp = _package(c, env["folder"])
    item = wp["items"][0]["item_id"]
    c.post(f"/api/workpackages/{wp['id']}/items/{item}/remove", headers=HUMAN, json={"expected_revision": wp["revision"], "reason": "x"})
    by_id = {r["item_id"]: r for r in _items(c, wp["id"], removed=True)}
    assert by_id[item]["state"] == "removed" and by_id[wp["items"][1]["item_id"]]["state"] == "pending"
