"""263 (plan E, E1; the owner's decisions of 2026-10-30: one list everywhere, searchable, sortable and grouped, a row
opening its thing's page): the lists of Settings as datasets. Each list's row names the page it opens (`link`
`settings` with the section, and a product list's word), says which columns may group it, and comes in the request's
language. Invented partners and the processes' own invented example material; no AI call."""

from __future__ import annotations

import pytest

from jav.app import datasets, examples, partners, registrations
from jav.app.tablequery import Query
from jav.core import display, store
from jav.core.identity import person

registrations.load_all()
ANNA = person("Minta Anna")
ALL = Query(limit=1000)


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "lists.sqlite"):
        yield tmp_path


def _spec(page: dict, key: str) -> dict:
    return next(c for c in page["columns"] if c["key"] == key)


def test_every_settings_list_is_a_registered_dataset():
    names = {"settings_processes", "settings_partners", "settings_products", "settings_tariffs", "settings_rules",
             "settings_documents", "settings_proposal_runs", "settings_output_templates", "settings_letter_frames",
             "settings_price_lists", "settings_own_parties"}
    assert names <= set(datasets.REGISTRY)


def test_the_processes_list_opens_each_process_and_groups_by_period_and_hand(db):
    from jav.app import process_packs

    with display.use("hu"):
        page = datasets.query("settings_processes", {}, ALL)
    assert {r["_key"] for r in page["rows"]} == {p.id for p in process_packs.packs()}
    title = _spec(page, "title")
    assert (title["link"], title["section"]) == ("settings", "processes")
    assert _spec(page, "repeats")["group"] and _spec(page, "manual")["group"]
    monthly = next(r for r in page["rows"] if r["_key"] == "monthly_reconciliation")
    assert monthly["title"] == "Havi egyeztetés" and monthly["repeats"] is True  # in the request's language
    grouped = datasets.query("settings_processes", {}, Query(group="repeats"))
    assert [g["value"] for g in grouped["groups"]] == ["false", "true"]


def test_the_partners_list_holds_the_retired_ones_and_the_own_parties_by_name(db):
    zeta = partners.create(partners.PartnerIn(name="Zéta Kft.", roles=["supplier"]), ANNA)
    partners.create(partners.PartnerIn(name="Alfa Bt.", tax_number="12345676-2-41", roles=["customer", "supplier"]), ANNA)
    partners.retire(zeta["partner_id"], ANNA)
    examples.install("bank_statements", ANNA)  # an invented own party
    with display.use("hu"):
        page = datasets.query("settings_partners", {}, ALL)
    names = [r["name"] for r in page["rows"]]
    assert names == sorted(names, key=str.casefold) and "Zéta Kft." in names
    alfa = next(r for r in page["rows"] if r["name"] == "Alfa Bt.")
    assert (alfa["kind"], alfa["state"], alfa["roles"]) == ("partner", "active", "Vevő · Szállító")
    assert next(r for r in page["rows"] if r["name"] == "Zéta Kft.")["state"] == "retired"
    own = next(r for r in page["rows"] if r["kind"] == "own")
    assert own["_settings"] == ["parties"]  # edited in its own register
    assert _spec(page, "state")["marks"] == {"active": "done", "draft": "trial", "retired": "removed"}


def test_the_product_registrys_lists_open_their_things_under_their_list(db):
    examples.install("insurance_offer", ANNA)
    rules = datasets.query("settings_rules", {}, ALL)
    assert rules["rows"] and all(r["state"] == "active" for r in rules["rows"])
    title = _spec(rules, "title")
    assert (title["link"], title["section"], title["list"]) == ("settings", "products", "rules")
    grouped = datasets.query("settings_rules", {}, Query(group="kind", limit=1000))
    assert sum(g["count"] for g in grouped["groups"]) == rules["matched"]
    for name in ("settings_products", "settings_tariffs", "settings_documents"):
        page = datasets.query(name, {}, ALL)
        assert page["rows"], name
        assert _spec(page, page["columns"][0]["key"])["list"] == name.removeprefix("settings_")


def test_the_letter_frames_open_by_kind_and_id_and_are_named_by_their_subject(db):
    page = datasets.query("settings_letter_frames", {}, ALL)
    offer = next(r for r in page["rows"] if r["ident"] == "offer_letter")
    assert offer["_settings"] == ["letters", "letter_frame", "offer_letter"]
    assert offer["state"] == "system" and "{{policyholder}}" in offer["name"]


def test_the_price_lists_and_the_own_parties_are_their_domains_lists(db):
    examples.install("it_quote", ANNA)
    examples.install("bank_statements", ANNA)
    prices = datasets.query("settings_price_lists", {}, ALL)
    assert len(prices["rows"]) == 1 and prices["rows"][0]["state"] == "active" and prices["rows"][0]["items"] > 0
    assert _spec(prices, "name")["section"] == "prices"
    own = datasets.query("settings_own_parties", {}, ALL)
    assert len(own["rows"]) == 1 and _spec(own, "name")["section"] == "parties"


def test_a_processs_settings_name_every_library_value_not_only_the_active_choices(db):
    from jav.app import process_settings

    examples.install("allianz_property_offer", ANNA)  # the invented tariff
    with display.use("hu"):
        by = {r["key"]: r for r in process_settings.view("allianz_property_offer")["resources"]}
    assert by["tariff"]["names"][by["tariff"]["value"]].startswith("Allianz")
    assert by["letter_frame"]["names"]["offer_letter"] == "Biztosítási ajánlat – {{policyholder}}"  # its subject
    assert by["offer_output"]["names"]["rated_offer"] == "Díjazott ajánlat"
