"""Unified call log and upfront cost reservation (040 K1; for findings F05 and F06 of the 038 review).

Before every physical provider call (OpenAI, JEV, later OCR) a durable `reserved` entry is made with the maximum cost,
and if there is a budget (`budget_scope`) the reservation is created ONLY if the committed amount + the maximum fits.
Reservation and check run in one `BEGIN IMMEDIATE` transaction, so they stay correct under concurrent requests.

States and the amount counted against the budget:
- `reserved`   : the call is in progress or the process crashed → the maximum is committed; the same step is NOT called
                 again automatically (`UncertainAttempt`); at startup `recover_uncertain()` marks it `uncertain`.
- `uncertain`  : like `reserved`; manual resolution: `resolve_uncertain(id, cost_usd)`.
- `succeeded`  : the actual amount if the cost is known, otherwise the maximum stays committed. The response is saved as
                 a receipt; repeating the step returns the saved response (`replayed=True`) without a new call.
- `failed`     : the error type is logged; the cost is unknown, so the maximum stays committed (not zero, not released).
                 The same step can be retried with a new attempt number (the caller decides, e.g. the work queue's
                 retry allowance). Only for an error that shows the request was not processed (refused before it was
                 sent, or answered with an error).
- an error after the request was sent but before an answer came (a read timeout, a dropped connection; 085, re-audit
  A04: `outcome_unknown`) makes the call `uncertain` at once: the provider may have done (and billed) the work, so the
  maximum stays committed and the step is not called again automatically.
Money: `Decimal`, stored as text. The existing adapters still write the old `ledger` table; this log is the source of
truth for reservations and resumability.
"""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from typing import Any, Callable

from jav import store

log = logging.getLogger("jav.calls")

store.register_schema("runtime.calls", """
CREATE TABLE IF NOT EXISTS invocations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    step_id         TEXT NOT NULL,
    attempt         INTEGER NOT NULL,
    provider        TEXT NOT NULL,
    model_requested TEXT,
    model_actual    TEXT,
    request_hash    TEXT,
    budget_scope    TEXT,
    status          TEXT NOT NULL,              -- reserved | uncertain | succeeded | failed
    max_cost_usd    TEXT NOT NULL,
    cost_usd        TEXT,
    cost_known      INTEGER NOT NULL DEFAULT 0,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    error           TEXT,
    note            TEXT,
    created_at      TEXT NOT NULL,
    finished_at     TEXT,
    UNIQUE (run_id, step_id, attempt)
);
CREATE INDEX IF NOT EXISTS ix_invocations_step ON invocations(run_id, step_id);
CREATE INDEX IF NOT EXISTS ix_invocations_scope ON invocations(budget_scope, provider);
CREATE TABLE IF NOT EXISTS budgets (
    scope       TEXT NOT NULL,
    provider    TEXT NOT NULL,
    limit_usd   TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (scope, provider)
);
""")

RESPONSE_KIND = "invocation_response"


class BudgetExceeded(RuntimeError):
    """The maximum cost does not fit into the budget; the network was never reached."""


class UncertainAttempt(RuntimeError):
    """The step has an unfinished attempt (crashed or with an uncertain outcome); an automatic new call is forbidden."""


@dataclass(frozen=True)
class Outcome:
    """The result of the physical call, as returned by the call function (`fn`)."""
    response: Any
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: Decimal | None = None


@dataclass(frozen=True)
class Result:
    response: Any
    invocation_id: int
    replayed: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class RunContext:
    """Set by the worker for an item of a run: the provider adapters then call through the call log and the budget."""
    budget_scope: str | None


_context: ContextVar[RunContext | None] = ContextVar("jav_run_context", default=None)


@contextmanager
def use_run(*, budget_scope: str | None):
    token = _context.set(RunContext(budget_scope=budget_scope))
    try:
        yield
    finally:
        _context.reset(token)


def current() -> RunContext | None:
    """None: the legacy command-line / measurement path, without call log or budget (the earlier behaviour)."""
    return _context.get()


TOKEN_OVERHEAD = 1024
"""Tokens added to every physical request on top of its UTF-8 bytes: message framing and the provider's own wrapping.
Measured in the call log (2026-09-30): the smallest JEV request (the model probe) was 282 tokens; over 1385 JEV and 126
OpenAI calls the input tokens were at most 0.60 and 0.90 of the request's characters."""

OVERRUN_NOTE = "actual_exceeds_reserved"

NOT_SENT = frozenset({"ConnectTimeout", "ConnectError", "PoolTimeout", "ProxyError", "UnsupportedProtocol", "LocalProtocolError",
                      "InvalidURL", "URLError"})
"""Errors (by class name, anywhere in the chain) that show the request never reached the provider, or got a definite
answer (urllib's `URLError` covers a failure while connecting or sending, and its `HTTPError` an error response)."""
OUTCOME_UNKNOWN = frozenset({"TimeoutError", "TimeoutException", "ReadTimeout", "WriteTimeout", "ReadError", "WriteError",
                             "RemoteProtocolError", "APITimeoutError", "TypeSafeAPITimeoutError", "KeyboardInterrupt", "SystemExit"})
"""Errors after the request was handed over and before the answer arrived. Class names, so that the run time imports
no provider SDK; the SDKs' own wrappers keep the transport error as the cause (httpx / httpx2, openai, typesafe_sdk)."""


def _chain(exc: BaseException):
    """The exception and the ones it was raised from, as Python prints them: the cause, or else the context."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = cur.__cause__ if cur.__cause__ is not None else (None if cur.__suppress_context__ else cur.__context__)


def outcome_unknown(exc: BaseException) -> bool:
    """085 (re-audit A04): whether a failed call may still have been processed by the provider. A sign that the
    request was not sent wins; otherwise any timeout or broken read/write after sending means unknown. Anything else
    (a validation error, an error response, a refused budget) is a definite failure."""
    names = {cls.__name__ for e in _chain(exc) for cls in type(e).__mro__}
    return not names & NOT_SENT and bool(names & OUTCOME_UNKNOWN)


def _error_text(exc: BaseException) -> str:
    """The class names of the chain (`JevUnavailableError<-TypeSafeAPITimeoutError<-ReadTimeout`), for the log."""
    return "<-".join(type(e).__name__ for e in _chain(exc))[:200]


def utf8_bytes(*texts: str) -> int:
    return sum(len(t.encode("utf-8")) for t in texts)


def estimate_max_cost(*, input_bytes: int, max_output_tokens: int, usd_per_mtok: tuple[Decimal, Decimal],
                      rounds: int = 1, repeats: int = 1) -> Decimal:
    """Upper bound of one step's cost (075, finding S02 of the repeated security audit; before 075: 2 characters per
    token, which was not a bound). A byte-level BPE token covers at least one UTF-8 byte, so one request has at most
    `input_bytes + TOKEN_OVERHEAD` input tokens (`input_bytes`: everything sent, instructions and output schema too).
    `rounds`: conversation rounds (Pydantic AI's validation retries); round k also carries the k earlier answers and
    the retry prompts quoting them, so it adds k * (2 * max_output_tokens + TOKEN_OVERHEAD) input tokens. `repeats`:
    identical transport attempts per round (an SDK's own retries), each at full price. Rounded up to 0.000001 USD."""
    price_in, price_out = usd_per_mtok
    total = Decimal(0)
    for k in range(rounds):
        in_tok = input_bytes + TOKEN_OVERHEAD + k * (2 * max_output_tokens + TOKEN_OVERHEAD)
        total += Decimal(in_tok) * price_in + Decimal(max_output_tokens) * price_out
    return (total * repeats / Decimal(1_000_000)).quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def set_budget(scope: str, provider: str, limit_usd: Decimal) -> None:
    with store.connect() as c:
        c.execute("INSERT INTO budgets(scope, provider, limit_usd, created_at) VALUES (?,?,?,?)"
                  " ON CONFLICT(scope, provider) DO UPDATE SET limit_usd=excluded.limit_usd", (scope, provider, str(limit_usd), _now()))


def ensure_budget(scope: str, provider: str, limit_usd: Decimal) -> None:
    """063: adds a budget only if there is none yet (to complete a half-finished run start; an existing one stays)."""
    with store.connect() as c:
        c.execute("INSERT INTO budgets(scope, provider, limit_usd, created_at) VALUES (?,?,?,?) ON CONFLICT(scope, provider) DO NOTHING",
                  (scope, provider, str(limit_usd), _now()))


def _committed(c, scope: str, provider: str | None = None) -> Decimal:
    rows = c.execute("SELECT status, max_cost_usd, cost_usd, cost_known FROM invocations WHERE budget_scope=?"
                     + (" AND provider=?" if provider else ""), (scope, provider) if provider else (scope,)).fetchall()
    total = Decimal(0)
    for r in rows:
        total += Decimal(r["cost_usd"]) if r["cost_known"] else Decimal(r["max_cost_usd"])
    return total


def has_budget(scope: str, provider: str) -> bool:
    """075: whether the run has a budget for this provider at all (e.g. no Azure budget = the recipe switch is off)."""
    with store.connect() as c:
        return c.execute("SELECT 1 FROM budgets WHERE scope=? AND provider=?", (scope, provider)).fetchone() is not None


def budget_usage(scope: str) -> dict[str, Any]:
    with store.connect() as c:
        limits = {r["provider"]: Decimal(r["limit_usd"]) for r in c.execute("SELECT provider, limit_usd FROM budgets WHERE scope=?", (scope,))}
        per = {p: {"limit_usd": lim, "committed_usd": _committed(c, scope, p)} for p, lim in limits.items()}
        return {"scope": scope, "committed_usd": _committed(c, scope), "providers": per}


def _reserve(*, run_id: str, step_id: str, provider: str, model: str | None, max_cost_usd: Decimal,
             budget_scope: str | None, request_hash: str | None) -> tuple[int | None, Any]:
    """Reserves in one transaction. Returns (new invocation id, None), or on a repeat (None, (id, saved response))."""
    with store.connect() as c:
        c.commit()
        c.execute("BEGIN IMMEDIATE")
        prior = c.execute("SELECT id, attempt, status FROM invocations WHERE run_id=? AND step_id=? ORDER BY attempt",
                          (run_id, step_id)).fetchall()
        for p in prior:
            if p["status"] == "succeeded":
                saved = c.execute("SELECT payload FROM artifacts WHERE kind=? AND artifact_id=?",
                                  (RESPONSE_KIND, str(p["id"]))).fetchone()
                return None, (p["id"], json.loads(saved["payload"])["response"] if saved else None)
            if p["status"] in ("reserved", "uncertain"):
                raise UncertainAttempt(f"{run_id}/{step_id} attempt {p['attempt']} is {p['status']}")
        if budget_scope is not None:
            lim = c.execute("SELECT limit_usd FROM budgets WHERE scope=? AND provider=?", (budget_scope, provider)).fetchone()
            if lim is None:
                raise BudgetExceeded(f"no budget for provider {provider!r} in scope {budget_scope!r}")
            if c.execute("SELECT 1 FROM invocations WHERE budget_scope=? AND provider=? AND note=?",
                         (budget_scope, provider, OVERRUN_NOTE)).fetchone():
                raise BudgetExceeded(f"{budget_scope}/{provider}: an earlier call exceeded its reservation; no further calls")
            committed = _committed(c, budget_scope, provider)
            if committed + max_cost_usd > Decimal(lim["limit_usd"]):
                raise BudgetExceeded(f"{budget_scope}/{provider}: committed {committed} + max {max_cost_usd} > limit {lim['limit_usd']}")
        attempt = (prior[-1]["attempt"] + 1) if prior else 1
        cur = c.execute(
            "INSERT INTO invocations(run_id, step_id, attempt, provider, model_requested, request_hash, budget_scope, status,"
            " max_cost_usd, created_at) VALUES (?,?,?,?,?,?,?,'reserved',?,?)",
            (run_id, step_id, attempt, provider, model, request_hash, budget_scope, str(max_cost_usd), _now()))
        return int(cur.lastrowid), None


def invoke(*, run_id: str, step_id: str, provider: str, model: str | None, max_cost_usd: Decimal,
           fn: Callable[[], Outcome], budget_scope: str | None = None, request_hash: str | None = None) -> Result:
    """One physical call through the call log and the budget. Repeating a successful step returns the saved response."""
    inv_id, replay = _reserve(run_id=run_id, step_id=step_id, provider=provider, model=model, max_cost_usd=max_cost_usd,
                              budget_scope=budget_scope, request_hash=request_hash)
    if inv_id is None:
        return Result(response=replay[1], invocation_id=replay[0], replayed=True)
    try:
        out = fn()
    except BaseException as exc:
        status = "uncertain" if outcome_unknown(exc) else "failed"  # 085 (A04): sent but unanswered is not failed
        if status == "uncertain":
            log.warning("call %s/%s may have been processed (%s); its maximum stays reserved until settled by hand",
                        run_id, step_id, _error_text(exc))
        with store.connect() as c:
            c.execute("UPDATE invocations SET status=?, error=?, finished_at=? WHERE id=?", (status, _error_text(exc), _now(), inv_id))
        raise
    # 066 Á30: cost and tokens are saved with the response too, so that recovery after a shutdown can close it exactly
    store.save_artifact(RESPONSE_KIND, str(inv_id), {"response": out.response, "model": out.model, "input_tokens": out.input_tokens,
                                                     "output_tokens": out.output_tokens,
                                                     "cost_usd": None if out.cost_usd is None else str(out.cost_usd)})
    # 075 (S02): the bound failed if the actual cost is above it; the answer is kept (the money is spent), but the run
    # may not reserve with this provider again (`_reserve`), because its other reservations may be too low as well
    overrun = out.cost_usd is not None and out.cost_usd > max_cost_usd
    with store.connect() as c:
        c.execute("UPDATE invocations SET status='succeeded', model_actual=?, input_tokens=?, output_tokens=?, cost_usd=?, cost_known=?,"
                  " note=COALESCE(?, note), finished_at=? WHERE id=?",
                  (out.model, out.input_tokens, out.output_tokens, None if out.cost_usd is None else str(out.cost_usd),
                   int(out.cost_usd is not None), OVERRUN_NOTE if overrun else None, _now(), inv_id))
    if overrun:
        log.warning("call %s/%s cost %s, above its reserved maximum %s", run_id, step_id, out.cost_usd, max_cost_usd)
    return Result(response=out.response, invocation_id=inv_id, replayed=False)


def recover_uncertain() -> int:
    """At worker startup: unfinished reservations become uncertain (the maximum stays committed). 066 Á30: if the
    response is already saved (the shutdown came between saving it and marking the call "succeeded"), the call becomes
    succeeded with the saved cost (failing that, with an unknown cost and the maximum committed), so repeating the step
    returns the saved response. 085 (re-audit A05): a saved cost above the reservation sets the same overrun lock as
    the normal path. Returns the number of reservations that became uncertain."""
    with store.connect() as c:
        c.commit()
        c.execute("BEGIN IMMEDIATE")
        for r in c.execute("SELECT i.id, i.max_cost_usd, a.payload FROM invocations i JOIN artifacts a ON a.kind=?"
                           " AND a.artifact_id=CAST(i.id AS TEXT) WHERE i.status IN ('reserved','uncertain')", (RESPONSE_KIND,)).fetchall():
            saved = json.loads(r["payload"])
            cost = saved.get("cost_usd")
            overrun = cost is not None and Decimal(cost) > Decimal(r["max_cost_usd"])
            if overrun:
                log.warning("recovered call %s cost %s, above its reserved maximum %s", r["id"], cost, r["max_cost_usd"])
            c.execute("UPDATE invocations SET status='succeeded', model_actual=?, input_tokens=?, output_tokens=?, cost_usd=?,"
                      " cost_known=?, note=CASE WHEN ? THEN ? ELSE COALESCE(note, 'recovered_saved_response') END, finished_at=?"
                      " WHERE id=?",
                      (saved.get("model"), saved.get("input_tokens"), saved.get("output_tokens"), cost, int(cost is not None),
                       int(overrun), OVERRUN_NOTE, _now(), r["id"]))
        return c.execute("UPDATE invocations SET status='uncertain' WHERE status='reserved'").rowcount


def resolve_uncertain(invocation_id: int, *, cost_usd: Decimal | None, note: str) -> None:
    """Manual resolution (e.g. after checking the provider's console): the attempt becomes `failed`, with a known cost
    or with the maximum still committed; afterwards the step can run with a new attempt."""
    with store.connect() as c:
        row = c.execute("SELECT status FROM invocations WHERE id=?", (invocation_id,)).fetchone()
        if row is None or row["status"] not in ("reserved", "uncertain"):
            raise ValueError(f"invocation {invocation_id} is not uncertain")
        c.execute("UPDATE invocations SET status='failed', cost_usd=?, cost_known=?, note=?, error=COALESCE(error, 'uncertain_resolved'),"
                  " finished_at=? WHERE id=?",
                  (None if cost_usd is None else str(cost_usd), int(cost_usd is not None), note, _now(), invocation_id))


def uncertain_list() -> list[dict[str, Any]]:
    """Calls with an uncertain outcome awaiting manual resolution (066 Á30: CLI listing before `resolve_uncertain`)."""
    with store.connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, run_id, step_id, attempt, provider, model_requested, budget_scope, max_cost_usd, created_at, status"
            " FROM invocations WHERE status='uncertain' ORDER BY id")]


def journal(run_id: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM invocations WHERE run_id=? ORDER BY id", (run_id,))]


def scope_journal(scope: str) -> list[dict[str, Any]]:
    """All calls of one budget (run), regardless of items: for the run's cost view (040 K2)."""
    with store.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM invocations WHERE budget_scope=? ORDER BY id", (scope,))]
