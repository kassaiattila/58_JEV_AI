"""075 (repeated security audit, S02): the up-front reservation is an upper bound of the call's cost, not an estimate.

Before 075 the reservation assumed 2 characters per token, which the audit showed is not a bound (100 emoji: 50
estimated tokens, 300 real ones). Now: at most one token per UTF-8 byte plus a fixed overhead, conversation retries
that grow, identical transport retries, rounding up; and a call that still costs more than its reservation stops the
run's further reservations with that provider. No model call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav import store
from jav.runtime import calls

PRICE = (Decimal("0.75"), Decimal("4.5"))


@pytest.fixture
def isolated(tmp_path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield


def test_bytes_bound_covers_the_audit_emoji_sample():
    sample = chr(0x1F9EC) * 100  # 100 characters, 400 UTF-8 bytes; o200k_base: 300 tokens (audit, 2026-09-30)
    bound = calls.estimate_max_cost(input_bytes=calls.utf8_bytes(sample), max_output_tokens=0,
                                    usd_per_mtok=(Decimal(1), Decimal(0)))
    assert bound >= Decimal(300 + calls.TOKEN_OVERHEAD) / Decimal(1_000_000)


def test_conversation_rounds_grow_and_repeats_multiply():
    one = calls.estimate_max_cost(input_bytes=10_000, max_output_tokens=1_000, usd_per_mtok=PRICE)
    assert one == Decimal("0.012768")  # (11024 * 0.75 + 1000 * 4.5) / 1e6
    three = calls.estimate_max_cost(input_bytes=10_000, max_output_tokens=1_000, usd_per_mtok=PRICE, rounds=3)
    growth = Decimal(2 * 1_000 + calls.TOKEN_OVERHEAD) * PRICE[0] / Decimal(1_000_000)
    assert three == 3 * one + 3 * growth  # rounds 0, 1, 2 carry 0, 1 and 2 earlier answers and retry prompts
    assert calls.estimate_max_cost(input_bytes=10_000, max_output_tokens=1_000, usd_per_mtok=PRICE, repeats=4) == 4 * one


def test_the_bound_is_rounded_up():
    assert calls.estimate_max_cost(input_bytes=1, max_output_tokens=0, usd_per_mtok=(Decimal("0.042"), Decimal(0))) == Decimal("0.000044")


def test_cost_above_the_reservation_stops_further_reservations(isolated):
    calls.set_budget("run-a", "openai", Decimal("1"))
    over = calls.invoke(run_id="run-a", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.001"),
                        budget_scope="run-a", fn=lambda: calls.Outcome(response={"ok": 1}, cost_usd=Decimal("0.002")))
    assert over.response == {"ok": 1}  # the money is spent: the answer is kept
    row = calls.journal("run-a")[0]
    assert row["note"] == calls.OVERRUN_NOTE and row["status"] == "succeeded"
    with pytest.raises(calls.BudgetExceeded, match="exceeded its reservation"):
        calls.invoke(run_id="run-a", step_id="s2", provider="openai", model="m", max_cost_usd=Decimal("0.001"),
                     budget_scope="run-a", fn=lambda: calls.Outcome(response={}))
    calls.set_budget("run-a", "jev", Decimal("1"))
    calls.invoke(run_id="run-a", step_id="s3", provider="jev", model="m", max_cost_usd=Decimal("0.001"),
                 budget_scope="run-a", fn=lambda: calls.Outcome(response={}))  # another provider is not affected


def test_openai_client_does_not_retry_on_its_own(monkeypatch):
    """The transport retries of the OpenAI client would be unreserved paid requests; the queue retries instead."""
    from jav import config, email_tasks, extract_llm

    monkeypatch.setattr(config, "get_openai_key", lambda: "synthetic-test-value")
    for agent_cache in (extract_llm.get_agent, email_tasks.get_agent):
        agent_cache.cache_clear()
    try:
        assert config.OPENAI_SETTINGS["sdk_max_retries"] == 0
        assert extract_llm.get_agent().model.client.max_retries == 0
        assert email_tasks.get_agent().model.client.max_retries == 0
    finally:
        for agent_cache in (extract_llm.get_agent, email_tasks.get_agent):
            agent_cache.cache_clear()  # no agent with the synthetic key stays cached for other tests
