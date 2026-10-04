"""080: one processing for every package (F-feldolgozási-mód). No calls, synthetic files.

The active recipe `processing` chooses the flow per item kind (email: intent + attachments; document: type
recognition, then extraction of the recognised type). `invoice-extraction` (a given type, no recognition) stays an
internal recipe for tests and the command line; the other two are retired: they stay readable for old runs and
assignments, but cannot be assigned again. A package without an assignment runs with the default settings, and the
migration moves every old assignment onto the active recipe, keeping its settings.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from jav import app_settings, store, work, work_views


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield tmp_path


def _docs(tmp_path: Path, n: int = 2) -> Path:
    d = tmp_path / "bejovo"
    d.mkdir(parents=True)
    for i in range(n):
        (d / f"irat_{i}.pdf").write_bytes(f"%PDF-1.4 minta {i}".encode())
    return d


def _email(tmp_path: Path, name: str = "level") -> Path:
    d = tmp_path / "inbox" / name
    d.mkdir(parents=True)
    p = d / "message.json"
    p.write_text(json.dumps({"subject": "Számla", "sender": "a@b.hu"}, ensure_ascii=False), encoding="utf-8")
    return p


def test_catalogue_offers_only_the_active_processing(isolated):
    assert [r["id"] for r in work_views.recipe_catalog()] == ["processing", "multi-format-processing"]
    assert work.default_recipe()["id"] == "processing"
    status = {r["id"]: r.get("status", "active") for r in work.recipes()}
    assert status == {"processing": "active", "multi-format-processing": "active", "invoice-extraction": "internal",
                      "document-processing": "retired", "email-intent": "retired"}
    p = work.recipe("processing")
    assert p["flows"] == {"email": "email", "document": "document"} and set(p["input_kinds"]) == {"email", "document"}
    assert set(p["params"]) == {"arm", "jev_cache", "tasks", "azure_ocr", "jev"}  # 086: + jev


def test_retired_recipe_cannot_be_assigned_but_internal_can(isolated):
    wp = work.create_from_folder(_docs(isolated), name="x")
    with pytest.raises(work.RetiredRecipe):
        work.assign_recipe(wp["id"], "document-processing", params={}, expected_revision=0, actor="t")
    with pytest.raises(ValueError):  # a named error, but still a ValueError (the service answers 422)
        work.assign_recipe(wp["id"], "email-intent", params={}, expected_revision=0, actor="t")
    a = work.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S"}, expected_revision=0, actor="t")
    assert a["recipe_id"] == "invoice-extraction"


def test_package_without_assignment_is_ready_with_the_default_settings(isolated):
    wp = work.create_from_folder(_docs(isolated), name="x")
    r = work.readiness(wp["id"])
    assert r["ready"] and r["blockers"] == [] and r["assignment_default"] is True and r["assignment_revision"] == 0
    # two documents of unknown type: the worst case (G path) is reserved; 0.07 JEV + 0.15 OpenAI + 0.02 Azure each
    assert r["budget"] == {"jev": Decimal("0.14"), "openai": Decimal("0.30"), "azure_di": Decimal("0.04")}
    assert work_views.next_step(work.get(wp["id"]), None, True)["code"] == "start"


def test_empty_package_still_blocks(isolated):
    wp = work.create_workpackage(name="üres", source_kind="manual", source_ref=None)
    assert {b["code"] for b in work.readiness(wp["id"])["blockers"]} == {"no_items"}


def test_start_without_assignment_pins_the_default_settings(isolated):
    wp = work.create_from_folder(_docs(isolated), name="x")
    r = work.readiness(wp["id"])
    res = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=0, input_hash=r["input_hash"], actor="Anna")
    a = work.current_assignment(wp["id"])
    assert a["revision"] == 1 and a["recipe_id"] == "processing" and a["actor"] == "Anna"
    assert a["params"] == {"arm": "auto", "jev_cache": "reuse", "tasks": "off", "azure_ocr": "on", "jev": "on"}
    assert a["note"]
    run = work.get_run(res["run_id"])
    assert run["recipe_id"] == "processing" and run["assignment_revision"] == 1
    with pytest.raises(work.RevisionConflict):  # a second start with the old revision does not assign again
        work.start_run(wp["id"], mode="shadow", expected_assignment_revision=0, input_hash=r["input_hash"], actor="Anna")


def test_plan_counts_kinds_paths_and_reasons(isolated):
    wp = work.create_from_folder(_docs(isolated, 3), name="vegyes")
    first, second, _third = work.get(wp["id"])["items"]
    store.upsert_document(doc_id=first["sha256"], source_path=first["source_path"], detail_type="invoice_hu")  # S
    store.upsert_document(doc_id=second["sha256"], source_path=second["source_path"], detail_type="mohu_szamla")  # G
    mail = _email(isolated)
    work.add_items(wp["id"], [mail], kind="email", expected_revision=work.get(wp["id"])["revision"])
    work.assign_recipe(wp["id"], "processing", params={"tasks": "propose", "azure_ocr": "off"}, expected_revision=0, actor="t")
    r = work.readiness(wp["id"])
    assert r["plan"] == {"documents": 3, "emails": 1, "attachments": 0, "paths": {"S": 1, "G": 1, "unknown": 1},
                         "tasks_emails": 1, "azure": False, "jev_reuse": True, "arm": "auto",  # 082: the chosen path
                         "jev": True}  # 086: JEV is used
    # OpenAI: the G-path document, the document of unknown type and the task proposal on the email
    assert r["budget"] == {"jev": Decimal("0.26"), "openai": Decimal("0.306")}


def _assign_raw(wp_id: str, recipe_id: str, params: dict) -> None:
    """An old assignment as the store holds it (a retired recipe can no longer be assigned through `assign_recipe`)."""
    r = work.recipe(recipe_id)
    with store.connect() as c:
        rev = (c.execute("SELECT MAX(revision) m FROM recipe_assignments WHERE workpackage_id=?", (wp_id,)).fetchone()["m"] or 0) + 1
        c.execute("INSERT INTO recipe_assignments VALUES (?,?,?,?,?,?,?,?,?)",
                  (wp_id, rev, recipe_id, r["version"], work.recipe_hash(r), json.dumps(params), "régi", None, "2026-09-28T10:00:00"))


def test_retired_assignment_warns_and_migration_moves_every_package(isolated):
    wps = {}
    for name, recipe_id, params in (
            ("szamla", "invoice-extraction", {"arm": "S", "doc_type": "invoice_hu", "jev_cache": "reuse", "azure_ocr": "off"}),
            ("irat", "document-processing", {"arm": "auto", "jev_cache": "live", "azure_ocr": "on"}),
            ("level", "email-intent", {"arm": "auto", "jev_cache": "reuse", "tasks": "propose"}),
            ("uj", "processing", {"arm": "G", "jev_cache": "reuse", "tasks": "off", "azure_ocr": "on", "jev": "on"})):
        wp = work.create_from_folder(_docs(isolated / name), name=name)
        _assign_raw(wp["id"], recipe_id, params)
        wps[name] = wp["id"]
    assert "recipe_retired" in {w["code"] for w in work.readiness(wps["irat"])["warnings"]}

    planned = work.migrate_assignments(write=False)
    assert sorted(p["workpackage_id"] for p in planned) == sorted([wps["szamla"], wps["irat"], wps["level"]])
    assert work.current_assignment(wps["irat"])["recipe_id"] == "document-processing"  # a dry run changes nothing

    done = work.migrate_assignments(write=True)
    assert len(done) == 3
    szamla = work.current_assignment(wps["szamla"])
    assert szamla["recipe_id"] == "processing" and szamla["revision"] == 2 and szamla["actor"] == "rendszer"
    assert szamla["params"] == {"arm": "S", "jev_cache": "reuse", "tasks": "off", "azure_ocr": "off", "jev": "on"}  # the type is dropped
    assert "invoice_hu" in szamla["note"]
    assert work.current_assignment(wps["irat"])["params"] == {"arm": "auto", "jev_cache": "live", "tasks": "off", "azure_ocr": "on", "jev": "on"}
    assert work.current_assignment(wps["level"])["params"]["tasks"] == "propose"
    assert work.current_assignment(wps["uj"])["revision"] == 1  # already on the active recipe: untouched
    assert work.readiness(wps["irat"])["warnings"] == []
    assert work.migrate_assignments(write=True) == []  # repeatable


def test_migration_moves_watched_folders_off_retired_recipes(isolated):
    folder = _docs(isolated)
    [f] = app_settings.save_folders([app_settings.WatchedFolder(path=str(folder))], check_dir=lambda p: Path(p))
    with store.connect() as c:
        c.execute("UPDATE watched_folders SET recipe_id='document-processing', params=? WHERE id=?",
                  (json.dumps({"arm": "S"}), f["id"]))
    assert [x["id"] for x in app_settings.migrate_folder_recipes(write=False)] == [f["id"]]
    app_settings.migrate_folder_recipes(write=True)
    [f2] = app_settings.folders()
    assert f2["recipe_id"] == "processing" and f2["params"] == {"arm": "S", "jev_cache": "reuse", "tasks": "off", "azure_ocr": "on", "jev": "on"}
    assert app_settings.migrate_folder_recipes(write=True) == []


def test_cli_lists_every_status_and_migrates_on_request(isolated, capsys):
    from jav import cli

    wp = work.create_from_folder(_docs(isolated), name="x")
    _assign_raw(wp["id"], "email-intent", {"arm": "auto", "jev_cache": "reuse", "tasks": "off"})
    assert cli.main(["recipes"]) == 0
    out = capsys.readouterr().out
    assert "processing v1 [active]" in out and "invoice-extraction" in out and "[retired]" in out
    assert cli.main(["processing-migrate", "--json"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert not dry["written"] and [p["workpackage_id"] for p in dry["packages"]] == [wp["id"]]
    assert work.current_assignment(wp["id"])["recipe_id"] == "email-intent"
    assert cli.main(["processing-migrate", "--write"]) == 0
    assert "1 package(s)" in capsys.readouterr().out
    assert work.current_assignment(wp["id"])["recipe_id"] == "processing"


def test_service_offers_active_processing_and_knows_every_title(isolated):
    from fastapi.testclient import TestClient

    from jav import api

    client = TestClient(api.create_app(store_path=isolated / "w.sqlite"), base_url="http://127.0.0.1:8930")
    body = client.get("/api/recipes").json()
    assert [r["id"] for r in body["recipes"]] == ["processing", "multi-format-processing"]
    assert set(body["titles"]) == {"processing", "multi-format-processing", "invoice-extraction", "document-processing", "email-intent"}


def test_watched_folder_saved_with_a_retired_recipe_moves_onto_the_processing(isolated):
    # the UI no longer shows the folder's recipe, so saving the list must not fail on an old one
    [f] = app_settings.save_folders([app_settings.WatchedFolder(path=str(_docs(isolated)), recipe_id="email-intent",
                                                                params={"tasks": "propose"})], check_dir=lambda p: Path(p))
    assert f["recipe_id"] == "processing" and f["params"] == {"arm": "auto", "jev_cache": "reuse", "tasks": "propose", "azure_ocr": "on", "jev": "on"}
    with pytest.raises(ValueError):
        app_settings.save_folders([app_settings.WatchedFolder(path=str(_docs(isolated / "b")), recipe_id="nincs-ilyen")],
                                  check_dir=lambda p: Path(p))
