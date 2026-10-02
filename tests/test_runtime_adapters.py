"""Provider adapters through the call log and the budget (040 K1): JEV and GPT extract, with a fake client, no calls."""

from decimal import Decimal
from pathlib import Path

import pytest
from typesafe_sdk import Choice, SystemOneResponse

from jav import store
from jav.adapters.jev import JevAdapter, JevUnavailableError
from jav.runtime import calls


class FakeClient:
    def __init__(self, fail: Exception | None = None) -> None:
        self.calls = 0
        self.fail = fail

    def system_one(self, *, state, questions, model):
        self.calls += 1
        if self.fail:
            raise self.fail
        answers = {qid: {"type": "choice", "choice": next(iter(q.criteria)), "confidence": 0.9,
                         "probabilities": {k: 0.5 for k in q.criteria}} for qid, q in questions.items()}
        return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 1000, "output_tokens": 0}, "answers": answers})


QS = {"pick": Choice(instructions="which?", criteria={"a": None, "none": "n"})}


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "a.sqlite"):
        yield tmp_path


def test_without_run_context_nothing_is_journaled(isolated):
    jev = JevAdapter(client=FakeClient(), cache_dir=isolated / "cache", model="jev-1.13.0")
    jev.ask("t", {"x": 1}, QS, run_id="legacy", use_cache=False)
    assert calls.journal("legacy") == []


def test_jev_call_in_run_context_is_journaled_with_cost(isolated):
    client = FakeClient()
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.13.0")
    calls.set_budget("wp", "jev", Decimal("1"))
    with calls.use_run(budget_scope="wp"):
        r = jev.ask("t", {"x": 1}, QS, run_id="run-1", use_cache=False)
        again = jev.ask("t", {"x": 1}, QS, run_id="run-1", use_cache=False)  # the same step: saved response
    assert r.response.choices["pick"].choice == "a" and again.response.choices["pick"].choice == "a"
    assert client.calls == 1
    row = calls.journal("run-1")[0]
    assert row["status"] == "succeeded" and row["provider"] == "jev" and row["cost_usd"] == "0.000042"



def test_replayed_jev_step_is_not_booked_as_a_second_paid_call(isolated):
    """066 Á16: replaying a saved response (resuming after a stop) is not new spending: it goes into the old call log
    (the ledger) with zero cost, marked as reused, so that the sum of the two logs does not double the spending."""
    jev = JevAdapter(client=FakeClient(), cache_dir=isolated / "cache", model="jev-1.13.0")
    calls.set_budget("wp", "jev", Decimal("1"))
    with calls.use_run(budget_scope="wp"):
        first = jev.ask("t", {"x": 1}, QS, run_id="run-1", use_cache=False)
        again = jev.ask("t", {"x": 1}, QS, run_id="run-1", use_cache=False)
    assert not first.cached and first.call.cost_usd > 0
    assert again.cached and again.call.cost_usd == 0.0
    rows = store.ledger_for_run("run-1")
    assert [(r["cached"], r["cost_usd"] > 0) for r in rows] == [(0, True), (1, False)]

def test_jev_budget_exhaustion_becomes_unavailable_without_network(isolated):
    client = FakeClient()
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.13.0")
    calls.set_budget("wp", "jev", Decimal("0.0000001"))
    with calls.use_run(budget_scope="wp"), pytest.raises(JevUnavailableError) as err:
        jev.ask("t", {"x": 1}, QS, run_id="run-1", use_cache=False)
    assert err.value.reason == "budget_exceeded" and client.calls == 0


def test_jev_sdk_failure_is_journaled_as_failed(isolated):
    from typesafe_sdk import TypeSafeError
    jev = JevAdapter(client=FakeClient(fail=TypeSafeError("down")), cache_dir=isolated / "cache", model="jev-1.13.0")
    with calls.use_run(budget_scope=None), pytest.raises(JevUnavailableError):
        jev.ask("t", {"x": 1}, QS, run_id="run-1", use_cache=False)
    row = calls.journal("run-1")[0]
    # 085: the error names the chain; an SDK error that is not a timeout is a definite failure
    assert row["status"] == "failed" and row["error"] == "JevUnavailableError<-TypeSafeError" and row["cost_known"] == 0


def test_uncertain_prior_attempt_blocks_jev_call(isolated):
    client = FakeClient()
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.13.0")
    from jav.adapters.jev import request_hash
    key = request_hash("jev-1.13.0", {"x": 1}, QS)
    calls._reserve(run_id="run-1", step_id=f"jev:t:{key[:16]}", provider="jev", model="jev-1.13.0",
                   max_cost_usd=Decimal("0.01"), budget_scope=None, request_hash=key)
    calls.release_holder()  # 092: the process stops; the operating system lets go of its holder lock
    calls.recover_uncertain()
    with calls.use_run(budget_scope=None), pytest.raises(JevUnavailableError) as err:
        jev.ask("t", {"x": 1}, QS, run_id="run-1", use_cache=False)
    assert err.value.reason == "uncertain_attempt" and client.calls == 0


class _FailingAgent:
    def run_sync(self, *a, **k):
        raise TimeoutError("provider timeout")


def test_gpt_failure_is_ledgered_outside_run_context(isolated):
    """F05: a failed call of the normal GPT extract is also recorded in the ledger (with unknown cost, not zero)."""
    from jav import extract_llm
    with extract_llm.use_agent_factory(lambda pack: _FailingAgent()), pytest.raises(TimeoutError):
        extract_llm.extract("szöveg", run_id="g1")
    rows = store.ledger_for_run("g1")
    assert len(rows) == 1 and rows[0]["error"] == "TimeoutError" and rows[0]["cost_usd"] is None


def test_gpt_failure_in_run_context_keeps_reservation(isolated):
    from jav import extract_llm
    calls.set_budget("wp", "openai", Decimal("1"))
    with calls.use_run(budget_scope="wp"), extract_llm.use_agent_factory(lambda pack: _FailingAgent()), pytest.raises(TimeoutError):
        extract_llm.extract("szöveg", run_id="g2")
    row = calls.journal("g2")[0]
    # 085 (re-audit A04): a provider timeout may have been processed, so the call is uncertain, not failed
    assert row["status"] == "uncertain" and row["provider"] == "openai"
    assert calls.budget_usage("wp")["committed_usd"] == Decimal(row["max_cost_usd"]) > 0


class _MustNotRun:
    def run_sync(self, *a, **k):
        raise AssertionError("fizetős hívás ár nélküli modellel")


def test_unpriced_model_is_refused_under_a_budget(isolated, monkeypatch):
    """066 Á38: if the configured model has no price, the budget reservation would see zero and the budget would not
    stop the spending. In a worker run it therefore stops with a named error (the flow raises an
    `llm:failed:UnpricedModelError` to-do)."""
    from jav import email_tasks, extract_llm
    from jav.config import UnpricedModelError

    monkeypatch.setattr(extract_llm, "OPENAI_MODEL", "gpt-kitalalt-modell")
    monkeypatch.setattr(email_tasks, "OPENAI_MODEL", "gpt-kitalalt-modell")
    monkeypatch.setattr(email_tasks, "get_agent", lambda: _MustNotRun())
    calls.set_budget("wp", "openai", Decimal("1"))
    with calls.use_run(budget_scope="wp"), extract_llm.use_agent_factory(lambda pack: _MustNotRun()):
        with pytest.raises(UnpricedModelError):
            extract_llm.extract("szöveg", run_id="u1")
        with pytest.raises(UnpricedModelError):
            email_tasks.extract({"messages": [{"message_id": "m1", "subject": "x", "body": "y"}]}, intent_hint=None, run_id="u2")
    assert calls.journal("u1") == [] and calls.journal("u2") == []
