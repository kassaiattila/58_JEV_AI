"""231 (stage D, D-h): a structured GPT answer that fails after an answer came back is settled at what it cost.

The first paid round of rule proposals stopped at its first call: the answer was not taken and no request was left for
a retry, and the call log kept its reserved maximum with no reason. Now an answer cut off at its output cap ends the
call at once (no paid retries that would be cut off again), and a failed call that got an answer is settled at that
answer's cost, with why it was not taken in the ledger. A stand-in model (Pydantic AI's function model); no call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from jav.ai import gpt_answer, output_cap
from jav.core import calls, store
from jav.core.config import OPENAI_MODEL


class _Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rules: list[str]


def _agent_answering(text: str, *, finish: str = "stop"):
    def respond(_messages, _info):
        return ModelResponse(parts=[TextPart(text)], model_name=OPENAI_MODEL, finish_reason=finish,
                             usage=RequestUsage(input_tokens=1000, output_tokens=2000))

    return lambda output_model, instructions: Agent(output_cap.StopOnTruncation(FunctionModel(respond)),
                                                    output_type=NativeOutput(output_model), instructions=instructions,
                                                    retries=2)  # as the live agent: retries left, requests not


@pytest.fixture()
def budget(tmp_path):
    with store.use_store(tmp_path / "answers.sqlite"), calls.measurement("answers", {"openai": Decimal("1")}):
        yield


def _call_row() -> dict:
    with store.connect() as c:
        return dict(c.execute("SELECT status, cost_usd, cost_known, input_tokens, output_tokens FROM invocations").fetchone())


def _ledger_error() -> str:
    with store.connect() as c:
        return c.execute("SELECT error FROM ledger ORDER BY rowid DESC LIMIT 1").fetchone()["error"]


def test_an_answer_cut_off_at_its_cap_ends_the_call_at_once_and_is_settled_at_its_cost(budget) -> None:
    with gpt_answer.use_agent_factory(_agent_answering('{"rules": ["a", "b"', finish="length")):
        with pytest.raises(output_cap.OutputTruncated):
            gpt_answer.ask("invented", "a question", _Answer, instructions="answer", max_output_tokens=2000, run_id="r1")
    row = _call_row()
    assert (row["status"], row["cost_known"], row["input_tokens"], row["output_tokens"]) == ("failed", 1, 1000, 2000)
    assert Decimal(row["cost_usd"]) > 0 and _ledger_error() == "OutputTruncated"


def test_an_answer_of_another_form_with_no_request_left_is_settled_with_why(budget, monkeypatch) -> None:
    from jav.core import config

    monkeypatch.setitem(config.OPENAI_SETTINGS, "retries", 0)  # one request: no room for a retry
    with gpt_answer.use_agent_factory(_agent_answering("not the asked form")):
        with pytest.raises(Exception) as caught:
            gpt_answer.ask("invented", "a question", _Answer, instructions="answer", max_output_tokens=2000, run_id="r2")
    assert type(caught.value).__name__ == "UsageLimitExceeded"
    row = _call_row()
    assert (row["status"], row["cost_known"], row["input_tokens"]) == ("failed", 1, 1000)
    assert _ledger_error().startswith("UsageLimitExceeded: ")
