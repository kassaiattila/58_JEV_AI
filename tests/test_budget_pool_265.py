"""265 (plan L, L2): a provider reserves from the budget the provider registry names.

OpenAI Decisions books its calls under its own name, but spends from the OpenAI budget (the owner's decision of
2026-11-01): the two share one limit, and what one committed the other cannot spend. A provider spending its own budget
(JEV, OpenAI, a connector) behaves as before.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav.core import calls, store


def _outcome(cost: str):
    return lambda: calls.Outcome(response={"ok": True}, model="invented-model", cost_usd=Decimal(cost))


def _invoke(step: str, provider: str, max_cost: str, cost: str, scope: str = "scope-265"):
    return calls.invoke(run_id="run-265", step_id=step, provider=provider, model="invented-model",
                        max_cost_usd=Decimal(max_cost), fn=_outcome(cost), budget_scope=scope)


@pytest.fixture
def work(tmp_path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield


def test_decisions_spends_from_the_openai_budget(work):
    calls.set_budget("scope-265", "openai", Decimal("0.10"))
    _invoke("decisions-1", "openai_decisions", "0.06", "0.05")
    assert calls.left("scope-265", "openai") == Decimal("0.05")
    assert calls.left("scope-265", "openai_decisions") == Decimal("0.05")  # the same budget, by either name
    assert calls.has_budget("scope-265", "openai_decisions")
    with pytest.raises(calls.BudgetExceeded):  # GPT cannot spend what Decisions committed
        _invoke("gpt-1", "openai", "0.06", "0.01")
    _invoke("gpt-2", "openai", "0.05", "0.01")
    with store.connect() as c:
        rows = c.execute("SELECT provider, status FROM invocations ORDER BY id").fetchall()
    assert [(r["provider"], r["status"]) for r in rows] == [("openai_decisions", "succeeded"), ("openai", "succeeded")]


def test_without_the_openai_budget_decisions_is_refused(work):
    calls.set_budget("scope-265", "jev", Decimal("1.00"))
    with pytest.raises(calls.BudgetExceeded, match="it spends from 'openai'"):
        _invoke("decisions-1", "openai_decisions", "0.01", "0.01")
    assert not calls.has_budget("scope-265", "openai_decisions")


def test_own_budgets_stay_apart(work):
    calls.set_budget("scope-265", "jev", Decimal("0.02"))
    calls.set_budget("scope-265", "openai", Decimal("0.02"))
    _invoke("jev-1", "jev", "0.02", "0.02")
    _invoke("gpt-1", "openai", "0.02", "0.01")  # JEV's spending does not touch the OpenAI budget
    with pytest.raises(calls.BudgetExceeded):
        _invoke("jev-2", "jev", "0.01", "0.01")
    summary = calls.budget_usage("scope-265")
    assert summary["providers"]["jev"]["committed_usd"] == Decimal("0.02")
    assert summary["providers"]["openai"]["committed_usd"] == Decimal("0.01")


def test_a_key_check_follows_the_registry(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("TypeSafeJAV_API_KEY", "synthetic-offline-key")
    limits = {"jev": Decimal("0.1"), "openai": Decimal("0.1"), "invented_connector": Decimal("0")}
    assert calls.missing_keys(limits) == ["openai"]
