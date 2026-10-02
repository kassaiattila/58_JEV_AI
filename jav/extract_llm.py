"""G path, step 1: generative extraction with Pydantic AI (OpenAI gpt-5.4-mini), using the legacy prompt verbatim.

The output is a dict following the type pack's schema: for the Hungarian invoice it is `InvoiceLLM` (a 1:1 mirror of the
legacy schema.json), for other types the Pydantic model generated from the pack's `schema_file`
(`typepack.TypePack.llm_model`). The legacy flow also sent the PDF/image to the model; here only the text layer goes -
so it is not directly comparable with the legacy golden floor.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModelSettings
from pydantic_ai.usage import UsageLimits

from jav import store
from jav.runtime import calls
from jav.config import OPENAI_MODEL, OPENAI_SETTINGS, OPENAI_USD_PER_MTOK, load_prompt, openai_chat_model, openai_price
from jav.typepack import DEFAULT_KEY, TypePack, get as get_pack

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

USER_PREFIX = "SOURCE TEXT extracted from the invoice PDF (layout-preserving, one line per printed line):\n\n"

_agent_factory = ContextVar('extraction_agent_factory', default=None)


@contextmanager
def use_agent_factory(factory):
    """A model dependency limited to one round; the usual client and cache are unchanged."""
    token = _agent_factory.set(factory)
    try:
        yield
    finally:
        _agent_factory.reset(token)


@lru_cache(maxsize=None)
def get_agent(pack_key: str = DEFAULT_KEY) -> Agent[None, BaseModel]:
    pack = get_pack(pack_key)
    model = openai_chat_model()
    # The legacy sidecar setting: reasoning none, temperature 0 (we measure non-determinism, we do not fight it)
    settings = OpenAIChatModelSettings(openai_reasoning_effort=OPENAI_SETTINGS["reasoning_effort"], temperature=OPENAI_SETTINGS["temperature"])
    return Agent(model, output_type=pack.llm_model(), instructions=load_prompt(pack.prompt_file), model_settings=settings, retries=OPENAI_SETTINGS["retries"])


# In a worker run (040 K1) the output and the number of physical requests are actually limited, so the reserved
# maximum is a guarantee.
RUN_MAX_OUTPUT_TOKENS = 4000


def _price_for(actual_model: str | None) -> tuple[float, float] | None:
    """A price only if the response's model is the configured model (or its dated variant); otherwise unknown."""
    price = OPENAI_USD_PER_MTOK.get(OPENAI_MODEL)
    if price is None or actual_model is None or not re.fullmatch(re.escape(OPENAI_MODEL) + r"(-\d{4}-\d{2}-\d{2})?", actual_model):
        return None
    return price


def _physical(agent, prompt: str, *, run_id: str, pack: TypePack, limited: bool) -> calls.Outcome:
    """One `run_sync` (including Pydantic AI's validation retries). Errors go into the ledger too (F05)."""
    t0 = time.perf_counter()
    kwargs: dict[str, Any] = {}
    if limited:
        kwargs = {"model_settings": {"max_tokens": RUN_MAX_OUTPUT_TOKENS},
                  "usage_limits": UsageLimits(request_limit=1 + int(OPENAI_SETTINGS["retries"]))}
    try:
        result = agent.run_sync(prompt, **kwargs)
    except Exception as exc:
        store.ledger_add(run_id=run_id, step="extract_llm", provider="openai", model=OPENAI_MODEL, input_tokens=None,
                         output_tokens=None, cost_usd=None, seconds=round(time.perf_counter() - t0, 3),
                         config_hash=pack.config_hash, error=type(exc).__name__)
        raise
    usage = result.usage() if callable(result.usage) else result.usage  # pydantic-ai: it was a method, newer versions have a property
    in_tok, out_tok = usage.input_tokens or 0, usage.output_tokens or 0
    actual = getattr(getattr(result, "response", None), "model_name", None) or OPENAI_MODEL
    price = _price_for(actual)
    cost = None if price is None else round((in_tok * price[0] + out_tok * price[1]) / 1_000_000, 6)
    store.ledger_add(
        run_id=run_id,
        step="extract_llm",
        provider="openai",
        model=actual,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=cost,
        seconds=round(time.perf_counter() - t0, 3),
        config_hash=pack.config_hash,
    )
    return calls.Outcome(response=result.output.model_dump(mode="json"), model=actual, input_tokens=in_tok,
                         output_tokens=out_tok, cost_usd=None if cost is None else Decimal(str(cost)))


def extract(text: str, *, run_id: str = "adhoc", pack: TypePack | None = None) -> dict[str, Any]:
    """The extract as a dict (with the keys of the pack's schema); the call goes into the ledger (tokens, cost, time,
    errors too).

    In a worker run it goes through the call log and the budget: an up-front reservation for the worst case, the saved
    answer on a repeat, and no automatic new paid request after an earlier attempt with an uncertain outcome.
    """
    pack = pack or get_pack(DEFAULT_KEY)
    factory = _agent_factory.get()
    agent = factory(pack) if factory is not None else get_agent(pack.key)
    prompt = USER_PREFIX + text
    ctx = calls.current()
    if ctx is None:
        return _physical(agent, prompt, run_id=run_id, pack=pack, limited=False).response
    price = openai_price(OPENAI_MODEL)  # 066 Á38: no budgeted call without a price (the reservation would be zero)
    schema = json.dumps(pack.llm_model().model_json_schema(), ensure_ascii=False)  # sent as the output tool's schema
    max_cost = calls.estimate_max_cost(
        input_bytes=calls.utf8_bytes(prompt, load_prompt(pack.prompt_file), schema), max_output_tokens=RUN_MAX_OUTPUT_TOKENS,
        usd_per_mtok=(Decimal(str(price[0])), Decimal(str(price[1]))), rounds=1 + int(OPENAI_SETTINGS["retries"]),
        repeats=1 + int(OPENAI_SETTINGS["sdk_max_retries"]))
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    # 090: the question's fingerprint for reusing an earlier answer (the step id keeps the text's own digest)
    key = calls.answer_key("openai", OPENAI_MODEL, load_prompt(pack.prompt_file), schema,
                           json.dumps(OPENAI_SETTINGS, sort_keys=True), str(RUN_MAX_OUTPUT_TOKENS), prompt)
    result = calls.invoke(run_id=run_id, step_id=f"openai:extract_llm:{pack.key}:{digest[:16]}", provider="openai",
                          model=OPENAI_MODEL, max_cost_usd=max_cost, budget_scope=ctx.budget_scope, request_hash=key,
                          reusable=True, fn=lambda: _physical(agent, prompt, run_id=run_id, pack=pack, limited=True))
    return result.response
