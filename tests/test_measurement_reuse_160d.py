"""160-D (F-csak-gpt Sz6): a measurement reuses the earlier GPT answers to the same question, as a work run does (090).

A golden measurement and a processing command reuse an earlier answer unless told to ask again (`--no-cache`): the
JEV cache and the call log's answers follow the same setting. A determinism measurement always asks again, since it
measures the run-to-run variation. Without a budget a reused answer still comes back for free, while a question
nobody asked before is refused, so a measurement can be replayed at no cost before its sub-budget is spent. The
measurement prints how many answers were live and how many were reused.

Stand-in calls only; no paid call.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

import pytest

from jav import cli, store
from jav.runtime import calls

KEY = calls.answer_key("openai", "gpt-test", "instructions", "schema", "document text")
OTHER = calls.answer_key("openai", "gpt-test", "instructions", "schema", "another document")


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield tmp_path


def _ask(run_id: str, asked: list[int], *, key: str = KEY) -> calls.Result:
    def fn():
        asked.append(1)
        return calls.Outcome(response={"value": "first"}, model="gpt-test-2026", cost_usd=Decimal("0.01"))

    ctx = calls.current()
    return calls.invoke(run_id=run_id, step_id="openai:q:1", provider="openai", model="gpt-test", max_cost_usd=Decimal("0.05"),
                        budget_scope=ctx.budget_scope if ctx else None, request_hash=key, reusable=True, fn=fn)


def _earlier_answer(asked: list[int]) -> calls.Result:
    with calls.use_run(budget_scope=None):
        return _ask("run-earlier", asked)


def test_a_measurement_reuses_an_earlier_answer_without_a_budget(isolated):
    asked: list[int] = []
    first = _earlier_answer(asked)
    with calls.measurement("measure-a", {}, reuse=True):
        again = _ask("golden-1", asked)
        with pytest.raises(calls.BudgetExceeded):  # a question nobody asked before needs the sub-budget
            _ask("golden-2", asked, key=OTHER)
    assert len(asked) == 1 and again.reused_from == first.invocation_id and again.response == {"value": "first"}


def test_a_measurement_asks_again_when_told_to(isolated):
    asked: list[int] = []
    _earlier_answer(asked)
    with calls.measurement("measure-b", {}):  # reuse is off unless asked for (a determinism measurement)
        with pytest.raises(calls.BudgetExceeded):
            _ask("golden-1", asked)
    with calls.measurement("measure-c", {"openai": Decimal("0.10")}, reuse=False):
        live = _ask("golden-1", asked)
    assert len(asked) == 2 and live.reused_from is None


def test_a_measurement_reports_its_live_and_reused_answers(isolated, capsys):
    asked: list[int] = []
    _earlier_answer(asked)
    with calls.measurement("measure-d", {"openai": Decimal("0.10")}, reuse=True) as scope:
        _ask("golden-1", asked)
        _ask("golden-2", asked, key=OTHER)
    out = capsys.readouterr().out
    assert "1 live call (0.01 USD)" in out and "1 earlier answer reused (0 USD)" in out
    assert calls.scope_calls(scope) == {"live": 1, "live_cost_usd": Decimal("0.01"), "reused": 1}


def test_a_measurement_without_calls_reports_nothing(isolated, capsys):
    with calls.measurement("measure-e", {}, reuse=True):
        pass
    assert "live call" not in capsys.readouterr().out


@pytest.mark.parametrize(("no_cache", "reuse"), [(False, True), (True, False)])
def test_a_command_reuses_unless_told_to_ask_again(isolated, no_cache, reuse):
    args = argparse.Namespace(no_cache=no_cache, jev_budget_usd=None, budget_usd=None)
    with cli._under_budget(args, "detect"):
        assert calls.current().reuse is reuse and calls.current().measurement


def test_a_determinism_command_always_asks_again(isolated, monkeypatch):
    seen: list[bool] = []
    import jav.evals as evals
    import jav.evals_detect as evals_detect
    import jav.evals_email as evals_email

    def record(*_a, **_k):
        seen.append(calls.current().reuse)

    monkeypatch.setattr(evals, "determinism", record)
    monkeypatch.setattr(evals_detect, "detect_determinism", record)
    monkeypatch.setattr(evals_email, "email_determinism", record)
    assert cli.main(["determinism", "--arm", "G", "--n", "2", "--engine", "gpt"]) == 0
    assert cli.main(["detect-determinism", "--n", "2", "--engine", "gpt"]) == 0
    assert cli.main(["email-determinism", "--n", "2", "--engine", "gpt"]) == 0
    assert seen == [False, False, False]


class _Stop(Exception):
    pass


def test_the_golden_measurements_reuse_unless_told_to_ask_again(isolated, monkeypatch):
    """The measurement guard is where the setting lands; it stops the measurement before any case runs."""
    seen: list[bool] = []

    def spy(scope, limits, *, reuse=False):
        seen.append(reuse)
        raise _Stop

    monkeypatch.setattr(calls, "measurement", spy)
    from jav import evals, evals_detect, evals_email, reconcile_ai

    monkeypatch.setattr(evals_email, "_cases", lambda limit: [])
    runs = [
        lambda cache: evals.golden("G", lambda *a, **k: None, cases=[object()], use_cache=cache, type_key="invoice_hu", jev=False),
        lambda cache: evals_detect.detect_golden(use_cache=cache, jev=False, cases=[]),
        lambda cache: evals_email.email_golden(use_cache=cache, jev=False),
        lambda cache: evals_email.email_injection_probe(use_cache=cache, jev=False),
        lambda cache: reconcile_ai.golden(engines=["gpt"], limits={"openai": Decimal("0.01")}, use_cache=cache,
                                          out_dir=isolated),
    ]
    for run in runs:
        for cache in (True, False):
            with pytest.raises(_Stop):
                run(cache)
    assert seen == [True, False] * len(runs)
