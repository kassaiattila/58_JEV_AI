"""274 (the engine registry's integration): what the review of the registry's branch found, fixed.

- A finished rule-proposal run checked again with a judgement budget is judged by JEV when the application runs on
  GPT only, as it was before the registry (the budget asks for a judgement; GPT only has no judgement service).
- The measurement report's default inputs: the latest file of each flow, once, whichever pattern found it (a JEV
  determinism pattern also finds OpenAI Decisions' and GPT's files); every judgement service's budget refusal counts
  as a budget skip.
- A measurement does not say that every Azure DI call would be refused when its key is missing, since Azure DI is
  still reached through the legacy sidecar (`key_fallback`, as before the registry).
- A provider off by the registry's default says why (`off_reason`): OpenAI Decisions is under measurement; one an
  installation switched off says so.
- OpenAI Decisions' reservation bounds its cost: a price per output token is refused without the most output tokens
  a request may produce.

Synthetic documents only; nothing is called (the judgement is a stand-in).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from jav.app import app_settings, product_sets, rule_proposal_runs, rule_support
from jav.ai import decisions
from jav.core import calls, cfg, providers, queue, store
from jav.evals import eval_report

ANNA = "Minta Anna"
SET = product_sets.load()
GENERAL = "inv_general_conditions@1"


@pytest.fixture()
def env(tmp_path):
    written = product_sets.write_documents(SET, tmp_path / "documents")
    with store.use_store(tmp_path / "runs.sqlite"):
        product_sets.install(SET, maker=ANNA)
        yield written


def _run(path) -> dict:
    started = rule_proposal_runs.start(GENERAL, path, catalogue="property", actor=ANNA, proposer="stand_in:golden_products")
    rule_proposal_runs.process_job(queue.claim("test", kinds=(rule_proposal_runs.JOB_KIND,)))
    return rule_proposal_runs.run(started["run_id"])


@pytest.mark.parametrize("application_engine", ["jev", "gpt"])
def test_a_recheck_with_a_judgement_budget_asks_jev_unless_the_application_names_another_judge(
        env, monkeypatch, application_engine):
    app_settings.save_engine_default(application_engine, actor=ANNA)
    run = _run(env["inv_general_conditions"])
    asked: list[str] = []

    def stand_in(rule, pages, *, run_id, use_cache=True, engine="jev"):
        asked.append(engine)
        return rule_support.Support(mark="supported")

    monkeypatch.setattr(rule_support, "support", stand_in)
    rule_proposal_runs.recheck(run["run_id"], jev_budget=Decimal("0.05"))
    assert asked and set(asked) == {"jev"}
    asked.clear()
    rule_proposal_runs.recheck(run["run_id"])  # no budget: nothing is asked
    assert asked == []


def test_the_reports_default_inputs_take_each_flows_latest_file_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(eval_report, "RUNS_DIR", tmp_path)
    names = ("20261101_100000_determinism_S_n5.jsonl", "20261101_110000_determinism_S_n5_decisions.jsonl",
             "20261101_090000_determinism_G_n3.jsonl", "20261101_120000_determinism_G_n3_nojev.jsonl")
    for name in names:
        (tmp_path / name).write_text("", encoding="utf-8")
    picked = [p.name for p in eval_report.default_inputs()]
    assert sorted(picked) == sorted(names)  # each one, once: JEV's S and G, OpenAI Decisions' S, GPT's G
    assert {eval_report.flow_of(n) for n in picked} == {"invoice_S", "invoice_S_decisions", "invoice_G", "invoice_G_gpt"}


def test_every_judgement_services_budget_refusal_is_a_budget_skip():
    rows = [{"case_id": "a", "review_reasons": ["jev_unavailable:budget_exceeded"]},
            {"case_id": "b", "review_reasons": ["decisions_unavailable:budget_exceeded"]},
            {"case_id": "c", "review_reasons": ["decisions_unavailable:refusal"]}]
    assert eval_report.budget_skips(rows) == ["a", "b"]


def test_a_provider_reached_without_its_key_is_not_named_as_missing_one(monkeypatch):
    for name in ("AZURE_DI_ENDPOINT", "AZURE_DI_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert calls.missing_keys({"openai": Decimal("0.1"), "azure_di": Decimal("0.02")}) == ["openai"]


def test_an_output_price_without_its_token_limit_is_refused(monkeypatch):
    real = cfg.load

    def with_output_price(name):
        data = real(name)
        if name != "models":
            return data
        priced = {**data["decisions"], "usd_per_mtok": {**data["decisions"]["usd_per_mtok"], "output": 0.4}}
        return {**data, "decisions": priced}

    monkeypatch.setattr(cfg, "load", with_output_price)
    with pytest.raises(ValueError, match="max_output_tokens"):
        decisions.settings()


def test_a_provider_off_by_default_says_why_and_one_switched_off_here_says_so(monkeypatch):
    monkeypatch.delenv(providers.ON_ENV, raising=False)
    monkeypatch.delenv(providers.OFF_ENV, raising=False)
    assert providers.off_reason("openai_decisions") == providers.UNDER_MEASUREMENT
    assert providers.off_reason("jev") is None
    monkeypatch.setenv(providers.OFF_ENV, "openai_decisions,jev")
    assert providers.off_reason("openai_decisions") == providers.off_reason("jev") == providers.SWITCHED_OFF
    monkeypatch.setenv(providers.OFF_ENV, "")
    monkeypatch.setenv(providers.ON_ENV, "openai_decisions")
    assert providers.off_reason("openai_decisions") is None
