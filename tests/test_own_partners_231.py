"""231 (stage U, U3e; the owner's decision of 2026-10-28): the own parties stand among the partners with the role "own".

The partner list shows each own party by name with its first tax number, found by its name or a tax number, and none
of them when another role is chosen; no partner record can be given the role. The processes whose cases belong to an
own party say so in the partner role's "used by". Invented parties; no AI call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import parties, partners, process_settings, registrations
from jav.core import store
from jav.service.api import create_app

registrations.load_all()

TAX = "12121216-2-42"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "own.sqlite"):
        party = parties.create("Example Own Kft.", identities=[("tax", parties.tax_key(TAX), TAX)], actor="anna")["id"]
        parties.create("Example Association", identities=[], actor="anna")
        partners.create(partners.PartnerIn(name="Invented Buyer Ltd", roles=["customer"]), "anna")
        yield party


def test_the_own_parties_are_listed_by_name_with_the_role_own(db) -> None:
    own = partners.own_listing()
    assert [(o["name"], o["tax_number"]) for o in own] == [("Example Association", None), ("Example Own Kft.", TAX)]
    assert own[1]["party_id"] == db and own[1]["changed_at"]
    assert [o["name"] for o in partners.own_listing("12121216")] == ["Example Own Kft."]
    assert [o["name"] for o in partners.own_listing("association", partners.OWN)] == ["Example Association"]
    assert partners.own_listing(role="customer") == []
    assert partners.listing(role=partners.OWN) == []  # no partner record plays it


def test_no_partner_can_be_given_the_own_role(db) -> None:
    with pytest.raises(partners.PartnerError):
        partners.create(partners.PartnerIn(name="Example Other Kft.", roles=[partners.OWN]), "anna")


def test_the_service_lists_them_beside_the_partners(db) -> None:
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        listed = c.get("/api/partners").json()
        assert [p["name"] for p in listed["partners"]] == ["Invented Buyer Ltd"]
        assert [o["name"] for o in listed["own"]] == ["Example Association", "Example Own Kft."]
        assert partners.OWN not in listed["roles"]  # the partner card's roles stay the configured ones
        assert c.get("/api/partners", params={"role": "customer"}).json()["own"] == []


def test_the_processes_of_an_own_party_use_the_own_role(db) -> None:
    using = {e["id"] for e in process_settings.used_by("partner_role")[partners.OWN]}
    assert {"monthly_reconciliation", "bank_statements"} <= using
    assert "it_quote" not in using
