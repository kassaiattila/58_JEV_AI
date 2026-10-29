"""231 (stage U, U4b; the owner's decisions of 2026-10-29: every value of the rules view a default, the cost ones never).

Every value the rules view shows says whether the installation may keep its own value of it (`configs/rule_help.json`
`edit`): a kind with its bounds or options, the capability's own rule key, or fixed with why. A value that changes a
paid request or a budget (the paid text recognition, a run's item budget) is fixed as a cost, and no key a person may
set names one; U4z (the owner's decision of 2026-10-29): the only fixed values are those, the product catalogue's levels
and verdicts and the tax number's stem are defaults too. The file's value fits every declaration, and a default of each kind is checked before it is saved.
Real rule files, an empty store; nothing runs and no AI is asked.
"""

from __future__ import annotations

import pytest

from jav.app import registrations, rule_defaults
from jav.core import cfg, store

registrations.load_all()

COST_WORDS = ("usd", "budget", "escalat")  # (the issuer check's "engines" are the recognitions it checks, no cost)


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "editable.sqlite"):
        rule_defaults.use()
        rule_defaults._forget()
        try:
            yield tmp_path
        finally:
            cfg.use_defaults(None)
            rule_defaults._forget()


def _shown() -> set[str]:
    return {f"{v['file'].removesuffix('.json')}.{v['key']}" for p in cfg.load("rule_help")["points"].values()
            for v in p["values"]}


def test_every_value_the_rules_view_shows_is_a_default_or_fixed_with_why() -> None:
    editable, fixed = rule_defaults.editable(), rule_defaults.fixed()
    assert _shown() <= set(editable) | set(fixed)
    assert set(fixed.values()) == {"cost"}  # U4z: only the cost ones
    assert not set(editable) & set(fixed)
    assert {"facts_property.levels", "facts_property.outcomes.verdict.options",
            "fact_checks.parties.domestic_tax_stem_digits"} <= set(editable)


def test_no_value_that_costs_is_a_default() -> None:
    fixed = rule_defaults.fixed()
    for rid in ("ocr.escalation.enabled", "ocr.escalation.engine", "policy.ocr.escalate_min_mean_conf",
                "policy.ocr.escalate_max_low_conf_ratio"):
        assert fixed[rid] == "cost"
    assert all(why == "cost" for rid, why in fixed.items() if rid.startswith("recipes."))
    assert [rid for rid in rule_defaults.editable() if any(word in rid.lower() for word in COST_WORDS)] == []


def test_the_file_s_value_fits_every_declaration() -> None:
    for rid, rule in rule_defaults.editable().items():
        assert rule.problems(rule.file_value()) == [], rid


@pytest.mark.parametrize(("file", "key", "value", "problem"), [
    ("policy", "bands.default.choice_human_max_conf", 1.5, "between"),
    ("policy", "bands.default.uncertain_review", "yes", "yes or no"),
    ("case_decisions", "limits.inv_premium_second_person.above.amount", "a lot", "amount"),
    ("case_decisions", "limits.inv_premium_second_person.above.amount", "-1", "at least"),
    ("email", "m2_types", ["invoice_hu", "no_such_type"], "takes no no_such_type"),
    ("email", "m2_types", [], "at least 1"),
    ("email", "default_route", "human:nowhere", "is one of"),
    ("email", "intent_route", {"quote_request": "m2:quote_request"}, "names each of"),
    ("facts_property", "levels", ["holder", "Site!"], "is not a code"),
    ("facts_property", "levels", ["holder", "holder"], "distinct codes"),
    ("facts_property", "outcomes.verdict.options", ["allow"], "at least 2"),
    ("fact_checks", "parties.domestic_tax_stem_digits", 12, "between"),
])
def test_a_default_of_each_kind_is_checked(db, file, key, value, problem) -> None:
    with pytest.raises(rule_defaults.DefaultError, match=problem):
        rule_defaults.propose(file, key, value, "anna")


def test_a_band_a_route_and_a_list_take_their_defaults(db) -> None:
    routes = dict(cfg.load("email")["intent_route"])
    routes["quote_request"] = "human:inbox"
    for file, key, value in (("policy", "bands.default.choice_human_max_conf", 0.7), ("email", "intent_route", routes),
                             ("finance", "duplicates.compared_fields", ["issue_date", "gross_total"])):
        rule_defaults.propose(file, key, value, "anna")
        rule_defaults.activate(file, key, 1, "anna")
    assert cfg.load("policy")["bands"]["default"]["choice_human_max_conf"] == 0.7
    assert cfg.load("email")["intent_route"]["quote_request"] == "human:inbox"
    assert cfg.load("finance")["duplicates"]["compared_fields"] == ["issue_date", "gross_total"]
