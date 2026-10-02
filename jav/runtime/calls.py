"""Unified call log and upfront cost reservation (040 K1; for findings F05 and F06 of the 038 review).

Before every physical provider call (OpenAI, JEV, later OCR) a durable `reserved` entry is made with the maximum cost,
and if there is a budget (`budget_scope`) the reservation is created ONLY if the committed amount + the maximum fits.
Reservation and check run in one `BEGIN IMMEDIATE` transaction, so they stay correct under concurrent requests.

States and the amount counted against the budget:
- `reserved`   : the call is in progress or the process crashed → the maximum is committed; the same step is NOT called
                 again automatically (`UncertainAttempt`); at startup `recover_uncertain()` marks it `uncertain` once
                 the process that reserved it has stopped (092: the reservation names its holder, a lock the process
                 holds for its lifetime). It cannot be settled by hand (090, audit N03): it may still finish and cost
                 money.
- `uncertain`  : like `reserved`; manual resolution: `resolve_uncertain(id, cost_usd)`. A completion arriving later
                 closes it only while nobody has settled it.
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

import atexit
import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import IO, Any, Callable

from jav import store
from jav.runtime import lock

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
    holder          TEXT,                       -- 092: the reserving process's holder lock (`holder()`)
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



def _add_holder_column(conn) -> None:
    """092: the holder column on a call log created before it."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(invocations)")}
    if cols and "holder" not in cols:
        conn.execute("ALTER TABLE invocations ADD COLUMN holder TEXT")


store.register_migration("runtime.calls.holder", _add_holder_column)

RESPONSE_KIND = "invocation_response"
_OPEN = "('reserved', 'uncertain')"  # 090: the states a completion may still close


class BudgetExceeded(RuntimeError):
    """The maximum cost does not fit into the budget; the network was never reached."""


class UncertainAttempt(RuntimeError):
    """The step has an unfinished attempt (crashed or with an uncertain outcome); an automatic new call is forbidden."""


class NotUncertain(ValueError):
    """090 (audit N03): manual settlement refused: the call is unknown, still in progress (`reserved`), or settled."""


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
    reused_from: int | None = None  # 090: the earlier call whose answer was reused (another run, the same question)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class RunContext:
    """Set by the worker for an item of a run: the provider adapters then call through the call log and the budget.
    `reuse` (090): the run's "earlier answers" setting allows reusing an earlier answer to the same question."""
    budget_scope: str | None
    reuse: bool = False


_context: ContextVar[RunContext | None] = ContextVar("jav_run_context", default=None)


@contextmanager
def use_run(*, budget_scope: str | None, reuse: bool = False):
    token = _context.set(RunContext(budget_scope=budget_scope, reuse=reuse))
    try:
        yield
    finally:
        _context.reset(token)


@contextmanager
def measurement(scope: str, limits: dict[str, Decimal]):
    """086: a paid measurement outside a work run, under a hard budget (the owner's sub-budget): every call reserves from
    `scope`'s budget and goes into the call log; a provider without a limit here cannot be called at all (e.g. no
    Azure escalation, no stray JEV call)."""
    for provider, limit in limits.items():
        set_budget(scope, provider, limit)
    with use_run(budget_scope=scope):
        yield scope


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


REUSED_NOTE = "reused_answer"  # 090: `reused_answer:<id of the call whose answer was reused>`


def answer_key(provider: str, model: str | None, *parts: str) -> str:
    """090: the fingerprint of a question for reusing an earlier answer: the provider, the configured model and every
    text that shapes the answer (instructions, output schema, settings, the document). A change to any of them asks
    again. The configured model name counts: a model behind an unchanged name is not told apart."""
    return hashlib.sha256(json.dumps([provider, model, *parts], ensure_ascii=False).encode("utf-8")).hexdigest()


def _reuse_earlier(c, *, run_id: str, step_id: str, attempt: int, provider: str, model: str | None,
                   request_hash: str, budget_scope: str | None) -> tuple[int, int, Any] | None:
    """090: the latest succeeded answer of another call to the same question, copied as this step's answer (cost 0,
    noted with its origin, the saved response beside it so that the step replays within its run); None if there is
    none. Runs inside the reservation's transaction."""
    hit = c.execute("SELECT i.id, i.model_actual, a.payload FROM invocations i JOIN artifacts a ON a.kind=?"
                    " AND a.artifact_id=CAST(i.id AS TEXT) WHERE i.provider=? AND i.request_hash=? AND i.status='succeeded'"
                    " ORDER BY i.id DESC LIMIT 1", (RESPONSE_KIND, provider, request_hash)).fetchone()
    if hit is None:
        return None
    now = _now()
    cur = c.execute(
        "INSERT INTO invocations(run_id, step_id, attempt, provider, model_requested, model_actual, request_hash, budget_scope,"
        " status, max_cost_usd, cost_usd, cost_known, note, created_at, finished_at)"
        " VALUES (?,?,?,?,?,?,?,?,'succeeded','0','0',1,?,?,?)",
        (run_id, step_id, attempt, provider, model, hit["model_actual"], request_hash, budget_scope,
         f"{REUSED_NOTE}:{hit['id']}", now, now))
    new_id = int(cur.lastrowid)
    c.execute("INSERT INTO artifacts VALUES (?,?,?,?)", (RESPONSE_KIND, str(new_id), hit["payload"], now))
    return new_id, int(hit["id"]), json.loads(hit["payload"])["response"]


HOLDER_DIR = "call-holders"
HOLDER_STALE_S = 60
"""092: a holder's lock file lies next to the store; a file nobody holds is removed by the recovery once it is older than
this (a process creates and locks its file at once, so a young file may belong to a process that is just starting)."""
_HOLDER_TOKEN = re.compile(r"[0-9]+-[0-9a-f]+")
_holders: dict[str, tuple[str, IO[bytes]]] = {}
_holders_guard = threading.Lock()


def holder_path(token: str) -> Path:
    return store.current_path().with_name(HOLDER_DIR) / f"{token}.lock"


def holder() -> str:
    """092: this process's holder on the current store: a token whose lock file the process keeps locked for its
    lifetime (the operating system releases it when the process dies). Every reservation records it, so that a worker
    start can tell a call still in progress in another process (e.g. a command-line measurement) from a crashed one."""
    key = str(store.current_path())
    with _holders_guard:
        held = _holders.get(key)
        if held is None:
            token = f"{os.getpid()}-{secrets.token_hex(8)}"
            held = _holders[key] = (token, lock.hold(holder_path(token)))
        return held[0]


def release_holder() -> None:
    """092: the process lets go of its holder on the current store (at exit; the tests simulate the process's death
    with it). Its open reservations then count as abandoned; a later reservation takes a new holder."""
    with _holders_guard:
        held = _holders.pop(str(store.current_path()), None)
    if held is not None:
        lock.release(held[1])
        holder_path(held[0]).unlink(missing_ok=True)


@atexit.register
def release_all_holders() -> None:
    """092: at exit (and after each test) every holder this process took is let go."""
    with _holders_guard:
        held = list(_holders.values())
        _holders.clear()
    for _, f in held:
        lock.release(f)


def _holder_alive(token: str | None) -> bool:
    """Whether the process behind a reservation is still running; a reservation without a holder (before 092) or with
    an unreadable one counts as stopped, as all reservations did before."""
    return bool(token) and _HOLDER_TOKEN.fullmatch(token) is not None and lock.is_held(holder_path(token))


def _remove_stopped_holder_files() -> None:
    folder = store.current_path().with_name(HOLDER_DIR)
    if not folder.is_dir():
        return
    cutoff = time.time() - HOLDER_STALE_S
    for path in folder.glob("*.lock"):
        try:
            if path.stat().st_mtime < cutoff and not lock.is_held(path):
                path.unlink()
        except OSError as exc:  # taken or removed meanwhile by another process: the next start tries again
            log.debug("holder file %s left in place: %s", path.name, exc)


def _reserve(*, run_id: str, step_id: str, provider: str, model: str | None, max_cost_usd: Decimal,
             budget_scope: str | None, request_hash: str | None, reuse: bool = False) -> tuple[int | None, Any]:
    """Reserves in one transaction. Returns (new invocation id, None), or on a repeat (None, (id, saved response)), or,
    090, with `reuse`, an earlier answer to the same question: (None, (id, response, the call it came from))."""
    me = holder()
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
        attempt = (prior[-1]["attempt"] + 1) if prior else 1
        if reuse and request_hash:
            reused = _reuse_earlier(c, run_id=run_id, step_id=step_id, attempt=attempt, provider=provider, model=model,
                                    request_hash=request_hash, budget_scope=budget_scope)
            if reused is not None:
                return None, (reused[0], reused[2], reused[1])
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
        cur = c.execute(
            "INSERT INTO invocations(run_id, step_id, attempt, provider, model_requested, request_hash, budget_scope, status,"
            " max_cost_usd, created_at, holder) VALUES (?,?,?,?,?,?,?,'reserved',?,?,?)",
            (run_id, step_id, attempt, provider, model, request_hash, budget_scope, str(max_cost_usd), _now(), me))
        return int(cur.lastrowid), None


def invoke(*, run_id: str, step_id: str, provider: str, model: str | None, max_cost_usd: Decimal,
           fn: Callable[[], Outcome], budget_scope: str | None = None, request_hash: str | None = None,
           reusable: bool = False) -> Result:
    """One physical call through the call log and the budget. Repeating a successful step returns the saved response.
    090: a `reusable` caller (its `request_hash` is an `answer_key`) gets an earlier answer to the same question when
    the run allows it (`use_run(reuse=True)`): no call, cost 0, a cached row in the ledger."""
    ctx = current()
    reuse = reusable and ctx is not None and ctx.reuse
    inv_id, replay = _reserve(run_id=run_id, step_id=step_id, provider=provider, model=model, max_cost_usd=max_cost_usd,
                              budget_scope=budget_scope, request_hash=request_hash, reuse=reuse)
    if inv_id is None:
        if len(replay) == 3:  # 090: reused from another call
            store.ledger_add(run_id=run_id, step=step_id, provider=provider, model=model, input_tokens=None, output_tokens=None,
                             cost_usd=0.0, seconds=0.0, cached=True, cache_key=(request_hash or "")[:16])
            return Result(response=replay[1], invocation_id=replay[0], replayed=True, reused_from=replay[2])
        return Result(response=replay[1], invocation_id=replay[0], replayed=True)
    try:
        out = fn()
    except BaseException as exc:
        status = "uncertain" if outcome_unknown(exc) else "failed"  # 085 (A04): sent but unanswered is not failed
        if status == "uncertain":
            log.warning("call %s/%s may have been processed (%s); its maximum stays reserved until settled by hand",
                        run_id, step_id, _error_text(exc))
        with store.connect() as c:
            c.execute(f"UPDATE invocations SET status=?, error=?, finished_at=? WHERE id=? AND status IN {_OPEN}",
                      (status, _error_text(exc), _now(), inv_id))
        raise
    # 066 Á30: cost and tokens are saved with the response too, so that recovery after a shutdown can close it exactly
    store.save_artifact(RESPONSE_KIND, str(inv_id), {"response": out.response, "model": out.model, "input_tokens": out.input_tokens,
                                                     "output_tokens": out.output_tokens,
                                                     "cost_usd": None if out.cost_usd is None else str(out.cost_usd)})
    # 075 (S02): the bound failed if the actual cost is above it; the answer is kept (the money is spent), but the run
    # may not reserve with this provider again (`_reserve`), because its other reservations may be too low as well
    overrun = out.cost_usd is not None and out.cost_usd > max_cost_usd
    with store.connect() as c:
        # 090 (audit N03): an open attempt only. One settled by hand in the meantime (a worker start marked it
        # uncertain while this process was still waiting) keeps that settlement; the answer is in the saved receipt.
        closed = c.execute(
            "UPDATE invocations SET status='succeeded', model_actual=?, input_tokens=?, output_tokens=?, cost_usd=?, cost_known=?,"
            f" note=COALESCE(?, note), finished_at=? WHERE id=? AND status IN {_OPEN}",
            (out.model, out.input_tokens, out.output_tokens, None if out.cost_usd is None else str(out.cost_usd),
             int(out.cost_usd is not None), OVERRUN_NOTE if overrun else None, _now(), inv_id)).rowcount
    if not closed:
        log.warning("call %s/%s answered (cost %s) after it was settled by hand; the settlement stays", run_id, step_id,
                    out.cost_usd)
    if overrun:
        log.warning("call %s/%s cost %s, above its reserved maximum %s", run_id, step_id, out.cost_usd, max_cost_usd)
    return Result(response=out.response, invocation_id=inv_id, replayed=False)


def recover_uncertain() -> int:
    """At worker startup: unfinished reservations become uncertain (the maximum stays committed). 066 Á30: if the
    response is already saved (the shutdown came between saving it and marking the call "succeeded"), the call becomes
    succeeded with the saved cost (failing that, with an unknown cost and the maximum committed), so repeating the step
    returns the saved response. 085 (re-audit A05): a saved cost above the reservation sets the same overrun lock as
    the normal path. 092: only the reservations of processes that have stopped; a running process (e.g. a command-line
    measurement waiting for its answer) closes its own calls. Returns the number of reservations that became uncertain."""
    with store.connect() as c:
        c.commit()
        c.execute("BEGIN IMMEDIATE")
        live = sorted(r["holder"] for r in c.execute(
            "SELECT DISTINCT holder FROM invocations WHERE status IN ('reserved','uncertain') AND holder IS NOT NULL")
            if _holder_alive(r["holder"]))
        stopped = f" AND (holder IS NULL OR holder NOT IN ({','.join('?' * len(live))}))" if live else ""
        if live:
            log.info("%d running process(es) still hold reservations; their calls stay in progress", len(live))
        for r in c.execute("SELECT i.id, i.max_cost_usd, a.payload FROM invocations i JOIN artifacts a ON a.kind=?"
                           " AND a.artifact_id=CAST(i.id AS TEXT) WHERE i.status IN ('reserved','uncertain')"
                           + stopped.replace("holder", "i.holder"), (RESPONSE_KIND, *live)).fetchall():
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
        marked = c.execute("UPDATE invocations SET status='uncertain' WHERE status='reserved'" + stopped, live).rowcount
    _remove_stopped_holder_files()
    return marked


def resolve_uncertain(invocation_id: int, *, cost_usd: Decimal | None, note: str) -> None:
    """Manual resolution (e.g. after checking the provider's console): the attempt becomes `failed`, with a known cost
    or with the maximum still committed; afterwards the step can run with a new attempt.
    090 (audit N03): only an `uncertain` attempt, in one conditional write. A `reserved` one may still be in progress:
    releasing its maximum would let a second call spend the same budget while the first one can still finish and cost
    money. An interrupted process's reservation becomes uncertain at the next worker start (`recover_uncertain`), once
    that process has stopped (092)."""
    with store.connect() as c:
        settled = c.execute(
            "UPDATE invocations SET status='failed', cost_usd=?, cost_known=?, note=?, error=COALESCE(error, 'uncertain_resolved'),"
            " finished_at=? WHERE id=? AND status='uncertain'",
            (None if cost_usd is None else str(cost_usd), int(cost_usd is not None), note, _now(), invocation_id)).rowcount
        if settled:
            return
        row = c.execute("SELECT status FROM invocations WHERE id=?", (invocation_id,)).fetchone()
    if row is not None and row["status"] == "reserved":
        raise NotUncertain(f"invocation {invocation_id} is still in progress (reserved); it cannot be settled by hand")
    raise NotUncertain(f"invocation {invocation_id} is not uncertain")


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
