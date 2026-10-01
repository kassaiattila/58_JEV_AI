"""085: processing without JEV (F-jev-nélkül). Synthetic documents and stand-in clients only; no paid call."""

from decimal import Decimal
from pathlib import Path

import pytest

from jav import store
from jav.adapters import jev as jev_mod
from jav.adapters.jev import JevAdapter, JevUnavailableError
from jav.config import MissingAPIKeyError
from jav.runtime import calls
from tests.test_runtime_adapters import QS


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "a.sqlite"):
        yield tmp_path


def _no_key():
    raise MissingAPIKeyError("no TypeSafe API key (synthetic)")


# --- K1: a missing TypeSafe key is a to-do, not a failed item -------------------------------------------


def test_missing_key_is_jev_unavailable_before_any_reservation(isolated, monkeypatch):
    monkeypatch.setattr(jev_mod, "make_client", _no_key)
    jev = JevAdapter(cache_dir=isolated / "cache", model="jev-1.13.0")
    calls.set_budget("run-1", "jev", Decimal("1"))
    with calls.use_run(budget_scope="run-1"), pytest.raises(JevUnavailableError) as err:
        jev.ask("t", {"x": 1}, QS, run_id="run-1", use_cache=False)
    assert err.value.reason == "missing_key"
    assert calls.journal("run-1") == []  # nothing was reserved: no request could have left
    assert calls.budget_usage("run-1")["committed_usd"] == Decimal(0)


def test_missing_key_outside_a_run_is_jev_unavailable_too(isolated, monkeypatch):
    monkeypatch.setattr(jev_mod, "make_client", _no_key)
    jev = JevAdapter(cache_dir=isolated / "cache", model="jev-1.13.0")
    with pytest.raises(JevUnavailableError) as err:
        jev.ask("t", {"x": 1}, QS, run_id="adhoc", use_cache=False)
    assert err.value.reason == "missing_key"
