"""231 (stage D, D-c2): the rules of a product evaluated on a case's checked input, explained and replayable.

Each rule of the product that applies at quoting, to a requested module, is evaluated on every unit of its level: a
unit sees its own facts and its ancestors' (an asset group sees its site's flood zone). A decision table gives the
first matching row's outcomes (or every matching row's); a comparison with a missing fact makes the rule's outcome
unknown and names the fact, never a guess. The outcomes of several rules combine by the catalogue's rule: the worst
verdict, the largest deductible, the highest protection class, the lowest sublimit, the union of measures and
warnings, and exactly one premium factor (two different ones are a blocker). Every evaluation is a row of the decision
trace, and its replay gives the same outcome. Invented rules and units; no paid call.
"""

from __future__ import annotations

from decimal import Decimal

from jav.app import facts, rule_evaluation
from jav.app.product_rules import Resolved, Rule
from jav.core import store, trace
from jav.core.measures import Money

SRC = {"document": "general@1", "page": 1, "clause": "1"}


def _rule(ref: str, level: str, read: list[str], rows: list[dict], *, kind: str = "requirement", modules=(), hit="first") -> Resolved:
    return Resolved(ref, Rule.model_validate({"catalogue": "property", "kind": kind, "title": ref, "level": level,
                                              "modules": list(modules), "facts": read, "table": {"hit": hit, "rows": rows},
                                              "source": SRC}))


RULES = [
    _rule("activity@1", "holder", ["activity_code"], [{"when": {"activity_code": {"in": ["1610", "2011"]}}, "then": {"verdict": "refuse"}},
                                                       {"when": {}, "then": {"verdict": "allow"}}], kind="eligibility"),
    _rule("flood@1", "site", ["flood_zone"], [{"when": {"flood_zone": {"eq": "high"}}, "then": {"verdict": "refer", "warnings": ["flood_zone"]}}],
          kind="exclusion"),
    _rule("cash_class@1", "asset_group", ["asset_group", "sum_insured"],
          [{"when": {"asset_group": {"in": ["cash", "valuables"]}, "sum_insured": {"gt": {"amount": "2000000", "currency": "HUF"}}},
            "then": {"protection_class_required": 3, "measures": ["safe_class_3"]}},
           {"when": {}, "then": {"protection_class_required": 1}}], modules=["burglary"]),
    _rule("valuables_cap@1", "asset_group", ["asset_group"],
          [{"when": {"asset_group": {"eq": "valuables"}}, "then": {"sublimit": {"amount": "1000000", "currency": "HUF"}}}],
          kind="sublimit", modules=["burglary"]),
    _rule("new_value@1", "asset_group", ["valuation", "wear"],
          [{"when": {"valuation": {"eq": "new_value"}, "wear": {"gt": {"value": "30"}}}, "then": {"verdict": "refer", "warnings": ["new_value_worn"]}}],
          kind="valuation"),
    _rule("deductible_base@1", "asset_group", ["asset_group"], [{"when": {}, "then": {"deductible": {"amount": "50000", "currency": "HUF"}}}],
          kind="deductible"),
    _rule("deductible_surge@1", "site", ["surge_protection"],
          [{"when": {"surge_protection": {"eq": "none"}}, "then": {"deductible": {"amount": "150000", "currency": "HUF"}}}], kind="deductible"),
    _rule("claims_factor@1", "holder", ["claims_5y_count"],
          [{"when": {"claims_5y_count": {"eq": 0}}, "then": {"premium_factor": "0.9"}},
           {"when": {"claims_5y_count": {"between": [1, 2]}}, "then": {"premium_factor": "1.0"}},
           {"when": {}, "then": {"premium_factor": "1.3"}}], kind="premium_factor"),
    _rule("basement@1", "site", ["basement_storage"], [{"when": {"basement_storage": {"eq": True}}, "then": {"warnings": ["basement"]}}],
          kind="obligation"),
    _rule("asset_flood@1", "asset_group", ["flood_zone", "asset_group"],
          [{"when": {"flood_zone": {"in": ["medium", "high"]}, "asset_group": {"eq": "stock"}}, "then": {"warnings": ["stock_in_flood_zone"]}}],
          kind="exclusion"),
]


def _input(**holder_changes) -> facts.CheckedInput:
    holder = {"activity_code": "4719", "claims_5y_count": 0} | holder_changes
    return facts.checked_input({"catalogue": "property", "product": "invented_property@1", "cover_start": "2026-12-01", "units": [
        {"unit_id": "u-0000000001", "level": "holder", "facts": {k: v for k, v in holder.items() if v is not None}},
        {"unit_id": "u-0000000002", "level": "site", "parent_id": "u-0000000001",
         "facts": {"flood_zone": "medium", "surge_protection": "none", "basement_storage": True}},
        {"unit_id": "u-0000000003", "level": "asset_group", "parent_id": "u-0000000002",
         "facts": {"asset_group": "stock", "sum_insured": {"amount": "12000000", "currency": "HUF"}, "valuation": "current_value"}},
        {"unit_id": "u-0000000004", "level": "asset_group", "parent_id": "u-0000000002",
         "facts": {"asset_group": "valuables", "sum_insured": {"amount": "3000000", "currency": "HUF"}, "valuation": "new_value",
                   "wear": {"value": "40"}}}]})


def test_every_rule_family_gives_its_outcome_and_they_combine_by_the_catalogue() -> None:
    result = rule_evaluation.evaluate(RULES, _input(), modules=("property", "burglary"))
    stock, valuables, site, holder = (result.units[u] for u in ("u-0000000003", "u-0000000004", "u-0000000002", "u-0000000001"))
    assert holder.combined["verdict"] == "allow" and holder.combined["premium_factor"] == Decimal("0.9")
    assert valuables.combined["protection_class_required"] == 3 and valuables.combined["measures"] == ("safe_class_3",)
    assert valuables.combined["sublimit"] == Money(amount="1000000", currency="HUF")
    assert valuables.combined["verdict"] == "refer" and "new_value_worn" in valuables.combined["warnings"]
    assert stock.combined["protection_class_required"] == 1 and "stock_in_flood_zone" in stock.combined["warnings"]  # the site's flood zone
    assert site.combined["deductible"] == Money(amount="150000", currency="HUF") and site.combined["warnings"] == ("basement",)
    assert result.verdict == "refer" and not result.missing and not result.blockers


def test_a_refused_activity_refuses_the_whole_assessment() -> None:
    assert rule_evaluation.evaluate(RULES, _input(activity_code="1610"), modules=("property",)).verdict == "refuse"


def test_a_missing_fact_makes_the_outcome_unknown_and_names_it() -> None:
    result = rule_evaluation.evaluate(RULES, _input(claims_5y_count=None), modules=("property",))
    holder = result.units["u-0000000001"]
    assert holder.rules["claims_factor@1"].missing == ("claims_5y_count",) and "premium_factor" not in holder.combined
    assert ("u-0000000001", "claims_5y_count") in result.missing and holder.combined["verdict"] == "unknown"
    assert result.verdict == "refer"  # the worst of the units: the worn valuables are referred


def test_a_rule_of_a_module_not_requested_does_not_apply() -> None:
    result = rule_evaluation.evaluate(RULES, _input(), modules=("property",))
    assert "cash_class@1" not in result.units["u-0000000004"].rules


def test_two_different_premium_factors_are_a_blocker() -> None:
    twice = [*RULES, _rule("claims_factor_b@1", "holder", ["activity_code"], [{"when": {}, "then": {"premium_factor": "1.1"}}], kind="premium_factor")]
    result = rule_evaluation.evaluate(twice, _input(), modules=("property",))
    assert result.blockers == ("u-0000000001: premium_factor given twice: 0.9 (claims_factor@1), 1.1 (claims_factor_b@1)",)


def test_every_evaluation_is_traced_and_replays_the_same(tmp_path) -> None:
    result = rule_evaluation.evaluate(RULES, _input(), modules=("property", "burglary"))
    with store.use_store(tmp_path / "trace.sqlite"):
        with store.connect() as c:
            store.begin_immediate(c)
            ids = rule_evaluation.trace_in(c, "wp-0000000d0c20", result)
        rows = trace.rows(point=rule_evaluation.POINT)
        assert len(rows) == len(ids) == sum(len(u.rules) for u in result.units.values())
        for row in rows:
            assert trace.replay(row) == row["outcome"]
        row = next(r for r in rows if r["inputs"]["rule"] == "cash_class@1" and r["subject_id"].endswith("u-0000000004"))
        assert row["outcome"]["outcomes"]["protection_class_required"] == 3 and row["inputs"]["facts"]["sum_insured"]["amount"] == "3000000"
