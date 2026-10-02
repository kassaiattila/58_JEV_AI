"""090 (backlog F-gpt-answers, the owner's decision of 2026-10-02: one setting for JEV and GPT): an earlier GPT answer
to the same question is reused when the run's "earlier answers" setting allows it. The question is the same when the
provider, the configured model and every text that shapes the answer (instructions, output schema, settings, the
document) are the same. A reused answer costs nothing, is recorded in the call log (cost 0, which earlier call it
came from) and in the ledger as a cached answer. With "always a live call", and in a measurement, every question is
asked again. Only callers that opt in are reused (JEV and Azure keep their own caches).

Stand-in calls and a stand-in model only; no paid call.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from jav import extract_llm, store
from jav.runtime import calls, worker
from jav.typepack import get as get_pack
from tests.test_no_jev_085 import GOOD, _FakeAgent

KEY = calls.answer_key("openai", "gpt-test", "instructions", "schema", "document text")


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield tmp_path


def _answer(counter: list[int], value: str = "first"):
    def fn():
        counter.append(1)
        return calls.Outcome(response={"value": value}, model="gpt-test-2026", cost_usd=Decimal("0.01"))
    return fn


def _ask(run_id: str, counter: list[int], *, key: str = KEY, reusable: bool = True, step: str = "openai:q:1"):
    return calls.invoke(run_id=run_id, step_id=step, provider="openai", model="gpt-test", max_cost_usd=Decimal("0.05"),
                        request_hash=key, reusable=reusable, fn=_answer(counter))


def test_the_same_question_in_another_run_reuses_the_answer_for_free(isolated):
    asked: list[int] = []
    with calls.use_run(budget_scope=None):
        first = _ask("run-a", asked)
    with calls.use_run(budget_scope=None, reuse=True):
        again = _ask("run-b", asked)
    assert len(asked) == 1 and again.response == first.response == {"value": "first"}
    assert again.reused_from == first.invocation_id
    row = calls.journal("run-b")[0]
    assert row["status"] == "succeeded" and row["cost_usd"] == "0" and row["note"] == f"{calls.REUSED_NOTE}:{first.invocation_id}"
    ledger = [r for r in store.ledger_for_run("run-b") if r["provider"] == "openai"]
    assert len(ledger) == 1 and ledger[0]["cached"] == 1 and ledger[0]["cost_usd"] == 0


def test_a_live_run_asks_again(isolated):
    asked: list[int] = []
    with calls.use_run(budget_scope=None):
        _ask("run-a", asked)
        _ask("run-b", asked)  # reuse is off by default (a measurement too)
    assert len(asked) == 2


def test_a_different_question_is_asked(isolated):
    asked: list[int] = []
    other = calls.answer_key("openai", "gpt-test", "instructions", "schema", "another document")
    with calls.use_run(budget_scope=None, reuse=True):
        _ask("run-a", asked)
        _ask("run-b", asked, key=other)
    assert len(asked) == 2


def test_only_callers_that_opt_in_are_reused(isolated):
    asked: list[int] = []
    with calls.use_run(budget_scope=None, reuse=True):
        _ask("run-a", asked, reusable=False)
        _ask("run-b", asked, reusable=False)
    assert len(asked) == 2


def test_a_failed_answer_is_not_reused(isolated):
    asked: list[int] = []

    def broken():
        raise RuntimeError("synthetic provider error")

    with calls.use_run(budget_scope=None, reuse=True):
        with pytest.raises(RuntimeError):
            calls.invoke(run_id="run-a", step_id="openai:q:1", provider="openai", model="gpt-test", max_cost_usd=Decimal("0.05"),
                         request_hash=KEY, reusable=True, fn=broken)
        _ask("run-b", asked)
    assert len(asked) == 1


def test_a_reused_answer_replays_within_its_run(isolated):
    asked: list[int] = []
    with calls.use_run(budget_scope=None, reuse=True):
        _ask("run-a", asked)
        reused = _ask("run-b", asked)
        replay = _ask("run-b", asked)
    assert len(asked) == 1 and replay.replayed and replay.invocation_id == reused.invocation_id


def test_a_reused_answer_needs_no_budget(isolated):
    asked: list[int] = []
    calls.set_budget("run-b", "openai", Decimal("0.001"))  # less than the reservation of a live call
    with calls.use_run(budget_scope=None):
        _ask("run-a", asked)
    with calls.use_run(budget_scope="run-b", reuse=True):
        calls.invoke(run_id="run-b", step_id="openai:q:1", provider="openai", model="gpt-test", max_cost_usd=Decimal("0.05"),
                     budget_scope="run-b", request_hash=KEY, reusable=True, fn=_answer(asked))
    assert len(asked) == 1 and calls.budget_usage("run-b")["committed_usd"] == Decimal("0")


def test_the_question_changes_with_the_model_the_instructions_and_the_schema():
    base = ("openai", "gpt-test", "instructions", "schema", "text")
    keys = {calls.answer_key(*base), calls.answer_key("openai", "gpt-other", *base[2:]),
            calls.answer_key("openai", "gpt-test", "other instructions", "schema", "text"),
            calls.answer_key("openai", "gpt-test", "instructions", "other schema", "text")}
    assert len(keys) == 4


@pytest.mark.parametrize(("params", "expected"), [({"jev_cache": "reuse"}, True), ({}, True), ({"jev_cache": "live"}, False)])
def test_the_runs_earlier_answers_setting_decides(params, expected):
    assert worker.reuse_answers(params) is expected


def test_the_gpt_extraction_reuses_its_answer_in_another_run(isolated):
    seen: list[str] = []
    pack = get_pack("invoice_hu")

    def factory(p):
        seen.append(p.key)
        return _FakeAgent(p, GOOD)

    calls.set_budget("run-a", "openai", Decimal("1"))
    calls.set_budget("run-b", "openai", Decimal("1"))
    with extract_llm.use_agent_factory(factory):
        with calls.use_run(budget_scope="run-a", reuse=True):
            first = extract_llm.extract("Számla sorszáma: MINTA-1", run_id="run-a", pack=pack)
        with calls.use_run(budget_scope="run-b", reuse=True):
            again = extract_llm.extract("Számla sorszáma: MINTA-1", run_id="run-b", pack=pack)
    assert again == first
    assert [r["note"] for r in calls.journal("run-b")][0].startswith(calls.REUSED_NOTE)
    assert len([r for r in calls.journal("run-a") if r["status"] == "succeeded"]) == 1
