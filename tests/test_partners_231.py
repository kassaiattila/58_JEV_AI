"""231 (plan stage B, B1; DECISIONS 231): the shared partner register.

The outside parties the processes deal with, each with the roles it plays, every change a version of its own: a save
makes a new active version and supersedes the one before, a partner is retired rather than deleted and can be
restored. The same tax number, or the same name without one, as another partner is refused with that partner named;
so is a save from a page that shows an older version. The register starts empty and only a person records a partner;
the domains propose partners from what they read (the finance domain: an incoming invoice's supplier, an outgoing
invoice's buyer, never an own party). Invented partners; no AI call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import partners
from jav.core import store

ANNA = "anna"


@pytest.fixture()
def db(tmp_path):
    with store.use_store(tmp_path / "partners.sqlite"):
        yield tmp_path / "partners.sqlite"


def _in(name: str, roles: list[str], **values) -> partners.PartnerIn:
    return partners.PartnerIn(name=name, roles=roles, **values)


def test_a_partner_is_recorded_with_its_roles_and_found_by_name_tax_number_or_role(db) -> None:
    made = partners.create(_in("  Invented  Buyer Ltd ", ["supplier", "customer"], tax_number="12345678-2-42",
                               email="buyer@example.com"), ANNA)
    assert (made["name"], made["roles"], made["version"], made["retired"]) == ("Invented Buyer Ltd", ["customer", "supplier"],
                                                                              1, False)
    assert [v["state"] for v in made["versions"]] == ["active"] and made["versions"][0]["made_by"] == ANNA
    partners.create(_in("Example Monitors Kft.", ["supplier"]), ANNA)
    assert [p["name"] for p in partners.listing()] == ["Example Monitors Kft.", "Invented Buyer Ltd"]
    assert [p["name"] for p in partners.listing("12345678")] == ["Invented Buyer Ltd"]
    assert [p["name"] for p in partners.listing(role="customer")] == ["Invented Buyer Ltd"]
    assert set(partners.roles()) == {"customer", "supplier", "insured", "broker"}


@pytest.mark.parametrize("values", [{"name": "  ", "roles": ["customer"]}, {"name": "X", "roles": ["landlord"]}])
def test_a_partner_needs_a_name_and_known_roles(db, values) -> None:
    with pytest.raises(partners.PartnerError):
        partners.create(partners.PartnerIn(**values), ANNA)


def test_every_change_is_a_version_and_a_stale_page_is_refused(db) -> None:
    made = partners.create(_in("Invented Buyer Ltd", ["customer"]), ANNA)
    pid = made["partner_id"]
    changed = partners.update(pid, _in("Invented Buyer Ltd", ["customer"], phone="+36 1 234 5678"), "bela", expected_version=1)
    assert changed["version"] == 2 and changed["phone"] == "+36 1 234 5678"
    assert [(v["version"], v["state"], v["made_by"]) for v in changed["versions"]] == [(2, "active", "bela"),
                                                                                      (1, "superseded", ANNA)]
    with pytest.raises(partners.PartnerConflict) as stale:
        partners.update(pid, _in("Invented Buyer Ltd", ["customer"]), ANNA, expected_version=1)
    assert stale.value.partner_id == pid


def test_the_same_tax_number_or_name_as_another_partner_is_refused_with_it_named(db) -> None:
    first = partners.create(_in("Invented Buyer Ltd", ["customer"], tax_number="12345678-2-42"), ANNA)["partner_id"]
    with pytest.raises(partners.PartnerConflict) as same_tax:
        partners.create(_in("Another Name Kft.", ["supplier"], tax_number="12345678-1-13"), ANNA)  # the same party key
    assert same_tax.value.partner_id == first
    plain = partners.create(_in("Example Monitors Kft.", ["supplier"]), ANNA)["partner_id"]
    with pytest.raises(partners.PartnerConflict) as same_name:
        partners.create(_in("EXAMPLE Monitors kft", ["customer"]), ANNA)  # the name's words, the legal form ignored
    assert same_name.value.partner_id == plain
    # two companies of one name are told apart by their tax numbers
    partners.create(_in("Invented Buyer Ltd", ["customer"], tax_number="87654321-2-41"), ANNA)


def test_a_retired_partner_is_offered_no_more_and_can_be_restored(db) -> None:
    pid = partners.create(_in("Invented Buyer Ltd", ["customer"]), ANNA)["partner_id"]
    retired = partners.retire(pid, ANNA)
    assert retired["retired"] and partners.listing() == []
    assert [p["partner_id"] for p in partners.listing(retired=True)] == [pid]
    with pytest.raises(partners.PartnerStateError):
        partners.update(pid, _in("Invented Buyer Ltd", ["customer"]), ANNA, expected_version=1)
    restored = partners.restore(pid, "bela")
    assert not restored["retired"] and restored["version"] == 1
    with pytest.raises(partners.PartnerStateError):
        partners.restore(pid, ANNA)
    with pytest.raises(partners.UnknownPartner):
        partners.get("partner-000000000000")


def test_the_domains_proposals_leave_out_the_partners_already_recorded(db, monkeypatch) -> None:
    rows = [{"name": "Invented Supplier Kft.", "tax_number": "12121216-2-42", "role": "supplier", "seen": 3, "last": "2026-09-30"},
            {"name": "Invented Supplier Kft", "tax_number": "12121216-2-42", "role": "customer", "seen": 1, "last": "2026-10-02"},
            {"name": "Example Monitors Kft.", "tax_number": None, "role": "customer", "seen": 2}]
    monkeypatch.setattr(partners, "_SOURCES", {})
    partners.register_suggestions(partners.SuggestionSource("invented", __name__, lambda: rows))
    proposed = partners.suggestions()
    assert [(p["name"], p["roles"], p["seen"], p["last"]) for p in proposed] == [
        ("Invented Supplier Kft.", ["supplier", "customer"], 4, "2026-10-02"), ("Example Monitors Kft.", ["customer"], 2, None)]
    partners.create(_in("Example Monitors Kft.", ["customer"]), ANNA)
    assert [p["name"] for p in partners.suggestions()] == ["Invented Supplier Kft."]


def test_the_finance_domain_proposes_suppliers_and_customers_but_no_own_party(db, monkeypatch) -> None:
    from jav.domains.finance import party_views

    invoices = [{"doc_type": "invoice_hu", "supplier_name": "Invented Supplier Kft.", "supplier_tax_id": "12121216-2-42",
                 "buyer_name": "Own Company Kft.", "buyer_tax_id": "13570008-1-13", "issue_date": "2026-09-01"},
                {"doc_type": "invoice_out", "supplier_name": "Own Company Kft.", "supplier_tax_id": "13570008-1-13",
                 "buyer_name": "Invented Customer Bt.", "buyer_tax_id": None, "issue_date": "2026-09-05"},
                {"doc_type": "invoice_hu", "supplier_name": "Own Company Kft.", "supplier_tax_id": "13570008-1-13",
                 "buyer_name": "x", "buyer_tax_id": None, "issue_date": "2026-09-06"}]

    class Own:
        def by_tax(self, tax):
            return "party-own" if tax == "13570008-1-13" else None

        def by_name(self, name):
            return ("party-own", "exact") if name == "Own Company Kft." else (None, None)

    monkeypatch.setattr(party_views.reconcile_store, "snapshot", lambda: {"invoices": invoices, "statements": []})
    monkeypatch.setattr(party_views.parties, "resolver", lambda: Own())
    assert sorted((r["name"], r["role"]) for r in party_views.partner_suggestions()) == [
        ("Invented Customer Bt.", "customer"), ("Invented Supplier Kft.", "supplier")]


def test_the_service_records_changes_and_answers_a_conflict_with_the_other_partner(db) -> None:
    from jav.service.api import create_app

    human = {"X-Actor": "teszt.elek"}
    with TestClient(create_app(store_path=db), base_url="http://127.0.0.1:8930") as c:
        made = c.post("/api/partners", headers=human, json={"name": "Invented Buyer Ltd", "roles": ["customer"],
                                                             "tax_number": "12345678-2-42"})
        assert made.status_code == 201, made.text
        pid = made.json()["partner_id"]
        clash = c.post("/api/partners", headers=human, json={"name": "Other", "roles": ["supplier"], "tax_number": "12345678-2-42"})
        assert clash.status_code == 409 and clash.json()["other_id"] == pid
        changed = c.put(f"/api/partners/{pid}", headers=human, json={"name": "Invented Buyer Ltd", "roles": ["customer", "supplier"],
                                                                      "tax_number": "12345678-2-42", "expected_version": 1})
        assert changed.status_code == 200 and changed.json()["version"] == 2
        stale = c.put(f"/api/partners/{pid}", headers=human, json={"name": "X", "roles": ["customer"], "expected_version": 1})
        assert stale.status_code == 409
        listed = c.get("/api/partners", params={"role": "supplier"}).json()
        assert [p["partner_id"] for p in listed["partners"]] == [pid] and listed["roles"]["broker"]["label"] == "Broker"
        assert c.post(f"/api/partners/{pid}/retire", headers=human, json={}).json()["retired"] is True
        assert c.post(f"/api/partners/{pid}/restore", headers=human, json={}).json()["retired"] is False
        assert c.get(f"/api/partners/{pid}").json()["versions"][0]["version"] == 2
        assert c.get("/api/partners/partner-000000000000").status_code == 404
        assert c.get("/api/partners/suggestions").status_code == 200
