"""An OpenAI answer cut off at its output cap ends the call at once, and a failed call keeps what it cost (167, review
AI-7; 231, stage D, D-h: shared).

Plain-language summary: an answer that stops at its output token cap is cut-off JSON; asked again, it would stop at the
same place and be paid again, so the model wrapper ends the call at once instead of Pydantic AI's validation retries,
carrying the cut answer's model and usage. A call that fails after an answer came back (cut off, or not of the asked
form with no request left for a retry) was paid for: `paid` sums the usage of every answer of the run, so the call log
settles it at that cost instead of its reserved maximum, and `retry_reason` names why the answer was not taken. The
extraction (167) and every structured answer of `jav/ai/gpt_answer.py` (the rule proposals, D-h) use it.

Layer: AI adapter (OpenAI through pydantic_ai).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic_ai.messages import ModelRequest, ModelResponse, RetryPromptPart
from pydantic_ai.models.wrapper import WrapperModel

from jav.core import calls


class OutputTruncated(RuntimeError):
    """167 (review AI-7): the answer stopped at its output cap (finish reason `length`), so its JSON is cut off. Asked
    again, it would stop at the same place and be paid again, so it is not retried. Carries the cut answer's model and
    usage, for the ledger."""

    def __init__(self, model_name: str | None, usage: Any) -> None:
        super().__init__("the answer reached its output token cap and was cut off")
        self.model_name = model_name
        self.usage = usage


class StopOnTruncation(WrapperModel):
    """167 (review AI-7): the model, unchanged on the wire. An answer cut off at the output cap ends the run at once
    (`OutputTruncated`), instead of Pydantic AI's validation retries, each a paid request that would be cut off again."""

    async def request(self, messages, model_settings, model_request_parameters):
        response = await super().request(messages, model_settings, model_request_parameters)
        if response.finish_reason == "length":
            raise OutputTruncated(response.model_name, response.usage)
        return response


def paid(messages: list[Any], exc: BaseException, *, requested: str) -> calls.Outcome | None:
    """202, D-h: what a failed run certainly cost: every answer it got (the run's captured messages) and a cut-off
    one; None when it got none (nothing certain: the call log keeps its maximum) or a price is not known."""
    from jav.core.config import openai_cost

    usages = [m.usage for m in messages if isinstance(m, ModelResponse)]
    if isinstance(exc, OutputTruncated):
        usages.append(exc.usage)
    if not usages:
        return None
    actual = next((m.model_name for m in reversed(messages) if isinstance(m, ModelResponse) and m.model_name), None)
    actual = (exc.model_name if isinstance(exc, OutputTruncated) and exc.model_name else actual) or requested
    costs = [openai_cost(u, requested=requested, actual=actual) for u in usages]
    if any(c is None for c in costs):
        return None
    return calls.Outcome(response=None, model=actual, input_tokens=sum(getattr(u, "input_tokens", 0) or 0 for u in usages),
                         output_tokens=sum(getattr(u, "output_tokens", 0) or 0 for u in usages),
                         cost_usd=sum(costs, Decimal(0)))


def retry_reason(messages: list[Any]) -> str | None:
    """D-h: why the last answer was not taken, as Pydantic AI asked for a retry (its validation errors), cut short; None
    when it asked for none."""
    for m in reversed(messages):
        if isinstance(m, ModelRequest):
            parts = [p for p in m.parts if isinstance(p, RetryPromptPart)]
            if parts:
                text = parts[-1].model_response() if hasattr(parts[-1], "model_response") else str(parts[-1].content)
                return " ".join(str(text).split())[:300]
    return None


__all__ = ["OutputTruncated", "StopOnTruncation", "paid", "retry_reason"]
