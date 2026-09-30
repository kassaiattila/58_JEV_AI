"""Egységes hívásnapló és előzetes költségfoglalás (040 K1; a 038-as F05 és F06)."""

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
    """F05: timeout után is van napló; az ismeretlen költség nem nulla, nem szabadít fel keretet."""
    calls.set_budget("trial", "openai", Decimal("1.00"))
    def timeout():
        raise TimeoutError("provider timeout")
    with pytest.raises(TimeoutError):
        calls.invoke(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.30"), fn=timeout,
                     budget_scope="trial")
    row = calls.journal("r1")[0]
    assert row["status"] == "failed" and row["error"] == "TimeoutError" and row["cost_known"] == 0
    assert calls.budget_usage("trial")["committed_usd"] == Decimal("0.30")


def test_failed_step_may_be_retried_as_new_attempt(isolated):
    def boom():
        raise ConnectionError("x")
    with pytest.raises(ConnectionError):
        calls.invoke(run_id="r1", step_id="s1", provider="jev", model="m", max_cost_usd=Decimal("0.01"), fn=boom)
    calls.invoke(run_id="r1", step_id="s1", provider="jev", model="m", max_cost_usd=Decimal("0.01"), fn=_ok("0.001"))
    assert [(r["attempt"], r["status"]) for r in calls.journal("r1")] == [(1, "failed"), (2, "succeeded")]


def test_budget_blocks_before_network(isolated):
    """F06: 1,00 USD keretnél 0,99 USD után a 0,20 USD-os maximális kérés már el sem indul."""
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
    """Válasz utáni összeomlás: a lefoglalt, lezáratlan kísérlet bizonytalan; nincs automatikus második fizetős kérés."""
    calls._reserve(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.2"),
                   budget_scope=None, request_hash=None)  # a folyamat itt „összeomlott”
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
                     budget_scope="trial")  # a keret csak a JEV-et engedi


def test_estimate_counts_every_physical_attempt():
    est = calls.estimate_max_cost(input_chars=3000, max_output_tokens=1000, usd_per_mtok=(Decimal("0.75"), Decimal("4.5")),
                                  physical_attempts=3)
    # 2 karakter/token felső becslés (a magyar szöveg rosszul tokenizálódik): (1500 * 0,75 + 1000 * 4,5) / 1e6 * 3
    assert est == Decimal("0.016875")


def test_saved_response_left_reserved_by_a_crash_is_recovered_as_succeeded(isolated, monkeypatch):
    """066 Á30: ha a feldolgozó a válasz mentése és a „sikeres” jelölés között áll le, a hívás eddig bizonytalan lett,
    pedig a válasz megvan: a lépés nem volt ismételhető, a maximum lekötve maradt. Induláskor most sikeresre rendeződik,
    a mentett költséggel, és az ismétlés a mentett választ adja."""
    real_connect = store.connect
    calls_seen = {"n": 0}

    def crash_before_success_update(*a, **k):
        calls_seen["n"] += 1
        if calls_seen["n"] == 3:  # 1: foglalás, 2: válasz mentése, 3: a „sikeres” jelölés
            raise KeyboardInterrupt("leállás")
        return real_connect(*a, **k)

    calls.set_budget("wp", "openai", Decimal("1"))
    monkeypatch.setattr(store, "connect", crash_before_success_update)
    with pytest.raises(KeyboardInterrupt):
        calls.invoke(run_id="r9", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.5"), fn=_ok("0.10"),
                     budget_scope="wp")
    monkeypatch.setattr(store, "connect", real_connect)
    assert calls.journal("r9")[0]["status"] == "reserved"

    calls.recover_uncertain()
    row = calls.journal("r9")[0]
    assert (row["status"], row["cost_usd"], row["cost_known"]) == ("succeeded", "0.10", 1)
    assert calls.budget_usage("wp")["committed_usd"] == Decimal("0.10")

    def must_not_run():
        raise AssertionError("second paid call")
    again = calls.invoke(run_id="r9", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.5"), fn=must_not_run,
                         budget_scope="wp")
    assert again.replayed and again.response == {"answer": 42}
