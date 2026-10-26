"""One structured answer from GPT, through the call log and a budget (231, stage D, D-c7c).

Plain-language summary: several places asked GPT for an answer of a given form by hand, each building the model, the
call through the call log and the ledger rows the same way (the quote letter's paragraph, the extraction, the readers).
This module is that one way for a new call site: the model from the shared settings (`configs/models.json`), the
instructions and the answer's form from the call site, the call through the call log under the caller's budget (a
repeated question with the same text returns the saved answer, a sent call with no answer is uncertain), and every
attempt in the ledger, failed ones too. Nothing is asked without a budget. A stand-in model can be put in place for a
block (`use_agent_factory`), so the tests and a free demonstration never reach OpenAI.

- `ask(site, prompt, output_model, instructions=, max_output_tokens=, run_id=, config_hash=)`: the answer, validated.
- `use_agent_factory(factory)`: a stand-in model for a block.

Layer: AI adapter (OpenAI through pydantic_ai) over the call log (`jav/core/calls.py`) and the ledger.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from typing import Any, TypeVar

from pydantic import BaseModel

from jav.core import calls, store
from jav.core.user_messages import explained

__all__ = ["NoBudget", "ask", "use_agent_factory"]

M = TypeVar("M", bound=BaseModel)
_agent_factory: ContextVar[Callable[[type[BaseModel], str], Any] | None] = ContextVar("gpt_answer_agent", default=None)


class NoBudget(RuntimeError):
    """GPT asked outside a budget."""


@contextmanager
def use_agent_factory(factory: Callable[[type[BaseModel], str], Any]) -> Iterator[None]:
    """A stand-in model for one block: `factory(output_model, instructions)` returns an object with `run_sync`."""
    token = _agent_factory.set(factory)
    try:
        yield
    finally:
        _agent_factory.reset(token)


def _agent(output_model: type[BaseModel], instructions: str) -> Any:
    factory = _agent_factory.get()
    if factory is not None:
        return factory(output_model, instructions)
    from pydantic_ai import Agent, NativeOutput
    from pydantic_ai.models.openai import OpenAIChatModelSettings

    from jav.core.config import OPENAI_SETTINGS, openai_chat_model

    model_settings = OpenAIChatModelSettings(openai_reasoning_effort=OPENAI_SETTINGS["reasoning_effort"],
                                             temperature=OPENAI_SETTINGS["temperature"])
    return Agent(openai_chat_model(), output_type=NativeOutput(output_model), instructions=instructions,
                 model_settings=model_settings, retries=OPENAI_SETTINGS["retries"])


def _physical(agent: Any, site: str, prompt: str, *, max_output_tokens: int, run_id: str, rounds: int,
              config_hash: str | None) -> calls.Outcome:
    """One `run_sync` of at most `rounds` requests; into the ledger, errors too."""
    from pydantic_ai.usage import UsageLimits

    from jav.core.config import OPENAI_MODEL, openai_cost

    t0 = time.perf_counter()
    try:
        result = agent.run_sync(prompt, model_settings={"max_tokens": max_output_tokens}, usage_limits=UsageLimits(request_limit=rounds))
    except Exception as exc:
        store.ledger_add(run_id=run_id, step=f"{site}_gpt", provider="openai", model=OPENAI_MODEL, input_tokens=None,
                         output_tokens=None, cost_usd=None, seconds=round(time.perf_counter() - t0, 3),
                         config_hash=config_hash, error=type(exc).__name__)
        raise
    usage = result.usage() if callable(result.usage) else result.usage
    in_tok, out_tok = usage.input_tokens or 0, usage.output_tokens or 0
    actual = getattr(getattr(result, "response", None), "model_name", None) or OPENAI_MODEL
    cost = openai_cost(usage, requested=OPENAI_MODEL, actual=actual)
    store.ledger_add(run_id=run_id, step=f"{site}_gpt", provider="openai", model=actual, input_tokens=in_tok,
                     output_tokens=out_tok, cost_usd=None if cost is None else float(cost),
                     seconds=round(time.perf_counter() - t0, 3), config_hash=config_hash)
    saved = {"output": result.output.model_dump(mode="json"), "model": actual, "input_tokens": in_tok,
             "output_tokens": out_tok, "cost_usd": None if cost is None else float(cost)}
    return calls.Outcome(response=saved, model=actual, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost)


def max_cost(prompt: str, output_model: type[BaseModel], *, instructions: str, max_output_tokens: int, rounds: int = 1) -> Decimal:
    """The most one question can cost: its input, its longest answer, its rounds and the SDK's own retries."""
    from jav.core.config import OPENAI_MODEL, OPENAI_SETTINGS, openai_price

    price = openai_price(OPENAI_MODEL)
    return calls.estimate_max_cost(
        input_bytes=calls.utf8_bytes(prompt, instructions, json.dumps(output_model.model_json_schema())),
        max_output_tokens=max_output_tokens, usd_per_mtok=(Decimal(str(price[0])), Decimal(str(price[1]))),
        rounds=rounds, repeats=1 + int(OPENAI_SETTINGS["sdk_max_retries"]))


def ask(site: str, prompt: str, output_model: type[M], *, instructions: str, max_output_tokens: int, run_id: str,
        config_hash: str | None = None) -> M:
    """GPT's answer of `output_model`'s form to `prompt`, through the call log and the caller's OpenAI budget.
    `NoBudget` outside a budget; `calls.BudgetExceeded` without room in it."""
    from jav.core.config import OPENAI_MODEL, OPENAI_SETTINGS

    ctx = calls.current()
    if ctx is None:
        raise explained(NoBudget, "GPT is asked only under a budget")
    agent = _agent(output_model, instructions)
    rounds = 1 + int(OPENAI_SETTINGS["retries"])
    schema = json.dumps(output_model.model_json_schema())
    digest = hashlib.sha256((instructions + "\0" + prompt).encode("utf-8")).hexdigest()
    key = calls.answer_key("openai", OPENAI_MODEL, instructions, schema, json.dumps(OPENAI_SETTINGS, sort_keys=True),
                           str(max_output_tokens), prompt)

    def run(n: int) -> calls.Outcome:
        return _physical(agent, site, prompt, max_output_tokens=max_output_tokens, run_id=run_id, rounds=n,
                         config_hash=config_hash)

    cost = max_cost(prompt, output_model, instructions=instructions, max_output_tokens=max_output_tokens, rounds=rounds)
    lean = max_cost(prompt, output_model, instructions=instructions, max_output_tokens=max_output_tokens, rounds=1)
    saved = calls.invoke(run_id=run_id, step_id=f"openai:{site}:{digest[:16]}", provider="openai", model=OPENAI_MODEL,
                         max_cost_usd=cost, budget_scope=ctx.budget_scope, request_hash=key, reusable=True,
                         fn=lambda: run(rounds), lean=(lean, lambda: run(1))).response
    return output_model.model_validate(saved["output"])
