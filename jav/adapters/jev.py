"""Jev-adapter: egyetlen belépési pont a System One hívásokhoz.

Amit ad a nyers SDK fölé:
- **kérés-hash cache** (`runs/cache/<sha256>.json`): ugyanaz a (konkrét modellverzió, state, kérdések) → ugyanaz a
  válasz, nulla költséggel. Ettől az újraértékelés és a golden-újrafuttatás ingyenes; a determinizmus-mérés viszont
  `use_cache=False`-szal és `no_cache_write()` alatt fut, hogy a valódi futásról-futásra ingadozást mérje.
- **modellverzió a kulcsban**: a `configs/models.json` aliast ad (`jev-latest`), a `models.list()` viszont csak
  aliasokat sorol, ezért az alias egy apró szondával (egy Noul, ~100 token) oldódik konkrét verzióra (a válasz
  `model` mezője, pl. `jev-1.13.0`). A feloldás `runs/cache/_model_versions.json`-ban marad TTL-lel: offline is
  működnek a cache-találatok, modell-frissítéskor pedig a kulcs magától vált (a régi cache-fájlok nem sérülnek).
  A kérés az aliasszal megy; ha az élő válasz más verziót jelez, mint a feloldás (az alias a TTL alatt átállt), a válasz
  a válaszoló verzió kulcsa alá kerül, és a feloldás frissül (066 Á17).
- **ledger**: minden hívás (cache-találat, szonda és hiba is) sorba kerül a SQLite `ledger` táblába: run_id, lépés,
  modell, tokenek, USD, idő, cache-találat, `error`.
- **hiba-kezelés**: SDK-kivétel (429/5xx a RetryPolicy után, időtúllépés, kapcsolat) → ledger-sor `error`-ral +
  `JevUnavailableError`; a flow-k ezt review-okká alakítják (`jev_unavailable:<ok>`), nem dőlnek el. Programhiba
  (nem SDK-kivétel) továbbra is felfut.
- **token-költség**: a modell-oldal árlistája szerint (`config.JEV_USD_PER_MTOK`), csak input token fizetős.
- **config_hash**: a hívási hely konfig-verziója (`jav/cfg.py`) a ledger-sorban, hogy a mérés visszavezethető legyen.
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
CACHE_VERSION = JEV_CACHE_VERSION  # configs/models.json - léptetése minden cache-kulcsot érvénytelenít
MODEL_VERSIONS_FILE = "_model_versions.json"  # a cache-mappában: alias -> {model, resolved_at}
_CONCRETE_MODEL = re.compile(r"^jev-\d+\.\d+\.\d+$")
# A szonda: a legkisebb érvényes kérés; csak a válasz `model` mezője kell belőle.
_PROBE_STATE = {"text": "probe"}
_PROBE_QUESTIONS: dict[str, Question] = {"probe": Noul(instructions="Is the text exactly the word 'probe'?")}


class JevUnavailableError(RuntimeError):
    """A Jev-hívás az SDK újrapróbálkozásai után sem sikerült; a `reason` a ledger `error` oszlopának rövid alakja."""

    def __init__(self, reason: str, *, retry_after_ms: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after_ms = retry_after_ms


class InvalidJevResponse(RuntimeError):
    """Szerkezetileg dekódolható, de hiányos vagy a kérdésnek nem megfelelő válasz."""


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
    """(rövid ok a review-okhoz, ledger-alak, retry_after_ms) egy SDK-kivételből."""
    name = type(exc).__name__
    status = getattr(exc, "status", None)
    reason = f"{name}:{status}" if status is not None else name
    body = getattr(exc, "body", None)  # a szerver hiba-típusa (pl. max_tokens_exceeded) a ledgerbe és a review-okba is
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


# 066 Á16: a `_live` jelzése az `ask()`-nak, hogy a hívásnapló a lépés mentett válaszát adta (nem új költés)
_REPLAYED: ContextVar[bool] = ContextVar("jev_replayed", default=False)


class JevAdapter:
    def __init__(self, client: TypeSafeClient | None = None, cache_dir: Path = CACHE_DIR, model: str = JEV_MODEL) -> None:
        self._client = client
        self.cache_dir = cache_dir
        self.model = model
        self._resolved: dict[str, str] = {}  # alias -> konkrét verzió (folyamaton belül egyszer)
        # Élő hívás után a válasz alapból a cache-be kerül (referencia-frissítés). A determinizmus-mérés
        # `no_cache_write()` alatt fut: olvasás nélkül ÉS írás nélkül, hogy a referencia-válasz ne változzon.
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
        """Az élő válaszok a blokkon belül nem íródnak a cache-be (determinizmus-mérés)."""
        previous = self.write_cache
        self.write_cache = False
        try:
            yield self
        finally:
            self.write_cache = previous

    # --- modellverzió-feloldás ---------------------------------------------------------------------

    @property
    def resolved_model(self) -> str:
        """Az adapter modelljének konkrét verziója (alias esetén szonda / fájl)."""
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
            if entry:  # lejárt, de van mit használni: offline cache-találatok működnek, a ledger `model` mezője mutatja az igazságot
                print(f"[jev] figyelem: '{model}' feloldása nem frissíthető, a {entry['resolved_at'][:10]}-i '{entry['model']}' marad", file=sys.stderr)
                self._resolved[model] = entry["model"]
                return entry["model"]
            raise
        return self._remember(model, response.model or model)

    def _remember(self, alias: str, concrete: str) -> str:
        """Az álnév feloldásának rögzítése (folyamaton belül és a fájlban, friss időbélyeggel)."""
        versions = self._read_versions()
        versions[alias] = {"model": concrete, "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._versions_path().write_text(json.dumps(versions, ensure_ascii=False, indent=1), encoding="utf-8")
        self._resolved[alias] = concrete
        return concrete

    # --- hívás -----------------------------------------------------------------------------------

    @staticmethod
    def _read_cached(path: Path) -> SystemOneResponse | None:
        """A mentett válasz, vagy None, ha nincs, vagy olvashatatlan (066 Á37: egy félbeszakadt írás maradéka nem állítja
        meg a folyamatot; élő kérdés lesz belőle, és a helyére új, ép fájl kerül). JSON-módú beolvasás (az SDK saját
        dekódolási útja): a Score-válasz szint-kulcsai a fájlban stringek ("0"), a modell egész számot vár."""
        try:
            return SystemOneResponse.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:  # a pydantic ValidationError is ValueError
            print(f"[jev] figyelem: olvashatatlan gyorsítótár-fájl, élő kérdés lesz belőle: {path.name} ({type(exc).__name__})",
                  file=sys.stderr)
            return None

    def _write_cached(self, path: Path, response: SystemOneResponse) -> None:
        """Atomi írás (066 Á37): ideiglenes fájlba, majd cserével, így olvasó sosem lát félkész fájlt."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(response.model_dump(mode="json"), ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


    def _live(
        self, request_id: str, state: object, questions: dict[str, Question], *, model: str, run_id: str, config_hash: str | None
    ) -> tuple[SystemOneResponse, float]:
        """Fizikai hívás. Feldolgozói futásban (`jav.runtime.calls.current()`) a hívásnaplón és a kereten át (040 K1):
        túllépés és bizonytalan korábbi kísérlet `JevUnavailableError` lesz, így a folyamat review-okkal fut tovább.
        Ha a hívásnapló a lépés mentett válaszát adta (újrajátszás), azt a `_REPLAYED` jelzi a hívó `ask()`-nak (066 Á16);
        a visszatérési alak a felülíró kísérleti és teszt-adapterek miatt marad (válasz, másodperc)."""
        from jav.runtime import calls  # késleltetett: a runtime a store-ra épül, az adapter a legalsó réteg

        ctx = calls.current()
        if ctx is None:
            return self._sdk_live(request_id, state, questions, model=model, run_id=run_id, config_hash=config_hash)
        body = json.dumps({"state": state, "questions": {k: q.model_dump(mode="json") for k, q in questions.items()}},
                          ensure_ascii=False, default=str, sort_keys=True)
        key = request_hash(model, state, questions)
        attempts = 1 + int(JEV_RETRY.get("max_retries", 0))  # az SDK saját újrapróbálásai is fizikai kérések
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
        """Élő SDK-hívás. SDK-kivétel -> ledger-sor `error`-ral + JevUnavailableError (a hívó dönt, mi legyen)."""
        t0 = time.perf_counter()
        try:
            response = self.client.system_one(state=state, questions=questions, model=model)
            validate_response(response, questions)
        except (TypeSafeError, ValidationError, InvalidJevResponse) as exc:
            if isinstance(exc, ValidationError) and exc.title != "SystemOneResponse":
                raise  # Bemeneti / programozási hibát nem nevezünk szolgáltatáshibának.
            seconds = round(time.perf_counter() - t0, 3)
            reason, ledger_error, retry_after = _error_slugs(exc)
            store.ledger_add(
                run_id=run_id, step=request_id, provider="jev", model=model, input_tokens=None, output_tokens=None,
                cost_usd=0.0, seconds=seconds, cached=False, cache_key=None, config_hash=config_hash, error=ledger_error,
            )
            raise JevUnavailableError(reason, retry_after_ms=retry_after) from exc
        seconds = round(time.perf_counter() - t0, 3)
        if request_id == "model_probe":  # a szonda költsége is a ledgerben, hogy ne legyen láthatatlan hívás
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
                cached = _REPLAYED.get()  # 066 Á16: a mentett válasz újrajátszása nem új költés (a hívásnapló már elszámolta)
            finally:
                _REPLAYED.reset(token)
            answered = getattr(response, "model", None)
            if answered and answered != concrete:
                # 066 Á17: a kérés az álnévvel megy, a szolgáltató közben (a feloldás TTL-je alatt) új verzióra állíthatta.
                # A válasz a válaszoló verzió kulcsa alá kerül, és a feloldás frissül, hogy a gyorsítótár-találat mindig
                # ugyanannak a verziónak a válasza legyen, amelyiket a kulcs mond.
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
    """Csak a kérés-hash cache-ből válaszol; cache-hiánynál hiba, sosem hív szolgáltatót (visszajátszás, offline futás)."""

    def _live(self, *args, **kwargs):
        raise RuntimeError("cache_only_miss; baseline cannot call a provider")


@contextmanager
def use_adapter(adapter):
    """Futáshoz kötött adapter; a párhuzamos kontextusok alapértelmezését nem cseréli le."""
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


# Korábbi tesztek / CLI cache-törlési felületének megőrzése.
get_adapter.cache_clear = _default_adapter.cache_clear
