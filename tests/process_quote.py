"""The invented quote case of the process core's failure tests (213; ported from the engine trial of 212).

Plain-language summary: a quote request is checked, priced by a paid stand-in provider through the call log, approved
by a person, waits for a missing attachment until a deadline, and is handed over to a stand-in receiving system. The
provider and the receiver are other "systems" with their own SQLite files in the test's folder; they count every
physical call, so a test sees whether anything was paid for or sent twice. A worker process can be made to die at a
named point (`crash`). Synthetic data only; no network and no paid call.

Version 2 of the definition adds a `notify` step after the approval (T06). The worker entry is `tests.process_worker`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.core import calls, store
from jav.core.process import cases, engine, kinds, outbox
from jav.core.process.definition import ProcessDef, StepDef

OWNER = __name__
STORE_FILE = "process.sqlite"
RETRY_S = 1.0  # how often a case waiting for budget (or for a settled pricing call) tries its pricing again
VERSIONS = {
    1: ProcessDef(id="invented_quote", version="1", title="Invented quote", steps=(
        StepDef(id="checks", kind="quote_checks"),
        StepDef(id="pricing", kind="quote_pricing", gates=("checks",)),
        StepDef(id="approval", kind="quote_approval", gates=("pricing",)),
        StepDef(id="attachment", kind="quote_attachment", gates=("approval",)),
        StepDef(id="handover", kind="quote_handover", gates=("attachment",)))),
    2: ProcessDef(id="invented_quote", version="2", title="Invented quote", steps=(
        StepDef(id="checks", kind="quote_checks"),
        StepDef(id="pricing", kind="quote_pricing", gates=("checks",)),
        StepDef(id="approval", kind="quote_approval", gates=("pricing",)),
        StepDef(id="notify", kind="quote_notify", gates=("approval",)),
        StepDef(id="attachment", kind="quote_attachment", gates=("notify",)),
        StepDef(id="handover", kind="quote_handover", gates=("attachment",)))),
}


def folder() -> Path:
    """The test's folder: the store's, where the stand-in provider and receiver keep their files."""
    return store.current_path().parent


# --- crash points -----------------------------------------------------------------------------------------------------

CRASH_ENV, CRASH_MARK_ENV, CRASH_EXIT = "PROCESS_CRASH_AT", "PROCESS_CRASH_MARK", 1
CRASH_POINTS = frozenset({
    "before_approval_wait",  # the price is saved, the approval wait not yet entered
    "waiting_attachment",  # the case waits for the attachment and its deadline is armed
    "after_handover_sent",  # the receiver recorded the handover, its reply not yet sent
    "after_case_saved_before_notify",  # the handover is recorded with the case, not yet sent
    "pricing_in_flight",  # the provider took the call, its answer not yet returned
})


def crash(point: str) -> None:
    """Exits the process at once (no unwinding, no commit, as a killed process) when `PROCESS_CRASH_AT` names this
    point, first writing the point's name to the file `PROCESS_CRASH_MARK` names."""
    if point not in CRASH_POINTS:
        raise ValueError(f"unknown crash point {point!r}")
    if os.environ.get(CRASH_ENV) != point:
        return
    if mark := os.environ.get(CRASH_MARK_ENV):
        Path(mark).write_text(point, encoding="utf-8")
    os._exit(CRASH_EXIT)


# --- the stand-in provider and receiver -------------------------------------------------------------------------------

PROVIDER = "invented-pricer"
MAX_COST_USD = Decimal("0.60")  # reserved before every call
CASE_BUDGET_USD = Decimal("1.00")  # a case's own budget when its request names no shared one
BILLED_USD = Decimal("0.50")  # what the provider reports the call cost
UNIT_PRICE = Decimal("12.50")
_SYSTEM = """
CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, key TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS received (handover_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _system(where: Path, name: str) -> sqlite3.Connection:
    c = sqlite3.connect(where / f"{name}.sqlite", timeout=30)
    c.executescript(_SYSTEM)
    return c


def set_system(where: Path, name: str, key: str, value: str) -> None:
    """A switch of a stand-in system: the provider's `delay_s`, the receiver's `lose_reply`."""
    with closing(_system(where, name)) as c, c:
        c.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, value))


def physical_calls(where: Path, name: str, key: str | None = None) -> int:
    """The calls that reached a stand-in system ("provider" or "receiver"), for one key or for all."""
    with closing(_system(where, name)) as c:
        sql, args = ("SELECT COUNT(*) FROM calls WHERE key=?", (key,)) if key else ("SELECT COUNT(*) FROM calls", ())
        return int(c.execute(sql, args).fetchone()[0])


def _setting(c: sqlite3.Connection, key: str) -> str | None:
    row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _call_provider(where: Path, case_id: str, items: list[dict[str, Any]]) -> calls.Outcome:
    with closing(_system(where, "provider")) as c, c:
        c.execute("INSERT INTO calls(key, at) VALUES (?,?)", (case_id, time.time()))
        delay = _setting(c, "delay_s")
    if delay is not None:
        time.sleep(float(delay))
    crash("pricing_in_flight")
    total = sum((UNIT_PRICE * int(item["qty"]) for item in items), Decimal("0"))
    return calls.Outcome(response={"total": str(total)}, model="invented-pricer-1", cost_usd=BILLED_USD)


def _deliver(where: Path, handover_id: str, payload: dict[str, Any]) -> dict[str, str]:
    with closing(_system(where, "receiver")) as c, c:
        c.execute("INSERT INTO calls(key, at) VALUES (?,?)", (handover_id, time.time()))
        c.execute("INSERT INTO received(handover_id, payload) VALUES (?,?) ON CONFLICT(handover_id) DO NOTHING",
                  (handover_id, json.dumps(payload, sort_keys=True)))
        lose = _setting(c, "lose_reply")
    crash("after_handover_sent")
    if lose == "1":
        raise TimeoutError(f"the reply to handover {handover_id} was lost")
    return {"receipt": f"receipt:{handover_id}"}


# --- the steps ----------------------------------------------------------------------------------------------------------


def _checks(ctx: engine.StepContext) -> kinds.StepOutcome:
    request = ctx.data
    return kinds.Done({"customer": "ok" if request["customer"].strip() else "missing",
                       "items": "ok" if request["items"] and all(int(i.get("qty", 0)) > 0 for i in request["items"])
                       else "invalid"})


def _pricing(ctx: engine.StepContext) -> kinds.StepOutcome:
    """Prices through the call log under the case's id: a retry replays a successful call, never repeats one whose
    outcome is unknown, and waits while the budget cannot take the reservation."""
    scope = ctx.data.get("budget_scope")
    if scope is None:
        scope = f"case:{ctx.case_id}"
        calls.ensure_budget(scope, PROVIDER, CASE_BUDGET_USD)
    where = folder()
    try:
        result = calls.invoke(run_id=ctx.case_id, step_id="pricing", provider=PROVIDER, model=None,
                              max_cost_usd=MAX_COST_USD, budget_scope=scope,
                              fn=lambda: _call_provider(where, ctx.case_id, ctx.data["items"]))
    except calls.BudgetExceeded as exc:
        return ctx.wait("budget", timer=("retry", time.time() + RETRY_S), detail={"why": str(exc)})
    except calls.UncertainAttempt as exc:
        return ctx.wait("pricing_settlement", timer=("retry", time.time() + RETRY_S), detail={"why": str(exc)})
    return kinds.Done({"total": result.response["total"]})


def _approval(ctx: engine.StepContext) -> kinds.StepOutcome:
    decision = ctx.row()["result"]
    if decision is None:
        crash("before_approval_wait")
        return ctx.wait("approval")
    return kinds.Done(decision) if decision["decision"] == "approve" else kinds.Close("rejected")


def _approval_event(ctx: engine.StepContext, c: sqlite3.Connection, event: cases.Event) -> str:
    """An approval must name the priced result's version (rule 3) and be a decision."""
    version, _ = ctx.result_of("pricing")
    if event.payload.get("decision") not in ("approve", "reject") or event.payload.get("result_version") != version:
        return kinds.REFUSED
    cases.set_result(c, ctx.case_id, ctx.step.id, {"decision": event.payload["decision"], "event": event.event_id})
    return kinds.APPLIED


def _notify(ctx: engine.StepContext) -> kinds.StepOutcome:
    return kinds.DONE


def _attachment(ctx: engine.StepContext) -> kinds.StepOutcome:
    received = ctx.row()["result"]
    if ctx.data["has_attachment"] or received is not None:
        return kinds.Done(received or {"name": "with the request"})
    ctx.wait("attachment", timer=("deadline", time.time() + float(ctx.data["deadline_s"])))
    crash("waiting_attachment")
    return kinds.WAIT


def _attachment_event(ctx: engine.StepContext, c: sqlite3.Connection, event: cases.Event) -> str:
    cases.set_result(c, ctx.case_id, ctx.step.id, {"name": event.payload.get("name"), "event": event.event_id})
    return kinds.APPLIED


def _deadline(ctx: engine.StepContext, c: sqlite3.Connection, timer: Any) -> str:
    cases.close(c, ctx.case_id, "expired", ctx.actor)
    return "expired"


def handover_id(case_id: str) -> str:
    return f"{case_id}:handover:receiver"


def _handover(ctx: engine.StepContext) -> kinds.StepOutcome:
    hid = handover_id(ctx.case_id)
    if outbox.get(hid) is None:
        version, priced = ctx.result_of("pricing")
        ctx.record_handover("receiver", {"case_id": ctx.case_id, "customer": ctx.data["customer"],
                                         "total": priced["total"], "result_version": version}, handover_id=hid)
        crash("after_case_saved_before_notify")
    where = folder()
    status = ctx.send(hid, lambda h, payload: _deliver(where, h, payload))
    if status == outbox.ACKNOWLEDGED:
        return kinds.DONE
    if status == outbox.FAILED:
        return kinds.Close("failed")
    return kinds.WAIT  # uncertain: the step waits for a person to settle it


for _kind in (
    kinds.StepKind("quote_checks", OWNER, _checks),
    kinds.StepKind("quote_pricing", OWNER, _pricing),
    kinds.StepKind("quote_approval", OWNER, _approval, events=("approval",), on_event=_approval_event),
    kinds.StepKind("quote_notify", OWNER, _notify),
    kinds.StepKind("quote_attachment", OWNER, _attachment, events=("attachment",), on_event=_attachment_event,
                   on_timer=_deadline),
    kinds.StepKind("quote_handover", OWNER, _handover),
):
    kinds.register(_kind)
