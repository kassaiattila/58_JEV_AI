"""265 (code review APPR-05; the owner's decision of 2026-10-31, "A second approver is needed"): a tariff version is
made active only by another person than its maker, as a product version is.

A product's version needed a second person; its tariff's did not, and a product names its tariff by id (its active
version), so one person could change the premium of every case started after. Now `activate` and a product set's
`install` refuse the maker as the tariff's approver too. A version the examples' machine made is still made active by a
person (X-20, an earlier decision: the machine and the person are two). Invented data; no paid call.
"""

from __future__ import annotations

import pytest

from jav.app import product_rules, product_sets
from jav.core import identity, store
from tests.test_rating_231 import TARIFF

ANNA, BELA = "Minta Anna", "Minta Bela"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "tariffs.sqlite"):
        yield tmp_path


def test_a_tariff_s_maker_cannot_make_it_active(db) -> None:
    product_rules.add("tariff", "invented_tariff", TARIFF.model_dump(mode="json"), actor=ANNA)
    with pytest.raises(product_rules.SecondPersonNeeded, match="tariff version"):
        product_rules.activate("tariff", "invented_tariff", 1, actor=ANNA)
    assert product_rules.activate("tariff", "invented_tariff", 1, actor=BELA)["state"] == "active"


def test_a_set_with_a_tariff_alone_needs_another_approver(db) -> None:
    tariffs = product_sets.load("product_set_allianz_tariff")
    with pytest.raises(product_rules.SecondPersonNeeded):
        product_sets.install(tariffs, maker=ANNA, approver=ANNA)
    machine = identity.machine("examples")
    assert product_sets.install(tariffs, maker=machine, approver=ANNA)  # X-20: the examples' machine and a person
