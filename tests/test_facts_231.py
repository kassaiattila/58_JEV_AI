"""231 (stage D, D-b3; the reassessment after D0 of 2026-10-26, P05, P06): what is assessed, and with which facts.

A fact catalogue (a rule file, `configs/facts_<id>.json`, kept by a case as it started) names the levels of what is
assessed (for property: the policyholder, its sites, their asset groups) and each fact a rule may read: its type, its
unit or currency, its level, the codes it may take. An assessed unit has a durable id, its level and its parent, its
facts typed by the catalogue and, for each, the source claim it came from (the value, its original form, where it was
read, how sure it is, which reading made it). The checked input is the set of units a person accepted, with the
product version it is assessed for and the day cover starts. A wrong unit, currency, level, code or parent is refused
with what is wrong. Three invented examples; no paid call.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from jav.app import facts
from jav.core import cfg
from jav.core.measures import Money, Percentage, Quantity

CAT = "property"


def _claim(value, original: str, page: int = 1, revision: int | None = None) -> dict:
    return {"value": value, "original": original, "source": {"item": "it-1", "file": "request.pdf", "page": page, "quote": original},
            "uncertainty": {"verdict": "ok", "confidence": "0.97"},
            "interpretation": {"reading": "type:property_request@1.0.0", "correction_revision": revision}}


def _shop() -> dict:
    """A shop with one site and two asset groups."""
    return {"form": "checked_input/1", "catalogue": CAT, "product": "invented_property@1", "cover_start": "2026-12-01",
            "units": [
                {"unit_id": "u-0000000001", "level": "holder", "parent_id": None,
                 "facts": {"activity_code": "4719", "claims_5y_count": 0, "payment_frequency": "yearly"}, "sources": {}},
                {"unit_id": "u-0000000002", "level": "site", "parent_id": "u-0000000001",
                 "facts": {"country": "HU", "flood_zone": "none", "floor_area": {"value": "180", "unit": "m2"},
                           "alarm_remote": True}, "sources": {"floor_area": _claim({"value": "180", "unit": "m2"}, "180 m2")}},
                {"unit_id": "u-0000000003", "level": "asset_group", "parent_id": "u-0000000002",
                 "facts": {"asset_group": "stock", "sum_insured": {"amount": "12000000", "currency": "HUF"},
                           "valuation": "current_value"}, "sources": {}},
                {"unit_id": "u-0000000004", "level": "asset_group", "parent_id": "u-0000000002",
                 "facts": {"asset_group": "equipment", "sum_insured": {"amount": "4500000", "currency": "HUF"},
                           "valuation": "new_value", "wear": {"value": "20", "per": 100}}, "sources": {}}]}


def _workshop() -> dict:
    """A workshop with two sites; one floor area was corrected by a person."""
    data = _shop()
    data["units"][0]["facts"]["activity_code"] = "2562"
    data["units"].append({"unit_id": "u-0000000005", "level": "site", "parent_id": "u-0000000001",
                          "facts": {"country": "HU", "flood_zone": "low", "floor_area": {"value": "420", "unit": "m2"},
                                    "alarm_remote": False},
                          "sources": {"floor_area": _claim({"value": "420", "unit": "m2"}, "42O nm", page=2, revision=2)}})
    return data


def _no_claims_history() -> dict:
    """A request that says nothing of past claims: the fact is missing, not zero."""
    data = _shop()
    del data["units"][0]["facts"]["claims_5y_count"]
    return data


def test_the_catalogue_is_a_rule_file_and_every_fact_has_a_known_type() -> None:
    cat = facts.catalogue(CAT)
    assert cat.levels == ("holder", "site", "asset_group") and cat.version == cfg.version("facts_property")
    assert cat.facts["sum_insured"].currency == "HUF" and cat.facts["floor_area"].unit == "m2"
    assert {o.combine for o in cat.outcomes.values()} <= {"worst", "max", "min", "union", "one"}


@pytest.mark.parametrize("example", [_shop, _workshop, _no_claims_history])
def test_the_invented_examples_are_typed_by_the_catalogue(example) -> None:
    checked = facts.checked_input(example())
    holder, site = checked.units[0], checked.units[1]
    assert site.facts["floor_area"] == Quantity(value="180", unit="m2")
    assert checked.units[2].facts["sum_insured"] == Money(amount="12000000", currency="HUF")
    assert checked.units[3].facts["wear"] == Percentage(value="20")
    assert checked.cover_start == date(2026, 12, 1) and checked.product == "invented_property@1"
    assert ("claims_5y_count" in holder.facts) == (example is not _no_claims_history)  # missing stays missing, never 0
    again = facts.checked_input(checked.model_dump(mode="json"))
    assert again == checked


def test_a_corrected_fact_keeps_its_source_and_original_form() -> None:
    site = facts.checked_input(_workshop()).units[4]
    claim = site.sources["floor_area"]
    assert (claim.original, claim.source.page, claim.interpretation.correction_revision) == ("42O nm", 2, 2)


@pytest.mark.parametrize(("change", "problem"), [
    (lambda d: d["units"][1]["facts"].update(floor_area={"value": "420", "unit": "m3"}), "floor_area is in m2, not m3"),
    (lambda d: d["units"][2]["facts"].update(sum_insured={"amount": "1", "currency": "EUR"}), "sum_insured is in HUF, not EUR"),
    (lambda d: d["units"][1]["facts"].update(sum_insured={"amount": "1", "currency": "HUF"}), "sum_insured is a fact of the level asset_group, not of site"),
    (lambda d: d["units"][1]["facts"].update(colour="red"), "no fact colour in the catalogue property"),
    (lambda d: d["units"][1]["facts"].update(flood_zone="sometimes"), "flood_zone is one of none, low, medium, high"),
    (lambda d: d["units"][3].update(parent_id="u-0000000003"), "the parent of a unit of the level asset_group is of the level site, not asset_group"),
    (lambda d: d["units"][3].update(parent_id="u-0000000099"), "unit u-0000000004 names no unit u-0000000099 as its parent"),
    (lambda d: d["units"][1]["facts"].update(alarm_remote="yes"), "alarm_remote is true or false"),
])
def test_a_wrong_fact_is_refused_with_what_is_wrong(change, problem) -> None:
    data = _shop()
    change(data)
    with pytest.raises(facts.FactError) as raised:
        facts.checked_input(data)
    assert problem in str(raised.value), str(raised.value)


def test_a_checked_input_names_a_concrete_product_version() -> None:
    data = _shop() | {"product": "invented_property"}
    with pytest.raises(ValidationError):
        facts.checked_input(data)
