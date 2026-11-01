"""265 (code review AI-06): a failed OpenAI call is settled at what it certainly cost, whichever path asked.

The extraction's general error branch wrote no cost and left the whole reservation committed, and the GPT choices
(type, email intent) neither captured the run's answers nor stopped at a cut-off one. One rule now serves them all
(`output_cap.ledger_failure`): the ledger row carries the usage of every answer the run got and why the last was not
taken, and that cost settles the call. The choices' agent ends a cut-off answer at once (`StopOnTruncation`).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.usage import RequestUsage

from jav.ai import gpt_choice, output_cap
from jav.core import store
from jav.core.config import OPENAI_MODEL


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "failed.sqlite"):
        yield tmp_path


def test_a_failure_after_an_answer_carries_its_cost(db) -> None:
    exc = ValueError("the answer did not fit its form")
    answer = ModelResponse([TextPart("{}")], usage=RequestUsage(input_tokens=1000, output_tokens=100), model_name=OPENAI_MODEL)
    output_cap.ledger_failure([answer], exc, run_id="run-x", step="type_gpt", config_hash="h", seconds=0.5)
    assert exc.known_outcome.input_tokens == 1000 and exc.known_outcome.cost_usd > Decimal(0)
    with store.connect() as c:
        row = c.execute("SELECT cost_usd, error FROM ledger WHERE run_id='run-x'").fetchone()
    assert row["cost_usd"] > 0 and row["error"].startswith("ValueError")


def test_a_failure_before_any_answer_keeps_the_reservation(db) -> None:
    exc = ConnectionError("no route")
    output_cap.ledger_failure([], exc, run_id="run-y", step="type_gpt", config_hash="h", seconds=0.1)
    assert not hasattr(exc, "known_outcome")


def test_the_choices_agent_stops_at_a_cut_off_answer(monkeypatch) -> None:
    from pydantic_ai.models.function import FunctionModel

    monkeypatch.setattr(gpt_choice, "openai_chat_model", lambda: FunctionModel(lambda messages, info: None))
    seen = {}
    monkeypatch.setattr(gpt_choice, "Agent", lambda model, **kw: seen.setdefault("model", model))
    with gpt_choice.use_agent_factory(None):  # the real construction, with the model and the agent stood in for
        gpt_choice._agent(type("Out", (), {}), "pick", gpt_choice.Limits(top_logprobs=1, max_output_tokens=10, config_hash="h"))
    assert isinstance(seen["model"], output_cap.StopOnTruncation)


class _Failing:
    """An agent whose run fails after it was asked (as a reply that does not fit its form would)."""

    def run_sync(self, prompt, **_kw):
        raise ValueError("the answer did not fit its form")


@pytest.mark.parametrize("site", ["quote_letter", "email_tasks"])
def test_the_two_own_agents_settle_a_failure_by_the_shared_rule(db, monkeypatch, site) -> None:
    """272 (K3, the check of X-11): the reply letter's paragraph and the email tasks have agents of their own; their
    failure goes through the shared rule (a ledger row with why, the certain cost on the error) and is raised again."""
    from jav.domains.email import email_tasks
    from jav.domains.quotes import quote_letter

    seen: list[tuple[str, BaseException]] = []
    real = output_cap.ledger_failure
    monkeypatch.setattr(output_cap, "ledger_failure", lambda messages, exc, **kw: seen.append((kw["step"], exc)) or real(messages, exc, **kw))
    with pytest.raises(ValueError):
        if site == "quote_letter":
            monkeypatch.setattr(quote_letter, "config_hash", lambda: "h")
            quote_letter._physical(_Failing(), "a prompt", run_id="run-x", rounds=1)
        else:
            email_tasks._physical(_Failing(), "a prompt", run_id="run-x", limited=True)
    assert [step for step, _exc in seen] == [("quote_letter_gpt" if site == "quote_letter" else "email_tasks")]
    with store.connect() as c:
        row = c.execute("SELECT error FROM ledger WHERE run_id='run-x'").fetchone()
    assert row["error"].startswith("ValueError")
