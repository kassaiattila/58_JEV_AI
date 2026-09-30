"""Local service (040 K2): lifecycle, agreement with the command line, input and origin protection.

Synthetic PDFs, a fake JEV client, no paid calls. The worker runs in the test thread (in reality it is a separate
process): the service only enqueues and reads from the store.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav import api, cfg, cli, store, work
from jav.adapters import jev as jev_mod
from jav.runtime import lock, worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_runtime_worker import FakeClient

BASE = "http://127.0.0.1:8930"
HUMAN = {"X-Actor": "teszt.elek"}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    root = tmp_path / "gyoker"
    folder = root / "bejovo"
    folder.mkdir(parents=True)
    write_text_pdf(folder / "szamla_1.pdf", INVOICE_LINES)
    write_text_pdf(folder / "szamla_2.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-002") for line in INVOICE_LINES])
    monkeypatch.setenv("JAV_API_ROOTS", str(root))
    db = tmp_path / "w.sqlite"
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    client = TestClient(api.create_app(store_path=db), base_url=BASE)
    with store.use_store(db), jev_mod.use_adapter(adapter):
        yield {"client": client, "folder": folder, "root": root, "db": db, "tmp": tmp_path}


def _ready_wp(c: TestClient, folder: Path) -> dict:
    r = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(folder), "name": "Mesterséges számlák"})
    assert r.status_code == 201, r.text
    wp = r.json()["workpackage"]
    r = c.post(f"/api/workpackages/{wp['id']}/workflow", headers=HUMAN, json={"recipe_id": "invoice-extraction", "params": {"arm": "S"},
                                                                "expected_revision": 0, "note": "első"})
    assert r.status_code == 200, r.text
    return wp


def test_new_workpackage_owner_is_its_creator(env):
    """065 decision: a new package's owner is its creator (can be changed later)."""
    wp = _ready_wp(env["client"], env["folder"])
    assert wp["owner"] == "teszt.elek"
    assert work.create_from_folder(env["folder"], name="parancssorból")["owner"] is None  # no actor, no owner


def _start(c: TestClient, wp_id: str, mode: str = "apply"):
    ready = c.get(f"/api/workpackages/{wp_id}/workflow/readiness").json()
    return c.post(f"/api/workpackages/{wp_id}/workflow/start",
                  headers=HUMAN, json={"mode": mode, "expected_revision": ready["assignment_revision"], "input_hash": ready["input_hash"]})


def _cli_json(capsys, *argv):
    assert cli.main([*argv, "--json"]) == 0
    return json.loads(capsys.readouterr().out)


# --- lifecycle ------------------------------------------------------------------------------------------


def test_full_lifecycle_over_http(env):
    c = env["client"]
    assert c.get("/api/health").json()["ok"] is True
    wp = _ready_wp(c, env["folder"])
    assert len(wp["items"]) == 2
    first = _start(c, wp["id"])
    assert first.status_code == 201 and first.json()["deduped"] is False
    again = _start(c, wp["id"])  # the same request: the same run, no second one starts
    assert again.status_code == 200 and again.json()["run_id"] == first.json()["run_id"]
    run_id = first.json()["run_id"]
    assert c.get(f"/api/runs/{run_id}").json()["run"]["status"] == "queued"

    assert worker.run_worker(once=True)["processed"] == 2

    view = c.get(f"/api/runs/{run_id}").json()
    assert view["run"]["status"] in ("done", "needs_review")
    assert {i["status"] for i in view["run"]["items"]} == {"done"}
    assert isinstance(view["budget"]["committed_usd"], str)  # money as text, not as floating point
    assert c.get(f"/api/runs/{run_id}/journal").json()["calls"], "a futás hívásnaplója a keret szerint összegyűlik"
    assert [r["run_id"] for r in c.get(f"/api/workpackages/{wp['id']}/runs").json()["runs"]] == [run_id]
    listed = c.get("/api/workpackages").json()["workpackages"]
    assert listed[0]["id"] == wp["id"] and listed[0]["last_run_id"] == run_id

    # to-dos closed reason by reason, with a human author; after that the run can be approved
    for reason in (r for item in c.get(f"/api/workpackages/{wp['id']}/reviews").json()["items"] for r in item["open_reasons"]):
        res = c.post(f"/api/review-reasons/{reason['id']}/resolve", json={"note": "ellenőrizve"}, headers=HUMAN)
        assert res.status_code == 200, res.text
    assert c.get(f"/api/workpackages/{wp['id']}/reviews").json()["open_reasons"] == 0
    approved = c.post(f"/api/runs/{run_id}/approve", json={}, headers=HUMAN)
    assert approved.status_code == 200, approved.text
    assert approved.json()["run"]["approval"] == "approved" and approved.json()["run"]["approved_by"] == "teszt.elek"


def test_state_survives_client_and_service_restart(env):
    """Closing the browser or the service does not stop the run: the state is in the store."""
    wp = _ready_wp(env["client"], env["folder"])
    run_id = _start(env["client"], wp["id"]).json()["run_id"]
    env["client"].close()
    worker.run_worker(once=True)  # meanwhile only the worker works
    fresh = TestClient(api.create_app(store_path=env["db"]), base_url=BASE)
    view = fresh.get(f"/api/runs/{run_id}").json()
    assert view["run"]["status"] in ("done", "needs_review") and len(view["run"]["items"]) == 2


def test_cli_and_service_give_the_same_answer(env, capsys):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    assert c.get(f"/api/workpackages/{wp['id']}").json() == _cli_json(capsys, "wp-show", wp["id"])
    assert c.get("/api/recipes").json()["recipes"] == _cli_json(capsys, "recipes")
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    assert c.get(f"/api/runs/{run_id}").json() == _cli_json(capsys, "run-show", run_id)
    assert c.get(f"/api/workpackages/{wp['id']}/runs").json()["runs"] == _cli_json(capsys, "run-list", wp["id"])
    assert c.get("/api/workpackages").json()["workpackages"] == _cli_json(capsys, "wp-list")
    assert c.get("/api/worker").json() == _cli_json(capsys, "worker-status")


# --- version and conflict -------------------------------------------------------------------------------


def test_stale_workflow_save_is_refused(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    r = c.post(f"/api/workpackages/{wp['id']}/workflow", headers=HUMAN, json={"recipe_id": "invoice-extraction", "params": {"arm": "G"},
                                                                "expected_revision": 0})
    assert r.status_code == 409 and r.json()["error"] == "revision_conflict"
    assert c.get(f"/api/workpackages/{wp['id']}/workflow").json()["assignment"]["params"]["arm"] == "S"


def test_start_with_stale_input_or_not_ready(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    ready = c.get(f"/api/workpackages/{wp['id']}/workflow/readiness").json()
    extra = env["folder"] / "uj.pdf"
    write_text_pdf(extra, INVOICE_LINES[:-1] + ["Megjegyzés: új irat"])
    r = c.post(f"/api/workpackages/{wp['id']}/items", headers=HUMAN, json={"paths": [str(extra)], "expected_revision": wp["revision"]})
    assert r.status_code == 200 and len(r.json()["workpackage"]["items"]) == 3
    stale = c.post(f"/api/workpackages/{wp['id']}/workflow/start",
                   headers=HUMAN, json={"mode": "shadow", "expected_revision": 1, "input_hash": ready["input_hash"]})
    assert stale.status_code == 409 and stale.json()["error"] == "revision_conflict"

    empty = env["root"] / "ures"
    empty.mkdir()
    bare = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(empty)}).json()["workpackage"]
    r = c.post(f"/api/workpackages/{bare['id']}/workflow/start", headers=HUMAN, json={"mode": "shadow", "expected_revision": 0,
                                                                     "input_hash": "0" * 16})
    assert r.status_code == 409
    assert c.get(f"/api/workpackages/{bare['id']}/workflow/readiness").json()["ready"] is False


def test_correction_is_versioned_and_conflict_is_refused(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    item_id = wp["items"][0]["item_id"]
    before = c.get(f"/api/runs/{run_id}/items/{item_id}").json()
    assert before["correction"]["revision"] == 0 and before["extraction"]["doc_type"] == "invoice_hu"

    ok = c.post(f"/api/runs/{run_id}/items/{item_id}/correction", headers=HUMAN,
                json={"fields": {"invoice_number": "JAVITOTT-1", "gross_total": "12700"}, "expected_revision": 0})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["correction"]["revision"] == 1 and body["correction"]["actor"] == "teszt.elek"
    assert body["effective"]["invoice_number"] == "JAVITOTT-1"
    assert body["extraction"]["datapoints"]["invoice_number"] != "JAVITOTT-1"  # the machine data is kept

    stale = c.post(f"/api/runs/{run_id}/items/{item_id}/correction", headers=HUMAN,
                   json={"fields": {"invoice_number": "MASIK"}, "expected_revision": 0})
    assert stale.status_code == 409
    assert c.get(f"/api/runs/{run_id}/items/{item_id}").json()["effective"]["invoice_number"] == "JAVITOTT-1"

    for bad in ({"nincs_ilyen_mezo": "x"}, {"gross_total": "sok"}, {"issue_date": "2026.09.01"}):
        r = c.post(f"/api/runs/{run_id}/items/{item_id}/correction", headers=HUMAN, json={"fields": bad, "expected_revision": 1})
        assert r.status_code == 422, bad
    no_author = c.post(f"/api/runs/{run_id}/items/{item_id}/correction", json={"fields": {}, "expected_revision": 1})
    assert no_author.status_code == 422  # a human decision cannot be saved without an author

    results = c.get(f"/api/runs/{run_id}/results").json()["items"]
    assert len(results) == 2 and any(r["correction"]["revision"] == 1 for r in results)


def test_approval_needs_apply_mode_and_no_open_reason(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    shadow = _start(c, wp["id"], mode="shadow").json()["run_id"]
    worker.run_worker(once=True)
    assert c.post(f"/api/runs/{shadow}/approve", json={}, headers=HUMAN).status_code == 422
    assert c.post(f"/api/runs/{shadow}/approve", json={}).status_code == 422  # nor without an author


def test_cancel_queued_run(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    assert c.post(f"/api/runs/{run_id}/cancel", json={}).status_code == 422  # 066 Á35: not without an author
    r = c.post(f"/api/runs/{run_id}/cancel", json={}, headers=HUMAN)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert worker.run_worker(once=True)["processed"] == 0
    with store.use_store(env["db"]):
        events = work.workpackage_events(wp["id"])
    assert any(e["action"] == "run_cancel" and e["actor"] == "teszt.elek" and run_id in (e["detail"] or "") for e in events)


# --- input and origin ------------------------------------------------------------------------------------


def test_foreign_host_and_origin_are_refused(env):
    c = env["client"]
    assert c.get("/api/health", headers={"Host": "tamado.example"}).status_code == 403
    assert c.get("/api/health", headers={"Origin": "https://tamado.example"}).status_code == 403
    assert c.get("/api/health", headers={"Origin": "http://localhost:5173"}).status_code == 200  # the development UI


def test_origin_must_match_the_service_or_the_dev_ui_exactly(env):
    """066 Á34: until now any page on a local port (another local application) was accepted as origin; now only the
    service's own address (same host and port) and the address of the configured development UI."""
    c = env["client"]
    own = BASE.rstrip("/")
    assert c.get("/api/health", headers={"Origin": own}).status_code == 200
    assert c.get("/api/health", headers={"Origin": "http://127.0.0.1:5173"}).status_code == 200
    assert c.get("/api/health", headers={"Origin": "http://localhost:3000"}).status_code == 403
    assert c.get("/api/health", headers={"Origin": "http://127.0.0.1:9999"}).status_code == 403
    assert c.get("/api/health", headers={"Origin": "null"}).status_code == 403


def test_body_must_be_json_and_bounded(env):
    c = env["client"]
    r = c.post("/api/workpackages", content=b"folder=x", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 415
    huge = json.dumps({"folder": "x" * 300_000}).encode()
    assert c.post("/api/workpackages", content=huge, headers={"Content-Type": "application/json"}).status_code == 413

    def chunks():  # chunked upload, without Content-Length
        for _ in range(40):
            yield b" " * 10_000
    r = c.post("/api/workpackages", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_schema_rejects_unknown_fields_and_bad_ids(env):
    c = env["client"]
    r = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(env["folder"]), "torles": True})
    assert r.status_code == 422
    assert c.get("/api/workpackages/..%2F..%2Fetc").status_code in (404, 422)
    assert c.get("/api/workpackages/wp-nincs").status_code == 422
    assert c.get("/api/workpackages/wp-000000000000").status_code == 404
    assert c.get(f"/api/runs/run-000000000000/items/{'a' * 64}").status_code == 404
    r = c.post("/api/workpackages/wp-000000000000/workflow/start", headers=HUMAN, json={"mode": "torol", "expected_revision": 0,
                                                                        "input_hash": "0" * 16})
    assert r.status_code == 422


def restrict_paths(monkeypatch) -> None:
    """Switches the folder restriction on (off by default since 061: the owner allowed any existing folder)."""
    monkeypatch.setattr(api, "settings", lambda: {**cfg.load("service"), "restrict_paths": True})


def test_folder_outside_allowed_roots_is_refused(env, tmp_path, monkeypatch):
    restrict_paths(monkeypatch)
    c = env["client"]
    outside = tmp_path / "kivul"
    outside.mkdir()
    write_text_pdf(outside / "titok.pdf", INVOICE_LINES)
    r = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(outside)})
    assert r.status_code == 403 and r.json()["error"] == "forbidden_path"
    trick = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(env["root"] / ".." / "kivul")})
    assert trick.status_code == 403
    wp = _ready_wp(c, env["folder"])
    r = c.post(f"/api/workpackages/{wp['id']}/items", headers=HUMAN, json={"paths": [str(outside / "titok.pdf")], "expected_revision": 1})
    assert r.status_code == 403
    assert c.post("/api/workpackages", headers=HUMAN, json={"folder": str(env["root"] / "nincs")}).status_code == 422


def test_any_existing_folder_is_accepted_without_restriction(env, tmp_path):
    """061 decision: unrestricted, any existing folder or file is accepted; a missing path or wrong kind is not."""
    c = env["client"]
    assert cfg.load("service")["restrict_paths"] is False
    outside = tmp_path / "kivul"
    outside.mkdir()
    write_text_pdf(outside / "szamla.pdf", INVOICE_LINES)
    r = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(outside)})
    assert r.status_code == 201, r.text
    wp = r.json()["workpackage"]
    r = c.post(f"/api/workpackages/{wp['id']}/items", headers=HUMAN, json={"paths": [str(env["folder"] / "szamla_1.pdf")], "expected_revision": 1})
    assert r.status_code == 200, r.text
    assert c.post("/api/workpackages", headers=HUMAN, json={"folder": str(outside / "nincs")}).status_code == 422
    assert c.post("/api/workpackages", headers=HUMAN, json={"folder": str(outside / "szamla.pdf")}).status_code == 422
    assert c.get("/api/settings/folders").json()["roots"] == []


# --- worker: single instance, orderly stop --------------------------------------------------------------


def test_only_one_worker_at_a_time(env):
    assert not lock.is_held(worker.lock_path())
    with lock.single_instance(worker.lock_path()):
        assert lock.is_held(worker.lock_path())
        assert env["client"].get("/api/worker").json()["running"] is True
        with pytest.raises(lock.AlreadyRunning):
            worker.run_worker(once=True)
    assert not lock.is_held(worker.lock_path())


def test_worker_stops_after_current_item_on_request(env, monkeypatch):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    real = worker.process

    def process_then_ask_stop(job, **kw):
        res = real(job, **kw)
        assert c.post("/api/worker/stop", json={}).status_code == 422  # 066 Á35: not without an author
        assert c.post("/api/worker/stop", json={}, headers=HUMAN).json()["stop_requested"] is True
        return res

    monkeypatch.setattr(worker, "process", process_then_ask_stop)
    info = worker.run_worker(once=True)
    assert info["stopped"] is True and info["processed"] == 1
    assert c.get(f"/api/runs/{run_id}").json()["run"]["jobs"].get("queued") == 1  # the rest waits in the queue
    monkeypatch.setattr(worker, "process", real)
    assert worker.run_worker(once=True)["processed"] == 1


def test_serve_refuses_non_loopback_host():
    with pytest.raises(ValueError):
        api.serve(host="0.0.0.0")


# --- 040 K3 prerequisites: package from given files, live JEV call switch ---------------------------------


def test_workpackage_from_files_in_several_folders(env):
    c = env["client"]
    other = env["root"] / "masik"
    other.mkdir()
    write_text_pdf(other / "szamla_3.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-003") for line in INVOICE_LINES])
    paths = [str(env["folder"] / "szamla_1.pdf"), str(other / "szamla_3.pdf")]
    r = c.post("/api/workpackages", headers=HUMAN, json={"paths": paths, "name": "Válogatás"})
    assert r.status_code == 201, r.text
    wp = r.json()["workpackage"]
    assert wp["source_kind"] == "manual" and len(wp["items"]) == 2
    assert c.post("/api/workpackages", headers=HUMAN, json={"paths": paths}).status_code == 422  # without a name
    assert c.post("/api/workpackages", headers=HUMAN, json={"paths": paths, "folder": str(other), "name": "x"}).status_code == 422
    assert c.post("/api/workpackages", headers=HUMAN, json={"name": "x"}).status_code == 422


def test_live_jev_param_bypasses_cache_and_goes_through_journal(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run1 = _start(c, wp["id"], mode="shadow").json()["run_id"]
    worker.run_worker(once=True)
    first = len(c.get(f"/api/runs/{run1}/journal").json()["calls"])
    assert first > 0
    # the same package again, with the cache: the answers come from the cache, no paid call enters the log
    r = c.post(f"/api/workpackages/{wp['id']}/workflow", headers=HUMAN, json={"recipe_id": "invoice-extraction", "params": {"arm": "S"},
                                                                "expected_revision": 1, "note": "újra"})
    assert r.status_code == 200
    run2 = _start(c, wp["id"], mode="shadow").json()["run_id"]
    worker.run_worker(once=True)
    assert c.get(f"/api/runs/{run2}/journal").json()["calls"] == []
    # with the live switch every call goes through the log and the budget again
    r = c.post(f"/api/workpackages/{wp['id']}/workflow", headers=HUMAN, json={"recipe_id": "invoice-extraction",
                                                                "params": {"arm": "S", "jev_cache": "live"},
                                                                "expected_revision": 2})
    assert r.status_code == 200
    run3 = _start(c, wp["id"], mode="shadow").json()["run_id"]
    worker.run_worker(once=True)
    # in the first run, items could also hit the cache from each other
    assert len(c.get(f"/api/runs/{run3}/journal").json()["calls"]) >= first


def test_earlier_open_reasons_do_not_block_a_new_run(env):
    """Finding of the K3 live trial: an old measurement run's open reason on the same document must not put the new
    run into the "waiting for to-dos" state."""
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    item_id = wp["items"][0]["item_id"]
    store.review_enqueue(subject_kind="document", subject_id=item_id, run_id="regi-meres-S-r1", reasons=["pick:low_conf:x:0.5"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    view = c.get(f"/api/runs/{run_id}").json()
    assert [r["reason"] for r in view["earlier_open_reasons"][item_id]] == ["pick:low_conf:x:0.5"]
    assert all(r["run_id"].startswith(run_id) for rs in view["open_reasons"].values() for r in rs)
    for rs in view["open_reasons"].values():
        for r in rs:
            assert c.post(f"/api/review-reasons/{r['id']}/resolve", json={}, headers=HUMAN).status_code == 200
    approved = c.post(f"/api/runs/{run_id}/approve", json={}, headers=HUMAN)
    assert approved.status_code == 200, approved.text
    # the old reason stays open on the document and shows among the To-dos
    docs = c.get(f"/api/workpackages/{wp['id']}/reviews").json()["items"]
    assert any(r["reason"] == "pick:low_conf:x:0.5" for d in docs for r in d["open_reasons"])


# --- 040 K3: source document next to the correction, accented author ------------------------------------


def test_item_source_is_served_only_for_unchanged_items(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    item = wp["items"][0]
    r = c.get(f"/api/workpackages/{wp['id']}/items/{item['item_id']}/source")
    assert r.status_code == 200 and r.content.startswith(b"%PDF") and r.headers["content-type"] == "application/pdf"
    assert c.get(f"/api/workpackages/{wp['id']}/items/{'b' * 64}/source").status_code == 404
    work.source_file(item).write_bytes(b"%PDF-1.4 kicserelve")  # the source instance is what is served
    assert c.get(f"/api/workpackages/{wp['id']}/items/{item['item_id']}/source").status_code == 409


def test_actor_may_carry_accents_when_url_encoded(env):
    from urllib.parse import quote
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    item_id = wp["items"][0]["item_id"]
    r = c.post(f"/api/runs/{run_id}/items/{item_id}/correction", headers={"X-Actor": quote("Kővári Ödön")},
               json={"fields": {"currency": "HUF"}, "expected_revision": 0})
    assert r.status_code == 200 and r.json()["correction"]["actor"] == "Kővári Ödön"
    bad = c.post(f"/api/runs/{run_id}/items/{item_id}/correction", headers={"X-Actor": quote("<script>")},
                 json={"fields": {}, "expected_revision": 1})
    assert bad.status_code == 422


def test_unknown_api_path_is_json_404(env):
    r = env["client"].get("/api/nincs-ilyen")
    assert r.status_code == 404 and r.json()["error"] == "not_found"


# --- 045 K3b: page image ----------------------------------------------------------------------------------


def test_page_image_is_png_and_hash_protected(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    item = wp["items"][0]
    r = c.get(f"/api/workpackages/{wp['id']}/items/{item['item_id']}/pages/1.png?dpi=72")
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG") and r.headers["cache-control"] == "no-store"  # 071
    assert c.get(f"/api/workpackages/{wp['id']}/items/{item['item_id']}/pages/2.png").status_code == 422
    assert c.get(f"/api/workpackages/{wp['id']}/items/{item['item_id']}/pages/1.png?dpi=999").status_code == 422
    work.source_file(item).write_bytes(b"%PDF-1.4 kicserelve")
    assert c.get(f"/api/workpackages/{wp['id']}/items/{item['item_id']}/pages/1.png").status_code == 409


# --- 045 K3b: source location, word layer, selection on the image -------------------------------------------


def test_item_result_has_provenance_and_words_for_selection(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    item_id = wp["items"][0]["item_id"]
    res = c.get(f"/api/runs/{run_id}/items/{item_id}").json()
    assert res["source"]["text_source"] == "pdf" and res["source"]["pages"][0]["width_pt"] == 595.0
    located = [f for f, p in res["provenance"].items() if p["status"] == "located"]
    tax = res["provenance"]["supplier_tax_id"]
    assert "supplier_tax_id" in located and tax["method"] == "pick" and tax["quote"] == "13570008-1-13"
    words = c.get(f"/api/runs/{run_id}/items/{item_id}/words").json()
    assert words["layer_id"] == res["source"]["layer_id"] and any(w["text"] == "MINTA-2026-001" for w in words["words"])


def test_correction_with_selection_on_the_image(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    item_id = wp["items"][0]["item_id"]
    words = c.get(f"/api/runs/{run_id}/items/{item_id}/words").json()["words"]
    seller = [w["id"] for w in words if w["text"] in ("Minta", "Kereskedelmi", "Kft.") and w["line_no"] == 3]
    url = f"/api/runs/{run_id}/items/{item_id}/correction"
    ok = c.post(url, headers=HUMAN, json={"fields": {"supplier_name": "Minta Kereskedelmi Kft."}, "expected_revision": 0,
                                          "sources": {"supplier_name": seller}})
    assert ok.status_code == 200, ok.text
    prov = ok.json()["provenance"]["supplier_name"]
    assert prov["method"] == "manual" and prov["corrected"] is True and prov["quote"] == "Minta Kereskedelmi Kft."
    assert ok.json()["correction"]["sources"] == {"supplier_name": sorted(seller)}
    bad_ids = c.post(url, headers=HUMAN, json={"fields": {"supplier_name": "x"}, "expected_revision": 1,
                                               "sources": {"supplier_name": [99999]}})
    assert bad_ids.status_code == 422
    stray = c.post(url, headers=HUMAN, json={"fields": {}, "expected_revision": 1, "sources": {"supplier_name": seller}})
    assert stray.status_code == 422
    # a typed (not selected) correction: the service looks for it on the image; not found → the field has no box,
    # and the old location becomes an alternative
    typed = c.post(url, headers=HUMAN, json={"fields": {"supplier_tax_id": "NINCS-A-KEPEN"}, "expected_revision": 1})
    assert typed.status_code == 200, typed.text
    p = typed.json()["provenance"]["supplier_tax_id"]
    assert p["corrected"] is True and p["status"] == "not_found" and p["alternatives"][0]["machine"] is True


def test_settings_and_normalize_selected_text(env):
    c = env["client"]
    assert c.get("/api/settings").json()["confidence_bands"] == {"confident": 0.9, "check": 0.5}
    r = c.post("/api/normalize", json={"doc_type": "invoice_hu", "field": "gross_total", "text": "1 071 880 Ft"}).json()
    assert r["ok"] is True and r["value"] == "1071880" and r["kind"] == "money"
    d = c.post("/api/normalize", json={"doc_type": "invoice_hu", "field": "issue_date", "text": "2021.04.23."}).json()
    assert d["ok"] is True and d["value"] == "2021-04-23"
    bad = c.post("/api/normalize", json={"doc_type": "invoice_hu", "field": "issue_date", "text": "tegnap"}).json()
    assert bad["ok"] is False
    assert c.post("/api/normalize", json={"doc_type": "invoice_hu", "field": "nincs", "text": "x"}).status_code == 422


# --- 058: hiding, renaming and deleting a package ----------------------------------------------------------


def test_archive_rename_restore_and_delete_over_http(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    assert c.post(f"/api/workpackages/{wp['id']}/archive", json={}).status_code == 422  # not without an author
    assert c.post(f"/api/workpackages/{wp['id']}/archive", json={}, headers=HUMAN).status_code == 200
    assert [w["id"] for w in c.get("/api/workpackages").json()["workpackages"]] == []
    listed = c.post("/api/datasets/workpackages/query", json={"scope": {"include_archived": "1"}, "query": {}}).json()
    assert [r["id"] for r in listed["rows"]] == [wp["id"]] and listed["rows"][0]["status"] == "archived"
    r = c.post(f"/api/workpackages/{wp['id']}/rename", json={"name": "Új név"}, headers=HUMAN)
    assert r.status_code == 200 and r.json()["workpackage"]["name"] == "Új név"
    assert c.post(f"/api/workpackages/{wp['id']}/rename", json={"name": " "}, headers=HUMAN).status_code == 422
    assert c.post(f"/api/workpackages/{wp['id']}/restore", json={}, headers=HUMAN).status_code == 200
    assert [w["id"] for w in c.get("/api/workpackages").json()["workpackages"]] == [wp["id"]]
    _start(c, wp["id"], mode="shadow")
    # it has a run: it can only be hidden
    assert c.post(f"/api/workpackages/{wp['id']}/delete", json={}, headers=HUMAN).status_code == 409
    empty = c.post("/api/workpackages", headers=HUMAN, json={"paths": [str(env["folder"] / "szamla_1.pdf")], "name": "Egy irat"}).json()["workpackage"]
    assert c.post(f"/api/workpackages/{empty['id']}/delete", json={}, headers=HUMAN).status_code == 200
    assert c.get(f"/api/workpackages/{empty['id']}").status_code == 404


def test_resolving_reason_over_http_refreshes_run_status(env):
    # 058: once the run's last own to-do is closed, the run is "done" and does not stay "waiting for to-dos"
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"], mode="shadow").json()["run_id"]
    worker.run_worker(once=True)
    view = c.get(f"/api/runs/{run_id}").json()
    item = view["run"]["input"]["items"][0]
    store.review_enqueue(subject_kind="document", subject_id=item["item_id"], run_id=f"{run_id}:{item['item_id'][:16]}",
                         reasons=["x:1"], producer="teszt")
    reasons = [r["id"] for rs in c.get(f"/api/runs/{run_id}").json()["open_reasons"].values() for r in rs]
    assert reasons
    statuses = [c.post(f"/api/review-reasons/{rid}/resolve", json={}, headers=HUMAN).json()["run_status"] for rid in reasons]
    assert statuses[-1] == "done" and all(s == "needs_review" for s in statuses[:-1])
