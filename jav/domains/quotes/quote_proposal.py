"""The quote's proposal: each requested item matched with the active price list, by the worker (191, plan
F-quote-package B4c).

Plain-language summary (DECISIONS 191): the owner asked that the system proposes the quote's content. On a quote
package's page a person asks for the proposal; the button shows its cost cap (`configs/quotes.json`: a budget per
requested item and provider). The local service only queues the request; the worker matches each requested item with
the active price list (`jav/domains/quotes/quote_match.py`), with the application's AI engine (JEV, or GPT without JEV), under that
budget and through the call log, and stores each item's answer and mark. The latest proposal of a package is kept; it
says which request and price list version it was made for, so the page can tell when the request or the list has
changed since. Nothing is decided: a person reviews every line (B5).

- `request(wp_id, actor)`: queues a proposal (one at a time per package);
- `process_job(job)`, `abandon_job(job, error)`: the worker's job kind (`JOB`);
- `current(wp_id)`: the latest proposal, with `stale` when the request or the price list changed since.

Stage D0 (D0-b): a proposal is its case's match step's (`step`; None: the case's first match step,
`jav/domains/quotes/quote_steps.py`), so two match steps of a case keep two proposals, each under its own budget.

Layer: application operation of the quotes domain over the queue, the call log, the quote request and the match.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from jav.app import app_settings
from jav.core import cfg, identity, store
from jav.domains.quotes import price_lists, quote_match, quote_request, quote_steps
from jav.runtime import job_kinds
from jav.core import calls
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now

JOB_KIND = "quote_propose"
STATES = ("queued", "running", "done", "failed")

_DDL = """
-- 191 (plan F-quote-package B4c): a quote package's latest proposal: each requested item's match with the price list
CREATE TABLE IF NOT EXISTS quote_proposals (
    workpackage_id TEXT NOT NULL,
    step_id        TEXT NOT NULL DEFAULT '',  -- D0-b: the case's match step it is of ('': a package that is no case's)
    state          TEXT NOT NULL,      -- queued, running, done, failed
    engine         TEXT NOT NULL,      -- jev | gpt: the application's engine when it was asked
    request_key    TEXT NOT NULL,      -- the requested items it was asked for (sha256 of their JSON)
    price_list     TEXT NOT NULL,
    version        INTEGER NOT NULL,
    fingerprint    TEXT NOT NULL,      -- the price list version's
    limits         TEXT NOT NULL,      -- JSON: provider -> the budget in USD
    lines          TEXT,               -- JSON: per requested item its text, quantity, unit and the answer
    usage          TEXT,               -- JSON: the budget scope's use
    error          TEXT,
    scope          TEXT,
    requested_by   TEXT NOT NULL,
    requested_by_id TEXT,              -- 229 (SZ2c): the stable id beside the name (`jav.core.identity`)
    requested_at   TEXT NOT NULL,
    finished_at    TEXT,
    PRIMARY KEY (workpackage_id, step_id)
);
"""
store.register_schema("quote_proposals", _DDL)
store.register_migration("quote_proposals_actor_ids",
                         lambda conn: store.add_actor_ids(conn, "quote_proposals", ("requested_by",)))  # 229 (SZ2c)
store.register_migration("quote_proposals_steps",  # D0-b: keyed by the case's match step
                         lambda conn: quote_steps.rebuild(conn, "quote_proposals", _DDL, quote_steps.MATCH))


class ProposalRefused(ValueError):
    """A proposal that cannot be asked: no readable request, no requested item, no active price list, or too many."""


def settings() -> dict[str, Any]:
    return cfg.load("quotes")["proposal"]


def request_key(items: list[dict[str, Any]]) -> str:
    return hashlib.sha256(cfg.canonical({"items": items}).encode("utf-8")).hexdigest()


def cap(n_items: int, engine: str) -> dict[str, Decimal]:
    """The budget a proposal of `n_items` reserves with the engine: provider -> USD."""
    provider = quote_match.PROVIDERS[engine]
    return {provider: Decimal(settings()["max_item_usd"][provider]) * n_items}


def _active(selection: str = price_lists.NEWEST_ACTIVE) -> price_lists.PriceList | None:
    """The price list a proposal uses: by default the newest list's active version (B5 lets a quote choose another;
    231, A3b: a process names its own)."""
    return price_lists.chosen(selection)


def _source(wp_id: str) -> quote_request.Request:
    from jav.domains.quotes import quote_package

    ref = quote_package.request_of(wp_id)
    if not ref:
        raise explained(ProposalRefused, "the case names no request")
    try:
        return quote_request.read(ref["workpackage_id"], ref["item_id"])
    except quote_request.RequestNotFound as exc:
        raise explained(ProposalRefused, "the request can no longer be read") from exc


def _step(wp_id: str, step: str | None) -> str:
    """D0-b: the case's match step a proposal is of (None: the case's first)."""
    return quote_steps.of(wp_id).match if step is None else step


def _row(c: Any, wp_id: str, step: str) -> Any:
    return c.execute("SELECT * FROM quote_proposals WHERE workpackage_id=? AND step_id=?", (wp_id, step)).fetchone()


def request(wp_id: str, *, actor: identity.Who, selection: str = price_lists.NEWEST_ACTIVE,
            step: str | None = None) -> dict[str, Any]:
    """Queues the package's proposal with the application's engine and the cap for its requested items; a proposal
    already queued or running is returned as it is. `ProposalRefused` when it cannot be asked. 231 (A5): `selection`
    is the process's price list choice (`price_lists.chosen`). D0-b: of the case's match `step`."""
    from jav.core import queue

    step = _step(wp_id, step)
    req = _source(wp_id)
    if not req.items:
        raise explained(ProposalRefused, "the request names no item")
    if len(req.items) > int(settings()["max_items"]):
        raise explained(ProposalRefused, "the request names more items than a proposal asks about: {{n}}", n=len(req.items))
    prices = _active(selection)
    if prices is None:
        raise explained(ProposalRefused, "there is no active price list")
    engine = app_settings.engine_default()
    limits = cap(len(req.items), engine)
    with store.connect() as c:
        store.begin_immediate(c)
        row = _row(c, wp_id, step)
        if row is not None and row["state"] in ("queued", "running"):
            return current(wp_id, step=step) or {}
        c.execute("INSERT OR REPLACE INTO quote_proposals(workpackage_id, step_id, state, engine, request_key, price_list,"
                  " version, fingerprint, limits, requested_by, requested_by_id, requested_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (wp_id, step, "queued", engine, request_key(req.items), prices.price_list, prices.version, prices.fingerprint,
                   json.dumps({k: str(v) for k, v in limits.items()}), identity.name_of(actor), identity.id_of(actor), _now()))
    queue.enqueue(JOB_KIND, run_id=None, payload={"workpackage_id": wp_id, "step_id": step, "requested_at": _now()})
    return current(wp_id, step=step) or {}


def _ask(req: quote_request.Request, prices: price_lists.PriceList, engine: str, scope: str) -> list[dict[str, Any]]:
    written = [str(i.get("description") or "") for i in req.items]
    lines = []
    for n, item in enumerate(req.items):
        requested = {"description": item.get("description"), "quantity": item.get("quantity"), "unit": item.get("unit")}
        context = [w for k, w in enumerate(written) if k != n]
        try:
            answer = quote_match.match(requested, context, prices, engine=engine, run_id=scope)
        except Exception as exc:  # noqa: BLE001 - JEV unavailable, the budget spent or an OpenAI error: this item's, the rest go on
            answer = {"mark": None, "error": f"{type(exc).__name__}: {exc}"}
        lines.append({"row": n, **requested, "answer": answer})
    return lines


def process_job(job: Any) -> str:
    """The worker's proposal job: each requested item asked under the proposal's budget; the job is always completed,
    a failure shows on the proposal."""
    from jav.core import queue

    wp_id = job.payload["workpackage_id"]
    step = _step(wp_id, job.payload.get("step_id"))  # D0-b: a job queued before names no step: the case's first
    with store.connect() as c:
        row = _row(c, wp_id, step)
    if row is None or row["state"] not in ("queued", "running"):
        return queue.complete(job.id)
    with store.connect() as c:
        c.execute("UPDATE quote_proposals SET state='running' WHERE workpackage_id=? AND step_id=?", (wp_id, step))
    try:
        req = _source(wp_id)
        prices = price_lists.version(row["price_list"], row["version"])
        limits = {k: Decimal(v) for k, v in json.loads(row["limits"]).items()}
        scope = f"quote-{wp_id}-{step + '-' if step else ''}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        with calls.outside_run(scope, limits) as scope:  # 231 (A3a): business work, not a measurement
            lines = _ask(req, prices, row["engine"], scope)
        failed = all(line["answer"].get("error") for line in lines)
        with store.connect() as c:
            c.execute("UPDATE quote_proposals SET state=?, request_key=?, lines=?, usage=?, scope=?, finished_at=?, error=?"
                      " WHERE workpackage_id=? AND step_id=?",
                      ("failed" if failed else "done", request_key(req.items), json.dumps(lines, ensure_ascii=False, default=str),
                       json.dumps(calls.budget_usage(scope), default=str), scope, _now(),
                       lines[0]["answer"]["error"] if failed and lines else None, wp_id, step))
    except Exception as exc:  # noqa: BLE001 - the proposal shows why it failed; the worker goes on
        abandon(wp_id, f"{type(exc).__name__}: {exc}", step=step)
    return queue.complete(job.id)


def abandon(wp_id: str, error: str, *, step: str | None = None) -> None:
    step = _step(wp_id, step)
    with store.connect() as c:
        c.execute("UPDATE quote_proposals SET state='failed', error=?, finished_at=? WHERE workpackage_id=? AND step_id=?",
                  (error[:500], _now(), wp_id, step))


def current(wp_id: str, *, step: str | None = None) -> dict[str, Any] | None:
    """The package's latest proposal; `stale` when its request items or the active price list changed since. D0-b: of
    the case's match `step` (None: the case's first)."""
    step = _step(wp_id, step)
    with store.connect() as c:
        row = _row(c, wp_id, step)
    if row is None:
        return None
    out = {k: row[k] for k in ("state", "engine", "price_list", "version", "requested_by", "requested_at", "finished_at",
                               "error")}
    out["limits"] = json.loads(row["limits"])
    out["lines"] = json.loads(row["lines"]) if row["lines"] else []
    if out["lines"]:  # each proposed item's name from the price list version the proposal used
        names = {i.sku: i.name for i in price_lists.version(row["price_list"], row["version"]).items}
        for line in out["lines"]:
            line["answer"]["name"] = names.get(line["answer"].get("sku") or "")
    out["usage"] = json.loads(row["usage"]) if row["usage"] else None
    stale = False
    if row["state"] == "done":
        try:
            stale = request_key(_source(wp_id).items) != row["request_key"]
        except ProposalRefused:
            stale = True
        prices = _active()
        stale = stale or prices is None or prices.fingerprint != row["fingerprint"]
    out["stale"] = stale
    return out


def mark() -> tuple[Any, ...]:
    """What changes when a proposal is asked or finishes (the quote package's list mark)."""
    with store.connect() as c:
        return tuple(c.execute("SELECT COUNT(*), MAX(requested_at), MAX(finished_at) FROM quote_proposals").fetchone())


JOB = job_kinds.JobKind(JOB_KIND, __name__, process=lambda job: process_job(job),
                        abandon=lambda job, error: abandon(job.payload["workpackage_id"], error,
                                                           step=job.payload.get("step_id")))


__all__ = ["JOB", "JOB_KIND", "ProposalRefused", "abandon", "cap", "current", "mark", "process_job", "request",
           "request_key", "settings"]
