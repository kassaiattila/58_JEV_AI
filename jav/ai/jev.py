"""JEV adapter: the single entry point for System One calls.

What it adds on top of the raw SDK:
- **request-hash cache** (`runs/cache/<sha256>.json`): the same (concrete model version, state, questions) → the same
  answer at zero cost. This makes re-evaluation and golden re-runs free; the determinism measurement, however, runs
  with `use_cache=False` and under `no_cache_write()` so that it measures the real run-to-run variation.
- **model version in the key**: `configs/models.json` gives an alias (`jev-latest`), but `models.list()` lists only
  aliases, so the alias is resolved to a concrete version with a tiny probe (one Noul, ~100 tokens; the answer's
  `model` field, e.g. `jev-1.13.0`). The resolution is kept in `runs/cache/_model_versions.json` with a TTL: cache
  hits work offline too, and on a model update the key switches by itself (old cache files are left intact).
  The request is sent with the alias; if the live answer reports a different version from the resolution (the alias
  moved on within the TTL), the answer is stored under the answering version's key and the resolution is refreshed
  (066 Á17).
- **ledger**: every call (cache hits, probes and errors included) gets a row in the SQLite `ledger` table: run_id,
  step, model, tokens, USD, time, cache hit, `error`.
- **error handling**: an SDK exception (429/5xx after the RetryPolicy, timeout, connection) → a ledger row with
  `error` + `JevUnavailableError`; the flows turn it into reviews (`jev_unavailable:<reason>`) and do not crash.
  A programming error (not an SDK exception) still propagates.
- **token cost**: according to the model's price list (`config.JEV_USD_PER_MTOK`); only input tokens are billed.
- **config_hash**: the call site's config version (`jav/core/cfg.py`) in the ledger row, so that a measurement can be
  traced back.
- **the judgement service of the engine** (265, plan L): `get_adapter()` gives the adapter of the judgement service the
  context names (`use_judge`, set by the flow's engine, `jav/ai/engine.py`; JEV by default): a run-scoped one
  (`use_adapter`, keyed by the adapter's own `judge`) or that service's default adapter.
- **refusal without JEV** (160, plan F-csak-gpt): inside `disabled()` (a flow built without JEV runs every step in it,
  `jav/ai/engine.py`) every question is refused with `JevUnavailableError("disabled")` before the model probe, the cache
  and the call log, so processing without JEV is a guarantee, not a convention.
- **another judgement service** (265, plan L): the provider's name, the price, the model's resolution, the request key and
  the physical call are the adapter's own methods, so OpenAI Decisions (`jav/ai/decisions.py`) is this adapter with its
  own; the cache, the call log, the budget, the ledger, the too-large memory and `disabled()` stay one mechanism.
- **a request known to be too large** (200, Q-tul-nagy-keres): a request the service refused for its token limit
  (`max_tokens_exceeded`) has no answer to cache, so every later run sent it again (a failed call and a kept
  reservation each time) before the request-size frame (`jav/ai/jev_budget.py`) went on to its tighter request. Its key is
  remembered (`runs/cache/too_large/<sha256>.json`, under the concrete version that refused it), and the same request
  is refused again without a call, with the same reason and a ledger row. Read and written as the cache is: a
  determinism measurement asks live and remembers nothing; another model version tries the request again.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import NoReturn

from typesafe_sdk import Choice, Noul, Score, SystemOneResponse, TypeSafeClient, TypeSafeError
from pydantic import ValidationError

from jav.core import store
from jav.core.config import CACHE_DIR, JEV_ALIAS_TTL_H, JEV_CACHE_VERSION, JEV_MODEL, JEV_RETRY, JEV_USD_PER_MTOK, MissingAPIKeyError, make_client
from jav.ai.models import JevCall
from jav.core import observability  # 231 (E4): the calls are timed through one helper

Question = Choice | Noul | Score
CACHE_VERSION = JEV_CACHE_VERSION  # configs/models.json - bumping it invalidates every cache key
MODEL_VERSIONS_FILE = "_model_versions.json"  # in the cache folder: alias -> {model, resolved_at}
TOO_LARGE_DIR = "too_large"  # 200: in the cache folder, the keys of requests refused for the token limit
TOKEN_LIMIT_MARK = "max_tokens_exceeded"  # the service's error type for a request over its token limit
_CONCRETE_MODEL = re.compile(r"^jev-\d+\.\d+\.\d+$")
# The probe: the smallest valid request; only the answer's `model` field is needed from it.
_PROBE_STATE = {"text": "probe"}
_PROBE_QUESTIONS: dict[str, Question] = {"probe": Noul(instructions="Is the text exactly the word 'probe'?")}


class JevUnavailableError(RuntimeError):
    """The JEV call failed even after the SDK's retries; `reason` is the short form of the ledger's `error` column."""

    def __init__(self, reason: str, *, retry_after_ms: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after_ms = retry_after_ms


class InvalidJevResponse(RuntimeError):
    """An answer that decodes structurally but is incomplete or does not fit the question."""


def validate_response(response: SystemOneResponse, questions: dict[str, Question]) -> None:
    for key, question in questions.items():
        if isinstance(question, Choice):
            answer = response.choices.get(key)
            if answer is None or answer.choice not in question.criteria:
                raise InvalidJevResponse("missing or invalid choice")
        elif isinstance(question, Noul):
            answer = response.nouls.get(key)
            if answer is None or not 0 <= answer.noul <= 1:
                raise InvalidJevResponse("missing or invalid noul")
        elif key not in response.scores:
            raise InvalidJevResponse("missing score")


def _error_slugs(exc: BaseException) -> tuple[str, str, float | None]:
    """(short reason for the reviews, ledger form, retry_after_ms) from an SDK exception."""
    name = type(exc).__name__
    status = getattr(exc, "status", None)
    reason = f"{name}:{status}" if status is not None else name
    body = getattr(exc, "body", None)  # server error type (e.g. max_tokens_exceeded) for the ledger and the reviews
    error_type = (body.get("detail") or {}).get("error_type") if isinstance(body, dict) and isinstance(body.get("detail"), dict) else None
    if error_type:
        reason += f":{error_type}"
    retry_after = getattr(exc, "retry_after_ms", None)
    ledger = reason + (f":retry_after_ms={int(retry_after)}" if retry_after is not None else "")
    return reason, ledger, retry_after


@dataclass
class JevResult:
    response: SystemOneResponse
    call: JevCall
    cached: bool
    cache_key: str


def request_hash(model: str, state: object, questions: dict[str, Question]) -> str:
    payload = {
        "v": CACHE_VERSION,
        "model": model,
        "state": state,
        "questions": {k: q.model_dump(mode="json") for k, q in sorted(questions.items())},
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# 066 Á16: `_live` signals to `ask()` that the call log returned the step's saved answer (no new spending)
_REPLAYED: ContextVar[bool] = ContextVar("jev_replayed", default=False)


def call_max_cost(state: object, questions: dict[str, Question]) -> Decimal:
    """272 (K2): the most one JEV request may cost, its SDK's own retries included: the bound `_live` reserves."""
    from jav.core import calls  # deferred: the runtime builds on the store, the adapter is the lowest layer

    body = json.dumps({"state": state, "questions": {k: q.model_dump(mode="json") for k, q in questions.items()}},
                      ensure_ascii=False, default=str, sort_keys=True)
    return calls.estimate_max_cost(input_bytes=calls.utf8_bytes(body), max_output_tokens=0,
                                   usd_per_mtok=(Decimal(str(JEV_USD_PER_MTOK)), Decimal(0)),
                                   repeats=1 + int(JEV_RETRY.get("max_retries", 0)))


class JevAdapter:
    # 265 (plan L): what another judgement service's adapter sets for itself (`jav/ai/decisions.py`)
    provider = "jev"
    cache_subdir = ""  # 265: the folder of this service's answers under a caller's cache folder (JEV: the folder itself)  # the call log's and the ledger's provider (configs/providers.json)
    judge = "jev"  # the judgement service (configs/engines.json `judges`); the call log's step prefix
    response_type: type[SystemOneResponse] = SystemOneResponse
    alias_ttl_hours: float | None = JEV_ALIAS_TTL_H  # None: a resolution stays until an answer names another model

    def __init__(self, client: TypeSafeClient | None = None, cache_dir: Path | None = None, model: str = JEV_MODEL) -> None:
        self._client = client
        # 265 (code review SEC-02, TOOL-04): the client this adapter makes from the environment's key is the paid one; a
        # client handed over (a test's or a measurement tool's fake) is the caller's
        self._own_client = client is None
        # 265 (code review X-28): the folder read when the adapter is made, not when the module was, so the tests'
        # temporary folder (tests/conftest.py) holds for an adapter made without one
        self.cache_dir = cache_dir if cache_dir is not None else CACHE_DIR
        self.model = model
        self._resolved: dict[str, str] = {}  # alias -> concrete version (once per process)
        # After a live call the answer goes into the cache by default (reference refresh). The determinism
        # measurement runs under `no_cache_write()`: no reading AND no writing, so the reference answer stays unchanged.
        self.write_cache = True

    @property
    def client(self) -> TypeSafeClient:
        """085: without a TypeSafe key the adapter is unavailable (`missing_key`), like any other JEV failure, so the
        flows continue with a to-do instead of failing the item."""
        if self._client is None:
            try:
                self._client = make_client()
            except MissingAPIKeyError as exc:
                raise JevUnavailableError("missing_key") from exc
        return self._client

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    # --- what another judgement service replaces (265, plan L) -------------------------------------

    def _is_concrete(self, model: str) -> bool:
        """Whether `model` names one version (`jev-1.14.0`) rather than a moving alias."""
        return bool(_CONCRETE_MODEL.match(model))

    def _probe(self, model: str, *, run_id: str) -> str:
        """The version an alias answers with now: one tiny live question (its answer's `model` field)."""
        response, _ = self._live("model_probe", _PROBE_STATE, _PROBE_QUESTIONS, model=model, run_id=run_id, config_hash=None)
        return response.model or model

    def _request_key(self, model: str, state: object, questions: dict[str, Question]) -> str:
        """The cache key of a request: the answering version, the state and the questions."""
        return request_hash(model, state, questions)

    def _request_body(self, state: object, questions: dict[str, Question], model: str) -> str:
        """What leaves the machine, for the call log's worst-case reservation."""
        return json.dumps({"state": state, "questions": {k: q.model_dump(mode="json") for k, q in questions.items()}},
                          ensure_ascii=False, default=str, sort_keys=True)

    def _attempts(self) -> int:
        """Physical requests one call may make: the SDK's own retries are requests too."""
        return 1 + int(JEV_RETRY.get("max_retries", 0))

    def _max_cost(self, body: str) -> Decimal:
        from jav.core import calls

        return self.max_cost_for(calls.utf8_bytes(body))

    def max_cost_for(self, input_bytes: int) -> Decimal:
        """The most one request of `input_bytes` sent may cost with this service, every attempt included (265: also
        what a caller reserves before it has built the request, the native reader's limits)."""
        from jav.core import calls

        return calls.estimate_max_cost(input_bytes=input_bytes, max_output_tokens=0,
                                       usd_per_mtok=(Decimal(str(JEV_USD_PER_MTOK)), Decimal(0)), repeats=self._attempts())

    def _call_cost(self, response: SystemOneResponse) -> Decimal | None:
        """A live answer's cost for the call log (exact); None when the usage is not known."""
        in_tok = getattr(getattr(response, "usage", None), "input_tokens", None)
        if in_tok is None:
            return None
        return (Decimal(in_tok) * Decimal(str(JEV_USD_PER_MTOK)) / Decimal(1_000_000)).quantize(Decimal("0.000001"))

    def _ledger_cost(self, response: SystemOneResponse) -> float:
        """A live answer's cost for the ledger (0 when the usage is not known)."""
        in_tok = getattr(getattr(response, "usage", None), "input_tokens", None)
        return 0.0 if in_tok is None else round(in_tok * JEV_USD_PER_MTOK / 1_000_000, 6)

    def _send(self, state: object, questions: dict[str, Question], *, model: str) -> SystemOneResponse:
        """The physical request and its checked answer; a service failure raises a kind `_service_error` accepts."""
        response = self.client.system_one(state=state, questions=questions, model=model)
        validate_response(response, questions)
        return response

    def _service_error(self, exc: BaseException) -> bool:
        """Whether `exc` is the service's failure (a to-do), not an input or programming error (raised)."""
        if isinstance(exc, ValidationError):
            return exc.title == "SystemOneResponse"
        return isinstance(exc, (TypeSafeError, InvalidJevResponse))

    def _error_reason(self, exc: BaseException) -> tuple[str, str, float | None]:
        """(short reason for the reviews, ledger form, retry_after_ms) of a service failure."""
        return _error_slugs(exc)

    def unanswered_cost(self, parts: list[tuple[object, dict[str, Question]]] | tuple, *, use_cache: bool) -> Decimal:
        """272 (K2, the rest of AI-01): what asking every (state, questions) part would reserve at most; a part
        answered in the cache costs nothing when the cache is read (265: by this service's key and bound)."""
        concrete = self.resolve_model(self.model)
        return sum((self._max_cost(self._request_body(state, questions, concrete)) for state, questions in parts
                    if not (use_cache and self._cache_path(self._request_key(concrete, state, questions)).exists())),
                   Decimal(0))

    @contextmanager
    def no_cache_write(self):
        """Live answers inside the block are not written to the cache (determinism measurement)."""
        previous = self.write_cache
        self.write_cache = False
        try:
            yield self
        finally:
            self.write_cache = previous

    # --- model version resolution ------------------------------------------------------------------

    @property
    def resolved_model(self) -> str:
        """The concrete version of the adapter's model (for an alias: probe / file)."""
        return self.resolve_model(self.model)

    def _versions_path(self) -> Path:
        return self.cache_dir / MODEL_VERSIONS_FILE

    def _read_versions(self) -> dict[str, dict[str, str]]:
        p = self._versions_path()
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def resolve_model(self, model: str, *, run_id: str = "adhoc") -> str:
        if self._is_concrete(model):
            return model
        if model in self._resolved:
            return self._resolved[model]
        versions = self._read_versions()
        entry = versions.get(model)
        now = datetime.now(timezone.utc)
        if entry:
            try:
                fresh = (self.alias_ttl_hours is None
                         or now - datetime.fromisoformat(entry["resolved_at"]) < timedelta(hours=self.alias_ttl_hours))
            except (KeyError, ValueError):
                fresh = False
            if fresh:
                self._resolved[model] = entry["model"]
                return entry["model"]
        try:
            answered = self._probe(model, run_id=run_id)
        except JevUnavailableError:
            if entry:  # expired but usable: offline cache hits keep working; the ledger's `model` field shows the truth
                print(f"[jev] warning: '{model}' cannot be resolved again; '{entry['model']}' of {entry['resolved_at'][:10]} stays", file=sys.stderr)
                self._resolved[model] = entry["model"]
                return entry["model"]
            raise
        return self._remember(model, answered)

    def _remember(self, alias: str, concrete: str) -> str:
        """Record the alias resolution (in the process and in the file, with a fresh timestamp)."""
        versions = self._read_versions()
        versions[alias] = {"model": concrete, "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._versions_path().write_text(json.dumps(versions, ensure_ascii=False, indent=1), encoding="utf-8")
        self._resolved[alias] = concrete
        return concrete

    # --- call ------------------------------------------------------------------------------------

    def _read_cached(self, path: Path) -> SystemOneResponse | None:
        """The saved answer, or None if it is missing or unreadable (066 Á37: the remains of an interrupted write do not
        stop the process; it becomes a live question, and a new, intact file takes its place). Read in JSON mode
        (the SDK's own decoding path): the Score answer's level keys are strings ("0") in the file, the model expects
        integers."""
        try:
            return self.response_type.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:  # pydantic's ValidationError is a ValueError too
            print(f"[jev] warning: an unreadable cache file, it becomes a live question: {path.name} ({type(exc).__name__})",
                  file=sys.stderr)
            return None

    def _too_large_path(self, key: str) -> Path:
        return self.cache_dir / TOO_LARGE_DIR / f"{key}.json"

    def _known_too_large(self, key: str) -> str | None:
        """200: the reason the service refused this request for its token limit, or None if it has not."""
        try:
            return str(json.loads(self._too_large_path(key).read_text(encoding="utf-8"))["reason"])
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as exc:  # an unreadable mark: the request is simply sent
            print(f"[jev] warning: unreadable too-large mark, the request is sent: {key[:16]} ({type(exc).__name__})",
                  file=sys.stderr)
            return None

    def _remember_too_large(self, key: str, model: str, exc: JevUnavailableError) -> None:
        """200: remembers a refusal for the token limit (only that one: another refusal may not come again)."""
        if not self.write_cache or TOKEN_LIMIT_MARK not in (exc.reason or ""):
            return
        path = self._too_large_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"reason": exc.reason, "model": model,
                                   "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}), encoding="utf-8")
        os.replace(tmp, path)

    def _write_cached(self, path: Path, response: SystemOneResponse) -> None:
        """Atomic write (066 Á37): to a temporary file, then a replace, so a reader never sees a half-written file (265:
        the shared helper the OCR cache uses too)."""
        from jav.core import jsonfile

        jsonfile.write_atomic(path, response.model_dump(mode="json"))


    def _live(
        self, request_id: str, state: object, questions: dict[str, Question], *, model: str, run_id: str, config_hash: str | None
    ) -> tuple[SystemOneResponse, float]:
        """Physical call. In a worker run (`jav.core.calls.current()`) it goes through the call log and the budget
        (040 K1): an overrun or an uncertain earlier attempt becomes `JevUnavailableError`, so the process continues
        with reviews. If the call log returned the step's saved answer (replay), `_REPLAYED` tells the calling `ask()`
        (066 Á16); the return shape (answer, seconds) stays because experimental and test adapters override it."""
        from jav.core import calls  # deferred: the runtime builds on the store, the adapter is the lowest layer

        ctx = calls.current()
        if ctx is None:
            if self._own_client:
                # 265 (code review SEC-02, TOOL-04): outside a run or a budgeted command (`calls.measurement`) only
                # earlier answers count; the key is checked first (`missing_key` stays what a missing key says)
                self.client
                raise JevUnavailableError("no_budget")
            return self._sdk_live(request_id, state, questions, model=model, run_id=run_id, config_hash=config_hash)
        self.client  # 085: a missing key fails here, before anything is reserved (no request can leave)
        key = self._request_key(model, state, questions)
        max_cost = self._max_cost(self._request_body(state, questions, model))
        attempts = self._attempts()  # 272 (K2): the SDK's own retries are physical requests too
        seconds_box: list[float] = []

        def physical() -> calls.Outcome:
            try:
                response, seconds = self._sdk_live(request_id, state, questions, model=model, run_id=run_id, config_hash=config_hash)
            except JevUnavailableError as exc:
                if TOKEN_LIMIT_MARK in (exc.reason or ""):  # 202: refused as too large, before any processing: costs 0
                    exc.known_outcome = calls.Outcome(response=None, model=model, cost_usd=Decimal(0))
                raise
            seconds_box.append(seconds)
            in_tok = getattr(getattr(response, "usage", None), "input_tokens", None)
            return calls.Outcome(response=response.model_dump(mode="json"), model=getattr(response, "model", None),
                                 input_tokens=in_tok, cost_usd=self._call_cost(response))

        try:
            result = calls.invoke(run_id=run_id, step_id=f"{self.judge}:{request_id}:{key[:16]}", provider=self.provider,
                                  model=model,
                                  max_cost_usd=max_cost, fn=physical, budget_scope=ctx.budget_scope, request_hash=key,
                                  retried_inside=attempts > 1)  # 272 (K2): the SDK repeats a failure itself
        except calls.BudgetExceeded as exc:
            raise JevUnavailableError("budget_exceeded") from exc
        except calls.UncertainAttempt as exc:
            raise JevUnavailableError("uncertain_attempt") from exc
        response = self.response_type.model_validate_json(json.dumps(result.response, ensure_ascii=False))
        _REPLAYED.set(result.replayed)
        return response, (seconds_box[0] if seconds_box else 0.0)

    def _sdk_live(
        self, request_id: str, state: object, questions: dict[str, Question], *, model: str, run_id: str, config_hash: str | None
    ) -> tuple[SystemOneResponse, float]:
        """Live SDK call. SDK exception -> ledger row with `error` + JevUnavailableError (the caller decides)."""
        t0 = observability.start()
        try:
            response = self._send(state, questions, model=model)
        except Exception as exc:
            if not self._service_error(exc):
                raise  # An input / programming error is not reported as a service failure.
            seconds = observability.since(t0)
            reason, ledger_error, retry_after = self._error_reason(exc)
            store.ledger_add(
                run_id=run_id, step=request_id, provider=self.provider, model=model, input_tokens=None, output_tokens=None,
                cost_usd=0.0, seconds=seconds, cached=False, cache_key=None, config_hash=config_hash, error=ledger_error,
            )
            raise JevUnavailableError(reason, retry_after_ms=retry_after) from exc
        seconds = observability.since(t0)
        if request_id == "model_probe":  # the probe's cost goes to the ledger too, so no call is invisible
            usage = getattr(response, "usage", None)
            in_tok = getattr(usage, "input_tokens", None)
            store.ledger_add(
                run_id=run_id, step=request_id, provider=self.provider, model=getattr(response, "model", None) or model,
                input_tokens=in_tok, output_tokens=getattr(usage, "output_tokens", None),
                cost_usd=self._ledger_cost(response),
                seconds=seconds, cached=False, cache_key=None, config_hash=None,
            )
        return response, seconds

    def ask(
        self,
        request_id: str,
        state: object,
        questions: dict[str, Question],
        *,
        run_id: str | None = None,
        use_cache: bool = True,
        model: str | None = None,
        config_hash: str | None = None,
    ) -> JevResult:
        if _disabled.get():
            _refuse(request_id)
        model = model or self.model
        run_id = run_id or "adhoc"
        concrete = self.resolve_model(model, run_id=run_id)
        key = self._request_key(concrete, state, questions)
        path = self._cache_path(key)
        cached = False
        t0 = observability.start()
        response = self._read_cached(path) if use_cache else None
        if response is None and use_cache and (known := self._known_too_large(key)) is not None:
            store.ledger_add(run_id=run_id, step=request_id, provider=self.provider, model=concrete, input_tokens=None,
                             output_tokens=None, cost_usd=0.0, seconds=0.0, cached=True, cache_key=key,
                             config_hash=config_hash, error=f"known_too_large:{known}")
            raise JevUnavailableError(known)  # 200: the same refusal as the live one, without a call
        if response is not None:
            cached = True
            seconds = observability.since(t0)
        else:
            token = _REPLAYED.set(False)
            try:
                response, seconds = self._live(request_id, state, questions, model=model, run_id=run_id, config_hash=config_hash)
                cached = _REPLAYED.get()  # 066 Á16: a replayed answer is no new spending (already booked)
            except JevUnavailableError as exc:
                self._remember_too_large(key, concrete, exc)
                raise
            finally:
                _REPLAYED.reset(token)
            answered = getattr(response, "model", None)
            if answered and answered != concrete:
                # 066 Á17: the request goes with the alias; the provider may have moved it to a new version meanwhile
                # (within the resolution's TTL). The answer is stored under the answering version's key and the
                # resolution is refreshed, so a cache hit is always an answer from the version the key names.
                concrete = self._remember(model, answered) if not self._is_concrete(model) else answered
                key = self._request_key(concrete, state, questions)
                path = self._cache_path(key)
            if self.write_cache:
                self._write_cached(path, response)

        usage = getattr(response, "usage", None)
        in_tok = getattr(usage, "input_tokens", None)
        call = JevCall(
            request_id=request_id,
            n_questions=len(questions),
            state_chars=len(json.dumps(state, ensure_ascii=False, default=str)),
            model=getattr(response, "model", None) or concrete,
            input_tokens=in_tok,
            output_tokens=getattr(usage, "output_tokens", None),
            seconds=seconds,
            cached=cached,
            cost_usd=0.0 if cached else self._ledger_cost(response),
        )
        store.ledger_add(
            run_id=run_id,
            step=request_id,
            provider=self.provider,
            model=call.model or concrete,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cost_usd=call.cost_usd,
            seconds=seconds,
            cached=cached,
            cache_key=key,
            config_hash=config_hash,
        )
        return JevResult(response=response, call=call, cached=cached, cache_key=key)


_scoped_adapters: ContextVar[dict[str, JevAdapter]] = ContextVar("judge_scoped_adapters", default={})
_judge: ContextVar[str] = ContextVar("judge", default="jev")  # 265: the judgement service the context asks
_disabled: ContextVar[bool] = ContextVar("jev_disabled", default=False)


@contextmanager
def disabled():
    """160 (plan F-csak-gpt): JEV is switched off inside (processing without JEV). Every question is refused before
    anything happens: no model probe, no cache read (a cached answer is a JEV judgement too), no call-log reservation,
    no ledger row (nothing was asked). The flows turn the refusal into the `jev_unavailable:disabled` to-do."""
    token = _disabled.set(True)
    try:
        yield
    finally:
        _disabled.reset(token)


def _refuse(request_id: str) -> NoReturn:
    """The refusal inside `disabled()`. The tests replace it with a test failure (`tests/conftest.py`), so that a
    forgotten JEV question in processing without JEV cannot hide behind the to-do it becomes in production."""
    raise JevUnavailableError("disabled")


class _RefusingAdapter(JevAdapter):
    """What `get_adapter()` gives inside `disabled()`: it refuses even where a run installed its own adapter."""

    def ask(self, request_id: str, *args, **kwargs) -> JevResult:
        _refuse(request_id)


class CacheOnlyAdapter(JevAdapter):
    """Answers only from the request-hash cache; a miss is an error, it never calls a provider (replay, offline run)."""

    def _live(self, *args, **kwargs):
        raise RuntimeError("cache_only_miss; baseline cannot call a provider")


@contextmanager
def use_adapter(adapter):
    """Run-scoped adapter of its own judgement service (`adapter.judge`; JEV for an object without one); it does not
    replace the default of parallel contexts, nor another service's adapter."""
    judge = getattr(adapter, "judge", "jev")
    token = _scoped_adapters.set({**_scoped_adapters.get(), judge: adapter})
    try:
        yield adapter
    finally:
        _scoped_adapters.reset(token)


@contextmanager
def use_judge(judge: str):
    """265 (plan L): the questions inside are asked of this judgement service (configs/engines.json `judges`)."""
    token = _judge.set(judge)
    try:
        yield
    finally:
        _judge.reset(token)


def current_judge() -> str:
    """The judgement service the context asks (JEV unless an engine named another)."""
    return _judge.get()


@lru_cache(maxsize=None)
def _default_adapter(judge: str = "jev") -> JevAdapter:
    if judge == "jev":
        return JevAdapter()
    from jav.ai.engine import judge_adapter  # deferred: the engine module builds on this one

    return judge_adapter(judge)()


def get_adapter() -> JevAdapter:
    """The adapter of the context's judgement service; inside `disabled()` one that refuses every question."""
    if _disabled.get():
        return _RefusingAdapter()
    judge = _judge.get()
    return _scoped_adapters.get().get(judge) or _default_adapter(judge)


# Keeps the cache-clearing interface that earlier tests / the CLI use.
get_adapter.cache_clear = _default_adapter.cache_clear
