"""Unified call log and advance cost reservation (040 K1; F05 and F06 from 038)."""

from decimal import Decimal
from pathlib import Path

import pytest

from jav import store
from jav.runtime import calls


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "c.sqlite"):
        yield tmp_path


def _ok(cost="0.10", model="gpt-5.4-mini-2026-03-01"):
    def fn():
        return calls.Outcome(response={"answer": 42}, model=model, input_tokens=100, output_tokens=10,
                             cost_usd=None if cost is None else Decimal(cost))
    return fn


def test_success_is_journaled_with_actual_model_and_cost(isolated):
    out = calls.invoke(run_id="r1", step_id="s1", provider="openai", model="gpt-5.4-mini", max_cost_usd=Decimal("0.5"), fn=_ok())
    assert out.response == {"answer": 42} and not out.replayed
    row = calls.journal("r1")[0]
    assert (row["status"], row["model_actual"], row["cost_usd"], row["cost_known"]) == ("succeeded", "gpt-5.4-mini-2026-03-01", "0.10", 1)


def test_repeat_of_succeeded_step_replays_without_second_call(isolated):
    calls.invoke(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.5"), fn=_ok())
    def must_not_run():
        raise AssertionError("second paid call")
    again = calls.invoke(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.5"), fn=must_not_run)
    assert again.replayed and again.response == {"answer": 42}
    assert len(calls.journal("r1")) == 1


def test_failed_call_is_journaled_and_keeps_reservation(isolated):
    """F05: a timeout still leaves a log entry; the unknown cost is not zero and frees no budget. 085 (re-audit A04):
    a timeout may come after the provider did the work, so the call is uncertain, not failed."""
    calls.set_budget("trial", "openai", Decimal("1.00"))
    def timeout():
        raise TimeoutError("provider timeout")
    with pytest.raises(TimeoutError):
        calls.invoke(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.30"), fn=timeout,
                     budget_scope="trial")
    row = calls.journal("r1")[0]
    assert row["status"] == "uncertain" and row["error"] == "TimeoutError" and row["cost_known"] == 0
    assert calls.budget_usage("trial")["committed_usd"] == Decimal("0.30")
    assert [c["id"] for c in calls.uncertain_list()] == [row["id"]]


def test_failed_step_may_be_retried_as_new_attempt(isolated):
    def boom():
        raise ConnectionError("x")
    with pytest.raises(ConnectionError):
        calls.invoke(run_id="r1", step_id="s1", provider="jev", model="m", max_cost_usd=Decimal("0.01"), fn=boom)
    calls.invoke(run_id="r1", step_id="s1", provider="jev", model="m", max_cost_usd=Decimal("0.01"), fn=_ok("0.001"))
    assert [(r["attempt"], r["status"]) for r in calls.journal("r1")] == [(1, "failed"), (2, "succeeded")]


def test_budget_blocks_before_network(isolated):
    """F06: with a 1.00 USD budget, after 0.99 USD a request with a 0.20 USD maximum does not even start."""
    calls.set_budget("trial", "openai", Decimal("1.00"))
    calls.invoke(run_id="r1", step_id="a", provider="openai", model="m", max_cost_usd=Decimal("0.99"), fn=_ok("0.99"),
                 budget_scope="trial")
    def must_not_run():
        raise AssertionError("network reached")
    with pytest.raises(calls.BudgetExceeded):
        calls.invoke(run_id="r1", step_id="b", provider="openai", model="m", max_cost_usd=Decimal("0.20"), fn=must_not_run,
                     budget_scope="trial")
    assert [r["step_id"] for r in calls.journal("r1")] == ["a"]


def test_known_cost_releases_unused_reservation(isolated):
    calls.set_budget("trial", "openai", Decimal("1.00"))
    calls.invoke(run_id="r1", step_id="a", provider="openai", model="m", max_cost_usd=Decimal("0.60"), fn=_ok("0.05"),
                 budget_scope="trial")
    assert calls.budget_usage("trial")["committed_usd"] == Decimal("0.05")
    calls.invoke(run_id="r1", step_id="b", provider="openai", model="m", max_cost_usd=Decimal("0.60"), fn=_ok("0.05"),
                 budget_scope="trial")


def test_unknown_cost_on_success_keeps_reservation(isolated):
    calls.set_budget("trial", "openai", Decimal("1.00"))
    calls.invoke(run_id="r1", step_id="a", provider="openai", model="m", max_cost_usd=Decimal("0.40"), fn=_ok(None),
                 budget_scope="trial")
    assert calls.budget_usage("trial")["committed_usd"] == Decimal("0.40")


def test_crash_after_reservation_blocks_automatic_second_call(isolated):
    """Crash after the response: the reserved, unclosed attempt is uncertain; no automatic second paid request."""
    calls._reserve(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.2"),
                   budget_scope=None, request_hash=None)  # the process "crashed" here
    calls.release_holder()  # 092: the process stops; the operating system lets go of its holder lock
    assert calls.recover_uncertain() == 1
    def must_not_run():
        raise AssertionError("second paid call")
    with pytest.raises(calls.UncertainAttempt):
        calls.invoke(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.2"), fn=must_not_run)
    calls.resolve_uncertain(calls.journal("r1")[0]["id"], cost_usd=Decimal("0.07"), note="szolgáltatói felületen ellenőrizve")
    assert calls.journal("r1")[0]["status"] == "failed" and calls.journal("r1")[0]["cost_usd"] == "0.07"


def test_budget_is_per_provider(isolated):
    calls.set_budget("trial", "jev", Decimal("0.01"))
    with pytest.raises(calls.BudgetExceeded):
        calls.invoke(run_id="r1", step_id="a", provider="openai", model="m", max_cost_usd=Decimal("0.01"), fn=_ok(),
                     budget_scope="trial")  # the budget only allows JEV


def test_estimate_counts_every_physical_attempt():
    price = (Decimal("0.75"), Decimal("4.5"))
    one = calls.estimate_max_cost(input_bytes=3000, max_output_tokens=1000, usd_per_mtok=price)
    # 075: at most one token per UTF-8 byte plus the fixed overhead: (4024 * 0.75 + 1000 * 4.5) / 1e6
    assert one == Decimal("0.007518")
    assert calls.estimate_max_cost(input_bytes=3000, max_output_tokens=1000, usd_per_mtok=price, repeats=3) == 3 * one


def test_saved_response_left_reserved_by_a_crash_is_recovered_as_succeeded(isolated, monkeypatch):
    """066 Á30: if the worker stopped between saving the response and marking it "succeeded", the call used to become
    uncertain although the response was there: the step could not be repeated and the maximum stayed reserved. On
    start-up it is now settled as succeeded with the saved cost, and the repeat returns the saved response."""
    real_connect = store.connect
    calls_seen = {"n": 0}

    def crash_before_success_update(*a, **k):
        calls_seen["n"] += 1
        if calls_seen["n"] == 3:  # 1: reservation, 2: saving the response, 3: marking "succeeded"
            raise KeyboardInterrupt("leállás")
        return real_connect(*a, **k)

    calls.set_budget("wp", "openai", Decimal("1"))
    monkeypatch.setattr(store, "connect", crash_before_success_update)
    with pytest.raises(KeyboardInterrupt):
        calls.invoke(run_id="r9", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.5"), fn=_ok("0.10"),
                     budget_scope="wp")
    monkeypatch.setattr(store, "connect", real_connect)
    assert calls.journal("r9")[0]["status"] == "reserved"

    calls.release_holder()  # 092: the process stops; the operating system lets go of its holder lock
    calls.recover_uncertain()
    row = calls.journal("r9")[0]
    assert (row["status"], row["cost_usd"], row["cost_known"]) == ("succeeded", "0.10", 1)
    assert calls.budget_usage("wp")["committed_usd"] == Decimal("0.10")

    def must_not_run():
        raise AssertionError("second paid call")
    again = calls.invoke(run_id="r9", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.5"), fn=must_not_run,
                         budget_scope="wp")
    assert again.replayed and again.response == {"answer": 42}
