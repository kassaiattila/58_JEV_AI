"""231 (stage D, D-c5): an invented insurer's product set, kept as data, holds together and gives its hand-worked cases.

The set (`configs/golden_products.json`) has five condition documents in the structure of real ones, the 16 rules a
careful person reads from them, a product with four cover modules and its tariff. Every rule cites a page and clause of
a document of the product whose text holds its quote; each reference case's verdict, missing facts, combined outcomes,
premium lines and total are worked by hand (in the file's generator comments and below) and compared with the rule
evaluation and the rating. The set installs into a store as drafts by one person and is made active by another; a store
holding another content of one of its things refuses it before anything is written. Invented data; no paid call.
"""

from __future__ import annotations

import pytest

from jav.app import facts, product_rules, product_sets, rule_evaluation
from jav.app.product_rules import Resolved
from jav.core import store, versions

ANNA, BELA = "Minta Anna", "Minta Bela"
SET = product_sets.load()


@pytest.fixture()
def db(tmp_path):
    with store.use_store(tmp_path / "product-set.sqlite"):
        yield


def test_the_invented_set_holds_together() -> None:
    assert product_sets.problems(SET) == []
    assert (len(SET.documents), len(SET.rules), len(SET.products), len(SET.tariffs)) == (5, 16, 1, 1)
    assert {r.kind for r in SET.rules.values()} == {"eligibility", "premium_factor", "valuation", "deductible", "exclusion",
                                                     "obligation", "sublimit", "requirement"}


@pytest.mark.parametrize("case", SET.cases, ids=lambda c: c.id)
def test_every_reference_case_gives_its_hand_worked_outcome(case) -> None:
    assert product_sets.case_differences(SET, case) == []


def test_the_reference_case_in_figures() -> None:
    """Property 222 750 + burglary 117 450 (no building line) + surge 66 625 + interruption 66 000 = 472 825; half
    yearly x 1.03 = 487 009.75, rounded to 487 000."""
    evaluation, calc = product_sets.run_case(SET, SET.cases[0])
    assert evaluation.verdict == "allow" and calc is not None
    assert {code: str(m["total"].amount) for code, m in calc.modules.items()} == {
        "property": "222750", "burglary": "117450", "surge": "66625", "interruption": "66000"}
    assert "u-0000000011" not in {line.unit_id for line in calc.lines if line.module == "burglary"}
    assert str(calc.subtotal.amount) == "472825" and str(calc.total.amount) == "487000"


def _changed(path: tuple, value) -> product_sets.ProductSet:
    data = SET.model_dump(mode="json")
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return product_sets.ProductSet.model_validate(data)


@pytest.mark.parametrize(("path", "value", "problem"), [
    (("rules", "inv_flood_high", "source", "quote"), "az árvízkár biztosított",
     "rule inv_flood_high: its quote is not in clause 6.1 of inv_general_conditions@1"),
    (("rules", "inv_flood_high", "source", "page"), 4, "rule inv_flood_high cites page 4, but clause 6.1 is on page 3"),
    (("documents", "inv_surge_clause", "text"), {}, "document inv_surge_clause: clause 1 has no text"),
    (("products", "inv_business_property", "rules"), ["inv_flood_high@2"],
     "product inv_business_property names rule inv_flood_high@2, which is not a first version of the set"),
    (("products", "inv_business_property", "documents"), ["inv_general_conditions@1"],
     "product inv_business_property: rule inv_class_cash@1 cites inv_security_rules@1, which the product does not name"),
])
def test_a_wrong_citation_text_or_reference_is_a_problem(path, value, problem) -> None:
    assert problem in product_sets.problems(_changed(path, value))


def test_installed_by_one_person_and_made_active_by_another(db) -> None:
    refs = product_sets.install(SET, maker=ANNA, approver=BELA)
    assert len(refs) == 23 and "product:inv_business_property@1" in refs
    at = product_rules.product_at("inv_business_property@1")
    assert len(at.rules) == 16 and len(at.documents) == 5
    assert product_rules.resolve("tariff", "inv_business_property_tariff")["state"] == versions.ACTIVE
    # the installed rules give the same outcome as the set's
    case = SET.cases[3]
    installed = rule_evaluation.evaluate([Resolved(r.ref, r.content) for r in at.rules], facts.checked_input(case.input),
                                         modules=case.modules)
    assert installed.verdict == product_sets.run_case(SET, case)[0].verdict == "refer"
    # again: nothing new
    assert product_sets.install(SET, maker=ANNA, approver=BELA) == refs
    assert product_rules.latest("rule", "inv_flood_high")["version"] == 1


def test_one_person_cannot_make_their_own_set_active(db) -> None:
    with pytest.raises(product_rules.SecondPersonNeeded):
        product_sets.install(SET, maker=ANNA, approver=ANNA)
    assert product_rules.latest("document", "inv_general_conditions") is None


def test_a_store_holding_another_content_refuses_the_set(db) -> None:
    other = SET.rules["inv_claims_factor"].model_dump(mode="json") | {"title": "Another title"}
    product_rules.add("rule", "inv_claims_factor", other, actor=ANNA)
    with pytest.raises(product_sets.SetRefused, match="rule inv_claims_factor: the store holds another version of it"):
        product_sets.install(SET, maker=ANNA)
    assert product_rules.latest("document", "inv_general_conditions") is None


def test_drafts_without_an_approver(db) -> None:
    product_sets.install(SET, maker=ANNA)
    assert product_rules.latest("product", "inv_business_property")["state"] == versions.DRAFT
