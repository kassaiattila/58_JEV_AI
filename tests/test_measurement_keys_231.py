"""231 (stage D, D-h): a paid measurement names, at its start, a budgeted provider whose key this environment lacks.

The first paid round of stage D ran from a worktree that keeps no key file: every document came back unanswered with
no reason and nothing was spent. Now the measurement says so before it starts; a provider with its key, or one not
budgeted, is not named. Invented environment values; no call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav.core import calls, config, store


@pytest.fixture()
def keyless(monkeypatch, tmp_path):
    for name in (*config.API_KEY_ENV_VARS, config.OPENAI_KEY_ENV_VAR):
        monkeypatch.delenv(name, raising=False)
    with store.use_store(tmp_path / "keys.sqlite"):
        yield monkeypatch


def test_a_budgeted_provider_without_its_key_is_named_at_the_start(keyless, capsys) -> None:
    with calls.measurement("keys-1", {"jev": Decimal("0.10"), "openai": Decimal("0.10")}):
        pass
    out = capsys.readouterr().out
    assert out.count("No JEV key in this environment") == 1 and out.count("No OpenAI key in this environment") == 1


def test_a_provider_with_its_key_or_without_a_budget_is_not_named(keyless, capsys) -> None:
    keyless.setenv(config.OPENAI_KEY_ENV_VAR, "invented-not-a-key")
    assert calls.missing_keys({"openai": Decimal("0.10"), "azure": Decimal("0.01")}) == []
    with calls.measurement("keys-2", {}):
        pass
    assert "key in this environment" not in capsys.readouterr().out
