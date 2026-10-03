"""Keep provider receipts even when the business answer fails validation.

These receipts stay in the caller's explicitly selected experiment store. They
are not log messages and do not imply that a returned proposal was accepted.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import ValidationError
from pydantic_ai import capture_run_messages
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.usage import UsageLimits

from jav.extract_llm import _price_for
from jav.runtime import calls


class InterpretationRejected(ValueError):
    """A paid provider answered, but its saved proposal was not valid."""


def _validation_details(error: BaseException) -> list[dict]:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, ValidationError):
            return [{"type": row["type"], "location": list(row["loc"])}
                    for row in error.errors(include_input=False, include_context=False, include_url=False)]
        error = error.__cause__ or error.__context__
    return []


def run_gpt_once(agent, prompt: str, settings: dict, requested_model: str) -> calls.Outcome:
    """One bounded request; retain any rejected, provably received response.

    Transport failures still follow the existing failed/uncertain ledger path.
    A received invalid answer can be replayed without another paid request.
    """
    failure = None
    with capture_run_messages() as messages:
        try:
            answer = agent.run_sync(prompt, model_settings=settings, usage_limits=UsageLimits(request_limit=1))
        except UnexpectedModelBehavior as exc:
            details = _validation_details(exc)
            responses = [m for m in messages if isinstance(m, ModelResponse)]
            # A refusal or empty answer may have no Pydantic validation details.
            # The captured response proves receipt and carries its reported usage.
            if len(responses) != 1:
                raise
            failure = {"type": type(exc).__name__, "validation": details}
        responses = [m for m in messages if isinstance(m, ModelResponse)]
        if failure:
            response = responses[0]
            usage = response.usage
            actual = response.model_name or requested_model
            proposal = None
        else:
            usage = answer.usage() if callable(answer.usage) else answer.usage
            actual = getattr(getattr(answer, "response", None), "model_name", None) or requested_model
            proposal = answer.output.model_dump(mode="json")
        price = _price_for(actual)
        known_usage = not hasattr(usage, "has_values") or usage.has_values()
        cost = None if price is None or not known_usage else (
            Decimal(usage.input_tokens or 0) * Decimal(str(price[0]))
            + Decimal(usage.output_tokens or 0) * Decimal(str(price[1]))) / Decimal(1_000_000)
        return calls.Outcome(response={"proposal": proposal, "actual_model": actual,
            "validation_error": failure,
            "provider_responses": ModelMessagesTypeAdapter.dump_python(responses, mode="json")},
            model=actual, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost_usd=cost)
