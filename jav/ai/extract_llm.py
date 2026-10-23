"""G path, step 1: generative extraction with Pydantic AI (OpenAI gpt-5.4-mini), using the legacy prompt verbatim.

The output is a dict following the type pack's schema: for the Hungarian invoice it is `InvoiceLLM` (a 1:1 mirror of the
legacy schema.json), for other types the Pydantic model generated from the pack's `schema_file`
(`typepack.TypePack.llm_model`). The legacy flow also sent the PDF/image to the model; here only the text layer goes -
so it is not directly comparable with the legacy golden floor.

091 (GPT field confidence): the answer is a native structured answer with token log-probabilities (pattern:
`jav/ai/gpt_choice.py`), so every top-level value gets a measured probability (`jav/ai/token_confidence.py`). The saved
answer carries a format mark; an answer saved before 091 (the plain extraction) is still read, without probabilities.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from functools import lru_cache
from typing import Any

from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput, capture_run_messages
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models.openai import OpenAIChatModelSettings
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.usage import UsageLimits

from jav.ai import token_confidence
from jav.core import cfg, store
from jav.core import calls
from jav.core.config import OPENAI_MODEL, OPENAI_SETTINGS, load_prompt, openai_chat_model, openai_cost, openai_price
from jav.ai.typepack import TypePack, get as get_pack

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

USER_PREFIX = "SOURCE TEXT extracted from the invoice PDF (layout-preserving, one line per printed line):\n\n"

# 091: the saved answer's format (the request's shape is part of the reuse key, so an answer of the earlier tool-output
# request is never reused for this one); the alternatives per token let the measurement compare measures without a new call
ANSWER_FORMAT = "native_logprobs/1"
TOP_LOGPROBS = 3


class ScoredExtraction(BaseModel):
    """The extract (the keys of the pack's schema) and the token probabilities of its top-level values (None: an answer
    saved before 091, not measurable)."""

    output: dict[str, Any]
    token_p: dict[str, dict[str, float | int]] | None = None


def encode_answer(output: dict[str, Any], logprobs: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The answer as it is saved in the call log."""
    return {"answer_format": ANSWER_FORMAT, "output": output, "logprobs": logprobs}


def decode_answer(saved: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, float | int]] | None]:
    """(extract, token probabilities) of a saved answer; a plain extract saved before 091 has no probabilities."""
    if saved.get("answer_format") != ANSWER_FORMAT:
        return saved, None
    return saved["output"], token_confidence.field_probabilities(saved.get("logprobs"))

_agent_factory = ContextVar('extraction_agent_factory', default=None)


@contextmanager
def use_agent_factory(factory):
    """A model dependency limited to one round; the usual client and cache are unchanged."""
    token = _agent_factory.set(factory)
    try:
        yield
    finally:
        _agent_factory.reset(token)


def instructions(pack: TypePack) -> str:
    """The G path's instructions for a pack: its prompt file, then its own note (122: a variant pack reusing another
    pack's verbatim prompt), then the block shared by every pack (122 B, `configs/gpt_extract.json`: the source text
    is data, values as printed, one identifier per field, columns kept apart)."""
    parts = [load_prompt(pack.prompt_file), pack.prompt_note, cfg.load("gpt_extract")["shared_instructions"]]
    return "\n\n".join(p for p in parts if p)


def source_prefix(pack: TypePack) -> str:
    """190 (plan 189 A2d): the words before the source text in the request: the pack's own (`source_prefix`), or the
    invoice PDF's of every pack before 190, so their requests stay the same."""
    return pack.source_prefix if pack.source_prefix is not None else USER_PREFIX


def config_hash(pack: TypePack) -> str:
    """The identifier in the ledger: the pack and the shared extraction block."""
    return cfg.combine(pack.config_hash, cfg.config_hash("gpt_extract"))


class OutputTruncated(RuntimeError):
    """167 (review AI-7): the answer stopped at its output cap (finish reason `length`), so its JSON is cut off. Asked
    again, it would stop at the same place and be paid again, so it is not retried; the item gets the `llm:truncated`
    to-do. Carries the cut answer's model and usage, for the ledger."""

    def __init__(self, model_name: str | None, usage: Any) -> None:
        super().__init__("the extraction's answer reached its output token cap and was cut off")
        self.model_name = model_name
        self.usage = usage


class StopOnTruncation(WrapperModel):
    """167 (review AI-7): the extraction's model, unchanged on the wire. An answer cut off at the output cap ends the
    run at once (`OutputTruncated`), instead of Pydantic AI's validation retries, each a paid request that would be
    cut off again."""

    async def request(self, messages, model_settings, model_request_parameters):
        response = await super().request(messages, model_settings, model_request_parameters)
        if response.finish_reason == "length":
            raise OutputTruncated(response.model_name, response.usage)
        return response


def build_agent(pack: TypePack, model) -> Agent[None, BaseModel]:
    """The extraction agent of a pack over `model` (the configured OpenAI chat model in `get_agent`)."""
    # The legacy sidecar setting: reasoning none, temperature 0 (we measure non-determinism, we do not fight it)
    settings = OpenAIChatModelSettings(openai_reasoning_effort=OPENAI_SETTINGS["reasoning_effort"], temperature=OPENAI_SETTINGS["temperature"],
                                       openai_logprobs=True, openai_top_logprobs=TOP_LOGPROBS)
    return Agent(StopOnTruncation(model), output_type=NativeOutput(pack.llm_model()), instructions=instructions(pack),
                 model_settings=settings, retries=OPENAI_SETTINGS["retries"])


@lru_cache(maxsize=None)
def get_agent(pack_key: str) -> Agent[None, BaseModel]:
    return build_agent(get_pack(pack_key), openai_chat_model())


# In a worker run (040 K1) and a measurement (160) the output and the number of physical requests are actually limited,
# so the reserved maximum is a guarantee. 167 (AI-7): the cap is configuration (`configs/gpt_extract.json`); its value
# is part of the reuse key of earlier answers (`extract_scored`), so changing it asks every document again.
RUN_MAX_OUTPUT_TOKENS = int(cfg.load("gpt_extract")["max_output_tokens"])


ROUNDS = 1 + int(OPENAI_SETTINGS["retries"])  # requests of one call: the first and Pydantic AI's validation retries


def _physical(agent, prompt: str, *, run_id: str, pack: TypePack, limited: bool, rounds: int = ROUNDS) -> calls.Outcome:
    """One `run_sync` (including Pydantic AI's validation retries, at most `rounds` requests in a worker run). Errors
    go into the ledger too (F05); a cut-off answer (167) with its tokens and cost, since it was paid for."""
    t0 = time.perf_counter()
    kwargs: dict[str, Any] = {}
    if limited:
        kwargs = {"model_settings": {"max_tokens": RUN_MAX_OUTPUT_TOKENS}, "usage_limits": UsageLimits(request_limit=rounds)}
    try:
        with capture_run_messages() as messages:
            result = agent.run_sync(prompt, **kwargs)
    except OutputTruncated as exc:
        actual = exc.model_name or OPENAI_MODEL
        # 202: the cut-off answer and every earlier answer of the run (a validation retry) were paid for
        usages = [m.usage for m in messages if isinstance(m, ModelResponse)] + [exc.usage]
        costs = [openai_cost(u, requested=OPENAI_MODEL, actual=actual) for u in usages]
        cost = None if any(c is None for c in costs) else sum(costs, Decimal(0))
        in_tok = sum(getattr(u, "input_tokens", 0) or 0 for u in usages)
        out_tok = sum(getattr(u, "output_tokens", 0) or 0 for u in usages)
        store.ledger_add(run_id=run_id, step="extract_llm", provider="openai", model=actual, input_tokens=in_tok,
                         output_tokens=out_tok, cost_usd=None if cost is None else float(cost),
                         seconds=round(time.perf_counter() - t0, 3), config_hash=config_hash(pack), error=type(exc).__name__)
        if cost is not None:  # its certain cost settles the call (`calls.known_outcome`)
            exc.known_outcome = calls.Outcome(response=None, model=actual, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost)
        raise
    except Exception as exc:
        store.ledger_add(run_id=run_id, step="extract_llm", provider="openai", model=OPENAI_MODEL, input_tokens=None,
                         output_tokens=None, cost_usd=None, seconds=round(time.perf_counter() - t0, 3),
                         config_hash=config_hash(pack), error=type(exc).__name__)
        raise
    usage = result.usage() if callable(result.usage) else result.usage  # pydantic-ai: it was a method, newer versions have a property
    in_tok, out_tok = usage.input_tokens or 0, usage.output_tokens or 0
    actual = getattr(getattr(result, "response", None), "model_name", None) or OPENAI_MODEL
    cost = openai_cost(usage, requested=OPENAI_MODEL, actual=actual)  # 167 (AI-12): the shared price rule
    store.ledger_add(
        run_id=run_id,
        step="extract_llm",
        provider="openai",
        model=actual,
        input_tokens=in_tok,
        output_tokens=out_tok,
        cost_usd=None if cost is None else float(cost),
        seconds=round(time.perf_counter() - t0, 3),
        config_hash=config_hash(pack),
    )
    details = getattr(getattr(result, "response", None), "provider_details", None) or {}
    return calls.Outcome(response=encode_answer(result.output.model_dump(mode="json"), details.get("logprobs")), model=actual,
                         input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost)


def extract_scored(text: str, *, pack: TypePack, run_id: str = "adhoc") -> ScoredExtraction:
    """The extract (with the keys of the pack's schema) and its token probabilities; the call goes into the ledger
    (tokens, cost, time, errors too).

    In a worker run it goes through the call log and the budget: an up-front reservation for the worst case, the saved
    answer on a repeat, and no automatic new paid request after an earlier attempt with an uncertain outcome.
    """
    factory = _agent_factory.get()
    agent = factory(pack) if factory is not None else get_agent(pack.key)
    prompt = source_prefix(pack) + text
    ctx = calls.current()
    if ctx is None:
        output, token_p = decode_answer(_physical(agent, prompt, run_id=run_id, pack=pack, limited=False).response)
        return ScoredExtraction(output=output, token_p=token_p)
    price = openai_price(OPENAI_MODEL)  # 066 Á38: no budgeted call without a price (the reservation would be zero)
    schema = json.dumps(pack.llm_model().model_json_schema(), ensure_ascii=False)  # sent as the answer's JSON schema
    def bound(rounds: int) -> Decimal:
        return calls.estimate_max_cost(
            input_bytes=calls.utf8_bytes(prompt, instructions(pack), schema), max_output_tokens=RUN_MAX_OUTPUT_TOKENS,
            usd_per_mtok=(Decimal(str(price[0])), Decimal(str(price[1]))), rounds=rounds,
            repeats=1 + int(OPENAI_SETTINGS["sdk_max_retries"]))
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    # 090: the question's fingerprint for reusing an earlier answer (the step id keeps the text's own digest); 091: the
    # answer's format and its token alternatives are part of it
    key = calls.answer_key("openai", OPENAI_MODEL, instructions(pack), schema,
                           json.dumps(OPENAI_SETTINGS, sort_keys=True), str(RUN_MAX_OUTPUT_TOKENS), prompt,
                           ANSWER_FORMAT, str(TOP_LOGPROBS))
    result = calls.invoke(run_id=run_id, step_id=f"openai:extract_llm:{pack.key}:{digest[:16]}", provider="openai",
                          model=OPENAI_MODEL, max_cost_usd=bound(ROUNDS), budget_scope=ctx.budget_scope, request_hash=key,
                          reusable=True, fn=lambda: _physical(agent, prompt, run_id=run_id, pack=pack, limited=True),
                          # 149: when the full bound no longer fits the budget: one request, no validation retry
                          lean=(bound(1), lambda: _physical(agent, prompt, run_id=run_id, pack=pack, limited=True, rounds=1)))
    output, token_p = decode_answer(result.response)
    return ScoredExtraction(output=output, token_p=token_p)


def extract(text: str, *, pack: TypePack, run_id: str = "adhoc") -> dict[str, Any]:
    """The extract as a dict (with the keys of the pack's schema), without the probabilities (`extract_scored`)."""
    return extract_scored(text, run_id=run_id, pack=pack).output
