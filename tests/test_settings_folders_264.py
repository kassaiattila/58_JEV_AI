"""264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): the watched work folders are a
list of the service - each with its path, whether it is on, its packaging, how often it is checked and how its last
check ended - each opening its own page. Synthetic folders."""
from __future__ import annotations

import pytest

from jav.app import app_settings, datasets
from jav.app.tablequery import Query
from jav.core import store


@pytest.fixture()
def db(tmp_path):
    (tmp_path / "in").mkdir()
    (tmp_path / "daily").mkdir()
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def test_the_work_folders_are_a_list_each_opening_its_page(db):
    app_settings.save_folders([
        app_settings.WatchedFolder(name="Incoming", path=str(db / "in")),
        app_settings.WatchedFolder(name="Daily scans", path=str(db / "daily"), enabled=False, batch_mode="daily", interval_min=60),
    ], check_dir=lambda p: __import__("pathlib").Path(p))
    page = datasets.query("settings_folders", {}, Query(limit=100))
    cols = {c["key"]: c for c in page["columns"]}
    assert cols["name"]["link"] == "settings" and cols["name"]["section"] == "folders"
    assert cols["state"].get("group") and cols["batch_mode"].get("group")
    rows = {r["name"]: r for r in page["rows"]}
    assert (rows["Incoming"]["state"], rows["Incoming"]["batch_mode"], rows["Incoming"]["interval_min"]) == ("on", "folder", "15")
    assert (rows["Daily scans"]["state"], rows["Daily scans"]["batch_mode"], rows["Daily scans"]["interval_min"]) == ("off", "daily", "60")
    assert rows["Incoming"]["_key"].startswith("wf-") and rows["Incoming"]["path"].endswith("in")
