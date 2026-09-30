"""Egységes hívásnapló és előzetes költségfoglalás (040 K1; a 038-as értékelés F05 és F06 hibájára).

Minden fizikai szolgáltatói hívás (OpenAI, JEV, később OCR) előtt tartós `reserved` bejegyzés készül a maximális
költséggel, és ha van keret (`budget_scope`), a foglalás CSAK akkor jön létre, ha a lekötött összeg + a maximum
belefér. A foglalás és az ellenőrzés egy `BEGIN IMMEDIATE` tranzakció, ezért egyidejű kérésnél is helyes.

Állapotok és a keretbe számított összeg:
- `reserved`   : a hívás folyamatban vagy a folyamat összeomlott → a maximum lekötve; ugyanazt a lépést NEM hívjuk újra
                 automatikusan (`UncertainAttempt`); induláskor `recover_uncertain()` jelöli `uncertain`-nek.
- `uncertain`  : mint a `reserved`; kézi rendezés: `resolve_uncertain(id, cost_usd)`.
- `succeeded`  : ismert költségnél a tényleges összeg, ismeretlennél a maximum marad lekötve. A válasz bizonylatként
                 mentve; a lépés ismétlése a mentett választ adja (`replayed=True`), új hívás nélkül.
- `failed`     : a hiba típusa naplózva; a költség ismeretlen, ezért a maximum lekötve marad (nem nulla, nem szabadul fel).
                 Ugyanaz a lépés új kísérletszámmal újrapróbálható (a hívó dönt, pl. a munkasor próbálkozáskerete).
Pénz: `Decimal`, szövegként tárolva. A régi `ledger` táblát a meglévő adapterek továbbra is írják; ez a napló a
foglalás és a folytathatóság forrása.
"""

from __future__ import annotations

import json
import math
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable

from jav import store

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
    """A maximális költség nem fér bele a keretbe; a hálózatot el sem értük."""


class UncertainAttempt(RuntimeError):
    """A lépésnek van lezáratlan (összeomlott vagy bizonytalan kimenetű) kísérlete; automatikus új hívás tilos."""


@dataclass(frozen=True)
class Outcome:
    """A fizikai hívás eredménye, amit a hívó függvény ad vissza."""
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
    """A feldolgozó állítja be egy futás tételére: ekkor a szolgáltatói adapterek a naplón és a kereten át hívnak."""
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
    """None: régi parancssori / mérési út, napló és keret nélkül (a korábbi viselkedés)."""
    return _context.get()


def estimate_max_cost(*, input_chars: int, max_output_tokens: int, usd_per_mtok: tuple[Decimal, Decimal],
                      physical_attempts: int, chars_per_token: int = 2) -> Decimal:
    """Felső becslés: minden lehetséges fizikai kísérlet (SDK- és validációs újrapróbálás) teljes áron."""
    in_tok = math.ceil(input_chars / chars_per_token)
    per_call = (Decimal(in_tok) * usd_per_mtok[0] + Decimal(max_output_tokens) * usd_per_mtok[1]) / Decimal(1_000_000)
    return (per_call * physical_attempts).quantize(Decimal("0.000001"))


def set_budget(scope: str, provider: str, limit_usd: Decimal) -> None:
    with store.connect() as c:
        c.execute("INSERT INTO budgets(scope, provider, limit_usd, created_at) VALUES (?,?,?,?)"
                  " ON CONFLICT(scope, provider) DO UPDATE SET limit_usd=excluded.limit_usd", (scope, provider, str(limit_usd), _now()))


def ensure_budget(scope: str, provider: str, limit_usd: Decimal) -> None:
    """063: keret felvétele csak akkor, ha még nincs (a félbemaradt futásindítás pótlásához; a meglévő keret marad)."""
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


def budget_usage(scope: str) -> dict[str, Any]:
    with store.connect() as c:
        limits = {r["provider"]: Decimal(r["limit_usd"]) for r in c.execute("SELECT provider, limit_usd FROM budgets WHERE scope=?", (scope,))}
        per = {p: {"limit_usd": lim, "committed_usd": _committed(c, scope, p)} for p, lim in limits.items()}
        return {"scope": scope, "committed_usd": _committed(c, scope), "providers": per}


def _reserve(*, run_id: str, step_id: str, provider: str, model: str | None, max_cost_usd: Decimal,
             budget_scope: str | None, request_hash: str | None) -> tuple[int | None, Any]:
    """Foglalás egy tranzakcióban. Visszaad: (új invocation id, None) vagy (None, mentett válasz) ismétlésnél."""
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
    """Egy fizikai hívás a naplón és a kereten át. Sikeres lépés ismétlése a mentett választ adja új hívás nélkül."""
    inv_id, replay = _reserve(run_id=run_id, step_id=step_id, provider=provider, model=model, max_cost_usd=max_cost_usd,
                              budget_scope=budget_scope, request_hash=request_hash)
    if inv_id is None:
        return Result(response=replay[1], invocation_id=replay[0], replayed=True)
    try:
        out = fn()
    except BaseException as exc:
        with store.connect() as c:
            c.execute("UPDATE invocations SET status='failed', error=?, finished_at=? WHERE id=?", (type(exc).__name__, _now(), inv_id))
        raise
    # 066 Á30: a költség és a tokenek is a mentett válasz mellé, hogy egy leállás után a helyreállítás pontosan lezárhassa
    store.save_artifact(RESPONSE_KIND, str(inv_id), {"response": out.response, "model": out.model, "input_tokens": out.input_tokens,
                                                     "output_tokens": out.output_tokens,
                                                     "cost_usd": None if out.cost_usd is None else str(out.cost_usd)})
    with store.connect() as c:
        c.execute("UPDATE invocations SET status='succeeded', model_actual=?, input_tokens=?, output_tokens=?, cost_usd=?, cost_known=?,"
                  " finished_at=? WHERE id=?",
                  (out.model, out.input_tokens, out.output_tokens, None if out.cost_usd is None else str(out.cost_usd),
                   int(out.cost_usd is not None), _now(), inv_id))
    return Result(response=out.response, invocation_id=inv_id, replayed=False)


def recover_uncertain() -> int:
    """A feldolgozó indulásakor: a lezáratlan foglalások bizonytalanná válnak (a maximum lekötve marad). 066 Á30: ha a
    válasz már el van mentve (a leállás a mentés és a „sikeres” jelölés között történt), a hívás sikeres lesz a mentett
    költséggel (ennek híján ismeretlen költséggel, a maximum lekötve), így a lépés ismétlése a mentett választ adja.
    Visszaadja a bizonytalanná vált foglalások számát."""
    with store.connect() as c:
        c.commit()
        c.execute("BEGIN IMMEDIATE")
        for r in c.execute("SELECT i.id, a.payload FROM invocations i JOIN artifacts a ON a.kind=? AND a.artifact_id=CAST(i.id AS TEXT)"
                           " WHERE i.status IN ('reserved','uncertain')", (RESPONSE_KIND,)).fetchall():
            saved = json.loads(r["payload"])
            cost = saved.get("cost_usd")
            c.execute("UPDATE invocations SET status='succeeded', model_actual=?, input_tokens=?, output_tokens=?, cost_usd=?,"
                      " cost_known=?, note=COALESCE(note, 'recovered_saved_response'), finished_at=? WHERE id=?",
                      (saved.get("model"), saved.get("input_tokens"), saved.get("output_tokens"), cost, int(cost is not None),
                       _now(), r["id"]))
        return c.execute("UPDATE invocations SET status='uncertain' WHERE status='reserved'").rowcount


def resolve_uncertain(invocation_id: int, *, cost_usd: Decimal | None, note: str) -> None:
    """Kézi rendezés (pl. a szolgáltatói felületen ellenőrizve): a kísérlet `failed` lesz, ismert költséggel vagy
    továbbra is lekötött maximummal; utána a lépés új kísérlettel futtatható."""
    with store.connect() as c:
        row = c.execute("SELECT status FROM invocations WHERE id=?", (invocation_id,)).fetchone()
        if row is None or row["status"] not in ("reserved", "uncertain"):
            raise ValueError(f"invocation {invocation_id} is not uncertain")
        c.execute("UPDATE invocations SET status='failed', cost_usd=?, cost_known=?, note=?, error=COALESCE(error, 'uncertain_resolved'),"
                  " finished_at=? WHERE id=?",
                  (None if cost_usd is None else str(cost_usd), int(cost_usd is not None), note, _now(), invocation_id))


def uncertain_list() -> list[dict[str, Any]]:
    """A kézi rendezésre váró, bizonytalan kimenetű hívások (066 Á30: a `resolve_uncertain` parancssori előzménye)."""
    with store.connect() as c:
        return [dict(r) for r in c.execute(
            "SELECT id, run_id, step_id, attempt, provider, model_requested, budget_scope, max_cost_usd, created_at, status"
            " FROM invocations WHERE status='uncertain' ORDER BY id")]


def journal(run_id: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM invocations WHERE run_id=? ORDER BY id", (run_id,))]


def scope_journal(scope: str) -> list[dict[str, Any]]:
    """Egy keret (futás) összes hívása, tételektől függetlenül: a futás költségnézetéhez (040 K2)."""
    with store.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM invocations WHERE budget_scope=? ORDER BY id", (scope,))]
