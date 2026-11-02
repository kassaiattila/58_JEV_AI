"""OpenAI Decisions as a judgement service (265, plan L; glossary: OpenAI Decisions, Judgement service).

Plain-language summary: the same adapter the flows ask JEV through (`jav/ai/jev.py`: the cache of earlier answers, the
call log and the budget, the ledger, the memory of a request too large, the refusal in processing without a judgement
service), with OpenAI's Decisions API behind it. The questions and the answers are translated by
`jav/ai/decisions_wire.py`, so a flow asks and reads exactly what it asks and reads of JEV.

What is its own:
- **the request**: `POST /v1/decisions` with the OpenAI key, through the OpenAI client's plain `post` (the installed
  SDK's typed parameters predate the API's JSON parts); no SDK retry (`configs/models.json` `decisions.sdk_max_retries`,
  as for GPT since 075): the work queue repeats a failed item instead;
- **the provider and the budget**: its calls are booked as `openai_decisions` and spend from the OpenAI budget
  (`configs/providers.json`);
- **the price**: per token kind (uncached, read from and written to its prompt cache), twice above 272 000 input
  tokens; the prompt cache is off unless `decisions.prompt_cache` says `implicit` (a cache write costs 1.25 times an
  uncached token, and our requests rarely share a prefix);
- **the model**: one name (`gpt-6-luna`) without a dated version; no probe is sent: the answer names its model, and a
  model the answer names other than the one asked is remembered for the cache key, as JEV's moving alias is;
- **the cache**: `runs/cache/decisions/`, keyed by the translated request itself, so a change of the request's
  translation is a new question; it keeps the answer as translated, so a change of the answer's translation raises
  `decisions.cache_version` (274);
- **its failures**: an error answer, a lost connection, a refused question or an answer that does not fit its
  question become `JevUnavailableError`, and the flow its to-do, as with JEV; an answer over the token limit names
  the shared mark (`max_tokens_exceeded`), so the request-size frame (`jav/ai/jev_budget.py`) works the same way.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from jav.ai import decisions_wire as wire
from jav.ai import jev
from jav.ai.jev import TOKEN_LIMIT_MARK, InvalidJevResponse, JevAdapter, JevUnavailableError, Question, validate_response
from jav.core import cfg
from jav.core.config import MissingAPIKeyError, get_openai_key

CACHE_SUBDIR = "decisions"
PATH = "/decisions"
TOO_LARGE_CODES = frozenset({"context_length_exceeded", "max_tokens_exceeded", "string_above_max_length"})


def settings() -> dict[str, Any]:
    """`configs/models.json` `decisions`. 274: a price per output token needs the most output tokens a request may
    produce (`max_output_tokens`), else a reservation would not bound the call's cost."""
    out = dict(cfg.load("models")["decisions"])
    if Decimal(str(out["usd_per_mtok"]["output"])) > 0 and int(out.get("max_output_tokens", 0)) <= 0:
        raise ValueError("configs/models.json decisions: an output price needs max_output_tokens, the most a request "
                         "may produce, so a reservation bounds the call's cost")
    return out


class DecisionsAdapter(JevAdapter):
    provider = "openai_decisions"
    judge = "decisions"
    response_type = wire.DecisionsResponse
    alias_ttl_hours = None
    cache_subdir = CACHE_SUBDIR

    def __init__(self, client: Any | None = None, cache_dir=None, model: str | None = None) -> None:
        self._settings = settings()
        super().__init__(client=client, cache_dir=cache_dir if cache_dir is not None else jev.CACHE_DIR / self.cache_subdir,
                         model=model or str(self._settings["model"]))

    # --- the client -------------------------------------------------------------------------------------------------

    @property
    def client(self):
        """Without an OpenAI key the adapter is unavailable (`missing_key`), as JEV's is without its key."""
        if self._client is None:
            try:
                key = get_openai_key()
            except MissingAPIKeyError as exc:
                raise JevUnavailableError("missing_key") from exc
            self._client = self._new_client(key)
        return self._client

    def _new_client(self, key: str):
        from openai import OpenAI

        return OpenAI(api_key=key, max_retries=int(self._settings["sdk_max_retries"]),
                      timeout=float(self._settings["timeout_s"]))

    # --- the model and the request ----------------------------------------------------------------------------------

    def _is_concrete(self, model: str) -> bool:
        return False  # one name without versions: the answering model is remembered (`_remember`), never probed

    def _probe(self, model: str, *, run_id: str) -> str:
        return model  # no call: the answer names its model

    def _body(self, state: object, questions: dict[str, Question], model: str) -> dict[str, Any]:
        try:
            body = wire.request(state, questions, model=model, state_mode=str(self._settings["state"]))
        except wire.Unfit as exc:
            raise JevUnavailableError("unfit") from exc  # a request the API's limits do not admit: the flow's to-do
        if self._settings["prompt_cache"] == "off":
            body["prompt_cache_options"] = {"mode": "explicit"}  # no breakpoint marked: no prompt caching, no cache write
        return body

    def _request_key(self, model: str, state: object, questions: dict[str, Question]) -> str:
        """The translated request itself, with the cache's version: what the service is asked decides the answer."""
        body = {k: v for k, v in self._body(state, questions, model).items() if k != "prompt_cache_options"}
        canonical = json.dumps({"v": self._settings["cache_version"], "provider": self.provider, "request": body},
                               ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _request_body(self, state: object, questions: dict[str, Question], model: str) -> str:
        return json.dumps(self._body(state, questions, model), ensure_ascii=False, sort_keys=True)

    def _attempts(self) -> int:
        return 1 + int(self._settings["sdk_max_retries"])

    # --- the price --------------------------------------------------------------------------------------------------

    def _prices(self) -> dict[str, Decimal]:
        return {k: Decimal(str(v)) for k, v in self._settings["usd_per_mtok"].items()}

    def max_cost_for(self, input_bytes: int) -> Decimal:
        from jav.core import calls

        prices, long = self._prices(), self._settings["long_context"]
        per_token = prices["input"] if self._settings["prompt_cache"] == "off" else max(prices["input"], prices["cache_write"])
        if input_bytes + calls.TOKEN_OVERHEAD > int(long["above_input_tokens"]):
            per_token *= Decimal(str(long["factor"]))
        return calls.estimate_max_cost(input_bytes=input_bytes, max_output_tokens=int(self._settings.get("max_output_tokens", 0)),
                                       usd_per_mtok=(per_token, prices["output"]), repeats=self._attempts())

    def _call_cost(self, response) -> Decimal | None:
        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "input_tokens", None)
        if in_tok is None:
            return None
        prices, long = self._prices(), self._settings["long_context"]
        cached = int(getattr(response, "cached_tokens", 0) or 0)
        written = int(getattr(response, "cache_write_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        usd = (Decimal(max(in_tok - cached - written, 0)) * prices["input"] + Decimal(cached) * prices["cached_input"]
               + Decimal(written) * prices["cache_write"] + Decimal(out_tok) * prices["output"])
        if in_tok > int(long["above_input_tokens"]):
            usd *= Decimal(str(long["factor"]))
        return (usd / Decimal(1_000_000)).quantize(Decimal("0.000001"))

    def _ledger_cost(self, response) -> float:
        cost = self._call_cost(response)
        return 0.0 if cost is None else float(cost)

    # --- the call ---------------------------------------------------------------------------------------------------

    def _send(self, state: object, questions: dict[str, Question], *, model: str):
        from openai.types.decision import Decision
        from pydantic import ValidationError

        decision = self.client.post(PATH, cast_to=Decision, body=self._body(state, questions, model))
        answer = decision.model_dump(mode="json")
        try:
            response = wire.to_system_one(answer, questions)
            validate_response(response, questions)
        except (wire.Refused, InvalidJevResponse, ValidationError) as exc:
            # 275: answered, so billed: the call is settled at the cost its answer's usage gives, not its maximum
            exc.known_outcome = self._answered_outcome(answer, model)  # type: ignore[attr-defined]
            raise
        return response

    def _answered_outcome(self, answer: dict[str, Any], model: str):
        """The certain outcome of an answer that could not be used (a refusal, a value missing): its cost from its usage."""
        from jav.core import calls  # deferred: the runtime builds on the store, the adapter is the lowest layer

        usage = answer.get("usage") or {}
        details = usage.get("input_tokens_details") or {}
        tokens = SimpleNamespace(usage=SimpleNamespace(input_tokens=usage.get("input_tokens"),
                                                       output_tokens=usage.get("output_tokens")),
                                 cached_tokens=details.get("cached_tokens") or 0,
                                 cache_write_tokens=details.get("cache_write_tokens") or 0)
        cost = self._call_cost(tokens)
        if cost is None:
            return None
        return calls.Outcome(response=None, model=answer.get("model") or model, input_tokens=usage.get("input_tokens"),
                             output_tokens=usage.get("output_tokens"), cost_usd=cost)

    def _service_error(self, exc: BaseException) -> bool:
        from openai import APIError
        from pydantic import ValidationError

        return isinstance(exc, (APIError, wire.Refused, InvalidJevResponse, ValidationError))

    def _error_reason(self, exc: BaseException) -> tuple[str, str, float | None]:
        """`Name:status:code` of an error answer (a token-limit code also names the shared mark), `refusal` of a declined
        question, the class name otherwise; the retry hint of a 429 for the ledger."""
        if isinstance(exc, wire.Refused):
            return "refusal", f"refusal:{len(exc.names)}", None
        reason = type(exc).__name__
        status, code = getattr(exc, "status_code", None), getattr(exc, "code", None)
        if status is not None:
            reason += f":{status}"
        if code:
            reason += f":{code}"
            if code in TOO_LARGE_CODES:
                reason += f":{TOKEN_LIMIT_MARK}"
        retry_after = None
        headers = getattr(getattr(exc, "response", None), "headers", None)
        if headers is not None:
            raw = headers.get("retry-after-ms") or headers.get("retry-after")
            try:
                retry_after = float(raw) * (1 if headers.get("retry-after-ms") else 1000) if raw else None
            except ValueError:
                retry_after = None
        ledger = reason + (f":retry_after_ms={int(retry_after)}" if retry_after is not None else "")
        return reason, ledger, retry_after


__all__ = ["DecisionsAdapter", "settings"]
