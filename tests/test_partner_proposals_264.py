"""264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): the partner register's
proposals from the data are a list of the service - each party with its tax number, the roles it was seen in, how many
documents and when last - searchable and grouped by its first role, with no cap of 200; the list is kept until what it
reads changes (reading it goes through every invoice). Synthetic parties."""
from __future__ import annotations

import pytest

from jav.app import datasets, partners
from jav.app.tablequery import Query
from jav.core import store


@pytest.fixture()
def db(tmp_path, monkeypatch):
    rows = [{"name": "Example Supplier Kft.", "tax_number": "12345676-2-41", "role": "supplier", "seen": 3, "last": "2026-06-08"},
            {"name": "Example Buyer Ltd", "tax_number": None, "role": "customer", "seen": 1, "last": "2026-05-02"}]
    monkeypatch.setitem(partners._SOURCES, "synthetic", partners.SuggestionSource("synthetic", "tests", lambda: rows))
    with store.use_store(tmp_path / "s.sqlite"):
        yield


def test_the_proposals_are_a_list_grouped_by_their_role(db):
    page = datasets.query("settings_partner_proposals", {}, Query(limit=100))
    cols = {c["key"]: c for c in page["columns"]}
    assert cols["role"].get("group") and cols["role"]["labels"]
    rows = {r["name"]: r for r in page["rows"]}
    assert (rows["Example Supplier Kft."]["role"], rows["Example Supplier Kft."]["seen"]) == ("supplier", 3)
    assert rows["Example Supplier Kft."]["_roles"] == ["supplier"] and rows["Example Buyer Ltd"]["tax_number"] is None
    assert datasets.get("settings_partner_proposals").fingerprint is not None  # kept until what it reads changes
