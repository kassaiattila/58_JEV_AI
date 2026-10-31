"""264 (plan G, G1; the owner's decision of 2026-10-31: partner proposals from the processed data, as the own parties
have them): a proposal is recorded at once with its suggested values, several or all at once; one that is not a
partner is dismissed, stays dismissed and can be restored; a proposal says its other spellings. Synthetic parties."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import datasets, partners
from jav.app.tablequery import Query
from jav.core import store

ROWS = [{"name": "Example Supplier Kft.", "tax_number": "12345676-2-41", "role": "supplier", "seen": 3, "last": "2026-06-08"},
        {"name": "Example Supplier KFT", "tax_number": "12345676-2-41", "role": "supplier", "seen": 1, "last": "2026-06-01"},
        {"name": "Example Buyer Ltd", "tax_number": None, "role": "customer", "seen": 1, "last": "2026-05-02"},
        {"name": "Misread Ticket Vendor", "tax_number": None, "role": "supplier", "seen": 1, "last": "2026-04-01"}]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setitem(partners._SOURCES, "synthetic", partners.SuggestionSource("synthetic", "tests", lambda: ROWS))
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path / "s.sqlite"


def _by_name() -> dict[str, dict]:
    return {s["name"]: s for s in partners.suggestions(limit=100)}


def test_a_proposal_says_its_key_and_its_other_spellings(db):
    found = _by_name()
    supplier = found["Example Supplier Kft."]
    assert supplier["key"] == "domestic:12345676" and supplier["names"] == ["Example Supplier KFT"] and supplier["seen"] == 4
    assert found["Example Buyer Ltd"]["key"].startswith("name:")


def test_proposals_are_recorded_at_once_with_their_values_and_not_twice(db):
    keys = [_by_name()["Example Supplier Kft."]["key"]]
    done = partners.accept_suggestions(keys, actor="Synthetic owner", names={keys[0]: "Example Supplier Kft. (main)"})
    [made] = done["created"]
    partner = partners.get(made)
    assert (partner["name"], partner["tax_number"], partner["roles"]) == ("Example Supplier Kft. (main)", "12345676-2-41", ["supplier"])
    assert "Example Supplier Kft." not in _by_name()  # it is a partner now
    again = partners.accept_suggestions(keys, actor="Synthetic owner")
    assert (again["created"], again["skipped"]) == ([], 1)


def test_every_proposal_is_recorded_when_no_key_is_named(db):
    done = partners.accept_suggestions(None, actor="Synthetic owner")
    assert len(done["created"]) == 3 and _by_name() == {}


def test_a_dismissed_proposal_stays_away_and_can_be_restored(db):
    key = _by_name()["Misread Ticket Vendor"]["key"]
    partners.dismiss_suggestions([key], actor="Synthetic owner")
    assert "Misread Ticket Vendor" not in _by_name()
    assert [d["name"] for d in partners.dismissed_suggestions()] == ["Misread Ticket Vendor"]
    assert partners.accept_suggestions(None, actor="Synthetic owner")["created"]  # all: the dismissed one is not among them
    assert "Misread Ticket Vendor" not in [p["name"] for p in partners.listing()]
    partners.restore_suggestions([key], actor="Synthetic owner")
    assert "Misread Ticket Vendor" in _by_name() and partners.dismissed_suggestions() == []


def test_the_lists_follow_the_dismissals(db):
    key = _by_name()["Misread Ticket Vendor"]["key"]
    partners.dismiss_suggestions([key], actor="Synthetic owner")
    proposals = datasets.query("settings_partner_proposals", {}, Query(limit=100))
    assert "Misread Ticket Vendor" not in [r["name"] for r in proposals["rows"]]
    assert all(r["_key"] for r in proposals["rows"])
    dismissed = datasets.query("settings_partner_dismissed", {}, Query(limit=100))
    assert [(r["_key"], r["name"]) for r in dismissed["rows"]] == [(key, "Misread Ticket Vendor")]


def test_the_service_records_dismisses_and_restores_proposals(db):
    from jav.service.api import create_app

    human = {"X-Actor": "teszt.elek"}
    with TestClient(create_app(store_path=db), base_url="http://127.0.0.1:8930") as c:
        key = _by_name()["Example Buyer Ltd"]["key"]
        done = c.post("/api/partners/suggestions/accept", headers=human, json={"keys": [key]})
        assert done.status_code == 200 and len(done.json()["created"]) == 1
        other = _by_name()["Misread Ticket Vendor"]["key"]
        assert c.post("/api/partners/suggestions/dismiss", headers=human, json={"keys": [other]}).status_code == 200
        assert c.post("/api/partners/suggestions/restore", headers=human, json={"keys": [other]}).status_code == 200
        everything = c.post("/api/partners/suggestions/accept", headers=human, json={"all": True})
        assert everything.status_code == 200 and len(everything.json()["created"]) == 2
        assert c.post("/api/partners/suggestions/accept", json={"keys": [key]}).status_code in (400, 401, 403, 422)  # a person acts
