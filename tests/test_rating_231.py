"""231 (stage D, D-c3; the reassessment after D0 of 2026-10-26, T14): a premium from a versioned tariff, step by step.

A tariff (a versioned thing of the product registry, in force on some days) prices each requested module on the units
of its level: the basis (a sum insured) times the module's rate per thousand, then its factors in their order (each
read from a fact the unit sees or an outcome of the rules), rounded once per line; a module's minimum; the modules
summed in one currency, the total factors (the payment frequency), rounded once more, and the policy's minimum. Every
step is itemised. A missing factor, a cover start the tariff is not in force on, or another currency gives no total
but a blocker, never a default. The calculation is traced and replays the same. Hand-computed invented cases (HUF).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav.app import facts, rating, rule_evaluation
from jav.app.product_rules import Resolved, Rule, Tariff
from jav.core import store, trace
from jav.core.measures import Money

HUF = lambda n: Money(amount=str(n), currency="HUF")  # noqa: E731 - a short constructor for the expected amounts

TARIFF = Tariff.model_validate({
    "currency": "HUF", "valid": {"valid_from": "2026-01-01", "valid_to": "2026-12-31"},
    "line_rounding": {"unit": "1", "mode": "half_up"}, "total_rounding": {"unit": "100", "mode": "half_up"},
    "modules": {
        "property": {"level": "asset_group", "basis": "sum_insured", "rate": {"value": "1.2"}, "factors": ["activity", "claims"]},
        "burglary": {"level": "asset_group", "basis": "sum_insured", "rate": {"value": "2.0"},
                     "minimum": {"amount": "20000", "currency": "HUF"}, "factors": ["protection", "claims"]}},
    "factors": {
        "activity": {"title": "Activity class", "fact": "activity_code",
                     "table": [{"when": {"in": ["4719"]}, "factor": "1.0"}, {"when": {"in": ["2562"]}, "factor": "1.25"},
                               {"when": {}, "factor": "1.5"}]},
        "claims": {"title": "Claims history", "outcome": "premium_factor"},
        "protection": {"title": "Protection in place", "fact": "protection_class_in_place",
                       "table": [{"when": {"gte": 3}, "factor": "0.9"}, {"when": {}, "factor": "1.0"}]},
        "frequency": {"title": "Payment frequency", "fact": "payment_frequency",
                      "table": [{"when": {"eq": "yearly"}, "factor": "1.0"}, {"when": {"eq": "half_yearly"}, "factor": "1.02"},
                                {"when": {"eq": "quarterly"}, "factor": "1.04"}]}},
    "total_factors": ["frequency"], "policy_minimum": {"amount": "10000", "currency": "HUF"}})

CLAIMS = Resolved("claims_factor@1", Rule.model_validate({
    "catalogue": "property", "kind": "premium_factor", "title": "claims", "level": "holder", "facts": ["claims_5y_count"],
    "table": {"rows": [{"when": {"claims_5y_count": {"eq": 0}}, "then": {"premium_factor": "0.9"}},
                       {"when": {}, "then": {"premium_factor": "1.1"}}]},
    "source": {"document": "general@1", "page": 1}}))


def _case(*, activity="4719", frequency="yearly", claims=0, protection=None, groups=(("stock", "12000000"), ("equipment", "4500000")),
          cover_start="2026-12-01") -> tuple[facts.CheckedInput, rule_evaluation.Evaluation]:
    holder = {"activity_code": activity, "payment_frequency": frequency} | ({"claims_5y_count": claims} if claims is not None else {})
    site = {"country": "HU"} | ({"protection_class_in_place": protection} if protection is not None else {})
    units = [{"unit_id": "u-0000000001", "level": "holder", "facts": holder},
             {"unit_id": "u-0000000002", "level": "site", "parent_id": "u-0000000001", "facts": site}]
    units += [{"unit_id": f"u-00000000{10 + n}", "level": "asset_group", "parent_id": "u-0000000002",
               "facts": {"asset_group": g, "sum_insured": {"amount": s, "currency": "HUF"}}} for n, (g, s) in enumerate(groups)]
    checked = facts.checked_input({"catalogue": "property", "product": "invented_property@1", "cover_start": cover_start,
                                   "units": units})
    return checked, rule_evaluation.evaluate([CLAIMS], checked, modules=("property", "burglary"))


@pytest.mark.parametrize(("case", "modules", "lines", "total", "minimum"), [
    # property: 12 000 000 x 1.2 per mille = 14 400 x 1.0 x 0.9 = 12 960; 4 500 000 -> 5 400 x 0.9 = 4 860; 17 820 -> 17 800
    (dict(), ("property",), [12960, 4860], 17800, False),
    # + burglary with protection class 3: 24 000 x 0.9 x 0.9 = 19 440; 9 000 x 0.81 = 7 290; 44 550 -> 44 600 (half up)
    (dict(protection=3), ("property", "burglary"), [12960, 4860, 19440, 7290], 44600, False),
    # quarterly, activity 2562: 14 400 x 1.25 x 0.9 = 16 200; 5 400 x 1.125 = 6 075; 22 275 x 1.04 = 23 166 -> 23 200
    (dict(activity="2562", frequency="quarterly"), ("property",), [16200, 6075], 23200, False),
    # one small group with burglary, protection class 1: 1 080 + the burglary minimum 20 000 (2 000 x 1.0 x 0.9 = 1 800
    # under it) -> 21 080 -> 21 100
    (dict(groups=(("equipment", "1000000"),), protection=1), ("property", "burglary"), [1080, 1800], 21100, False),
    # one line rounded half up: 1 234 567 x 1.2 per mille = 1 481.4804 x 0.9 = 1 333.33... -> 1 333; the policy minimum 10 000
    (dict(groups=(("stock", "1234567"),)), ("property",), [1333], 10000, True),
])
def test_hand_computed_premiums(case, modules, lines, total, minimum) -> None:
    checked, evaluation = _case(**case)
    result = rating.calculate(TARIFF, "invented_tariff@1", checked, evaluation, modules=modules)
    assert result.blockers == ()
    assert [line.amount.amount for line in result.lines] == [Decimal(n) for n in lines]
    assert result.total == HUF(total) and result.policy_minimum_applied is minimum


def test_every_step_of_a_line_is_itemised() -> None:
    checked, evaluation = _case(protection=3)
    line = rating.calculate(TARIFF, "invented_tariff@1", checked, evaluation, modules=("burglary",)).lines[0]
    assert [(s.name, str(s.factor)) for s in line.steps] == [("protection", "0.9"), ("claims", "0.9")]
    assert line.base == HUF("24000.0") and line.amount == HUF(19440)


@pytest.mark.parametrize(("case", "modules", "blocker"), [
    (dict(claims=None), ("property",), "u-0000000010: no claims factor: the outcome premium_factor is missing"),
    (dict(protection=None), ("burglary",), "u-0000000010: no protection factor: the fact protection_class_in_place is missing"),
    (dict(cover_start="2027-02-01"), ("property",), "the tariff is not in force on 2027-02-01"),
])
def test_a_missing_factor_or_validity_gives_no_total(case, modules, blocker) -> None:
    checked, evaluation = _case(**case)
    result = rating.calculate(TARIFF, "invented_tariff@1", checked, evaluation, modules=modules)
    assert result.total is None and blocker in result.blockers, result.blockers


def test_a_module_prices_only_the_units_its_only_takes() -> None:
    """D-c5: a burglary module limited to stock prices the stock line and not the equipment line; a unit without the
    fact it is limited by is a blocker, not a guess."""
    checked, evaluation = _case(protection=3)
    burglary = TARIFF.modules["burglary"].model_copy(update={"only": {"asset_group": {"in": ["stock"]}}})
    limited = TARIFF.model_copy(update={"modules": {**TARIFF.modules, "burglary": burglary}})
    result = rating.calculate(limited, "invented_tariff@1", checked, evaluation, modules=("burglary",))
    # 24 000 x 0.9 x 0.9 = 19 440, under the module's minimum 20 000
    assert [(line.unit_id, line.amount) for line in result.lines] == [("u-0000000010", HUF(19440))]
    assert result.total == HUF(20000)
    data = checked.model_dump(mode="json")
    data["units"] = [u | {"facts": {k: v for k, v in u["facts"].items() if k != "asset_group"}}
                     if u["unit_id"] == "u-0000000011" else u for u in data["units"]]
    checked = facts.checked_input(data)
    evaluation = rule_evaluation.evaluate([CLAIMS], checked, modules=("burglary",))
    result = rating.calculate(limited, "invented_tariff@1", checked, evaluation, modules=("burglary",))
    assert result.total is None
    assert "u-0000000011: the module burglary prices by asset_group, which is missing" in result.blockers


def test_a_module_limited_by_a_presence_check_is_refused() -> None:
    with pytest.raises(ValueError, match="by comparisons, not by present"):
        type(TARIFF.modules["burglary"]).model_validate(
            TARIFF.modules["burglary"].model_dump(mode="json") | {"only": {"asset_group": {"present": True}}})


def test_another_currency_gives_no_total() -> None:
    checked, evaluation = _case()
    euro = TARIFF.model_copy(update={"currency": "EUR"})
    result = rating.calculate(euro, "invented_tariff@1", checked, evaluation, modules=("property",))
    assert result.total is None and "the tariff is in EUR, the sum_insured of u-0000000010 in HUF" in result.blockers


def test_the_calculation_is_traced_and_replays_the_same(tmp_path) -> None:
    checked, evaluation = _case(protection=3)
    result = rating.calculate(TARIFF, "invented_tariff@1", checked, evaluation, modules=("property", "burglary"))
    with store.use_store(tmp_path / "rating.sqlite"):
        with store.connect() as c:
            store.begin_immediate(c)
            row_id = rating.trace_in(c, "wp-0000000d0c30", result)
        row = next(r for r in trace.rows(point=rating.POINT) if r["id"] == row_id)
        assert row["outcome"]["total"] == {"amount": "44600", "currency": "HUF"} and trace.replay(row) == row["outcome"]
