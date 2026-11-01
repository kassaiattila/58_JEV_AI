"""265 (plan L, L4d): the domain packs ask through the engine registry.

Until 265 the reconciliation's proposals, the quote matching and proposal, the pairing proposal and the rule
proposals' check knew two engines, JEV and GPT, by name. Now an engine with a judgement service (JEV or OpenAI
Decisions) asks its service the same questions, GPT only asks GPT; "both" is the engine and GPT beside it; a budget is
named by the budget its calls reserve from (OpenAI Decisions spends OpenAI's). The quick review's "AI sure" needs two
engines or more to agree, a judgement service among them, each at least as probable as the threshold (OpenAI Decisions
is held to JEV's until it is measured). Stand-in answers only; nothing leaves the machine.
"""

from __future__ import annotations

import argparse
from decimal import Decimal

import pytest

from jav.ai import gpt_choice
from jav.ai import jev as jev_mod
from jav.app import rule_proposal_runs
from jav.ai import engine as engines
from jav.domains.finance import reconcile_ai, reconcile_review
from jav.domains.quotes import quote_match, quote_proposal
from tests.test_quote_match_191 import PRICES, REQUESTED, StandInJev
from tests.test_reconcile_ai_134 import FakeJev, _fake_gpt, _package, db  # noqa: F401 - the fixture


class Judged:
    """Wraps a stand-in judgement service and notes which judge the scope had when it was asked."""

    def __init__(self, inner):
        self.inner, self.judges = inner, []

    def ask(self, *args, **kwargs):
        self.judges.append(jev_mod.current_judge())
        return self.inner.ask(*args, **kwargs)


# --- the reconciliation's proposals ------------------------------------------------------------------------------------


def test_each_engine_proposes_beside_gpt_or_alone():
    assert reconcile_ai.paired("jev") == ["jev", "gpt"]
    assert reconcile_ai.paired("decisions") == ["decisions", "gpt"]
    assert reconcile_ai.paired("gpt") == ["gpt"]
    assert reconcile_ai.ENGINES == tuple(engines.ids())
    assert reconcile_ai.PROVIDERS == {"jev": "jev", "decisions": "openai_decisions", "gpt": "openai"}


def test_an_engine_is_budgeted_by_the_budget_its_calls_reserve_from():
    assert reconcile_ai.unbudgeted(["decisions", "gpt"], {"openai": Decimal("1")}) == []
    assert reconcile_ai.unbudgeted(["jev", "gpt"], {"openai": Decimal("1")}) == ["jev"]
    assert reconcile_ai.unbudgeted(["decisions"], {"openai_decisions": Decimal("1")}) == []
    assert reconcile_ai.unbudgeted(["decisions"], {"jev": Decimal("1")}) == ["decisions"]


def test_decisions_answers_the_reconciliation_questions_through_its_own_service(db, monkeypatch, tmp_path):  # noqa: F811
    wp = _package()
    judge = Judged(FakeJev())
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: judge)
    monkeypatch.setattr(gpt_choice, "ask", _fake_gpt)
    r = reconcile_ai.run(wp, engines=["decisions", "gpt"], limits={"openai": Decimal("0.40")}, out_dir=tmp_path)
    assert r["counts"]["decisions"]["asked"] == 3 and r["counts"]["gpt"]["asked"] == 3
    assert set(judge.judges) == {"decisions"}
    from jav.domains.finance import reconcile_package

    jane = next(ln for ln in reconcile_package.workspace(wp)["lines"] if ln["counterparty_name"] == "Jane Example")
    assert set(jane["ai"]) == {"decisions", "gpt"} and jane["ai"]["decisions"]["kind"] == "retail_purchase"
    assert jane["ai"]["decisions"]["config_hash"] == reconcile_ai.jev_hash()  # the same question as JEV's
    ev = reconcile_ai.evaluate(wp)
    assert list(ev["engines"])[:2] == ["jev", "gpt"]  # JEV and GPT always, another engine with its answers


def test_the_free_estimate_plans_the_engines_asked_and_names_decisions_reservation(db):  # noqa: F811
    wp = _package()
    default = reconcile_ai.estimate(wp)
    assert set(default["plan"]) == {"jev", "gpt"} and set(default["reservations_usd"]) == {"jev", "openai"}
    est = reconcile_ai.estimate(wp, engines=["decisions", "gpt"])
    assert set(est["plan"]) == {"decisions", "gpt"} and set(est["reservations_usd"]) == {"openai_decisions", "openai"}
    assert Decimal(est["reservations_usd"]["openai_decisions"]) > Decimal(default["reservations_usd"]["jev"])


def test_the_command_proposes_with_the_applications_engine_and_gpt(monkeypatch):
    from jav.app import app_settings
    from jav.domains.finance import finance_cli

    seen = {}

    def fake_estimate(wp_id, **kwargs):
        seen["engines"] = kwargs["engines"]
        return {"lines": 0, "with_options": 0, "options": 0, "plan": {}, "reservations_usd": {}}

    monkeypatch.setattr(reconcile_ai, "estimate", fake_estimate)

    def engines_of(app: str, *argv: str) -> list[str]:
        monkeypatch.setattr(app_settings, "engine_default", lambda: app)
        args = argparse.Namespace(engine=None, golden=False, workpackage_id="wp-000000000000", evaluate=False,
                                  jev_budget_usd=None, budget_usd=None, redo=False, stale=False, incoming=False)
        for flag in argv:
            args.engine = flag
        assert finance_cli.cmd_reconcile_ai(args) == 0
        return seen["engines"]

    assert engines_of("decisions") == ["decisions", "gpt"]
    assert engines_of("jev") == ["jev", "gpt"]
    assert engines_of("gpt") == ["gpt"]
    assert engines_of("gpt", "both") == ["jev", "gpt"]
    assert engines_of("decisions", "both") == ["decisions", "gpt"]
    assert engines_of("jev", "decisions") == ["decisions"]


# --- the quick review --------------------------------------------------------------------------------------------------


def _ai(kind: str, p: float | None) -> dict:
    return {"kind": kind, "kind_probability": p, "suggested_mark": "private", "error": None}


def _line(**ai) -> dict:
    return {"id": "l1", "candidates": [], "other_candidates": [], "allocated": "0", "ai": ai}


@pytest.mark.parametrize("ai, group", [
    ({"jev": _ai("private", 0.97), "gpt": _ai("private", 0.6)}, "ai_sure"),  # as before 265
    ({"jev": _ai("private", 0.90), "gpt": _ai("private", 0.9)}, "ai_review"),
    ({"decisions": _ai("private", 0.97), "gpt": _ai("private", 0.6)}, "ai_sure"),  # JEV's threshold until measured
    ({"decisions": _ai("private", 0.90), "gpt": _ai("private", 0.99)}, "ai_review"),
    ({"jev": _ai("private", 0.97), "decisions": _ai("private", 0.90)}, "ai_review"),  # each service at least as probable
    ({"jev": _ai("private", 0.97), "decisions": _ai("private", 0.96), "gpt": _ai("private", 0.5)}, "ai_sure"),
    ({"decisions": _ai("private", 0.99)}, "ai_review"),  # one engine alone
    ({"gpt": _ai("private", 0.99), "jev": {**_ai("private", 0.99), "error": "JevUnavailableError: x"}}, "ai_review"),
])
def test_ai_sure_needs_two_engines_a_judgement_service_among_them(ai, group):
    assert reconcile_review._place(_line(**ai), {}, 0.95)[0] == group


# --- the quotes --------------------------------------------------------------------------------------------------------


def test_decisions_matches_a_quote_item_through_its_own_service(monkeypatch):
    judge = Judged(StandInJev({"HW-MON-24": 0.97, "none": 0.03}))
    monkeypatch.setattr(quote_match, "get_adapter", lambda: judge)
    answer = quote_match.match(REQUESTED, [], PRICES, engine="decisions", run_id="t")
    assert (answer["engine"], answer["method"], answer["sku"]) == ("decisions", "decisions", "HW-MON-24")
    assert judge.judges == ["decisions"]


def test_a_quote_proposal_with_decisions_reserves_from_openai():
    assert quote_proposal.cap(10, "decisions") == {"openai_decisions": Decimal("0.0750")}
    assert quote_proposal.cap(10, "jev") == {"jev": Decimal("0.030")}  # as before


def test_the_quote_golden_takes_openais_budget_for_decisions(monkeypatch, tmp_path):
    from jav.domains.quotes import invented_golden

    with pytest.raises(ValueError, match="no budget for: decisions"):
        quote_match.golden(invented_golden.load(), engine="decisions", limits={"jev": Decimal("1")}, out_dir=tmp_path)


# --- the rule proposals' check -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("engine, expected", [
    ("jev", {"openai": Decimal("1"), "jev": Decimal("0.2")}),
    ("decisions", {"openai": Decimal("1"), "openai_decisions": Decimal("0.2")}),
    ("gpt", {"openai": Decimal("1"), "jev": Decimal("0.2")}),  # no service asks; the cap stays unspent
])
def test_the_checks_cap_is_the_application_engines_service(engine, expected):
    limits = {"openai": Decimal("1"), "jev": Decimal("0.2")}
    assert rule_proposal_runs._judge_limits(limits, engines.get(engine)) == expected
