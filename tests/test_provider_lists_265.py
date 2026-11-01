"""265 (plan L, L4c): the provider lists come from the provider registry (configs/providers.json).

Until 265 each module wrote its own list of providers (JEV, OpenAI, Azure DI), so a new provider would have been
refused by the capabilities, the workflows' budgets and the service's forms, and left unnamed and unordered in the
views. Now a capability may name any described provider, a budget is kept per budget the calls reserve from (OpenAI
Decisions' amount in OpenAI's, the owner's decision of 2026-11-01), and the views name and order the providers as the
registry does. Nothing is called.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from jav.app import capabilities, costs, workflow_records
from jav.core import calls, providers, store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def work(tmp_path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield


def test_the_budgets_are_the_providers_that_spend_their_own():
    assert providers.budgets() == ["jev", "openai", "azure_di"]  # OpenAI Decisions spends OpenAI's
    assert all(providers.budget_of(p) in providers.budgets() for p in providers.ids())


def test_a_budget_field_takes_a_budget_and_refuses_a_provider_spending_another():
    field = TypeAdapter(dict[providers.BudgetId, str])
    assert field.validate_python({"openai": "1", "jev": "2"}) == {"openai": "1", "jev": "2"}
    for wrong in ("openai_decisions", "gpt", "anthropic"):
        with pytest.raises(ValidationError):
            field.validate_python({wrong: "1"})


def test_amounts_are_pooled_per_budget_in_their_order():
    pooled = providers.pooled({"jev": Decimal("0.07"), "openai_decisions": Decimal("0.18"), "openai": Decimal("0.15")})
    assert pooled == {"jev": Decimal("0.07"), "openai": Decimal("0.33")} and list(pooled) == ["jev", "openai"]
    assert providers.pooled({"mnb_rates": Decimal("0")}) == {"mnb_rates": Decimal("0")}  # undescribed: its own


def test_the_lists_follow_the_registry():
    assert capabilities.PROVIDERS == tuple(providers.ids())
    assert costs.PROVIDER_ORDER == tuple(providers.ids())
    assert workflow_records.PROVIDERS == tuple(providers.budgets())


def test_the_interface_reads_the_same_registry():
    """The interface imports configs/providers.json for the names and the order (`ui/src/labels.ts`)."""
    labels = (ROOT / "ui/src/labels.ts").read_text(encoding="utf-8")
    assert 'from "../../configs/providers.json"' in labels
    described = json.loads((ROOT / "configs/providers.json").read_text(encoding="utf-8"))["providers"]
    assert {p: d["label"] for p, d in described.items()} == {p: providers.label(p) for p in providers.ids()}


def test_a_workflow_step_budget_names_a_budget(work):
    assert workflow_records._budget({"openai": "1.5"}) == {"openai": "1.5"}
    with pytest.raises(workflow_records.WorkflowError):
        workflow_records._budget({"openai_decisions": "1.5"})


def test_work_outside_a_run_keeps_decisions_cap_in_openais_budget(work):
    limits = {"openai_decisions": Decimal("0.20"), "openai": Decimal("0.10")}
    with calls.outside_run("case:265:step:1", limits) as scope:
        assert calls.budget_usage(scope)["providers"] == {
            "openai": {"limit_usd": Decimal("0.30"), "committed_usd": Decimal("0")}}
        assert calls.left(scope, "openai_decisions") == Decimal("0.30")


def test_a_measurement_keeps_decisions_cap_in_openais_budget(work):
    with calls.measurement("measure-265", {"openai_decisions": Decimal("0.50")}) as scope:
        assert calls.left(scope, "openai_decisions") == calls.left(scope, "openai") == Decimal("0.50")
        assert calls.left(scope, "jev") is None  # an unbudgeted provider stays uncallable
