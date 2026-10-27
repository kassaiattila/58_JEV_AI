"""231 (stage U, U-A1; the owner's decisions of 2026-10-27): the fact catalogue of the real corporate property product.

The catalogue loads as a rule file on the invented catalogue's three levels; the facts the invented one has with the
same meaning keep their names; the required protection class is a code from VII (the least) to I (the most), so of two
rules' requirements the stricter one counts; and every outcome a rule may give combines. No AI call.
"""

from __future__ import annotations

from jav.app import facts, rule_evaluation

CAT = facts.catalogue("allianz_property")
INVENTED = facts.catalogue("property")


def test_the_catalogue_has_the_three_levels_and_keeps_the_shared_names() -> None:
    assert CAT.levels == INVENTED.levels == ("holder", "site", "asset_group")
    same = ("company_name", "tax_number", "activity_code", "claims_5y_count", "claims_5y_paid", "sanctions_listed",
            "site_address", "country", "floor_area", "basement_storage", "asset_group", "sum_insured", "wear",
            "requested_modules", "interruption_sum_insured")
    for name in same:
        assert CAT.facts[name].level == INVENTED.facts[name].level and CAT.facts[name].type == INVENTED.facts[name].type, name
    assert len(CAT.facts) >= 90 and set(INVENTED.outcomes) <= set(CAT.outcomes)


def test_of_two_required_protection_classes_the_stricter_counts() -> None:
    required = CAT.outcomes["protection_class_required"]
    assert required.options == ("VII", "VI", "V", "IV", "III", "II", "I")
    clashes: list[str] = []
    value, _ = rule_evaluation._combine(required, [("r1", "V"), ("r2", "III"), ("r3", "VI")], clashes)
    assert value == "III" and clashes == []
