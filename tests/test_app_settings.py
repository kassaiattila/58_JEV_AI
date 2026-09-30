"""Settings (057): the user name list and the watched work folders. Synthetic data, no AI calls."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from jav import app_settings, store
from tests import test_api
from tests.test_api import HUMAN, INVOICE_LINES, write_text_pdf

env = test_api.env
LATER = datetime.now(timezone.utc) + timedelta(minutes=5)  # a freshly written file has already "settled"


def _resolve(raw: str) -> Path:
    return Path(raw).resolve()


def test_users_are_deduplicated_and_trimmed(env):
    c = env["client"]
    r = c.put("/api/settings/users", json={"users": ["  Teszt   Elek ", "teszt elek", "Minta Anna", ""]})
    assert r.status_code == 200 and r.json()["users"] == ["Minta Anna", "Teszt Elek"]
    assert c.get("/api/settings/users").json()["users"] == ["Minta Anna", "Teszt Elek"]


def test_folder_must_be_inside_allowed_roots_when_restricted(env, tmp_path, monkeypatch):
    test_api.restrict_paths(monkeypatch)
    c = env["client"]
    outside = tmp_path / "kint"
    outside.mkdir()
    bad = c.put("/api/settings/folders", headers=HUMAN, json={"folders": [{"path": str(outside)}]})
    assert bad.status_code == 403
    ok = c.put("/api/settings/folders", headers=HUMAN, json={"folders": [{"path": str(env["folder"]), "recipe_id": "invoice-extraction",
                                                                         "params": {"arm": "S"}}]})
    assert ok.status_code == 200, ok.text
    [f] = ok.json()["folders"]
    assert f["name"] == "bejovo" and f["batch_mode"] == "folder" and f["id"].startswith("wf-")
    assert c.put("/api/settings/folders", json={"folders": []}).status_code == 422  # cannot be saved without an author


def test_any_existing_folder_can_be_watched_without_restriction(env, tmp_path):
    """Decision 061: a work folder can be anywhere, without restriction; a missing folder still cannot be saved."""
    c = env["client"]
    outside = tmp_path / "kint"
    outside.mkdir()
    ok = c.put("/api/settings/folders", headers=HUMAN, json={"folders": [{"path": str(outside)}]})
    assert ok.status_code == 200, ok.text
    missing = c.put("/api/settings/folders", headers=HUMAN, json={"folders": [{"path": str(outside / "nincs")}]})
    assert missing.status_code == 422


def test_scan_creates_one_package_then_extends_it_without_readding_removed(env):
    with store.use_store(env["db"]):
        [f] = app_settings.save_folders([app_settings.WatchedFolder(path=str(env["folder"]), recipe_id="invoice-extraction",
                                                                    params={"arm": "S"})],
                                        check_dir=_resolve)
        first = app_settings.scan(f["id"], now=LATER)
        assert first["status"] == "ok" and first["new"] == 2
        wp_id = first["workpackage"]
        c = env["client"]
        view = c.get(f"/api/workpackages/{wp_id}").json()
        assert view["workpackage"]["source_kind"] == "watch" and view["workpackage"]["assignment"]["recipe_id"] == "invoice-extraction"
        assert view["runs"] == 0  # no paid run starts by itself

        again = app_settings.scan(f["id"], now=LATER)
        assert again["new"] == 0 and again["workpackage"] == wp_id  # a file already seen is not taken in again

        removed = view["workpackage"]["items"][0]["item_id"]
        c.post(f"/api/workpackages/{wp_id}/items/{removed}/remove", headers=HUMAN, json={"expected_revision": view["workpackage"]["revision"]})
        write_text_pdf(env["folder"] / "szamla_3.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-003") for line in INVOICE_LINES])
        third = app_settings.scan(f["id"], now=LATER)
        assert third["new"] == 1 and third["workpackage"] == wp_id
        items = {i["item_id"] for i in c.get(f"/api/workpackages/{wp_id}").json()["workpackage"]["items"]}
        assert removed not in items and len(items) == 2  # the document removed by hand did not come back


def test_fresh_file_waits_and_daily_mode_makes_a_package_per_day(env):
    with store.use_store(env["db"]):
        [f] = app_settings.save_folders([app_settings.WatchedFolder(path=str(env["folder"]), batch_mode="daily", name="Napi")],
                                        check_dir=_resolve)
        now = datetime.now(timezone.utc)
        wait = app_settings.scan(f["id"], now=now)
        assert wait["new"] == 0 and wait["settling"] == 2  # may still be being written: it waits for the next scan
        day1 = app_settings.scan(f["id"], now=LATER)
        assert day1["new"] == 2
        write_text_pdf(env["folder"] / "szamla_4.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-004") for line in INVOICE_LINES])
        day2 = app_settings.scan(f["id"], now=LATER + timedelta(days=1))
        assert day2["new"] == 1 and day2["workpackage"] != day1["workpackage"]


def test_tick_scans_only_due_enabled_folders(env):
    with store.use_store(env["db"]):
        saved = app_settings.save_folders([app_settings.WatchedFolder(path=str(env["folder"])),
                                           app_settings.WatchedFolder(path=str(env["folder"]), enabled=False, name="ki")],
                                          check_dir=_resolve)
        on = next(f for f in saved if f["enabled"])
        assert app_settings.tick(LATER) == [on["id"]]
        assert app_settings.tick(LATER) == []  # the next scan is due only after the interval


def test_new_files_go_to_a_new_package_after_the_old_one_is_archived(env):
    # 058: no new document goes into a hidden package; files already seen do not come back
    with store.use_store(env["db"]):
        from jav import work

        [f] = app_settings.save_folders([app_settings.WatchedFolder(path=str(env["folder"]))], check_dir=_resolve)
        first = app_settings.scan(f["id"], now=LATER)
        work.archive_workpackage(first["workpackage"], actor="t")
        write_text_pdf(env["folder"] / "szamla_3.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-003") for line in INVOICE_LINES])
        second = app_settings.scan(f["id"], now=LATER + timedelta(minutes=1))
        assert second["new"] == 1 and second["workpackage"] != first["workpackage"]
        assert len(work.get(second["workpackage"])["items"]) == 1
