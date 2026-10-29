"""The AI pairing proposal as a pairing case's step (231, plan stage C, C2c; the owner's decision of 2026-10-25, DECISIONS 231).

Plain-language summary: on a pairing case's page a person may ask the AI which invoice each statement line still to
decide pays and what kind of payment it is (the reconciliation's AI proposal, `reconcile_ai.py`, until now asked from
the command line only, as a measurement). A person starts it; it asks JEV only (the GPT path is a separate decision),
under a cap of at most 0.20 USD a run (`configs/finance.json` `reconcile.ai_proposal`), every call through the call log
as the case's business work, and stores the raw answers where the pairing cards read them. A person still decides every
pair. A run that failed shows why; starting the step again makes a new run with its own cap.

- `request(case_id, step_id, round_, actor)`: queues the run of a round (a run already queued or running stays).
- `latest(case_id, step_id)`: the step's latest run; `mark_reported(...)`: its failure was told to the step.
- `cap()`: the providers and the most a run may spend; `JOB`: the worker's job (`pairing_propose`).

Layer: the finance domain's business module; the worker runs its job, the capability (`capabilities.py`) its step.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from jav.core import calls, cfg, identity, store
from jav.core.clock import utc_stamp as _now
from jav.runtime import job_kinds

JOB_KIND = "pairing_propose"
STATES = ("queued", "running", "done", "failed")

store.register_schema("pairing_proposals", """
-- 231 (C2c): the runs of a pairing case's AI proposal step, one per round (a failed run started again is a new round)
CREATE TABLE IF NOT EXISTS pairing_proposals (
    case_id         TEXT NOT NULL,      -- the case (its container work package)
    step_id         TEXT NOT NULL,
    round           INTEGER NOT NULL,
    state           TEXT NOT NULL,      -- queued | running | done | failed
    engines         TEXT NOT NULL,      -- JSON: the engines asked
    limits          TEXT NOT NULL,      -- JSON: provider -> the most the run may spend (USD)
    scope           TEXT,               -- the run's budget scope in the call log
    lines           INTEGER,            -- the lines it asked about
    counts          TEXT,               -- JSON: per engine asked, inherited, skipped, pays, failed
    usage           TEXT,               -- JSON: the budget scope's spending
    error           TEXT,
    reported        INTEGER NOT NULL DEFAULT 0,  -- a failure told to the step (a run after it is a new round)
    requested_by    TEXT NOT NULL,
    requested_by_id TEXT,
    requested_at    TEXT NOT NULL,
    finished_at     TEXT,
    PRIMARY KEY (case_id, step_id, round)
);
""")


def cap() -> tuple[list[str], dict[str, Decimal]]:
    """The engines a run asks and the most it may spend per provider (`configs/finance.json` `reconcile.ai_proposal`)."""
    from jav.domains.finance import reconcile_ai

    conf = cfg.load("finance")["reconcile"]["ai_proposal"]
    engines = [e for e in reconcile_ai.ENGINES if e in conf["engines"]]
    return engines, {reconcile_ai.PROVIDERS[e]: Decimal(str(conf["max_run_usd"][reconcile_ai.PROVIDERS[e]])) for e in engines}


def _row(c: Any, case_id: str, step_id: str) -> Any:
    return c.execute("SELECT * FROM pairing_proposals WHERE case_id=? AND step_id=? ORDER BY round DESC LIMIT 1",
                     (case_id, step_id)).fetchone()


def latest(case_id: str, step_id: str) -> dict[str, Any] | None:
    """The step's latest run: its round, state, engines, cap, lines, counts, spending and error (None: none yet)."""
    with store.connect() as c:
        row = _row(c, case_id, step_id)
    if row is None:
        return None
    out = dict(row)
    for key in ("engines", "limits", "counts", "usage"):
        out[key] = json.loads(out[key]) if out[key] else None
    out["reported"] = bool(out["reported"])
    return out


def request(case_id: str, step_id: str, round_: int, *, actor: identity.Who) -> dict[str, Any]:
    """Queues the run of `round_` with the engines and the cap the rule file names; a run of the step already queued or
    running is returned as it is."""
    from jav.core import queue

    engines, limits = cap()
    with store.connect() as c:
        store.begin_immediate(c)
        row = _row(c, case_id, step_id)
        if row is not None and row["state"] in ("queued", "running"):
            return latest(case_id, step_id) or {}
        # 231 (E3): a round asked again starts afresh, in the form every database takes (until then a replacing insert)
        c.execute("INSERT INTO pairing_proposals(case_id, step_id, round, state, engines, limits, requested_by,"
                  " requested_by_id, requested_at) VALUES (?,?,?,?,?,?,?,?,?)"
                  " ON CONFLICT(case_id, step_id, round) DO UPDATE SET state=excluded.state, engines=excluded.engines,"
                  " limits=excluded.limits, requested_by=excluded.requested_by, requested_by_id=excluded.requested_by_id,"
                  " requested_at=excluded.requested_at, scope=NULL, lines=NULL, counts=NULL, usage=NULL, error=NULL,"
                  " reported=0, finished_at=NULL",
                  (case_id, step_id, round_, "queued", json.dumps(engines), json.dumps({k: str(v) for k, v in limits.items()}),
                   identity.name_of(actor), identity.id_of(actor), _now()))
    queue.enqueue(JOB_KIND, run_id=None, payload={"workpackage_id": case_id, "step_id": step_id, "round": round_})
    return latest(case_id, step_id) or {}


def mark_reported(case_id: str, step_id: str, round_: int) -> None:
    with store.connect() as c:
        c.execute("UPDATE pairing_proposals SET reported=1 WHERE case_id=? AND step_id=? AND round=?", (case_id, step_id, round_))


def process_job(job: Any) -> str:
    """The worker's job: the case's lines to decide asked under the round's own budget scope (`capabilities.step_budget`:
    business work, not a measurement); the job is always completed, a failure shows on the run. A run whose every line
    failed (JEV unavailable, the budget too small for one request) is a failed run."""
    from jav.app import capabilities
    from jav.core import queue
    from jav.domains.finance import reconcile_ai

    case_id, step_id, round_ = job.payload["workpackage_id"], job.payload["step_id"], int(job.payload["round"])
    with store.connect() as c:
        row = c.execute("SELECT * FROM pairing_proposals WHERE case_id=? AND step_id=? AND round=?",
                        (case_id, step_id, round_)).fetchone()
    if row is None or row["state"] not in ("queued", "running"):
        return queue.complete(job.id)
    with store.connect() as c:
        c.execute("UPDATE pairing_proposals SET state='running' WHERE case_id=? AND step_id=? AND round=?",
                  (case_id, step_id, round_))
    try:
        limits = {k: Decimal(v) for k, v in json.loads(row["limits"]).items()}
        with capabilities.step_budget(case_id, step_id, round_, limits) as scope:
            asked = reconcile_ai.ask_lines(case_id, engines=json.loads(row["engines"]), scope=scope)
        counts = asked["counts"]
        tried = sum(n["asked"] for n in counts.values())
        failed = tried > 0 and sum(n["failed"] for n in counts.values()) == tried
        with store.connect() as c:
            c.execute("UPDATE pairing_proposals SET state=?, scope=?, lines=?, counts=?, usage=?, error=?, finished_at=?"
                      " WHERE case_id=? AND step_id=? AND round=?",
                      ("failed" if failed else "done", scope, asked["lines"], json.dumps(counts),
                       json.dumps(calls.budget_usage(scope), default=str),
                       "every line's question failed" if failed else None, _now(), case_id, step_id, round_))
    except Exception as exc:  # noqa: BLE001 - the run shows why it failed; the worker goes on
        abandon(case_id, step_id, round_, f"{type(exc).__name__}: {exc}")
    return queue.complete(job.id)


def abandon(case_id: str, step_id: str, round_: int, error: str) -> None:
    with store.connect() as c:
        c.execute("UPDATE pairing_proposals SET state='failed', error=?, finished_at=? WHERE case_id=? AND step_id=? AND round=?"
                  " AND state IN ('queued', 'running')", (error[:500], _now(), case_id, step_id, round_))


JOB = job_kinds.JobKind(JOB_KIND, __name__, process=lambda job: process_job(job),
                        abandon=lambda job, error: abandon(job.payload["workpackage_id"], job.payload["step_id"],
                                                           int(job.payload["round"]), error))


__all__ = ["JOB", "JOB_KIND", "STATES", "abandon", "cap", "latest", "mark_reported", "process_job", "request"]
