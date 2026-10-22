"""149 (backlog Q-run-reservation-G; DECISIONS 149): a GPT call that no longer fits its full reservation is sent lean.

Before it is sent, a GPT call reserves its worst case (075, S02): the input counted as one token per byte, the output
limit, and Pydantic AI's validation retries, each carrying the earlier answers. For a G-path extraction that is about
0.094 USD, while a real call costs about 0.002-0.006 USD. With a tight run budget, the last 0.094 USD or so could never
be used: in a 148 run, 23 of 43 documents stopped at 'budget exceeded' with most of the budget unspent. Now, when the
full reservation does not fit what is left, the call is sent with a lean bound: one request, no validation retry. That
is still a true bound, so the budget is never exceeded. A validation error then fails the call (a to-do) instead of
being retried, and the call log marks the call as lean.

Stand-in models only; no paid call.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from jav import extract_llm, gpt_choice, store
from jav.runtime import calls
from jav.typepack import get as get_pack
from tests.test_gpt_extract_logprobs_091 import _LogprobAgent
from tests.test_no_jev_085 import GOOD

FULL, LEAN = Decimal("0.09"), Decimal("0.02")


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield tmp_path


def _outcome(tag: str) -> calls.Outcome:
    return calls.Outcome(response={"tag": tag}, model="m", input_tokens=1, output_tokens=1, cost_usd=Decimal("0.001"))


def _invoke(step: str, sent: list[str], *, lean: bool = True) -> calls.Result:
    return calls.invoke(run_id="run-a", step_id=step, provider="openai", model="m", max_cost_usd=FULL, budget_scope="run-a",
                        fn=lambda: sent.append("full") or _outcome("full"),
                        lean=(LEAN, lambda: sent.append("lean") or _outcome("lean")) if lean else None)


def _row(step: str) -> dict:
    with store.connect() as c:
        return dict(c.execute("SELECT max_cost_usd, note, status FROM invocations WHERE step_id=?", (step,)).fetchone())


def test_the_full_bound_is_used_while_it_fits(isolated):
    calls.set_budget("run-a", "openai", Decimal("1"))
    sent: list[str] = []
    assert _invoke("s1", sent).response == {"tag": "full"} and sent == ["full"]
    assert _row("s1") == {"max_cost_usd": "0.09", "note": None, "status": "succeeded"}


def test_the_lean_bound_is_used_when_only_it_fits(isolated):
    calls.set_budget("run-a", "openai", Decimal("0.05"))
    sent: list[str] = []
    assert _invoke("s1", sent).response == {"tag": "lean"} and sent == ["lean"]
    assert _row("s1") == {"max_cost_usd": "0.02", "note": calls.LEAN_NOTE, "status": "succeeded"}


def test_nothing_is_sent_when_neither_bound_fits(isolated):
    calls.set_budget("run-a", "openai", Decimal("0.01"))
    sent: list[str] = []
    with pytest.raises(calls.BudgetExceeded):
        _invoke("s1", sent)
    assert sent == []


def test_a_call_without_a_lean_bound_still_stops(isolated):
    calls.set_budget("run-a", "openai", Decimal("0.05"))
    sent: list[str] = []
    with pytest.raises(calls.BudgetExceeded):
        _invoke("s1", sent, lean=False)
    assert sent == []


def test_a_tight_budget_is_used_up_by_lean_calls(isolated):
    calls.set_budget("run-a", "openai", Decimal("0.10"))
    sent: list[str] = []
    for n in range(40):  # each call settles at 0.001, far below its reservation
        _invoke(f"s{n}", sent)
    # the full bound fits while 0.001 * n + 0.09 <= 0.10; before 149 the 12th call was refused
    assert sent == ["full"] * 11 + ["lean"] * 29
    with store.connect() as c:
        assert calls._committed(c, "run-a", "openai") == Decimal("0.040") <= Decimal("0.10")


class _Recording(_LogprobAgent):
    def __init__(self, pack, values):
        super().__init__(pack, values)
        self.limits: list[int] = []

    def run_sync(self, prompt, **kw):
        self.limits.append(kw["usage_limits"].request_limit)
        return super().run_sync(prompt, **kw)


@pytest.mark.parametrize("budget, request_limit", [("1", 3), ("0.05", 1)])
def test_the_extraction_sends_one_request_only_when_lean(isolated, budget, request_limit):
    calls.set_budget("run-a", "openai", Decimal(budget))
    agents: list[_Recording] = []

    def factory(pack):
        agents.append(_Recording(pack, GOOD))
        return agents[-1]

    with extract_llm.use_agent_factory(factory), calls.use_run(budget_scope="run-a"):
        extract_llm.extract_scored("Synthetic invoice text.", pack=get_pack("invoice_hu"), run_id="run-a")
    assert agents[0].limits == [request_limit]


@pytest.mark.parametrize("budget, request_limit", [("1", 3), ("0.002", 1)])
def test_a_gpt_question_sends_one_request_only_when_lean(isolated, budget, request_limit):
    calls.set_budget("run-a", "openai", Decimal(budget))
    seen: list[int] = []

    class Agent:
        def __init__(self, output_model):
            self.output_model = output_model

        def run_sync(self, prompt, **kw):
            from types import SimpleNamespace

            seen.append(kw["usage_limits"].request_limit)
            return SimpleNamespace(output=self.output_model(kind="a"), usage=SimpleNamespace(input_tokens=10, output_tokens=2),
                                   response=SimpleNamespace(model_name="gpt-5.4-mini", provider_details={}))

    limits = gpt_choice.Limits(config_hash="h", max_output_tokens=50, top_logprobs=0)
    with gpt_choice.use_agent_factory(lambda model, _instructions: Agent(model)), calls.use_run(budget_scope="run-a"):
        gpt_choice.ask("q", "Pick one.", "Synthetic text.", {"kind": ["a", "b"]}, run_id="run-a", limits=limits)
    assert seen == [request_limit]
