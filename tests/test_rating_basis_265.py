"""265 (code review APPR-01; the owner's decision of 2026-10-31, "Ask for it"): a missing premium basis is missing data.

A unit a module prices but whose basis (its sum insured) the input did not give was silently left out of the premium:
the module summed to 0 and its minimum applied (on the review's test document 32 000 HUF instead of 88 000), with no
blocker. Now the basis is one of the facts asked for before the premium (`missing_facts`), and while it is missing the
calculation stops with a blocker. A person may enter 0 when the unit really takes no part: it then gets no line. A
module that prices no unit at all gives no premium but a blocker, never its minimum alone.
Hand-computed invented cases (HUF); no paid call.
"""

from __future__ import annotations

from jav.app import facts, rating, rule_evaluation
from tests import test_allianz_tariff_231 as az
from tests.test_rating_231 import CLAIMS, HUF, TARIFF, _case


def _without_basis(checked: facts.CheckedInput, unit_id: str, amount: str | None = None) -> facts.CheckedInput:
    data = checked.model_dump(mode="json")
    for u in data["units"]:
        if u["unit_id"] == unit_id:
            u["facts"] = {k: v for k, v in u["facts"].items() if k != "sum_insured"}
            if amount is not None:
                u["facts"]["sum_insured"] = {"amount": amount, "currency": "HUF"}
    return facts.checked_input(data)


def _evaluated(checked: facts.CheckedInput, modules: tuple[str, ...]) -> rule_evaluation.Evaluation:
    return rule_evaluation.evaluate([CLAIMS], checked, modules=modules)


def test_a_unit_without_its_basis_is_asked_for_and_stops_the_premium() -> None:
    checked = _without_basis(_case()[0], "u-0000000011")
    evaluation = _evaluated(checked, ("property",))
    assert rating.missing_facts(TARIFF, checked, evaluation, modules=("property",)) == (("u-0000000011", "sum_insured"),)
    result = rating.calculate(TARIFF, "invented_tariff@1", checked, evaluation, modules=("property",))
    assert result.total is None
    assert "u-0000000011: the module property has no basis: the fact sum_insured is missing" in result.blockers


def test_a_basis_of_zero_takes_the_unit_out_of_the_module() -> None:
    """The stock group alone: 12 000 000 x 1.2 per mille = 14 400 x 1.0 x 0.9 = 12 960 -> 13 000."""
    checked = _without_basis(_case()[0], "u-0000000011", amount="0")
    evaluation = _evaluated(checked, ("property",))
    assert rating.missing_facts(TARIFF, checked, evaluation, modules=("property",)) == ()
    result = rating.calculate(TARIFF, "invented_tariff@1", checked, evaluation, modules=("property",))
    assert result.blockers == ()
    assert [(line.unit_id, line.amount) for line in result.lines] == [("u-0000000010", HUF(12960))]
    assert result.total == HUF(13000)


def test_a_module_that_prices_no_unit_gives_no_premium_and_no_minimum() -> None:
    checked = _without_basis(_without_basis(_case(protection=3)[0], "u-0000000010", "0"), "u-0000000011", "0")
    evaluation = _evaluated(checked, ("property", "burglary"))
    result = rating.calculate(TARIFF, "invented_tariff@1", checked, evaluation, modules=("burglary",))
    assert result.total is None and result.lines == ()
    assert "the module burglary prices no unit, so its minimum is not charged" in result.blockers, result.blockers
    # 272 (K3, the rest of APPR-01): nor is the minimum said to apply beside that blocker (the case page showed both)
    assert result.modules["burglary"]["minimum_applied"] is False
    assert result.modules["burglary"]["total"] == HUF(0)


def test_the_review_s_case_asks_for_the_interruption_sum_instead_of_charging_the_minimum() -> None:
    """The review's test document: business interruption requested, its sum insured not given. Before: the module's
    minimum alone; now the sum is asked for (with the waiting days its factor reads), and the premium waits for it."""
    checked = az._case(interruption=False)
    modules = ("property_ar", "interruption")
    evaluation = rule_evaluation.evaluate([], checked, modules=modules)
    assert rating.missing_facts(az.TARIFF, checked, evaluation, modules=modules) == (
        ("u-0000000001", "interruption_sum_insured"),)
    result = rating.calculate(az.TARIFF, f"{az.TARIFF_ID}@1", checked, evaluation, modules=modules)
    assert result.total is None
    assert "u-0000000001: the module interruption has no basis: the fact interruption_sum_insured is missing" in result.blockers
