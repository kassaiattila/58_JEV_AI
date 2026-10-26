"""231 (stage D, D-c7h): the rule proposals measured against the 16 rules of the invented insurer's documents.

The stand-in proposer scores 16 of 16 exact, with nothing extra, which tests the scorer; a deliberately wrong stand-in
shows a rule whose page differs (blocked by code, so never sent to JEV), one whose amount differs (JEV's "supported" on it
counted as a false acceptance), a missed rule and an extra proposal. Without a budget no document is answered (only
earlier answers count) and GPT is never asked. The golden set is listed with the others. Invented data; no paid call.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jav.ai import gpt_answer
from jav.app import product_sets, rule_proposals, rule_support
from jav.core import store
from jav.evals import goldens, rule_proposal_golden

SET = product_sets.load()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(rule_proposal_golden, "RUNS_DIR", tmp_path / "runs")
    with store.use_store(tmp_path / "golden.sqlite"):
        yield tmp_path


def test_the_stand_in_scores_sixteen_of_sixteen(env) -> None:
    outcome = rule_proposal_golden.measure(goldens.Options(engine="gpt"), stand_in=True)
    assert (outcome.cases, outcome.answered, outcome.right, outcome.scored, outcome.unit) == (16, 16, 16, 16, "rules")
    assert outcome.failures == ()
    [raw] = (env / "runs").glob("*_rule_proposals_stand_in.jsonl")
    assert '"exact": 16' in raw.read_text(encoding="utf-8")


def test_a_wrong_stand_in_shows_what_differs_what_is_missed_and_what_is_extra(env) -> None:
    wrong = SET.model_copy(deep=True)
    rules = dict(wrong.rules)
    rules["inv_flood_high"] = rules["inv_flood_high"].model_copy(update={
        "source": rules["inv_flood_high"].source.model_copy(update={"page": 4})})
    deductible = rules["inv_base_deductible"].model_dump(mode="json")
    deductible["table"]["rows"][1]["then"]["deductible"] = {"amount": "60000", "currency": "HUF"}
    rules["inv_base_deductible"] = type(rules["inv_base_deductible"]).model_validate(deductible)
    del rules["inv_basement_stock"]
    extra = rules["inv_flood_stock"].model_copy(update={"title": "Invented extra", "source": rules["inv_flood_stock"].source.model_copy(
        update={"clause": "1"})})
    rules["inv_extra"] = extra
    wrong = wrong.model_copy(update={"rules": rules})
    supported = rule_support.Support("supported")
    proposed, failed = rule_proposal_golden.propose_set(SET, env / "documents", proposer_for=lambda ref: rule_proposals.set_proposer(wrong),
                                                        verifier_for=lambda ref: lambda rule, pages: supported)
    s = rule_proposal_golden.score(SET, proposed)
    by = {r.expected: r for r in s.rules}
    assert failed == {}
    assert (by["inv_flood_high"].verdict, by["inv_flood_high"].differences) == ("differs", ("page",))
    assert by["inv_flood_high"].blocking and by["inv_flood_high"].support is None
    assert (by["inv_base_deductible"].verdict, by["inv_base_deductible"].differences, by["inv_base_deductible"].support) == (
        "differs", ("rows",), "supported")
    assert by["inv_basement_stock"].verdict == "missed"
    assert (s.count("exact"), s.count("differs"), s.count("missed")) == (13, 2, 1)
    assert s.false_acceptances == 1
    assert s.extra == ("inv_general_conditions: Invented extra",)


def test_without_a_budget_no_document_is_answered_and_gpt_is_not_asked(env) -> None:
    asked = []
    agent = SimpleNamespace(run_sync=lambda prompt, **kw: asked.append(prompt))
    with gpt_answer.use_agent_factory(lambda model, instructions: agent):
        outcome = rule_proposal_golden.measure(goldens.Options(engine="gpt"))
    assert (outcome.cases, outcome.answered, outcome.right) == (16, 0, 0) and asked == []


def test_the_golden_set_is_listed() -> None:
    golden = goldens.get("rules:proposals")
    assert (golden.layer, golden.engines, golden.count()) == ("rules", ("jev", "gpt"), 16)
