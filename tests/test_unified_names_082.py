"""Unified names in the item lists (082).

The content-based file name (078) appears while the work is going on, not only in the result's file-name view: the
run's and the package's item lists and the review queue can show it instead of the original name, and it can be added
as a column. Synthetic PDFs and a fake JEV client, no paid calls.
"""

from jav import cfg, naming, work
from jav.runtime import worker
from tests import test_api
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_api import HUMAN, _ready_wp, _start

env = test_api.env

READY = "2026-09-01_SZAMLA_Minta-Kereskedelmi-Kft_MINTA-2026-001.pdf"


def _run(c, folder):
    wp = _ready_wp(c, folder)
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    return wp, run_id


def _correct_first(c, wp, run_id):
    """A person fixes the two name fields the fake model got wrong on the first invoice."""
    item_id = next(i["item_id"] for i in wp["items"] if i["source_path"].endswith("szamla_1.pdf"))
    r = c.post(f"/api/runs/{run_id}/items/{item_id}/correction", headers=HUMAN, json={
        "fields": {"supplier_name": "Minta Kereskedelmi Kft.", "invoice_number": "MINTA-2026-001"}, "expected_revision": 0})
    assert r.status_code == 200, r.text
    return item_id


def _query(c, dataset, scope, **query):
    r = c.post(f"/api/datasets/{dataset}/query", json={"scope": scope, "query": query})
    assert r.status_code == 200, r.text
    return r.json()


# --- the names of a run and of a package ------------------------------------------------------------------------


def test_a_run_names_its_finished_documents_and_marks_the_uncertain_ones(env):
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    first = _correct_first(c, wp, run_id)
    names = naming.run_item_names(run_id)
    assert set(names) == {i["item_id"] for i in wp["items"]}
    assert names[first].unified == READY and names[first].state == "ready" and names[first].check is None
    assert names[first].run_id == run_id
    other = next(n for k, n in names.items() if k != first)
    # the display name is the file name only, without the review folder of the copies
    assert other.state == "review" and other.unified.startswith("2026-09-01_SZAMLA_") and "/" not in other.unified
    assert cfg.load("field_labels")["fields"]["invoice_number"] in other.check


def test_an_item_not_yet_processed_has_no_unified_name(env):
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]  # queued, the worker has not run
    names = naming.run_item_names(run_id)
    assert {(n.unified, n.state, n.check) for n in names.values()} == {(None, "pending", None)}
    assert {n.state for n in naming.package_item_names(work.get(wp["id"])).values()} == {"pending"}


def test_the_package_takes_each_item_from_its_latest_finished_run(env):
    c = env["client"]
    wp, first_run = _run(c, env["folder"])
    first = _correct_first(c, wp, first_run)
    third = env["folder"] / "szamla_3.pdf"
    write_text_pdf(third, [line.replace("MINTA-2026-001", "MINTA-2026-003") for line in INVOICE_LINES])
    added = work.add_documents(wp["id"], [third], expected_revision=work.get(wp["id"])["revision"])
    new_item = next(i["item_id"] for i in added["items"] if i["source_path"].endswith("szamla_3.pdf"))
    _start(c, wp["id"])  # a second run is queued but has not run: the first run's names stay
    names = naming.package_item_names(work.get(wp["id"]))
    assert names[first].unified == READY and names[first].run_id == first_run
    assert names[new_item].state == "pending" and names[new_item].unified is None


# --- the item lists -----------------------------------------------------------------------------------------------


def test_the_run_items_list_shows_the_chosen_name_and_offers_both_as_columns(env):
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    first = _correct_first(c, wp, run_id)

    plain = _query(c, "run_items", {"run_id": run_id})
    row = next(r for r in plain["rows"] if r["item_id"] == first)
    assert row["name"] == "szamla_1.pdf" and row["original_name"] == "szamla_1.pdf"  # the default: the original name
    assert row["unified_name"] == READY and row["name_state"] == "ready"
    cols = {col["key"]: col for col in plain["columns"]}
    assert cols["unified_name"]["hidden"] and cols["original_name"]["hidden"] and cols["name_state"]["hidden"]
    assert cols["name_state"]["labels"]["review"] == "Ellenőrzendő"

    unified = _query(c, "run_items", {"run_id": run_id, "names": "unified"}, sort=[{"col": "name"}])
    rows = {r["item_id"]: r for r in unified["rows"]}
    assert rows[first]["name"] == READY and rows[first]["original_name"] == "szamla_1.pdf"
    other = next(r for k, r in rows.items() if k != first)
    assert other["name_state"] == "review" and cfg.load("field_labels")["fields"]["invoice_number"] in other["_name_check"]
    # sorting and searching follow the name that is shown
    assert [r["name"] for r in unified["rows"]] == sorted(r["name"] for r in unified["rows"])
    found = _query(c, "run_items", {"run_id": run_id, "names": "unified"}, q="MINTA-2026-001")
    assert [r["item_id"] for r in found["rows"]] == [first]


def test_the_package_items_list_shows_the_unified_name_once_processed(env):
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    first = _correct_first(c, wp, run_id)
    body = _query(c, "workpackage_items", {"workpackage_id": wp["id"], "names": "unified"})
    rows = {r["item_id"]: r for r in body["rows"]}
    assert rows[first]["name"] == READY and rows[first]["original_name"] == "szamla_1.pdf"
    assert {r["name_state"] for r in body["rows"]} == {"ready", "review"}
    assert _query(c, "workpackage_items", {"workpackage_id": wp["id"]})["rows"][0]["name"].startswith("szamla_")


def test_an_unknown_name_choice_is_refused(env):
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    r = c.post("/api/datasets/run_items/query", json={"scope": {"run_id": run_id, "names": "both"}, "query": {}})
    assert r.status_code == 422


def test_the_run_view_carries_the_names_for_the_review_queue_only_when_asked(env):
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    first = _correct_first(c, wp, run_id)
    assert "names" not in c.get(f"/api/runs/{run_id}").json()
    names = c.get(f"/api/runs/{run_id}", params={"names": "unified"}).json()["names"]
    assert names[first] == {"unified": READY, "state": "ready", "check": None, "run_id": run_id}
