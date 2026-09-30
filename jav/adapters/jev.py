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
- **config_hash**: the call site's config version (`jav/cfg.py`) in the ledger row, so that a measurement can be
  traced back.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from typesafe_sdk import Choice, Noul, Score, SystemOneResponse, TypeSafeClient, TypeSafeError
from pydantic import ValidationError

from jav import store
from jav.config import CACHE_DIR, JEV_ALIAS_TTL_H, JEV_CACHE_VERSION, JEV_MODEL, JEV_RETRY, JEV_USD_PER_MTOK, make_client
from jav.models import JevCall

Question = Choice | Noul | Score
CACHE_VERSION = JEV_CACHE_VERSION  # configs/models.json - bumping it invalidates every cache key
MODEL_VERSIONS_FILE = "_model_versions.json"  # in the cache folder: alias -> {model, resolved_at}
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


class JevAdapter:
    def __init__(self, client: TypeSafeClient | None = None, cache_dir: Path = CACHE_DIR, model: str = JEV_MODEL) -> None:
        self._client = client
        self.cache_dir = cache_dir
        self.model = model
        self._resolved: dict[str, str] = {}  # alias -> concrete version (once per process)
        # After a live call the answer goes into the cache by default (reference refresh). The determinism
        # measurement runs under `no_cache_write()`: no reading AND no writing, so the reference answer stays unchanged.
        self.write_cache = True

    @property
    def client(self) -> TypeSafeClient:
        if self._client is None:
            self._client = make_client()
        return self._client

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

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
        if _CONCRETE_MODEL.match(model):
            return model
        if model in self._resolved:
            return self._resolved[model]
        versions = self._read_versions()
        entry = versions.get(model)
        now = datetime.now(timezone.utc)
        if entry:
            try:
                fresh = now - datetime.fromisoformat(entry["resolved_at"]) < timedelta(hours=JEV_ALIAS_TTL_H)
            except (KeyError, ValueError):
                fresh = False
            if fresh:
                self._resolved[model] = entry["model"]
                return entry["model"]
        try:
            response, _ = self._live("model_probe", _PROBE_STATE, _PROBE_QUESTIONS, model=model, run_id=run_id, config_hash=None)
        except JevUnavailableError:
            if entry:  # expired but usable: offline cache hits keep working; the ledger's `model` field shows the truth
                print(f"[jev] figyelem: '{model}' feloldása nem frissíthető, a {entry['resolved_at'][:10]}-i '{entry['model']}' marad", file=sys.stderr)
                self._resolved[model] = entry["model"]
                return entry["model"]
            raise
        return self._remember(model, response.model or model)

    def _remember(self, alias: str, concrete: str) -> str:
        """Record the alias resolution (in the process and in the file, with a fresh timestamp)."""
        versions = self._read_versions()
        versions[alias] = {"model": concrete, "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._versions_path().write_text(json.dumps(versions, ensure_ascii=False, indent=1), encoding="utf-8")
        self._resolved[alias] = concrete
        return concrete

    # --- call ------------------------------------------------------------------------------------

    @staticmethod
    def _read_cached(path: Path) -> SystemOneResponse | None:
        """The saved answer, or None if it is missing or unreadable (066 Á37: the remains of an interrupted write do not
        stop the process; it becomes a live question, and a new, intact file takes its place). Read in JSON mode
        (the SDK's own decoding path): the Score answer's level keys are strings ("0") in the file, the model expects
        integers."""
        try:
            return SystemOneResponse.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:  # pydantic's ValidationError is a ValueError too
            print(f"[jev] figyelem: olvashatatlan gyorsítótár-fájl, élő kérdés lesz belőle: {path.name} ({type(exc).__name__})",
                  file=sys.stderr)
            return None

    def _write_cached(self, path: Path, response: SystemOneResponse) -> None:
        """Atomic write (066 Á37): to a temporary file, then a replace, so a reader never sees a half-written file."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(response.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


    def _live(
        self, request_id: str, state: object, questions: dict[str, Question], *, model: str, run_id: str, config_hash: str | None
    ) -> tuple[SystemOneResponse, float]:
        """Physical call. In a worker run (`jav.runtime.calls.current()`) it goes through the call log and the budget
        (040 K1): an overrun or an uncertain earlier attempt becomes `JevUnavailableError`, so the process continues
        with reviews. If the call log returned the step's saved answer (replay), `_REPLAYED` tells the calling `ask()`
        (066 Á16); the return shape (answer, seconds) stays because experimental and test adapters override it."""
        from jav.runtime import calls  # deferred: the runtime builds on the store, the adapter is the lowest layer

        ctx = calls.current()
        if ctx is None:
            return self._sdk_live(request_id, state, questions, model=model, run_id=run_id, config_hash=config_hash)
        body = json.dumps({"state": state, "questions": {k: q.model_dump(mode="json") for k, q in questions.items()}},
                          ensure_ascii=False, default=str, sort_keys=True)
        key = request_hash(model, state, questions)
        attempts = 1 + int(JEV_RETRY.get("max_retries", 0))  # the SDK's own retries are physical requests too
        max_cost = calls.estimate_max_cost(input_chars=len(body), max_output_tokens=0,
                                           usd_per_mtok=(Decimal(str(JEV_USD_PER_MTOK)), Decimal(0)), physical_attempts=attempts)
        seconds_box: list[float] = []

        def physical() -> calls.Outcome:
            response, seconds = self._sdk_live(request_id, state, questions, model=model, run_id=run_id, config_hash=config_hash)
            seconds_box.append(seconds)
            in_tok = getattr(getattr(response, "usage", None), "input_tokens", None)
            cost = None if in_tok is None else (Decimal(in_tok) * Decimal(str(JEV_USD_PER_MTOK)) / Decimal(1_000_000)).quantize(Decimal("0.000001"))
            return calls.Outcome(response=response.model_dump(mode="json"), model=getattr(response, "model", None),
                                 input_tokens=in_tok, cost_usd=cost)

        try:
            result = calls.invoke(run_id=run_id, step_id=f"jev:{request_id}:{key[:16]}", provider="jev", model=model,
                                  max_cost_usd=max_cost, fn=physical, budget_scope=ctx.budget_scope, request_hash=key)
        except calls.BudgetExceeded as exc:
            raise JevUnavailableError("budget_exceeded") from exc
        except calls.UncertainAttempt as exc:
            raise JevUnavailableError("uncertain_attempt") from exc
        response = SystemOneResponse.model_validate_json(json.dumps(result.response, ensure_ascii=False))
        _REPLAYED.set(result.replayed)
        return response, (seconds_box[0] if seconds_box else 0.0)

    def _sdk_live(
        self, request_id: str, state: object, questions: dict[str, Question], *, model: str, run_id: str, config_hash: str | None
    ) -> tuple[SystemOneResponse, float]:
        """Live SDK call. SDK exception -> ledger row with `error` + JevUnavailableError (the caller decides)."""
        t0 = time.perf_counter()
        try:
            response = self.client.system_one(state=state, questions=questions, model=model)
            validate_response(response, questions)
        except (TypeSafeError, ValidationError, InvalidJevResponse) as exc:
            if isinstance(exc, ValidationError) and exc.title != "SystemOneResponse":
                raise  # An input / programming error is not reported as a service failure.
            seconds = round(time.perf_counter() - t0, 3)
            reason, ledger_error, retry_after = _error_slugs(exc)
            store.ledger_add(
                run_id=run_id, step=request_id, provider="jev", model=model, input_tokens=None, output_tokens=None,
                cost_usd=0.0, seconds=seconds, cached=False, cache_key=None, config_hash=config_hash, error=ledger_error,
            )
            raise JevUnavailableError(reason, retry_after_ms=retry_after) from exc
        seconds = round(time.perf_counter() - t0, 3)
        if request_id == "model_probe":  # the probe's cost goes to the ledger too, so no call is invisible
            usage = getattr(response, "usage", None)
            in_tok = getattr(usage, "input_tokens", None)
            store.ledger_add(
                run_id=run_id, step=request_id, provider="jev", model=getattr(response, "model", None) or model,
                input_tokens=in_tok, output_tokens=getattr(usage, "output_tokens", None),
                cost_usd=0.0 if in_tok is None else round(in_tok * JEV_USD_PER_MTOK / 1_000_000, 6),
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
        model = model or self.model
        run_id = run_id or "adhoc"
        concrete = self.resolve_model(model, run_id=run_id)
        key = request_hash(concrete, state, questions)
        path = self._cache_path(key)
        cached = False
        t0 = time.perf_counter()
        response = self._read_cached(path) if use_cache else None
        if response is not None:
            cached = True
            seconds = round(time.perf_counter() - t0, 3)
        else:
            token = _REPLAYED.set(False)
            try:
                response, seconds = self._live(request_id, state, questions, model=model, run_id=run_id, config_hash=config_hash)
                cached = _REPLAYED.get()  # 066 Á16: a replayed answer is no new spending (already booked)
            finally:
                _REPLAYED.reset(token)
            answered = getattr(response, "model", None)
            if answered and answered != concrete:
                # 066 Á17: the request goes with the alias; the provider may have moved it to a new version meanwhile
                # (within the resolution's TTL). The answer is stored under the answering version's key and the
                # resolution is refreshed, so a cache hit is always an answer from the version the key names.
                concrete = self._remember(model, answered) if not _CONCRETE_MODEL.match(model) else answered
                key = request_hash(concrete, state, questions)
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
            cost_usd=0.0 if cached or in_tok is None else round(in_tok * JEV_USD_PER_MTOK / 1_000_000, 6),
        )
        store.ledger_add(
            run_id=run_id,
            step=request_id,
            provider="jev",
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


_scoped_adapter: ContextVar[JevAdapter | None] = ContextVar("jev_scoped_adapter", default=None)


class CacheOnlyAdapter(JevAdapter):
    """Answers only from the request-hash cache; a miss is an error, it never calls a provider (replay, offline run)."""

    def _live(self, *args, **kwargs):
        raise RuntimeError("cache_only_miss; baseline cannot call a provider")


@contextmanager
def use_adapter(adapter):
    """Run-scoped adapter; it does not replace the default of parallel contexts."""
    token = _scoped_adapter.set(adapter)
    try:
        yield adapter
    finally:
        _scoped_adapter.reset(token)


@lru_cache(maxsize=1)
def _default_adapter() -> JevAdapter:
    return JevAdapter()


def get_adapter() -> JevAdapter:
    return _scoped_adapter.get() or _default_adapter()


# Keeps the cache-clearing interface that earlier tests / the CLI use.
get_adapter.cache_clear = _default_adapter.cache_clear
