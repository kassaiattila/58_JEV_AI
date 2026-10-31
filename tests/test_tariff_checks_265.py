"""265 (code review APPR-08): a tariff's amounts are sound and it fits the product it prices.

A tariff accepted a minimum in another currency than its own, a negative rate, factor or minimum, and modules, levels
and facts its product's catalogue does not have; each surfaced only when a premium was computed. The tariff's form now
refuses the first ones, and a product's manifest names the tariff's misfits before it is made active. Invented tariff
on the invented property catalogue; no AI.
"""

from __future__ import annotations

import pydantic
import pytest

from jav.app import product_rules
from jav.app.product_rules import Product, Tariff
from tests.test_rating_231 import TARIFF

PRODUCT = Product.model_validate({"name": "Invented shop cover", "catalogue": "property", "tariff": "shop",
                                  "modules": [{"code": "property", "name": "Property", "kind": "base"},
                                              {"code": "burglary", "name": "Burglary", "kind": "extension"}]})


def _with(**changes) -> dict:
    return TARIFF.model_dump(mode="json") | changes


def test_a_minimum_in_another_currency_is_refused() -> None:
    data = _with(policy_minimum={"amount": "40", "currency": "EUR"})
    with pytest.raises(pydantic.ValidationError, match="the minimum of the policy is not in the tariff's currency HUF"):
        Tariff.model_validate(data)


def test_a_negative_rate_or_factor_is_refused() -> None:
    data = _with()
    data["modules"]["property"]["rate"]["value"] = "-1.2"
    data["factors"]["activity"]["table"][0]["factor"] = "-1"
    with pytest.raises(pydantic.ValidationError, match="below zero: factor activity, the rate of module property"):
        Tariff.model_validate(data)


def test_the_tariff_fits_its_product() -> None:
    assert product_rules.tariff_problems(TARIFF, PRODUCT) == []


def test_a_misfit_is_named() -> None:
    data = _with()
    data["modules"]["glass"] = {"level": "floor", "basis": "country", "rate": {"value": "1"}}
    data["factors"]["claims"] = {"title": "Claims", "outcome": "no_such_outcome"}
    found = [p.template for p in product_rules.tariff_problems(Tariff.model_validate(data), PRODUCT)]
    assert found == ["module {{module}} is not the product's", "no level {{level}} in the catalogue {{catalogue}}",
                     "prices by {{fact}}, which is not an amount in {{currency}}",
                     "reads the outcome {{outcome}}, which the catalogue {{catalogue}} does not have"]
