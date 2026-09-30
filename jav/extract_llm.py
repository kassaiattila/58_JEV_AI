"""G-kar, 1. lépés: generatív kivonatolás Pydantic AI-jal (OpenAI gpt-5.4-mini), a régi prompt szó szerint.

A kimenet a típus-csomag sémája szerinti szótár: a magyar számlánál az `InvoiceLLM` (a régi schema.json 1:1 tükre),
más típusnál a csomag `schema_file`-jából generált Pydantic-modell (`typepack.TypePack.llm_model`). A régi flow a
PDF-et/képet is elküldte a modellnek; itt csak a szövegréteg megy - a régi golden floorral ezért nem 1:1 összevethető.
"""

from __future__ import annotations

import hashlib
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
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from jav import store
from jav.runtime import calls
from jav.config import OPENAI_MODEL, OPENAI_SETTINGS, OPENAI_USD_PER_MTOK, get_openai_key, load_prompt, openai_price
from jav.typepack import DEFAULT_KEY, TypePack, get as get_pack

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

USER_PREFIX = "SOURCE TEXT extracted from the invoice PDF (layout-preserving, one line per printed line):\n\n"

_agent_factory = ContextVar('extraction_agent_factory', default=None)


@contextmanager
def use_agent_factory(factory):
    """Körre korlátozott modellfüggőség; a szokásos kliens és cache változatlan."""
    token = _agent_factory.set(factory)
    try:
        yield
    finally:
        _agent_factory.reset(token)


@lru_cache(maxsize=None)
def get_agent(pack_key: str = DEFAULT_KEY) -> Agent[None, BaseModel]:
    pack = get_pack(pack_key)
    model = OpenAIChatModel(OPENAI_MODEL, provider=OpenAIProvider(api_key=get_openai_key()))
    # A régi sidecar-beállítás: reasoning none, temperature 0 (a nem-determinizmust mérjük, nem harcolunk vele)
    settings = OpenAIChatModelSettings(openai_reasoning_effort=OPENAI_SETTINGS["reasoning_effort"], temperature=OPENAI_SETTINGS["temperature"])
    return Agent(model, output_type=pack.llm_model(), instructions=load_prompt(pack.prompt_file), model_settings=settings, retries=OPENAI_SETTINGS["retries"])


# Feldolgozói futásban (040 K1) a kimenet és a fizikai kérések száma ténylegesen korlátozott, így a foglalt maximum garancia.
RUN_MAX_OUTPUT_TOKENS = 4000


def _price_for(actual_model: str | None) -> tuple[float, float] | None:
    """Ár csak akkor, ha a válasz modellje a konfigurált modell (vagy annak dátumos változata); különben ismeretlen."""
    price = OPENAI_USD_PER_MTOK.get(OPENAI_MODEL)
    if price is None or actual_model is None or not re.fullmatch(re.escape(OPENAI_MODEL) + r"(-\d{4}-\d{2}-\d{2})?", actual_model):
        return None
    return price


def _physical(agent, prompt: str, *, run_id: str, pack: TypePack, limited: bool) -> calls.Outcome:
    """Egy `run_sync` (a Pydantic AI validációs újrapróbálásai is benne). Hiba is a ledgerbe kerül (F05)."""
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
    usage = result.usage() if callable(result.usage) else result.usage  # pydantic-ai: metódus volt, újabb verzióban property
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
    """A kivonat szótárként (a csomag sémájának kulcsaival); a hívás a ledgerbe kerül (token, költség, idő, hiba is).

    Feldolgozói futásban a hívásnaplón és a kereten át megy: előzetes foglalás a legrosszabb esetre, ismétlésnél a
    mentett válasz, bizonytalan korábbi kísérletnél nincs automatikus új fizetős kérés.
    """
    pack = pack or get_pack(DEFAULT_KEY)
    factory = _agent_factory.get()
    agent = factory(pack) if factory is not None else get_agent(pack.key)
    prompt = USER_PREFIX + text
    ctx = calls.current()
    if ctx is None:
        return _physical(agent, prompt, run_id=run_id, pack=pack, limited=False).response
    price = openai_price(OPENAI_MODEL)  # 066 Á38: ár nélkül nincs keret alatti hívás (a foglalás nulla lenne)
    max_cost = calls.estimate_max_cost(
        input_chars=len(prompt) + len(load_prompt(pack.prompt_file)), max_output_tokens=RUN_MAX_OUTPUT_TOKENS,
        usd_per_mtok=(Decimal(str(price[0])), Decimal(str(price[1]))), physical_attempts=1 + int(OPENAI_SETTINGS["retries"]))
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    result = calls.invoke(run_id=run_id, step_id=f"openai:extract_llm:{pack.key}:{digest[:16]}", provider="openai",
                          model=OPENAI_MODEL, max_cost_usd=max_cost, budget_scope=ctx.budget_scope, request_hash=digest,
                          fn=lambda: _physical(agent, prompt, run_id=run_id, pack=pack, limited=True))
    return result.response
