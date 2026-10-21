"""167 (review R-9): a manual settlement of an uncertain call only books a finite, non-negative cost up to a cap.

`calls-resolve --cost -5` used to book -5 USD, so a 5.5 USD call fitted into a 0.5 USD budget; a NaN made every later
reservation in that budget raise `InvalidOperation`. The local service already refused both (its request model); the
check now lives in the settlement itself, so the command line gets it too.
"""

from decimal import Decimal

import pytest

from jav import api_system, cli, store
from jav.runtime import calls


def _uncertain(run_id: str = "r1", max_cost: str = "0.5", scope: str | None = None) -> int:
    calls._reserve(run_id=run_id, step_id="s1", provider="openai", model="m", max_cost_usd=Decimal(max_cost),
                   budget_scope=scope, request_hash=None)
    calls.release_holder()  # the process stops; the operating system lets go of its holder lock
    calls.recover_uncertain()
    return calls.journal(run_id)[0]["id"]


@pytest.mark.parametrize("cost", ["-5", "-0.000001", "NaN", "sNaN", "Infinity", "-Infinity", "100.000001", "1E+9"])
def test_a_settlement_outside_the_range_is_refused_and_the_call_stays_uncertain(tmp_path, cost):
    with store.use_store(tmp_path / "jav.sqlite"):
        inv_id = _uncertain()
        with pytest.raises(calls.InvalidSettlement):
            calls.resolve_uncertain(inv_id, cost_usd=Decimal(cost), note="checked on the provider's console")
        row = calls.journal("r1")[0]
        assert (row["status"], row["cost_usd"], row["cost_known"]) == ("uncertain", None, 0)


@pytest.mark.parametrize("cost", ["0", "-0", "0.07", "5.5", "100"])
def test_a_settlement_inside_the_range_is_booked(tmp_path, cost):
    with store.use_store(tmp_path / "jav.sqlite"):
        inv_id = _uncertain()
        calls.resolve_uncertain(inv_id, cost_usd=Decimal(cost), note="checked on the provider's console")
        row = calls.journal("r1")[0]
        assert (row["status"], Decimal(row["cost_usd"]), row["cost_known"]) == ("failed", Decimal(cost), 1)
        assert not row["cost_usd"].startswith("-")


def test_a_negative_settlement_can_no_longer_free_budget_for_a_dearer_call(tmp_path):
    """The scenario of the review: with -5 booked, a 5.5 USD reservation would have fitted into a 0.5 USD budget."""
    with store.use_store(tmp_path / "jav.sqlite"):
        calls.set_budget("run-1", "openai", Decimal("0.5"))
        inv_id = _uncertain(run_id="run-1", max_cost="0.5", scope="run-1")
        with pytest.raises(calls.InvalidSettlement):
            calls.resolve_uncertain(inv_id, cost_usd=Decimal("-5"), note="typo")
        with pytest.raises(calls.BudgetExceeded):
            calls._reserve(run_id="run-1", step_id="s2", provider="openai", model="m", max_cost_usd=Decimal("5.5"),
                           budget_scope="run-1", request_hash=None)


def test_the_service_and_the_settlement_share_one_cap():
    assert calls.MAX_SETTLED_COST_USD == Decimal("100")
    with pytest.raises(ValueError):
        api_system.ResolveCall(cost_usd=calls.MAX_SETTLED_COST_USD + Decimal("0.01"), note="too dear")
    assert api_system.ResolveCall(cost_usd=calls.MAX_SETTLED_COST_USD, note="at the cap").cost_usd == Decimal("100")


@pytest.mark.parametrize("cost", ["-5", "NaN", "abc", "1E+9"])
def test_the_command_line_reports_a_refused_settlement(tmp_path, capsys, cost):
    with store.use_store(tmp_path / "jav.sqlite"):
        inv_id = _uncertain()
        assert cli.main(["calls-resolve", str(inv_id), "--cost", cost, "--note", "typo"]) == 2
        out = capsys.readouterr().out
        assert "refused" in out.lower()
        assert calls.journal("r1")[0]["status"] == "uncertain"


def test_the_command_line_reports_a_call_that_is_not_uncertain(tmp_path, capsys):
    with store.use_store(tmp_path / "jav.sqlite"):
        calls._reserve(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.2"),
                       budget_scope=None, request_hash=None)  # still in progress
        inv_id = calls.journal("r1")[0]["id"]
        assert cli.main(["calls-resolve", str(inv_id), "--cost", "0", "--note", "too early"]) == 2
        assert "still in progress" in capsys.readouterr().out
        assert calls.journal("r1")[0]["status"] == "reserved"
