"""231 (plan stage C, C3i): how a workflow moves on, split out of `workflows.py`.

Plain-language summary: a step starts (its package made or linked, its run started within the approved budget, a
mailbox download asked for), a person's start and a step's update are recorded, the worker's tick moves every
workflow on and releases a start that stalled, the process core turns a workflow's case step by step (214), and the
new work wizard's estimate of a step's cost. The rules they follow are described in `workflows.py`.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.app import (
    app_settings, human_tasks, logic_packs, work, work_readiness,
    work_recipes, work_runs, workflow_cases, workflow_steps,
)
from jav.core import identity, store, trace
from jav.core.process import cases as process_cases
from jav.core.process import engine as process_engine
from jav.core.process import kinds as process_kinds
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now
from jav.app.workflow_records import OLD_APPROVAL, REAPPROVE_NOTE, STALE_START_S, TICK_EVERY_S, WorkflowError, _approval, _budget, _check_package, _engine, _event, _maker, _pack, _period, _ref_of, _row, _set, _set_logged, _source, _steps, _update_step, auto_actor, config, log, view


@store.one_connection
def advance(wf_id: str, *, actor: identity.Who) -> dict[str, Any]:
    """Moves the chain on: one turn of the workflow's case on the process core (214), woken, so a finished mailbox
    download or an approved package is seen at once. A finished download gets its package and run; a step whose steps it
    waits for are done starts (only while the workflow's chain is automatic; otherwise it waits for a person). A case
    another process is moving on is left to it. Idempotent."""
    wf = _row(wf_id)
    if wf["status"] != "open":
        return view(wf_id)
    workflow_cases.ensure(wf_id)
    _turn(wf_id, actor)
    return view(wf_id)


def start_step(wf_id: str, step: str, *, actor: identity.Who, budget: dict[str, Any] | None = None) -> dict[str, Any]:
    """A person starts a step now (whatever the steps it waits for), retries a failed one, or starts one that waits for
    a budget; a `budget` given here replaces the step's budget (the person's own decision, recorded). 214: the person's
    start reaches the case in the same transaction (`workflow_cases.person_starts`: the order overridden and recorded,
    a failed step retried, a wait ended), and the case's turn starts the step."""
    wf = _row(wf_id)
    if wf["status"] != "open":
        raise explained(WorkflowError, "the workflow is archived")
    sdef = next((s for s in wf["definition"]["steps"] if s["id"] == step), None)
    if sdef is None:
        raise explained(WorkflowError, "unknown step {{step}}", step=repr(step))
    st = _steps(wf_id)[step]
    if st["phase"] not in ("waiting", "failed", "needs_budget"):
        raise explained(WorkflowError, "step {{step}} is {{state}}: it cannot be started",
                        step=repr(step), state=st["phase"])
    new = _budget(budget) if budget is not None else None
    with store.connect() as c:
        store.begin_immediate(c)
        if new is not None:
            _update_step(c, wf_id, step, budget=json.dumps(new))
            _event(c, wf_id, step, "budget", actor, {"from": st["budget"], "to": new})
        workflow_cases.person_starts(c, wf_id, step, actor, decision={"budget": new if new is not None else st["budget"]})
    _turn(wf_id, actor)
    return view(wf_id)


def link(wf_id: str, step: str, wp_id: str, *, actor: identity.Who) -> dict[str, Any]:
    """A person makes an existing work package the step's package (the chain starts no run on it). 214: the step then
    waits for the package's approval in the case, whatever its order (`workflow_cases.person_links`)."""
    wf = _row(wf_id)
    sdef = next((s for s in wf["definition"]["steps"] if s["id"] == step), None)
    if sdef is None:
        raise explained(WorkflowError, "unknown step {{step}}", step=repr(step))
    _check_package(sdef["kind"], wp_id)
    with store.connect() as c:
        store.begin_immediate(c)
        if not _update_step(c, wf_id, step, expect=("waiting", "failed", "nothing_new"), phase="linked",
                            workpackage_id=wp_id, source=json.dumps({"kind": "package", "workpackage_id": wp_id}),
                            note=None):
            raise explained(WorkflowError, "step {{step}} has started already", step=repr(step))
        _event(c, wf_id, step, "link", actor, {"workpackage": wp_id})
        workflow_cases.person_links(c, wf_id, step, actor)
    _turn(wf_id, actor)
    return view(wf_id)


def update(wf_id: str, *, actor: identity.Who, auto: bool | None = None, name: str | None = None,
           archived: bool | None = None) -> dict[str, Any]:
    """Switches the automatic chain, renames, archives or restores a workflow (its packages stay as they are). 214: its
    case is held while it is archived, and the steps waiting for a person go on when the chain is switched on."""
    _row(wf_id)
    changes: dict[str, Any] = {}
    if auto is not None:
        changes["auto"] = int(auto)
    if name is not None and name.strip():
        changes["name"] = name.strip()[:200]
    if archived is not None:
        changes["status"] = "archived" if archived else "open"
    if changes:
        with store.connect() as c:
            store.begin_immediate(c)
            if archived is not None:
                workflow_cases.set_archived(c, wf_id, archived, actor)
            if auto:
                workflow_cases.chain_on(c, wf_id, actor)
            c.execute(f"UPDATE workflows SET {', '.join(f'{k}=?' for k in changes)}, updated_at=? WHERE id=?",
                      (*changes.values(), _now(), wf_id))
            _event(c, wf_id, None, "update", actor, changes)
    if changes.get("auto"):
        advance(wf_id, actor=actor)
    return view(wf_id)


def _done(wf: dict[str, Any], step: str, actor: identity.Who, action: str, **fields: Any) -> None:
    """A step's outcome and its event, in one transaction (213, `_set_logged`)."""
    _set_logged(wf["id"], step, action, actor,
                {k: v for k, v in fields.items() if k in ("workpackage_id", "run_id", "pull_id", "note")}, **fields)


def _start(wf: dict[str, Any], sdef: dict[str, Any], *, actor: identity.Who, states: tuple[str, ...] = ("waiting",)) -> None:
    """Makes the step's package (or queues its mailbox download) and starts its run; a failure stays on the step. 160
    (review R-2): the package is noted on the step as soon as it exists, so a start interrupted later (before or after
    the run was made) is started again with that package (`start_step`), never with a second one."""
    step = sdef["id"]
    if not _set(wf["id"], step, expect=states, phase="starting", note=None):
        return  # another process has it, or it is past waiting
    st = _steps(wf["id"])[step]
    try:
        workflow_steps.of(sdef["kind"]).start(_context(wf, sdef, st, actor))  # 181: the kind's own start
    except Exception as exc:  # the step shows why; a person retries it
        log.warning("workflow %s step %s did not start: %s", wf["id"], step, exc)
        _done(wf, step, actor, "failed", phase="failed", note=str(exc)[:1000])
    except BaseException:  # 153 (review D2): interrupted (the process stops): the claim is released, then it stops
        _done(wf, step, actor, "failed", phase="failed", note=INTERRUPTED)
        raise


def _exclude(source: dict[str, Any]) -> list[Path]:
    """With the subfolders, the output folder of the named copies is left out (they are not new documents)."""
    out = app_settings.output_folder() if source.get("recursive") else None
    return [Path(out)] if out else []


def _documents(source: dict[str, Any]) -> tuple[list[Path], list[Path]]:
    """A documents step's documents, and those left out because a live run has processed them (`only_new`, 147)."""
    if source["kind"] == "folder":
        files = work.folder_documents(Path(source["folder"]), recursive=source["recursive"], exclude=_exclude(source))
    else:
        files = [Path(p) for p in source["paths"]]
    return work.unprocessed(files) if source.get("only_new") else (files, [])


def _context(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], actor: identity.Who) -> workflow_steps.StepStart:
    """181: the workflow's shared operations for a step kind's start or fetch check, each recording its event."""
    wf_id, step = wf["id"], sdef["id"]

    def event(action: str, detail: dict[str, Any]) -> None:
        with store.connect() as c:
            store.begin_immediate(c)
            _event(c, wf_id, step, action, actor, detail)

    def package(wp_id: str) -> None:  # 160 (review R-2): an interrupted start goes on with this package
        _set(wf_id, step, workpackage_id=wp_id)

    packages = {sid: x.get("workpackage_id") for sid, x in _steps(wf_id).items()}
    return workflow_steps.StepStart(
        workflow=wf, step=sdef, state=st, actor=actor, packages=packages, package=package,
        run=lambda wp_id: _start_run(wf, sdef, st, wp_id, actor=actor),
        made=lambda wp_id: _done(wf, step, actor, "package", phase="started", workpackage_id=wp_id),
        nothing_new=lambda note: _done(wf, step, actor, "nothing_new", phase="nothing_new", note=note),
        fetching=lambda fetch_id: _done(wf, step, actor, "pull", phase="pulling", pull_id=fetch_id),
        claim=lambda: _set(wf_id, step, expect=("pulling",), phase="starting"),
        failed=lambda note: _done(wf, step, actor, "failed", phase="failed", note=note[:1000]),
        event=event)


def _poll(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], actor: identity.Who) -> None:
    """A step whose source is being fetched (a mailbox download) goes on once the fetch has finished (181: the kind's
    own check)."""
    kind = workflow_steps.of(sdef["kind"])
    if kind.poll is not None:
        kind.poll(_context(wf, sdef, st, actor))


def documents_offer(ctx: workflow_steps.StepStart) -> str | None:
    """The documents step: the folder's or the files' documents (only those no live run has processed, when asked)
    become the step's package; none: the step found nothing new and keeps no empty package. 231 (C3b5b): the documents
    maker's workflow offer (`jav/app/document_processing.py`): the pack's step kind wraps the package by its case, notes
    it on the step and starts its live run (until then this step kind's own start did the last two)."""
    source, wf = ctx.source, ctx.workflow
    files, left_out = _documents(source)
    wp = None
    if files and source["kind"] == "folder":
        wp = work.create_from_folder(Path(source["folder"]), name=ctx.state["name"], owner=_maker(wf),
                                     recursive=source["recursive"], exclude=_exclude(source),
                                     only=files if left_out else None)
    elif files:
        wp = work.create_from_files(files, name=ctx.state["name"], owner=_maker(wf))
    if wp is None or not work.get(wp["id"])["items"]:
        if wp is not None:
            work.delete_workpackage(wp["id"], actor=ctx.actor)
        ctx.nothing_new(f"no new documents: {len(left_out)} already processed" if left_out else "no documents in the folder")
        return None
    if left_out:
        ctx.event("left_out", {"new": len(files), "left_out": len(left_out)})
    return str(wp["id"])


def _give_engine(wp_id: str, engine: str | None, *, actor: identity.Who) -> None:
    """160-D: the step's own engine on its package (keeping the package's other settings), before the readiness check
    sizes the run's budget. Without one the package keeps the engine it got: the application's when it was made, or
    when the run starts for a package without saved settings."""
    if engine is None:
        return
    a = work_recipes.current_assignment(wp_id)
    r = work_recipes.recipe(a["recipe_id"]) if a else work_recipes.default_recipe()
    want = work_recipes.engine_params(r, engine)
    if not want or (a is not None and a["params"].get("jev") == want["jev"]):
        return
    kept = a["params"] if a else work_recipes.default_params(r, engine)
    work_recipes.assign_recipe(wp_id, r["id"], params={**kept, **want}, expected_revision=a["revision"] if a else 0, actor=actor,
                       note=f"workflow step: engine {engine}")


BUDGET_GATE = "workflow.budget_gate"  # 218 (P3b): the decision point of a step's budget gate


def budget_gate(inputs: Mapping[str, Any]) -> dict[str, Any]:
    """218 (P3b): a workflow step's budget gate, a pure rule: each provider whose estimate (`estimate`, USD as text) is
    over the step's approved budget (`budget`; a provider without one has none); the step's package starts its live
    run only when none is, otherwise the step waits for a person's budget."""
    budget = inputs["budget"]
    over = {p: str(Decimal(v)) for p, v in sorted(inputs["estimate"].items()) if Decimal(v) > Decimal(budget.get(p, "0"))}
    return {"over": over, "decision": "needs_budget" if over else "start"}


def _gate_keys(wp_id: str) -> dict[str, tuple[str, ...]]:
    """The rule keys the estimate of the gate was made with: the item budgets of the package's recipe."""
    a = work_recipes.current_assignment(wp_id)
    rid = a["recipe_id"] if a else work_recipes.default_recipe()["id"]
    return {"recipes.json": (f"recipes[{rid}].max_item_usd", f"recipes[{rid}].max_item_usd_by_kind")}


def _start_run(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], wp_id: str, *, actor: identity.Who) -> None:
    """The package's live run, when its own estimate fits the step's budget; otherwise the step waits for a person.
    218 (P3b): the gate's decision is traced in the transaction that records it on the step."""
    step = sdef["id"]
    try:
        _give_engine(wp_id, st.get("engine"), actor=actor)
        ready = work_readiness.readiness(wp_id)
        if not ready["ready"]:
            raise WorkflowError("; ".join(b["message"] for b in ready["blockers"]) or "the package cannot start")
        budget = _steps(wf["id"])[step]["budget"]
        estimate = {p: Decimal(str(v)) for p, v in (ready.get("budget") or {}).items()}
        inputs = {"estimate": {p: str(v) for p, v in estimate.items()}, "budget": budget}
        gate = budget_gate(inputs)

        def traced(c: Any, run_id: str | None = None) -> None:
            trace.record_in(c, BUDGET_GATE, subject=("workflow_step", f"{wf['id']}:{step}"), inputs=inputs,
                            outcome=gate, keys=_gate_keys(wp_id), run_id=run_id, case_id=wf["id"])

        if gate["over"]:
            note = {**inputs, "over": gate["over"]}
            with store.connect() as c:  # 215: the wait, its event and the person's task in one transaction
                store.begin_immediate(c)
                if _update_step(c, wf["id"], step, phase="needs_budget", workpackage_id=wp_id, note=json.dumps(note)):
                    _event(c, wf["id"], step, "needs_budget", actor, {"workpackage_id": wp_id, "note": json.dumps(note)})
                    workflow_cases.ask_budget(c, wf["id"], step, human_tasks.assignee_for(c, wp_id, wf["actor"]), note)
                    traced(c)
            return
        res = work_runs.start_run(wp_id, mode="apply", expected_assignment_revision=ready["assignment_revision"],
                             input_hash=ready["input_hash"], actor=actor)
        with store.connect() as c:  # the step's start, its event and the gate's trace in one transaction
            store.begin_immediate(c)
            _update_step(c, wf["id"], step, phase="started", workpackage_id=wp_id, run_id=res["run_id"])
            _event(c, wf["id"], step, "run", actor, {"workpackage_id": wp_id, "run_id": res["run_id"]})
            traced(c, res["run_id"])
    except Exception as exc:
        log.warning("workflow %s step %s: run not started: %s", wf["id"], step, exc)
        _done(wf, step, actor, "failed", phase="failed", workpackage_id=wp_id, note=str(exc)[:1000])


_last_tick = 0.0


INTERRUPTED = "the start was interrupted; start the step again"


def release_stale_starts(max_age_s: float = STALE_START_S) -> int:
    """153 (review D2): steps claimed for a start more than `max_age_s` ago and never finished (the process that held
    the claim stopped) go to `failed` with a note, so a person can start them again; before, they stayed "starting" for
    good. Returns how many it released. 227: under the case's claim, so a start a live process is still making is
    left to it, and the step fails in its case too (before, only its phase did, and the case still had it running)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_s)).isoformat(timespec="seconds")
    with store.connect() as c:
        starting = set(process_cases.steps_in_phase_in(c, ("starting",)))  # 229: the core's rows through its own read
        stale = [r for r in c.execute("SELECT s.workflow_id, s.step, w.actor, w.actor_id FROM workflow_steps s"
                                      " JOIN workflows w ON w.id=s.workflow_id WHERE s.updated_at < ?", (cutoff,))
                 if (r["workflow_id"], r["step"]) in starting]
    released = 0
    for r in stale:
        if not process_engine.claim_case(r["workflow_id"]):
            continue  # a live process holds the case: its own turn settles the start
        try:
            with store.connect() as c:
                store.begin_immediate(c)
                if _update_step(c, r["workflow_id"], r["step"], expect=("starting",), phase="failed", note=INTERRUPTED):
                    _event(c, r["workflow_id"], r["step"], "failed", auto_actor(r), {"note": INTERRUPTED})
                    workflow_cases.fail_outside(c, r["workflow_id"], r["step"], INTERRUPTED)
                    released += 1
        finally:
            process_engine.release(r["workflow_id"])
    return released


def tick(now: float | None = None) -> int:
    """The worker's turn (at most every `TICK_EVERY_S`): releases interrupted starts (153), then advances every open,
    automatic workflow with a step still to move (214: a woken turn of its case, so each looks at its waiting steps
    every turn, as before). 229: the other workflow cases the process core has something for (a check timer that came
    due, an event, a step a person started while another process held the case) are turned by the core's own round
    (`process_engine.turn_due`), with every other case. Returns how many automatic workflows it advanced."""
    global _last_tick
    now = time.monotonic() if now is None else now
    if now - _last_tick < TICK_EVERY_S:
        return 0
    _last_tick = now
    release_stale_starts()
    with store.connect() as c:
        moving = {case_id for case_id, _ in process_cases.steps_in_phase_in(c, ("waiting", "pulling"))}  # 229
        rows = [r for r in c.execute("SELECT w.id, w.actor, w.actor_id FROM workflows w WHERE w.status='open' AND w.auto=1")
                if r["id"] in moving]
    for r in rows:
        try:
            advance(r["id"], actor=auto_actor(r))
        except Exception:  # one workflow's trouble does not stop the others
            log.exception("workflow %s could not advance", r["id"])
    return len(rows)


# who a turn acts for in the workflow's log and its runs: the caller of the turn (a person's start, the worker's turn as
# the maker's automatic one); a turn of the core's own due cases acts as the maker, marked automatic
_turn_actor: ContextVar[identity.Who | None] = ContextVar("workflow_turn_actor", default=None)


_ROUNDS = 6  # a start moves a step to its next state in a round or two; a step still moving after these does not settle


def _turn(wf_id: str, actor: identity.Who | None, *, wake: bool = True) -> bool:
    """One turn of the workflow's case under its claim (`process_engine.turn`); False when another process or thread
    holds it (that one moves it on)."""
    token = _turn_actor.set(actor)
    try:
        return process_engine.turn(wf_id, wake=wake)
    finally:
        _turn_actor.reset(token)


def _check() -> tuple[str, float]:
    """The check timer of a step that waits for its fetch or its package's approval: the next look, as often as the
    worker's turn."""
    return workflow_cases.CHECK, time.time() + TICK_EVERY_S


def _person_start(wf: dict[str, Any], sdef: dict[str, Any], st: dict[str, Any], actor: identity.Who) -> None:
    """A person's start: a step with a package that waits for a budget or failed starts its package's run (within the
    budget, which the person may have raised); any other is started from its source again."""
    if st.get("workpackage_id") and st["phase"] in ("needs_budget", "failed"):
        if _set(wf["id"], sdef["id"], expect=("needs_budget", "failed"), phase="starting"):
            _start_run(wf, sdef, _steps(wf["id"])[sdef["id"]], st["workpackage_id"], actor=actor)
    else:
        _start(wf, sdef, actor=actor, states=("waiting", "failed"))


def _case_step(ctx: process_engine.StepContext) -> process_kinds.StepOutcome:
    """The process core's workflow step (`workflow_cases.STEP_KIND`, 214): it runs under its case's claim and does what
    the step's phase asks for, until the step is done, waits or failed:
    - nothing new: done; started or linked: done once its package's latest live run is approved (a reconciliation's
      version), otherwise it waits for that with a check timer;
    - pulling: its fetch is checked (a finished one gets its package and run), otherwise it waits with a check timer;
    - starting: a start a stopped process left (the claim says nobody else is starting it): failed, to start again;
    - a person's start (`workflow_cases.take_go`): started now, in the person's name;
    - waiting for a budget: waits for a person; failed: failed with its note;
    - waiting: started when the chain is automatic, otherwise it waits for a person.
    An error while a step checks its download or its package's approval is logged and the step looks again at its next
    check, as before 214 (the worker's next turn); a start's own error fails the step with it (`_start`)."""
    wf = _row(ctx.case_id)
    sdef = next(s for s in wf["definition"]["steps"] if s["id"] == ctx.step.id)
    with ctx.transaction() as c:
        go = workflow_cases.take_go(c, ctx.case_id, ctx.step.id)
    actor = go or _turn_actor.get() or auto_actor(wf)
    try:
        return _drive(ctx, wf, sdef, go, actor)
    except Exception:
        waits = {"pulling": workflow_cases.FETCH, "started": workflow_cases.APPROVAL, "linked": workflow_cases.APPROVAL}
        phase = _steps(wf["id"])[sdef["id"]]["phase"]
        if phase not in waits:
            raise  # the case fails the step with the error; a person starts it again
        log.exception("workflow %s step %s: its check failed; it looks again at its next check", wf["id"], sdef["id"])
        return ctx.wait(waits[phase], timer=_check())


def _drive(ctx: process_engine.StepContext, wf: dict[str, Any], sdef: dict[str, Any], go: identity.Actor | None,
           actor: identity.Who) -> process_kinds.StepOutcome:
    """`_case_step`'s rounds: until the step is done, waits or failed."""
    polled = False
    for _ in range(_ROUNDS):
        st = _steps(wf["id"])[sdef["id"]]
        phase = st["phase"]
        if phase == "nothing_new":
            return process_kinds.Done({"state": phase, "ref": None, "built_on": _built_on(ctx)})
        if phase in ("started", "linked"):
            approved, ref = _approval(st)
            if _counts(ctx, wf, st, approved, ref):
                return process_kinds.Done({"state": phase, "workpackage_id": st["workpackage_id"], "run_id": st.get("run_id"),
                                           "ref": ref, "built_on": _built_on(ctx)})
            return ctx.wait(workflow_cases.APPROVAL, timer=_check())
        if phase == "pulling":
            if polled:
                return ctx.wait(workflow_cases.FETCH, timer=_check())
            _poll(wf, sdef, st, actor)
            polled = True
        elif phase == "starting":
            _set_logged(wf["id"], sdef["id"], "failed", auto_actor(wf), {"note": INTERRUPTED},
                        expect=("starting",), phase="failed", note=INTERRUPTED)
        elif go is not None:
            go = None
            _person_start(wf, sdef, st, actor)
        elif phase == "needs_budget":
            return ctx.wait(workflow_cases.BUDGET)
        elif phase == "failed":
            return process_kinds.Fail(st.get("note") or "the step failed")
        elif not wf["auto"]:
            return ctx.wait(workflow_cases.PERSON)
        else:
            _start(wf, sdef, actor=actor)
    return process_kinds.Fail(f"the step did not settle: it is still {st['phase']}")


def _built_on(ctx: process_engine.StepContext) -> dict[str, Any]:
    """218 (P3l, rule 3): the approval each of the step's earlier steps was done with, as their results name it now."""
    return {n: _ref_of(ctx.result_of(n)[1]) for n in ctx.step.needs()}


def _old_approvals(last: dict[str, Any], found: Any) -> list[Any]:
    """The approvals that no longer count for a step out of date: the one it was done with and the one its package had
    at its first look after its earlier steps were done again."""
    old: list[Any] = []
    for r in (last.get("ref"), found):
        if r is not None and r not in old:
            old.append(r)
    return old


def _counts(ctx: process_engine.StepContext, wf: dict[str, Any], st: dict[str, Any], approved: bool, ref: Any) -> bool:
    """218 (P3l; DECISIONS 218): whether the step's package's approval counts for the chain now. A step whose earlier
    steps have another result than it was built on (`built_on`: kept when it was done, or when it went out of date
    before it was ever done) keeps, at its first look after them, the approvals that no longer count (`OLD_APPROVAL`):
    the one it was done with and the one its package has then. Only another approval counts, so one given before the
    earlier step's new approval does not either, nor the old one coming back (a later run stopped). A logic pack's own
    version still holding is reopened with a reason (its approval waits for a person again); a processing package needs
    a new live run a person starts. A package done without an approval of its own (the email routing: a person decides
    each attachment) counts as it stands. Nothing runs by itself."""
    row = ctx.row()
    last = row["result"] if isinstance(row["result"], dict) else {}
    before = last.get("built_on")
    if before is None or before == _built_on(ctx):  # never out of date, or built on what its earlier steps have now
        return approved
    _, pack = _pack(st)
    own = logic_packs.has_own_approval(pack, st["workpackage_id"])  # 231 (C3a-1): a case's too
    if pack is not None and not pack.has_runs and not own:
        return approved
    if OLD_APPROVAL not in last:
        old = _old_approvals(last, ref if approved else None)
        with ctx.transaction() as c:
            process_cases.set_result(c, ctx.case_id, ctx.step.id, {**last, OLD_APPROVAL: old})
    else:
        old = last[OLD_APPROVAL]
    if not approved or ref not in old:
        return approved
    if pack is not None and own and pack.reopen is not None:
        pack.reopen(st["workpackage_id"], note=REAPPROVE_NOTE, actor=auto_actor(wf))
    return False


def _went_stale(c: Any, case_id: str, step_id: str | None, actor: Any) -> None:
    """218 (P3l): a workflow step that goes out of date before it was ever done keeps what its earlier steps' results
    were then (`built_on`), in the transaction that marks it, so its first look after them knows they changed. A done
    step keeps the one it was done with. Registered with the core's `on_leave`; nothing for another case."""
    if step_id is None:
        return
    case = process_cases.find_case_in(c, case_id)  # 229: the core's rows through its own reads
    if case is None or not case["definition_id"].startswith(workflow_cases.DEFINITION_PREFIX):
        return
    row = process_cases.find_step_in(c, case_id, step_id)
    if row is None or row["state"] != process_cases.STALE:
        return
    result = row["result"]
    if isinstance(result, dict) and "built_on" in result:
        return
    needs = process_cases.definition_of(process_cases.case_row(c, case_id)).step(step_id).needs()
    rows = process_cases.step_rows(c, case_id)
    process_cases.set_result(c, case_id, step_id, {**(result if isinstance(result, dict) else {}),
                                                   "built_on": {n: _ref_of(rows[n]["result"]) for n in needs}})


process_cases.on_leave(_went_stale)


# 214: registered on import, not by `register`: a case whose step kind the running code lacks waits for a migration for
# good, so any process that turns a workflow's case must know it. 215: it takes a task's closing for the budget and the
# package's approval it waits for (an earlier round's is refused); a case of before goes the same way
process_kinds.register(process_kinds.StepKind(workflow_cases.STEP_KIND, __name__, _case_step,
                                              events=(workflow_cases.BUDGET, workflow_cases.APPROVAL),
                                              on_event=workflow_cases.task_event))


# 218 (P3b): the budget gate's decision point
trace.register(trace.Point(
    BUDGET_GATE, owner=__name__, files=("recipes.json",), rule=budget_gate,
    what="whether a workflow step's package starts its live run or the step waits for a person's budget: the run's "
         "estimate per provider against the budget a person approved for the step",
    not_for="the run's reservations while it runs (the call log keeps those)"))


def _per_item(kind: str, engine: str | None = None) -> dict[str, Decimal]:
    r = work_recipes.default_recipe()
    return work_readiness.item_budget(r, work_recipes.default_params(r, engine), kind)  # 160-D: the step's engine or the application's


def _times(per: dict[str, Decimal], n: int) -> dict[str, str]:
    return {p: str((v * n).quantize(Decimal("0.0001"))) for p, v in per.items() if v and n}


def estimate(*, kind: str, source: dict[str, Any], party_id: str | None = None, period_start: Any = None,
             period_end: Any = None, engine: str | None = None) -> dict[str, Any]:
    """What a step would cost at most with the default processing: the items it would hold and the budget per provider
    (the recipe's item budget times the items). A mailbox's emails are counted only when a most is given; a step of an
    existing package or a reconciliation costs nothing here. With `only_new` the documents a live run has processed are
    not counted (`left_out`)."""
    if kind not in config()["kinds"]:  # 181: any registered kind of the templates
        raise explained(WorkflowError, "unknown step kind {{kind}}", kind=repr(kind))
    src = _source(kind, source)
    if src["kind"] in ("package", "none"):
        return {"items": None, "usd": {}, "note": None}
    engine = _engine(kind, src, engine)
    if (domain := workflow_steps.source_kind(src["kind"])) is not None:  # 185: a domain's source counts its items
        n, item_kind, note = domain.count(src)
        per = _per_item(item_kind, engine)
        return {"items": n or None, "usd": _times(per, n) if n else {}, "per_item": {p: str(v) for p, v in per.items()},
                "note": note}
    own = workflow_steps.of(kind).estimate
    if own is None:  # the documents are counted
        files, left_out = _documents(src)
        return {"items": len(files), "usd": _times(_per_item("document", engine), len(files)), "left_out": len(left_out),
                "note": None}
    # 181: the kind's own count (the statements': the code reads the exports for free; a PDF no reader knows is
    # extracted by AI), checked against the workflow's period first
    start, end = _period(period_start, period_end)
    counted = own(workflow_steps.paths_of(src), party_id=party_id, period_start=start, period_end=end)
    paid = counted.pop("paid")
    return {"items": counted.pop("items"), "usd": _times(_per_item("document", engine), paid), **counted, "note": None}
