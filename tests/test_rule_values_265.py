"""265 (code review APPR-02, APPR-06, APPR-09): a product rule's outcome and a rule value are never half-formed.

- APPR-02: a "collect" decision table that met an undecided row returned its outcomes uncombined (a list), and the
  step failed on every retry; now they combine before the early return.
- APPR-09: an undecided rule gives the verdict "unknown", so a catalogue whose verdict options lack it is refused when
  read, and an installation default of the verdict options keeps it.
- APPR-06: "not a number" passed a number's bounds (every comparison with it is false), and the service's form took
  it; a band threshold of NaN made every choice automatic. Now it is refused in the check and in the form.
Invented rules and units, real rule files, an empty store; no paid call.
"""

from __future__ import annotations

import math

import pytest
from pydantic import TypeAdapter, ValidationError

from jav.app import capabilities, facts, registrations, rule_defaults, rule_evaluation
from jav.app.product_rules import Rule
from jav.core import cfg, store

registrations.load_all()


def test_a_collect_rule_that_meets_an_undecided_row_combines_what_it_collected() -> None:
    rule = Rule.model_validate({"catalogue": "property", "kind": "exclusion", "title": "collect", "level": "holder",
                                "facts": ["activity_code", "claims_5y_count"], "source": {"document": "general@1", "page": 1},
                                "table": {"hit": "collect", "rows": [
                                    {"when": {"activity_code": {"in": ["4719"]}}, "then": {"verdict": "refer", "warnings": ["a"]}},
                                    {"when": {"claims_5y_count": {"gt": 2}}, "then": {"verdict": "refuse"}}]}})
    result = rule_evaluation.evaluate_rule(rule, "collect@1", {"activity_code": "4719"}, facts.catalogue("property"))
    assert result.missing == ("claims_5y_count",)
    assert result.outcomes["verdict"] == "refer" and list(result.outcomes["warnings"]) == ["a"]  # not a list of each


def test_a_catalogue_whose_verdicts_lack_unknown_is_refused() -> None:
    data = cfg.load("facts_property")
    outcomes = {**data["outcomes"], "verdict": {**data["outcomes"]["verdict"], "options": ["allow", "refer", "refuse"]}}
    with pytest.raises(ValidationError, match="unknown"):
        facts.Catalogue(id="property", version="0", levels=tuple(data["levels"]), facts=data["facts"], outcomes=outcomes)


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "values.sqlite"):
        rule_defaults.use()
        rule_defaults._forget()
        try:
            yield tmp_path
        finally:
            cfg.use_defaults(None)
            rule_defaults._forget()


def test_a_default_of_the_verdicts_keeps_unknown(db) -> None:
    with pytest.raises(rule_defaults.DefaultError, match="keeps unknown"):
        rule_defaults.propose("facts_property", "outcomes.verdict.options", ["allow", "refer", "refuse"], "anna")
    rule_defaults.propose("facts_property", "outcomes.verdict.options", ["allow", "unknown", "refuse", "refer"], "anna")


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_not_a_number_is_no_number(db, value) -> None:
    key = capabilities.RuleKey("policy", "x", "number", "w", least=0.0, most=1.0)
    assert key.problems(value) != []
    with pytest.raises(rule_defaults.DefaultError):
        rule_defaults.propose("policy", "bands.default.choice_human_max_conf", value, "anna")


def test_the_service_s_form_takes_no_nan() -> None:
    from jav.service.api_processes import DefaultValue

    with pytest.raises(ValidationError):
        TypeAdapter(DefaultValue).validate_python(math.nan)
    assert TypeAdapter(DefaultValue).validate_python(0.5) == 0.5
