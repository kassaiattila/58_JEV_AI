"""151: superseding an older live run.

A live run that is not approved pins its to-do reasons (066 Á06): no other run takes them over or closes them. When a
later live run of the same package has processed the same items again, the older run can be superseded by a person:
it stays as a cancelled run, its own open reasons close as `superseded` (they stay in the store), and the package's
event log records who did it and which run superseded it. Synthetic data, no paid calls.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav import api, store, work, work_views
from tests.pdfgen import INVOICE_LINES, write_text_pdf


def _finish(run_id: str) -> None:
    """Marks every job and item of the run finished (the worker is not run: the reasons are raised directly)."""
    with store.connect() as c:
        c.execute("UPDATE jobs SET status='done' WHERE run_id=?", (run_id,))
    for i in work.get_run(run_id)["input"]["items"]:
        work.record_item_result(run_id, i["item_id"], status="done")
    work.refresh_run_status(run_id)


@pytest.fixture()
def runs(tmp_path: Path):
    """One package with two documents and two live runs on them: the older one, then a rerun."""
    db = tmp_path / "w.sqlite"
    with store.use_store(db):
        folder = tmp_path / "in"
        folder.mkdir()
        write_text_pdf(folder / "a.pdf", INVOICE_LINES)
        write_text_pdf(folder / "b.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-002") for line in INVOICE_LINES])
        wp = work.create_from_folder(folder, name="Synthetic package")
        work.assign_recipe(wp["id"], "processing", params={"arm": "S"}, expected_revision=0, actor="t")
        ready = work.readiness(wp["id"])
        start = {"expected_assignment_revision": 1, "input_hash": ready["input_hash"], "actor": "t"}
        older = work.start_run(wp["id"], mode="apply", **start)["run_id"]
        _finish(older)
        newer = work.start_run(wp["id"], mode="apply", rerun_of=older, **start)["run_id"]
        items = [i["item_id"] for i in work.get_run(older)["input"]["items"]]

        def raise_reason(run_id: str, item: str, reason: str) -> None:
            store.review_enqueue(subject_kind="document", subject_id=item, run_id=work.flow_run_id(run_id, item),
                                 reasons=[reason], producer="m2")

        raise_reason(older, items[0], "pick:seller_name")
        raise_reason(older, items[1], "validator:tax_number")
        raise_reason(newer, items[0], "pick:seller_name")  # the same reason, raised again by the rerun
        _finish(older)
        _finish(newer)
        yield {"wp": wp["id"], "older": older, "newer": newer, "items": items, "db": db, "start": start}


def _open(run_id: str) -> list[str]:
    with store.connect() as c:
        return sorted(r["reason"] for r in c.execute(
            "SELECT reason FROM review_reasons WHERE status='open' AND substr(run_id, 1, ?) = ?",
            (len(run_id) + 1, run_id + ":")))


def test_an_older_live_run_offers_superseding_by_the_later_one(runs):
    offer = work.supersede_info(runs["older"])
    assert offer == {"by": runs["newer"], "open_reasons": 2, "resolved_reasons": 0, "corrected_items": 0}
    assert work.supersede_info(runs["newer"]) is None  # nothing later covers the latest run


def test_superseding_closes_only_the_older_runs_reasons(runs):
    out = work.supersede_run(runs["older"], actor="teszt.elek")
    assert out == {"run_id": runs["older"], "superseded_by": runs["newer"], "reasons_closed": 2}
    assert work.get_run(runs["older"])["status"] == "cancelled"
    assert _open(runs["older"]) == []
    assert _open(runs["newer"]) == ["pick:seller_name"]  # the later run's own reason stays open
    with store.connect() as c:
        closed = [r["status"] for r in c.execute(
            "SELECT status FROM review_reasons WHERE substr(run_id, 1, ?) = ?", (len(runs["older"]) + 1, runs["older"] + ":"))]
    assert closed == ["superseded", "superseded"]  # kept in the store, not deleted
    event = [e for e in work.workpackage_events(runs["wp"]) if e["action"] == "run_supersede"]
    assert len(event) == 1 and event[0]["actor"] == "teszt.elek"
    assert json.loads(event[0]["detail"]) == {"reasons_closed": 2, "run_id": runs["older"], "superseded_by": runs["newer"]}


def test_the_later_runs_page_no_longer_lists_the_superseded_reasons(runs):
    before = work_views.run_view(runs["newer"])["earlier_open_reasons"]
    assert sum(len(v) for v in before.values()) == 2
    work.supersede_run(runs["older"], actor="teszt.elek")
    after = work_views.run_view(runs["newer"])
    assert after["earlier_open_reasons"] == {}
    assert after["supersede"] is None
    page = work_views.run_view(runs["older"])
    assert page["supersede"] is None
    assert page["superseded"]["by"] == runs["newer"] and page["superseded"]["actor"] == "teszt.elek"
    assert page["superseded"]["reasons_closed"] == 2


def test_human_work_on_the_older_run_is_reported_before_superseding(runs):
    item = runs["items"][1]
    with store.connect() as c:
        c.execute("INSERT INTO run_item_corrections(run_id, item_id, revision, fields, actor, created_at)"
                  " VALUES (?,?,1,'{}','teszt.elek','2026-10-12T00:00:00+00:00')", (runs["older"], item))
        rid = c.execute("SELECT id FROM review_reasons WHERE status='open' AND run_id=?",
                        (work.flow_run_id(runs["older"], item),)).fetchone()["id"]
    work.resolve_reason(rid, actor="teszt.elek", resolution=None, note="rendben")
    offer = work.supersede_info(runs["older"])
    assert offer["corrected_items"] == 1 and offer["resolved_reasons"] == 1 and offer["open_reasons"] == 1


def test_only_an_unapproved_finished_live_run_with_a_later_cover_can_be_superseded(runs):
    trial = work.start_run(runs["wp"], mode="shadow", **runs["start"])["run_id"]
    _finish(trial)
    assert work.supersede_info(trial) is None  # a trial run pins nothing
    with pytest.raises(work.NotReady):
        work.supersede_run(trial, actor="t")
    with store.connect() as c:  # the later run still running: it covers nothing yet
        c.execute("UPDATE runs SET status='running' WHERE run_id=?", (runs["newer"],))
    assert work.supersede_info(runs["older"]) is None
    with store.connect() as c:  # the later run cancelled: it covers nothing either
        c.execute("UPDATE runs SET status='cancelled' WHERE run_id=?", (runs["newer"],))
    assert work.supersede_info(runs["older"]) is None
    with pytest.raises(work.NotReady):
        work.supersede_run(runs["older"], actor="t")
    with store.connect() as c:
        c.execute("UPDATE runs SET status='done' WHERE run_id=?", (runs["newer"],))
        c.execute("UPDATE runs SET approval='approved', approved_by='t' WHERE run_id=?", (runs["older"],))
    assert work.supersede_info(runs["older"]) is None  # an approved run stays
    with pytest.raises(work.NotReady):
        work.supersede_run(runs["older"], actor="t")


def test_a_later_run_on_fewer_items_does_not_supersede(runs):
    with store.connect() as c:
        row = c.execute("SELECT input FROM runs WHERE run_id=?", (runs["newer"],)).fetchone()
        snapshot = json.loads(row["input"])
        snapshot["items"] = snapshot["items"][:1]
        c.execute("UPDATE runs SET input=? WHERE run_id=?", (json.dumps(snapshot), runs["newer"]))
    assert work.supersede_info(runs["older"]) is None


def test_the_service_supersedes_in_the_persons_name(runs):
    client = TestClient(api.create_app(store_path=runs["db"]), base_url="http://127.0.0.1:8930")
    r = client.post(f"/api/runs/{runs['older']}/supersede", headers={"X-Actor": "teszt.elek"}, json={})
    assert r.status_code == 200, r.text
    assert r.json()["superseded_by"] == runs["newer"] and r.json()["status"] == "cancelled"
    again = client.post(f"/api/runs/{runs['older']}/supersede", headers={"X-Actor": "teszt.elek"}, json={})
    assert again.status_code == 409
