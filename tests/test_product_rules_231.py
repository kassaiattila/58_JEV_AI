"""231 (stage D, D-c1): products, their condition documents and rules, kept as versions.

A product (its cover modules, the condition documents and rules it is offered under) and each of its condition
documents and rules is a versioned thing: a draft, then active, then superseded or retired (the shared versions). A
rule is a decision table over the facts of a catalogue, with its source: the document version, page and clause it was
read from. A product version is the release manifest: it names exact rule and document versions, and it is made active
only by another person than the one who made it, and only when every rule it names is no draft, reads facts its
catalogue has on its own level or above, compares them with values of the right type, unit and currency, gives
outcomes the catalogue knows, and cites a document of the product and a clause that document has. A retired rule
stays readable by its version. Invented data; no paid call.
"""

from __future__ import annotations

import copy

import pytest

from jav.app import product_rules
from jav.core import store

ANNA, BELA = "Minta Anna", "Minta Bela"


@pytest.fixture()
def db(tmp_path):
    with store.use_store(tmp_path / "products.sqlite"):
        yield


GENERAL = {"kind": "general", "title": "Invented general conditions", "valid_from": "2026-01-01",
           "sections": [{"clause": "6.4.2", "page": 8, "title": "Valuation"}, {"clause": "6.7.4", "page": 8, "title": "Deductibles"}]}
SECURITY = {"kind": "special", "title": "Invented security rules", "valid_from": "2026-01-01",
            "sections": [{"clause": "3.2", "page": 3, "title": "Protection classes"}]}


def _rule(**changes) -> dict:
    base = {"catalogue": "property", "kind": "requirement", "title": "Protection class of cash and valuables",
            "level": "asset_group", "modules": ["burglary"], "facts": ["asset_group", "sum_insured"],
            "table": {"hit": "first", "rows": [
                {"when": {"asset_group": {"in": ["cash", "valuables"]}, "sum_insured": {"gt": {"amount": "2000000", "currency": "HUF"}}},
                 "then": {"protection_class_required": 3}},
                {"when": {}, "then": {"protection_class_required": 1}}]},
            "source": {"document": "security@1", "page": 3, "clause": "3.2", "quote": "protection class by value"}}
    return copy.deepcopy(base) | changes


def _setup() -> None:
    for doc, content in (("general", GENERAL), ("security", SECURITY)):
        product_rules.add("document", doc, content, actor=ANNA)
        product_rules.activate("document", doc, 1, actor=BELA)
    product_rules.add("rule", "cash_protection", _rule(), actor=ANNA)
    product_rules.activate("rule", "cash_protection", 1, actor=BELA)


def _product(**changes) -> dict:
    return {"name": "Invented property", "catalogue": "property",
            "modules": [{"code": "property", "name": "Property", "kind": "base"},
                        {"code": "burglary", "name": "Burglary", "kind": "extension", "requires": ["property"]}],
            "documents": ["general@1", "security@1"], "rules": ["cash_protection@1"]} | changes


def test_a_rule_is_a_draft_then_active_then_superseded_and_stays_readable(db) -> None:
    _setup()
    product_rules.add("rule", "cash_protection", _rule(title="Protection class, revised"), actor=ANNA)
    assert product_rules.get("rule", "cash_protection", 2)["state"] == "draft"
    product_rules.activate("rule", "cash_protection", 2, actor=BELA)
    assert product_rules.get("rule", "cash_protection", 1)["state"] == "superseded"
    product_rules.retire("rule", "cash_protection", actor=BELA)
    old = product_rules.resolve("rule", "cash_protection@1")
    assert old["content"]["title"] == "Protection class of cash and valuables" and old["state"] == "superseded"


def test_a_product_is_made_active_by_another_person_and_resolves_its_manifest(db) -> None:
    _setup()
    product_rules.add("product", "invented_property", _product(), actor=ANNA)
    with pytest.raises(product_rules.SecondPersonNeeded):
        product_rules.activate("product", "invented_property", 1, actor=ANNA)
    product_rules.activate("product", "invented_property", 1, actor=BELA)
    resolved = product_rules.product_at("invented_property@1")
    assert [r.ref for r in resolved.rules] == ["cash_protection@1"] and [d.ref for d in resolved.documents] == ["general@1", "security@1"]
    assert product_rules.kept("invented_property") == "invented_property@1"
    assert product_rules.named("invented_property@1") == {"name": "Invented property", "version": 1}


@pytest.mark.parametrize(("rule", "product", "problem"), [
    (None, {"rules": ["cash_protection@2"]}, "rule cash_protection@2: no such version"),
    ("draft", {"rules": ["cash_protection@2"]}, "rule cash_protection@2 is a draft"),
    (_rule(source={"document": "elsewhere@1", "page": 1}), None, "cites elsewhere@1, which the product does not name"),
    (_rule(source={"document": "security@1", "page": 3, "clause": "9.9"}), None, "cites clause 9.9, which security@1 does not have"),
    (_rule(facts=["asset_group", "colour"]), None, "reads colour, which the catalogue property does not have"),
    (_rule(level="site", facts=["sum_insured"], table={"rows": [{"when": {}, "then": {"protection_class_required": 1}}]}),
     None, "reads sum_insured of an asset_group, below its level site"),
    (_rule(table={"rows": [{"when": {"sum_insured": {"gt": {"amount": "1", "currency": "EUR"}}}, "then": {"protection_class_required": 2}}]}),
     None, "sum_insured is in HUF, not EUR"),
    (_rule(table={"rows": [{"when": {"floor_area": {"gt": 5}}, "then": {"protection_class_required": 2}}]}),
     None, "compares floor_area, which it does not read"),
    (_rule(table={"rows": [{"when": {}, "then": {"discount": 5}}]}), None, "gives discount, which the catalogue property does not have"),
])
def test_a_manifest_with_a_wrong_rule_is_refused_with_what_is_wrong(db, rule, product, problem) -> None:
    """A rule's own problems stop its own activation; what only the product shows (its documents) stops the product's."""
    _setup()
    if rule == "draft":
        product_rules.add("rule", "cash_protection", _rule(), actor=ANNA)
    elif rule is not None:
        product_rules.add("rule", "cash_protection", rule, actor=ANNA)
        if "cites" not in problem:
            with pytest.raises(product_rules.ManifestRefused) as refused:
                product_rules.activate("rule", "cash_protection", 2, actor=BELA)
            assert any(problem in p for p in refused.value.problems), refused.value.problems
            return
        product_rules.activate("rule", "cash_protection", 2, actor=BELA)
    refs = (product or {}).get("rules") or (["cash_protection@2"] if rule not in (None, "draft") else ["cash_protection@1"])
    product_rules.add("product", "invented_property", _product(rules=refs), actor=ANNA)
    with pytest.raises(product_rules.ManifestRefused) as refused:
        product_rules.activate("product", "invented_property", 1, actor=BELA)
    assert any(problem in p for p in refused.value.problems), refused.value.problems
