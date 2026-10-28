"""231 (stage U, U-A5): the real corporate property product's tariff, with invented rates marked as an example.

The owner's decision of 2026-10-27: the condition documents print no premium rate, so the tariff prices every module
of the product with invented rates per thousand, marked as an example, on the real premium factors: the activity, the
claims history, the deductible (the owner's design: 1.03 / 0.96 / 0.885), the flood area, the protection in place, the
surge protection, the business interruption's waiting days, the payment frequency and the contract term; each module
has a minimum, the policy one too. It is kept as a product set of its own (`configs/product_set_allianz_tariff.json`),
so it is installed as a process's example material and goes again. Hand-computed invented cases (HUF); no paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav.app import facts, product_sets, product_sources, rating, rule_evaluation
from jav.core import cfg, identity, store, versions
from jav.core.measures import Money

SET = product_sets.load("product_set_allianz_tariff")
TARIFF_ID = "az_corporate_property_tariff"
TARIFF = SET.tariffs[TARIFF_ID]
CAT = facts.catalogue("allianz_property")
HUF = lambda n: Money(amount=str(n), currency="HUF")  # noqa: E731 - a short constructor for the expected amounts


def test_the_set_holds_together_and_prices_every_module_of_the_product() -> None:
    assert product_sets.problems(SET) == []
    assert set(SET.tariffs) == {TARIFF_ID} and not SET.products and not SET.rules and not SET.documents
    product = product_sources.load("allianz_property").product
    assert set(TARIFF.modules) == {m.code for m in product.modules}
    assert "PÉLDA" in (TARIFF.title or "") and "kitalált" in (TARIFF.title or "")
    assert "example" in cfg.load("product_set_allianz_tariff")["meta"]["description"]


def test_every_factor_and_module_reads_the_catalogue_s_facts_as_they_are_typed() -> None:
    for name, factor in TARIFF.factors.items():
        if factor.outcome is not None:
            assert factor.outcome in CAT.outcomes, name
            continue
        d = CAT.facts[factor.fact]
        for row in factor.table:
            for op, value in row.when.items():
                facts.compared_value(factor.fact, d, op, value)  # raises when the table's value does not fit
    for code, module in TARIFF.modules.items():
        basis = CAT.facts[module.basis]
        assert basis.type == "money" and basis.currency == TARIFF.currency, code
        assert CAT.levels.index(basis.level) <= CAT.levels.index(module.level), code
        for fact, condition in module.only.items():
            for op, value in condition.items():
                facts.compared_value(fact, CAT.facts[fact], op, value)


def _case(*, activity="6201", claims=0, deductible="500000", frequency="yearly", term="indefinite", interruption=True,
          groups=(("buildings", "100000000", {}), ("stock", "20000000", {"protection_class_in_place": "IV"})),
          surge="t1_t2", cover_start="2026-12-01") -> facts.CheckedInput:
    holder = {"activity_code": activity, "claims_5y_count": claims, "payment_frequency": frequency, "contract_term": term}
    holder |= {"chosen_deductible": {"amount": deductible, "currency": "HUF"}} if deductible is not None else {}
    holder |= {"interruption_sum_insured": {"amount": "50000000", "currency": "HUF"}, "bi_deductible_days": 3} if interruption else {}
    units = [{"unit_id": "u-0000000001", "level": "holder", "facts": holder},
             {"unit_id": "u-0000000002", "level": "site", "parent_id": "u-0000000001",
              "facts": {"country": "HU", "flood_area_class": "protected"}
              | ({"surge_protection": surge} if surge is not None else {})}]
    units += [{"unit_id": f"u-00000000{10 + n}", "level": "asset_group", "parent_id": "u-0000000002",
               "facts": {"asset_group": g, "sum_insured": {"amount": s, "currency": "HUF"}} | more}
              for n, (g, s, more) in enumerate(groups)]
    return facts.checked_input({"catalogue": "allianz_property", "product": "az_corporate_property@1",
                                "cover_start": cover_start, "units": units})


def _priced(checked: facts.CheckedInput, modules: tuple[str, ...]) -> rating.Calculation:
    evaluation = rule_evaluation.evaluate([], checked, modules=modules)
    return rating.calculate(TARIFF, f"{TARIFF_ID}@1", checked, evaluation, modules=modules)


def test_a_hand_computed_premium_of_the_all_risks_burglary_and_interruption_cover() -> None:
    """Buildings 100 000 000 x 0.6 per mille = 60 000 x activity 1.0 x no claims 0.95 x deductible 500 000 0.96 x flood
    1.0 = 54 720; stock 20 000 000 -> 12 000 -> 10 944; burglary on the stock: 20 000 000 x 1.4 = 28 000 x group 1.0 x
    protection IV 0.9 x 0.95 x 0.96 = 22 982.4 -> 22 982; interruption 50 000 000 x 0.9 = 45 000 x 1.0 x 0.95 x three
    waiting days 1.0 = 42 750; 131 396 x yearly 1.0 x indefinite 1.0 -> 131 400 (half up to 100)."""
    result = _priced(_case(), ("property_ar", "burglary", "interruption"))
    assert result.blockers == ()
    assert [(line.module, line.amount.amount) for line in result.lines] == [
        ("property_ar", Decimal("54720")), ("property_ar", Decimal("10944")), ("burglary", Decimal("22982")),
        ("interruption", Decimal("42750"))]
    assert result.total == HUF(131400) and result.policy_minimum_applied is False
    burglary = next(line for line in result.lines if line.module == "burglary")
    assert [(s.name, str(s.factor)) for s in burglary.steps] == [
        ("burglary_group", "1.0"), ("protection", "0.9"), ("claims", "0.95"), ("deductible", "0.96")]


def test_module_minimums_the_policy_minimum_and_the_total_factors() -> None:
    """Machinery 10 000 000 with two claims, a 250 000 deductible, no surge protection: all risks 6 000 x 1.15 x 1.03 =
    7 107, under the module's minimum 30 000; the surge extension 400 x 1.5 = 600, under its minimum 3 000; 33 000 x
    quarterly 1.04 x fixed term 1.05 = 36 036 -> 36 000, under the policy minimum 50 000."""
    checked = _case(claims=2, deductible="250000", frequency="quarterly", term="fixed", interruption=False, surge="none",
                    groups=(("machinery", "10000000", {}),))
    result = _priced(checked, ("property_ar", "VIL"))
    assert result.blockers == ()
    assert [line.amount.amount for line in result.lines] == [Decimal("7107"), Decimal("600")]
    assert result.total == HUF(50000) and result.policy_minimum_applied is True


def test_a_missing_factor_gives_no_premium_but_a_blocker() -> None:
    result = _priced(_case(deductible=None), ("property_ar",))
    assert result.total is None
    assert "u-0000000010: no deductible factor: the fact chosen_deductible is missing" in result.blockers, result.blockers


def test_the_facts_a_premium_reads_that_the_input_does_not_give() -> None:
    """U-A8 (the walkthrough of 2026-10-28): each fact the requested modules' factors read that the input does not
    give, named on the unit that holds it at its own level (the holder's chosen deductible once, not once for each asset
    group it prices); a module's own condition is told first; nothing when the premium can be computed."""
    full = ("property_ar", "burglary", "interruption")
    assert rating.missing_facts(TARIFF, _case(), rule_evaluation.evaluate([], _case(), modules=full), modules=full) == ()
    checked = _case(deductible=None, surge=None, groups=(("buildings", "100000000", {}), ("stock", "20000000", {}),
                                                         ("machinery", "10000000", {})))
    evaluation = rule_evaluation.evaluate([], checked, modules=full + ("VIL",))
    assert rating.missing_facts(TARIFF, checked, evaluation, modules=full + ("VIL",)) == (
        ("u-0000000001", "chosen_deductible"), ("u-0000000011", "protection_class_in_place"),
        ("u-0000000012", "protection_class_in_place"), ("u-0000000002", "surge_protection"))  # the buildings: no burglary


def test_the_set_installs_as_a_draft_and_goes_again(tmp_path) -> None:
    with store.use_store(tmp_path / "tariff.sqlite"):
        maker, approver = identity.machine("examples"), "Minta Erika"
        assert product_sets.install(SET, maker=maker, approver=approver) == [f"tariff:{TARIFF_ID}@1"]
        found = product_sets.product_rules.latest("tariff", TARIFF_ID)
        assert found["state"] == versions.ACTIVE and found["made_by_id"] == maker.id
        assert product_sets.install(SET, maker=maker, approver=approver) == [f"tariff:{TARIFF_ID}@1"]  # the same again


@pytest.mark.parametrize("code", ["VIL", "GLASS", "G19", "IAK", "V111", "cold_store"])
def test_an_extension_requested_without_a_unit_it_prices_costs_its_minimum(code: str) -> None:
    result = _priced(_case(interruption=False, groups=(("buildings", "100000000", {}),)), ("property_ar", code))
    assert result.blockers == ()
    assert result.modules[code]["minimum_applied"] is True and result.modules[code]["lines"] == HUF(0)


def test_the_process_offers_the_tariff_as_its_example_material_by_its_title(tmp_path) -> None:
    """231 (U-A6): the real product's process names the tariff set and three packets of invented customers; a set with
    no product (the tariff alone) reads by its tariff's title, so the person sees it is an example."""
    from jav.app import examples, registrations

    registrations.load_all()
    with store.use_store(tmp_path / "examples.sqlite"):
        material = examples.of("allianz_property_offer")
        [one] = material["sets"]
        assert (one["name"], one["state"]) == ("product_set_allianz_tariff", examples.MISSING)
        assert one["title"] == f"Allianz Hungária Zrt.: {TARIFF.title}" and "PÉLDA" in one["title"]
        assert [p["documents"] for p in material["packets"]] == [3, 3, 3]
