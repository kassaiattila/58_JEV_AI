"""Type recognition with GPT, for processing without JEV (086, backlog item F-jev, step K4).

The same three judgements as the JEV detection (`jav/detect.py`), asked of GPT in one structured request:
`doc_type` (the registered types + `unknown`), `issuer_is_hungarian` (yes / no) and `language`. The document excerpt
and the question texts are those of the JEV call site (`callsite:detect`), so the two recognitions are comparable;
each type is offered with the first clause of its registry description (`configs/gpt_detect.json`).

Confidence comes from the token log-probabilities of the answer (temperature 0, top 5 alternatives per token): the
probability of the chosen option is the product of its tokens' probabilities, and an alternative token's branch is
credited to the one option it leads to. This is the model's own distribution, not a calibrated probability like
JEV's, so it has its own band in `configs/policy.json` (`detect.doc_type.gpt`). Without log-probabilities the
confidence is unknown (`measured=False`), never invented. Pattern: the legacy project's
`sidecar/app/detect_engine/service.py` (`compute_detect_margin`) and `orchestrator/framework/sidecar.py` (`detect`).

The detailed type (`choose_detail`) is the same kind of question among the category's type packs, plus `none`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, create_model
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.openai import OpenAIChatModelSettings
from pydantic_ai.usage import UsageLimits

from jav import cfg, store
from jav.config import OPENAI_MODEL, OPENAI_SETTINGS, openai_chat_model, openai_price
from jav.detect import DetectResult, build_state
from jav.doc_types import DOC_TYPES, UNKNOWN
from jav.models import JevCall
from jav.pdf import PdfText
from jav.runtime import calls

_CFG = cfg.load("gpt_detect")
_DETECT = cfg.load("callsite:detect")
CONFIG_HASH = cfg.config_hash("gpt_detect", "callsite:detect", "doc_types")
LANGUAGES: list[str] = list(_DETECT["questions"]["language"]["criteria"])
YES, NO, NONE = "yes", "no", "none"
OTHER_BRANCHES = "(other)"  # probability of alternative branches that do not lead to a single option

_agent_factory: ContextVar = ContextVar("gpt_detect_agent_factory", default=None)


@contextmanager
def use_agent_factory(factory):
    """A stand-in model for one block (tests): `factory(output_model, instructions)` returns an object with `run_sync`."""
    token = _agent_factory.set(factory)
    try:
        yield
    finally:
        _agent_factory.reset(token)


class GptAnswer(BaseModel):
    """One structured GPT answer: per field the chosen value, its confidence (None: not measurable) and the
    probabilities of the options seen."""

    values: dict[str, str]
    confidence: dict[str, float | None]
    probabilities: dict[str, dict[str, float]]
    measured: bool
    call: JevCall


def short_description(text: str) -> str:
    """The first clause of a description (up to the first `:`, `;` or sentence end)."""
    return re.split(r"(?::|;|\.)\s", text.strip(), maxsplit=1)[0].strip()


def _type_lines() -> str:
    lines = [f"- {t.key}: {short_description(t.what)}" for t in DOC_TYPES]
    lines.append(f"- {UNKNOWN}: {short_description(cfg.load('doc_types')['unknown']['what'])}")
    return "\n".join(lines)


def detect_instructions() -> str:
    q = _DETECT["questions"]
    return "\n\n".join([
        _CFG["preamble"],
        f"doc_type: {q['doc_type']['instructions']}\nDocument types:\n{_type_lines()}",
        f"issuer_is_hungarian ({YES} / {NO}): {q['issuer_is_hungarian']['instructions']}",
        f"language ({' / '.join(LANGUAGES)}): {q['language']['instructions']}",
    ])


# --- probability arithmetic on the provider's token log-probabilities -------------------------------------


def _value_span(text: str, field: str) -> tuple[int, int] | None:
    m = re.search(r'"' + re.escape(field) + r'"\s*:\s*"', text)
    if m is None:
        return None
    end = text.find('"', m.end())
    return (m.end(), end) if end >= 0 else None


def _option_of(partial: str, options: list[str]) -> str | None:
    """The single option a partial value leads to (a closing quote ends the value), or None if ambiguous."""
    if '"' in partial:
        value = partial.split('"', 1)[0]
        return value if value in options else None
    hits = [o for o in options if o.startswith(partial)]
    return hits[0] if len(hits) == 1 else None


def field_probabilities(tokens: list[dict[str, Any]], field: str, options: list[str]) -> tuple[str | None, float | None, dict[str, float]]:
    """(chosen value, its probability, probabilities of the options seen) for one string field of the JSON answer.
    Without log-probabilities, or if the field cannot be located in them: (None, None, {}) - not measurable."""
    if not tokens:
        return None, None, {}
    text, starts = "", []
    for t in tokens:
        starts.append(len(text))
        text += t.get("token") or ""
    span = _value_span(text, field)
    if span is None:
        return None, None, {}
    start, end = span
    value = text[start:end]
    cum, probs = 0.0, {}
    for t, s in zip(tokens, starts, strict=True):
        tok = t.get("token") or ""
        if s + len(tok) <= start or s > end:  # outside the value and its closing quote
            continue
        offset = max(0, start - s)
        prefix = text[start:max(start, s)]
        for alt in t.get("top_logprobs") or []:
            alt_tok = alt.get("token") or ""
            if alt_tok == tok or len(alt_tok) < offset or alt_tok[:offset] != tok[:offset]:
                continue
            option = _option_of(prefix + alt_tok[offset:], options)
            if option == value:  # another tokenisation of the same answer
                continue
            key = option or OTHER_BRANCHES
            probs[key] = probs.get(key, 0.0) + math.exp(cum + float(alt["logprob"]))
        cum += float(t.get("logprob") or 0.0)
    confidence = math.exp(cum)
    probs[value] = confidence
    return value, round(confidence, 4), {k: round(v, 4) for k, v in probs.items()}


# --- the call ---------------------------------------------------------------------------------------------


def _output_model(name: str, fields: dict[str, list[str]]) -> type[BaseModel]:
    return create_model(name, **{f: (Literal[tuple(opts)], ...) for f, opts in fields.items()})


def _agent(output_model: type[BaseModel], instructions: str):
    factory = _agent_factory.get()
    if factory is not None:
        return factory(output_model, instructions)
    settings = OpenAIChatModelSettings(openai_reasoning_effort=OPENAI_SETTINGS["reasoning_effort"],
                                       temperature=OPENAI_SETTINGS["temperature"], openai_logprobs=True,
                                       openai_top_logprobs=int(_CFG["top_logprobs"]))
    return Agent(openai_chat_model(), output_type=NativeOutput(output_model), instructions=instructions,
                 model_settings=settings, retries=OPENAI_SETTINGS["retries"])


def _physical(agent, prompt: str, *, run_id: str, step: str, limited: bool) -> calls.Outcome:
    """One `run_sync`; the call goes into the ledger, errors too."""
    t0 = time.perf_counter()
    kwargs: dict[str, Any] = {}
    if limited:
        kwargs = {"model_settings": {"max_tokens": int(_CFG["max_output_tokens"])},
                  "usage_limits": UsageLimits(request_limit=1 + int(OPENAI_SETTINGS["retries"]))}
    try:
        result = agent.run_sync(prompt, **kwargs)
    except Exception as exc:
        store.ledger_add(run_id=run_id, step=step, provider="openai", model=OPENAI_MODEL, input_tokens=None, output_tokens=None,
                         cost_usd=None, seconds=round(time.perf_counter() - t0, 3), config_hash=CONFIG_HASH, error=type(exc).__name__)
        raise
    usage = result.usage() if callable(result.usage) else result.usage
    in_tok, out_tok = usage.input_tokens or 0, usage.output_tokens or 0
    response = getattr(result, "response", None)
    actual = getattr(response, "model_name", None) or OPENAI_MODEL
    from jav.extract_llm import _price_for  # the same price rule as the extraction (dated variant of the model)

    price = _price_for(actual)
    cost = None if price is None else round((in_tok * price[0] + out_tok * price[1]) / 1_000_000, 6)
    store.ledger_add(run_id=run_id, step=step, provider="openai", model=actual, input_tokens=in_tok, output_tokens=out_tok,
                     cost_usd=cost, seconds=round(time.perf_counter() - t0, 3), config_hash=CONFIG_HASH)
    details = getattr(response, "provider_details", None) or {}
    saved = {"output": result.output.model_dump(mode="json"), "logprobs": details.get("logprobs"), "model": actual,
             "input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": cost}
    return calls.Outcome(response=saved, model=actual, input_tokens=in_tok, output_tokens=out_tok,
                         cost_usd=None if cost is None else Decimal(str(cost)))


def ask(request_id: str, instructions: str, prompt: str, fields: dict[str, list[str]], *, run_id: str) -> GptAnswer:
    """One structured GPT question. In a worker run it goes through the call log and the OpenAI budget (reservation for
    the worst case; a repeated step returns the saved answer); without a budget nothing is sent (`BudgetExceeded`)."""
    output_model = _output_model(f"{request_id}_answer", fields)
    agent = _agent(output_model, instructions)
    step = f"{request_id}_gpt"
    t0 = time.perf_counter()
    ctx = calls.current()
    if ctx is None:
        saved = _physical(agent, prompt, run_id=run_id, step=step, limited=False).response
    else:
        price = openai_price(OPENAI_MODEL)
        schema = json.dumps(output_model.model_json_schema(), ensure_ascii=False)
        max_cost = calls.estimate_max_cost(
            input_bytes=calls.utf8_bytes(prompt, instructions, schema), max_output_tokens=int(_CFG["max_output_tokens"]),
            usd_per_mtok=(Decimal(str(price[0])), Decimal(str(price[1]))), rounds=1 + int(OPENAI_SETTINGS["retries"]),
            repeats=1 + int(OPENAI_SETTINGS["sdk_max_retries"]))
        digest = hashlib.sha256((instructions + "\0" + prompt).encode("utf-8")).hexdigest()
        saved = calls.invoke(run_id=run_id, step_id=f"openai:{request_id}:{digest[:16]}", provider="openai", model=OPENAI_MODEL,
                             max_cost_usd=max_cost, budget_scope=ctx.budget_scope, request_hash=digest,
                             fn=lambda: _physical(agent, prompt, run_id=run_id, step=step, limited=True)).response
    tokens = saved.get("logprobs") or []
    values, confidence, probabilities = dict(saved["output"]), {}, {}
    for f, opts in fields.items():
        _v, conf, probs = field_probabilities(tokens, f, opts)
        confidence[f], probabilities[f] = conf, probs
    call = JevCall(request_id=request_id, n_questions=len(fields), state_chars=len(prompt), model=saved.get("model"),
                   input_tokens=saved.get("input_tokens"), output_tokens=saved.get("output_tokens"),
                   seconds=round(time.perf_counter() - t0, 3), cost_usd=float(saved.get("cost_usd") or 0.0))
    return GptAnswer(values=values, confidence=confidence, probabilities=probabilities,
                     measured=all(c is not None for c in confidence.values()), call=call)


# --- the two questions ------------------------------------------------------------------------------------


def detect(pdf: PdfText, path: str | Path, *, run_id: str = "adhoc") -> DetectResult:
    """The coarse type, the issuer's nationality and the language (the counterpart of `jav.detect.detect`)."""
    state = build_state(pdf, path)
    fields = {"doc_type": [t.key for t in DOC_TYPES] + [UNKNOWN], "issuer_is_hungarian": [YES, NO], "language": LANGUAGES}
    a = ask("detect", detect_instructions(), json.dumps(state, ensure_ascii=False), fields, run_id=run_id)
    issuer = a.values["issuer_is_hungarian"]
    issuer_conf = a.confidence["issuer_is_hungarian"]
    issuer_hu = (issuer_conf if issuer == YES else 1.0 - issuer_conf) if issuer_conf is not None else (1.0 if issuer == YES else 0.0)
    return DetectResult(
        doc_type=a.values["doc_type"], confidence=a.confidence["doc_type"] or 0.0, probabilities=a.probabilities["doc_type"],
        issuer_hu=round(issuer_hu, 4), language=a.values["language"], language_conf=a.confidence["language"] or 0.0,
        anchor_hits=state["anchor_hits"], call=a.call, engine="gpt", measured=a.measured,
    )


def choose_detail(broad: str, descriptions: dict[str, str], state: dict[str, Any], *, run_id: str) -> tuple[str | None, float | None, dict[str, float]]:
    """The detailed type among the category's type packs (`descriptions`: key -> description), or None for `none`.
    Returns (key, confidence, probabilities); the confidence is None when it is not measurable."""
    options = list(descriptions) + [NONE]
    lines = [f"- {k}: {short_description(d)}" for k, d in descriptions.items()] + [f"- {NONE}: {_CFG['detail_none_description']}"]
    instructions = _CFG["detail_preamble"].format(broad=broad) + "\nDetailed types:\n" + "\n".join(lines)
    a = ask("detect_detail", instructions, json.dumps(state, ensure_ascii=False), {"detail_type": options}, run_id=run_id)
    key = a.values["detail_type"]
    return (None if key == NONE else key), a.confidence["detail_type"], a.probabilities["detail_type"]
