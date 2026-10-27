"""231 (stage D, D-e2): a document's values become facts of assessed units by a rule file, and nothing is guessed.

Each value goes to its unit by the document's own values (a site by its number, an asset group by its row), through a
code table where the document prints a word; an amount needs the currency the document states; a list of covers is
read whole or not at all. A value that cannot be read is listed with why, never guessed. A rule file that names a fact
its level does not have is refused. Invented values; no paid call.
"""

from __future__ import annotations

import pytest

from jav.app import fact_readings
from jav.core import cfg

READINGS = fact_readings.load()


def _claims(pack: str, values: dict):
    return fact_readings.claims(READINGS, pack, values, source=lambda field, lst, row: {"item": "doc", "field": field, "row": row},
                                reading=f"type:{pack}")


def test_a_schedule_gives_its_holder_site_and_asset_groups_with_where_each_was_printed() -> None:
    out, unread = _claims("property_schedule", {
        "policyholder_name": "Minta Kft.", "site_no": "2", "site_address": "Minta utca 1.", "floor_area": "1 250",
        "flood_zone": " Közepes ", "alarm_remote": "Igen", "surge_protection": "T2 + T3", "basement_storage": "nem",
        "protection_class": "3", "currency": "huf",
        "asset_groups": [{"asset_group": "Gépek, berendezések", "sum_insured": "45000000", "valuation": "új érték", "wear": 15}]})
    assert unread == []
    got = {(c["unit"], c["fact"]): c["value"] for c in out}
    assert got[("site:2", "floor_area")] == {"value": "1250", "unit": "m2"}
    assert (got[("site:2", "flood_zone")], got[("site:2", "alarm_remote")], got[("site:2", "surge_protection")]) == ("medium", True, "t2_t3")
    assert got[("site:2/1", "sum_insured")] == {"amount": "45000000", "currency": "HUF"}
    assert got[("site:2/1", "asset_group")] == "equipment" and got[("site:2/1", "wear")] == {"value": "15", "per": 100}
    assert [c["unit"] for c in out][:2] == ["holder", "site:2"]  # a parent before its children
    group = next(c for c in out if c["unit"] == "site:2/1")
    assert (group["parent"], group["level"], group["source"]["row"]) == ("site:2", "asset_group", 1)


def test_an_amount_without_a_currency_and_a_word_no_table_knows_are_not_read() -> None:
    out, unread = _claims("property_schedule", {"site_no": "1", "flood_zone": "nagyon magas", "currency": None,
                                                "asset_groups": [{"asset_group": "készlet", "sum_insured": "100"}]})
    assert {(u["unit"], u["fact"], u["why"]) for u in unread} == {
        ("site:1", "flood_zone", "not a known code"), ("site:1/1", "sum_insured", "the document states no currency")}
    assert ("site:1/1", "asset_group") in {(c["unit"], c["fact"]) for c in out}


def test_a_schedule_without_its_site_number_says_no_unit() -> None:
    out, unread = _claims("property_schedule", {"site_no": None, "flood_zone": "alacsony"})
    assert out == [] and unread == [{"unit": None, "fact": "flood_zone", "value": "alacsony",
                                     "why": "the document does not say which unit it is"}]


def test_a_list_of_covers_is_read_whole_or_not_at_all() -> None:
    covers = [{"cover": "vagyonbiztosítás"}, {"cover": "betöréses lopás"}]
    out, _ = _claims("insurance_request", {"requested_covers": covers})
    assert [c["value"] for c in out if c["fact"] == "requested_modules"] == [["property", "burglary"]]
    out, unread = _claims("insurance_request", {"requested_covers": [*covers, {"cover": "üvegtörés"}]})
    assert not [c for c in out if c["fact"] == "requested_modules"]
    assert (unread[0]["why"], unread[0]["value"]) == ("not a known code", ["üvegtörés"])  # the word no table knows


def test_a_count_must_be_whole() -> None:
    out, unread = _claims("claims_history", {"claims_count": "1.5"})
    assert out == [] and unread[0]["why"] == "not a whole number"


def test_a_rule_file_naming_a_fact_its_level_does_not_have_is_refused(monkeypatch) -> None:
    real = cfg.load
    bad = real("fact_readings_property")
    bad = {**bad, "packs": {**bad["packs"], "claims_history": [{"level": "holder", "key": "holder",
                                                                 "facts": {"flood_zone": {"field": "claims_count"}}}]}}
    monkeypatch.setattr(cfg, "load", lambda name: bad if name == "fact_readings_invented" else real(name))
    with pytest.raises(ValueError, match="flood_zone is no fact of the level holder"):
        fact_readings.load("fact_readings_invented")
