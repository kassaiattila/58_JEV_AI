import pytest

from jav import store
from jav.adapters.jev import JevAdapter
from jav.experiments.grounded_revision_trial import RoundAdapter


def test_new_round_budget_is_reserved_before_external_call_and_failure_consumes_it(tmp_path, monkeypatch):
    calls = []
    def external(*args, **kwargs):
        calls.append(1)
        raise OSError("external unavailable")
    monkeypatch.setattr(JevAdapter, "_live", external)
    adapter = RoundAdapter(directory=tmp_path, limits={"round_adapter_call_limit":1,
                           "round_recorded_cost_limit_usd":1}, model="jev-1.13.0")
    with store.use_store(tmp_path / "business.sqlite"):
        with pytest.raises(OSError):
            adapter._live()
        # Recreating the adapter cannot reset the durable new-round call budget.
        fresh = RoundAdapter(directory=tmp_path, limits=adapter.limits, model=adapter.model)
        with pytest.raises(RuntimeError, match="budget exhausted"):
            fresh._live()
    assert len(calls) == 1


def test_recorded_cost_gate_blocks_before_external_call(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("cost gate must stop before external call")
    monkeypatch.setattr(JevAdapter, "_live", forbidden)
    adapter = RoundAdapter(directory=tmp_path, limits={"round_adapter_call_limit":10,
                           "round_recorded_cost_limit_usd":0}, model="jev-1.13.0")
    with store.use_store(tmp_path / "business.sqlite"):
        with pytest.raises(RuntimeError, match="cost stop"):
            adapter._live()
    assert not (tmp_path / "budget.sqlite").exists()
