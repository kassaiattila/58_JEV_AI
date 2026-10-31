"""264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): the users of "Who is
working?" are a list of the service, each name opening its own page; saving the list keeps when each name that stays
was added (until now every save wrote every name again as new). Synthetic names."""
from __future__ import annotations

import pytest

from jav.app import app_settings, datasets
from jav.app.tablequery import Query
from jav.core import store


@pytest.fixture()
def db(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        yield


def _added() -> dict[str, str]:
    with store.connect() as c:
        return {r["name"]: r["created_at"] for r in c.execute("SELECT name, created_at FROM app_users")}


def test_the_users_are_a_list_each_opening_its_page(db):
    app_settings.save_users(["Synthetic Owner", "Second Person"])
    page = datasets.query("settings_users", {}, Query(limit=100))
    cols = {c["key"]: c for c in page["columns"]}
    assert cols["name"]["link"] == "settings" and cols["name"]["section"] == "users"
    assert [r["_key"] for r in page["rows"]] == ["Second Person", "Synthetic Owner"]
    assert all(r["added"] for r in page["rows"])


def test_saving_the_list_keeps_when_a_staying_name_was_added(db, monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(app_settings, "_now", lambda: datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc))
    app_settings.save_users(["Synthetic Owner"])
    monkeypatch.setattr(app_settings, "_now", lambda: datetime(2026, 10, 31, 9, 0, tzinfo=timezone.utc))
    app_settings.save_users(["Synthetic Owner", "Second Person"])
    added = _added()
    assert added["Synthetic Owner"].startswith("2026-10-01") and added["Second Person"].startswith("2026-10-31")
    app_settings.save_users(["Second Person"])
    assert set(_added()) == {"Second Person"}
