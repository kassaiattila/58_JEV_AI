"""188 (plan 185 T3a): what each golden command measures, pinned before the shared measurement command.

The shared command (`measure`, `jav/goldens.py`) has to run every golden set exactly as the set's own command does:
the same measuring function with the same arguments, so the raw run files, their names and the reports stay
comparable with the earlier measurements. These tests were written against the commands as they were before the
shared command existed; `tests/test_goldens_188.py` checks the shared command against the same calls.

Stand-in measuring functions only: no case is run and no call is made.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from jav import cli, evals, evals_detect, evals_email
from jav.domains.finance import reconcile, reconcile_ai


class Recorder:
    """A stand-in measuring function that records how it was called and returns `result`."""

    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self.result


def record(monkeypatch: pytest.MonkeyPatch, module: Any, name: str, result: Any) -> Recorder:
    fake = Recorder(result)
    monkeypatch.setattr(module, name, fake)
    return fake


def golden_call(arm: str, type_key: str, *, cases: Any = None, use_cache: bool = True, jev: bool = True,
                budget_usd: Decimal | None = None, jev_budget_usd: Decimal | None = None,
                label: str = "golden") -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The call of `evals.golden` that measures one type pack's data points on one path."""
    from jav.flows.flow import run_one

    return ((arm, run_one), {"cases": cases, "tracker": False, "use_cache": use_cache, "type_key": type_key, "jev": jev,
                             "budget_usd": budget_usd, "jev_budget_usd": jev_budget_usd, "label": label})


def detect_call(*, use_cache: bool = True, jev: bool = True,
                budget_usd: Decimal | None = None) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The call of `evals_detect.detect_golden` that measures the type recognition."""
    return ((), {"use_cache": use_cache, "jev": jev, "descriptions": True, "budget_usd": budget_usd, "cases": None,
                 "label": "golden"})


def email_call(*, use_cache: bool = True, jev: bool = True, budget_usd: Decimal | None = None,
               jev_budget_usd: Decimal | None = None) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The call of `evals_email.email_golden` that measures the email intent."""
    return ((), {"use_cache": use_cache, "limit": None, "jev": jev, "budget_usd": budget_usd,
                 "jev_budget_usd": jev_budget_usd})


def credit_kinds_call(engine: str, limits: dict[str, Decimal], *,
                      use_cache: bool = True) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """The call of `reconcile_ai.golden` that measures the incoming money kinds with one engine."""
    return ((), {"engines": [engine], "limits": limits, "use_cache": use_cache})


CREDIT_RESULT = {"cases": 2, "golden_version": "1.0.0", "jev_config": "j", "gpt_config": "g", "scope": "s",
                 "usage": {}, "raw": "runs/x_credit_kinds_golden.jsonl",
                 "engines": {e: {"cases": 2, "right": 1, "failed": 0, "by_kind": {}, "confusions": {}} for e in ("jev", "gpt")}}


@pytest.mark.parametrize(("argv", "expected"), [
    (["golden", "--arm", "S"], golden_call("S", "invoice_hu")),
    (["golden", "--arm", "S", "--type", "viz_szamla", "--no-cache"], golden_call("S", "viz_szamla", use_cache=False)),
    (["golden", "--arm", "G", "--type", "invoice_foreign"], golden_call("G", "invoice_foreign")),
    (["golden", "--arm", "G", "--engine", "gpt", "--budget-usd", "0.10"],
     golden_call("G", "invoice_hu", jev=False, budget_usd=Decimal("0.10"))),
    (["golden", "--arm", "S", "--jev-budget-usd", "0.02"], golden_call("S", "invoice_hu", jev_budget_usd=Decimal("0.02"))),
])
def test_the_data_point_golden_command(monkeypatch, argv, expected):
    fake = record(monkeypatch, evals, "golden", [])
    assert cli.main(argv) == 0
    assert fake.calls == [expected]


def test_the_data_point_golden_command_on_the_synthetic_cases(monkeypatch):
    monkeypatch.setattr(evals, "load_synthetic_cases", lambda type_key: [f"case of {type_key}"])
    fake = record(monkeypatch, evals, "golden", [])
    assert cli.main(["golden", "--arm", "S", "--type", "invoice_out", "--synthetic"]) == 0
    assert fake.calls == [golden_call("S", "invoice_out", cases=["case of invoice_out"], label="synthetic")]


def test_the_s_path_without_jev_is_refused_before_anything_runs(monkeypatch):
    fake = record(monkeypatch, evals, "golden", [])
    assert cli.main(["golden", "--arm", "S", "--engine", "gpt"]) == 2
    assert fake.calls == []


@pytest.mark.parametrize(("argv", "expected"), [
    (["detect-golden"], detect_call()),
    (["detect-golden", "--no-cache"], detect_call(use_cache=False)),
    (["detect-golden", "--engine", "gpt", "--budget-usd", "0.20"], detect_call(jev=False, budget_usd=Decimal("0.20"))),
])
def test_the_type_golden_command(monkeypatch, argv, expected):
    fake = record(monkeypatch, evals_detect, "detect_golden", [])
    assert cli.main(argv) == 0
    assert fake.calls == [expected]


@pytest.mark.parametrize(("argv", "expected"), [
    (["email-golden"], email_call()),
    (["email-golden", "--engine", "gpt", "--budget-usd", "0.30"], email_call(jev=False, budget_usd=Decimal("0.30"))),
    (["email-golden", "--jev-budget-usd", "0.03"], email_call(jev_budget_usd=Decimal("0.03"))),
])
def test_the_intent_golden_command(monkeypatch, argv, expected):
    fake = record(monkeypatch, evals_email, "email_golden", [])
    assert cli.main(argv) == 0
    assert fake.calls == [expected]


def test_the_reconciliation_golden_command(monkeypatch, capsys):
    fake = record(monkeypatch, reconcile, "golden_score", {"passed": 3, "total": 3, "failures": {}})
    assert cli.main(["reconcile", "--golden"]) == 0
    assert fake.calls == [((), {})]
    assert "golden cases: 3/3" in capsys.readouterr().out
    record(monkeypatch, reconcile, "golden_score", {"passed": 2, "total": 3, "failures": {"c3": ["pairs differ"]}})
    assert cli.main(["reconcile", "--golden"]) == 1
    assert "c3: pairs differ" in capsys.readouterr().out


@pytest.mark.parametrize(("argv", "expected"), [
    (["reconcile-ai", "--golden", "--engine", "jev", "--jev-budget-usd", "0.01"],
     credit_kinds_call("jev", {"jev": Decimal("0.01")})),
    (["reconcile-ai", "--golden", "--engine", "gpt", "--budget-usd", "0.02", "--no-cache"],
     credit_kinds_call("gpt", {"openai": Decimal("0.02")}, use_cache=False)),
])
def test_the_incoming_money_kind_golden_command(monkeypatch, argv, expected):
    fake = record(monkeypatch, reconcile_ai, "golden", CREDIT_RESULT)
    assert cli.main(argv) == 0
    assert fake.calls == [expected]
