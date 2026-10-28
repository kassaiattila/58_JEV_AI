"""A case's page as data (231, plan stage A, A6; DECISIONS 231): its tabs and elements from its process pack.

Plain-language summary: a case's page has the tabs its process pack describes, each made of registered screen elements
(`configs/screen_elements.json`). The interface renders an element by its type; what the element shows comes from the
capability of the step it shows: an element's data is registered once for the pair (element type, capability), or for
the element type alone when it is the same for every capability. So the quote's line editor is the `line_draft`
capability's, and any process whose step uses that capability gets it. The page also says each step's state and which
steps wait for a person's start; starting one decides its start task, and the worker moves the case on.

- `register(ElementData(...))`: what an element of a type shows for a step of a capability (or for any); `gives(element,
  capability)` (D0-a): whether one is registered, which the pack check asks.
- `view(case_id)`: the case, its steps and its tabs with each element's data.
- `start_step(case_id, step_id, actor)`: a person starts a step that waits for its start (`CaseError` otherwise; an
  unknown case is a `KeyError`).
- `act(case_id, step_id, name, actor, note)` (A7d): a person's action on a step, one its capability offers and the step
  waits for now (say whether a message arrived, record a reply); each step's view lists the ones available.
- The shared elements every pack may show (A7e): `timeline` (who did what and when on the case) and `cost` (what each
  step spent, by service); (B1) `partner_link`: the partners the case is about, by the pack's partner links, each
  linked, or proposed from the record's fields with the partner it seems to be. `link_partner(case_id, role,
  partner_id, actor)`: a person links one (the case's scope names it). The next step comes from the first step that is not done, through the elements that show
  it; a step no element shows leaves it to the first element that names one. D-f9: `blockers`, what holds an open
  case, each with the tab where it is resolved.

Layer: application; it uses the process packs, the capability registry, the process runtime and the process core's
public operations.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from jav.app import capabilities, package_scope, partners, process_packs, process_runtime, scopes
from jav.core import calls, completion, identity, store
from jav.core.process import cases, engine, tasks
from jav.core.user_messages import explained

__all__ = ["CaseError", "ElementData", "act", "gives", "link_partner", "marks", "next_of", "register", "return_step",
           "start_step", "view"]


class CaseError(ValueError):
    """A case that cannot be shown as it is, or a step that does not wait for a start (an unknown case is a KeyError)."""


@dataclass(frozen=True)
class ElementData:
    """What an element of `element` type shows for a step of `capability` (None: for any step): `data(case_id, step,
    shared)` returns it; `shared` is one dict per page view, for data several elements read (computed once). `mark()`
    (A3d): a value that changes when what it shows may have changed (the work package list's cache mark)."""

    element: str
    capability: str | None
    module: str
    data: Callable[[str, str | None, dict[str, Any]], Any]
    mark: Callable[[], Any] | None = None
    applies: Callable[[str], bool] | None = None  # D0-d: an element's data for any step, only for these capabilities


_DATA: dict[tuple[str, str | None], ElementData] = {}


def register(entry: ElementData) -> None:
    prior = _DATA.get((entry.element, entry.capability))
    if prior is not None and prior.module != entry.module:
        raise ValueError(f"element data {entry.element}/{entry.capability} is registered by {prior.module}")
    _DATA[(entry.element, entry.capability)] = entry


def marks() -> list[Any]:
    """231 (A3d): the marks of every element's data that has one, once per providing module (a case's page and the
    package list read them)."""
    completion.complete("element data")
    seen: dict[str, Any] = {}
    for entry in _DATA.values():
        if entry.mark is not None and entry.module not in seen:
            seen[entry.module] = entry.mark()
    return [seen[k] for k in sorted(seen)]


def _provider(element: str, capability: str | None) -> ElementData | None:
    completion.complete("element data")  # once per process: the domains register theirs there (A7e: not only when empty)
    general = _DATA.get((element, None))
    if general is not None and general.applies is not None and (capability is None or not general.applies(capability)):
        general = None  # D0-d: a shared element that shows only some capabilities' steps (the approval)
    return _DATA.get((element, capability)) or general


def gives(element: str, capability: str | None) -> bool:
    """D0-a: whether an element of the type shows something for a step of the capability (None: an element that shows
    no step), so the pack check refuses an element that would stay empty."""
    return _provider(element, capability) is not None


RETRY = "retry"  # A7e: every failed step's own action: a person starts it again


def _actions(case_id: str, step: process_packs.Step, row: dict[str, Any]) -> list[dict[str, str]]:
    """The actions available on the step now: a failed step's retry (A7e), a running step's capability's (A7d)."""
    if row.get("state") == cases.FAILED:
        return [{"name": RETRY, "label": "Try again"}]
    state = row.get("state")
    if state not in (cases.RUNNING, cases.DONE):
        return []
    return [{"name": a.name, "label": a.label, **({"form": True} if a.form is not None else {})}  # D-f2: its element's
            for a in capabilities.of(step.uses).actions
            if (state == cases.RUNNING or a.on_done) and a.available(case_id, step.id)]  # D-f2: a reopening on a done one


def _reasons(state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """U-A8: why each step last stopped, in a person's words (its failure's history row), by step."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in state.get("history") or ():
        if row["kind"] == "step_failed" and row["step_id"]:
            out[row["step_id"]] = list(row["detail"].get("reasons") or [])
    return out


def _step_view(case_id: str, step: process_packs.Step, row: dict[str, Any],
               reasons: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    # 231 (C2d): `by_person`: a step of a human capability waits for a person, so its page need not ask again by itself;
    # U-A8: `reasons`, why a stopped step stopped in a person's words (none: its note says it); U1: `waits_on`, what
    # the event a running step waits for means, as its capability says (`Capability.waits`: a person's start, the
    # machine's work, a person) - a documents step waits for the machine while its live run works
    waits_on = capabilities.of(step.uses).waits.get(str(row.get("waiting_for"))) if row.get("state") == cases.RUNNING else None
    return {"title": step.title, "uses": step.uses, "start": step.start, "state": row.get("state"),
            "phase": row.get("phase"), "waiting_for": row.get("waiting_for"),
            "awaiting_start": row.get("phase") == capabilities.AWAITING_START, "note": row.get("note"),
            "result": row.get("result"), "actions": _actions(case_id, step, row),
            "by_person": capabilities.of(step.uses).kind == "human"} | (
        {"reasons": reasons} if reasons and row.get("state") == cases.FAILED else {}) | ({"waits_on": waits_on} if waits_on else {})


def view(case_id: str) -> dict[str, Any]:
    """The case's page: the case, its steps and its tabs, each element with its data."""
    pack = process_runtime.pack_for(case_id)  # A7a: the version the case started on, its screens too
    if pack is None:
        raise KeyError(case_id)
    state = engine.state(case_id)
    rows = state["steps"]
    said = _reasons(state)
    by_id = {s.id: s for s in pack.steps}
    shared: dict[str, Any] = {}
    tabs = []
    for tab in pack.screens.tabs:
        elements = []
        for element in tab.elements:
            cap = capabilities.of(by_id[element.step].uses).name if element.step else None
            provider = _provider(element.type, cap)
            elements.append({**element.model_dump(), "data": provider.data(case_id, element.step, shared) if provider else None})
        tabs.append({"id": tab.id, "label": tab.label, "elements": elements})
    return {"case": {"id": case_id, "pack": pack.id, "version": pack.version, "title": pack.title,
                     "name": state.get("data", {}).get("name"), "status": state["status"],
                     # U-A8: the worker has something to do for it now (a person's decision it takes next), so the page
                     # asks again until it moved
                     "due": state["status"] == cases.OPEN and engine.is_due(case_id)},
            "steps": {s.id: _step_view(case_id, s, rows.get(s.id, {}), said.get(s.id)) for s in pack.steps}, "tabs": tabs,
            "next": _next(tabs, [s.id for s in pack.steps if rows.get(s.id, {}).get("state") != "done"])
            if state["status"] == "open" else None}  # A7e: a closed case has no next step on its page


def _next(tabs: list[dict[str, Any]], open_steps: list[str] | None = None) -> dict[str, Any] | None:
    """The case's next step, with the tab of the element it is done on: the first element showing the first step that
    is not done and naming one (A7e: a send step after the quote's approval); otherwise the first element naming one.
    231 (C2d): a next step naming the element's `show` too is done on the tab whose element of that type shows it (one
    special element on several tabs)."""
    shown = [(tab, e) for tab in tabs for e in tab["elements"]]
    first_open = (open_steps or [None])[0]

    def fits(element: dict[str, Any], nxt: dict[str, Any]) -> bool:
        return element["type"] == nxt.get("element") and (nxt.get("show") is None or element.get("show") == nxt["show"])

    for tab, element in [x for x in shown if first_open and x[1].get("step") == first_open] + shown:
        nxt = element["data"].get("next") if isinstance(element["data"], dict) else None
        if nxt:
            where = next((x["id"] for x in tabs if any(fits(e, nxt) for e in x["elements"])), tab["id"])
            return {k: v for k, v in nxt.items() if k not in ("element", "show")} | {"tab": where}
    return None


def next_of(case_id: str) -> dict[str, Any] | None:
    """The case's next step as its page names it (the work package list's next step of its container)."""
    return view(case_id)["next"]


def start_step(case_id: str, step_id: str, actor: identity.Who) -> dict[str, Any]:
    """A person starts the step that waits for its start; the worker moves the case on."""
    tid = tasks.task_id(capabilities.STEP_START, f"{case_id}:{step_id}")
    task = tasks.get(tid) if process_runtime.pack_of(case_id) else None
    if task is None or task.status != tasks.OPEN:
        raise explained(CaseError, "the step {{step}} does not wait for a start", step=step_id)
    tasks.decide(tid, identity.who(actor))
    return view(case_id)


def act(case_id: str, step_id: str, name: str, actor: identity.Who, note: str | None = None,
        values: dict[str, Any] | None = None) -> dict[str, Any]:
    """A person's action on the case's step (A7d): one its capability offers and the step waits for now; `CaseError`
    otherwise. The worker moves the case on. D-f2: an action with a form takes `values`, checked by the form (422 when
    they do not fit; a page showing an older state is refused by the action itself, 409)."""
    pack = process_runtime.pack_for(case_id)
    if pack is None:
        raise KeyError(case_id)
    step = next((s for s in pack.steps if s.id == step_id), None)
    if step is not None and name == RETRY:
        try:
            cases.retry(case_id, step_id, identity.who(actor))
        except cases.StepStateError:
            raise explained(CaseError, "the step {{step}} does not wait for this action", step=step_id) from None
        return view(case_id)
    action = next((a for a in capabilities.of(step.uses).actions if a.name == name), None) if step else None
    if step is None or action is None or not action.available(case_id, step_id):
        raise explained(CaseError, "the step {{step}} does not wait for this action", step=step_id)
    if action.form is not None:
        if values is None:
            raise explained(CaseError, "the action {{name}} takes values", name=name)
        assert action.submit is not None
        action.submit(case_id, step_id, actor, action.form.model_validate(values))
        return view(case_id)
    action.run(case_id, step_id, actor, note.strip() if note and note.strip() else None)
    return view(case_id)


# --- the shared elements (A7e) ----------------------------------------------------------------------------------------

# the core's own bookkeeping, and what the next row says anyway (a step started, a person's task opened before its
# decision)
_QUIET = frozenset({"waiting", "wait_ended", "handover_recorded", "handover_sent", "event_applied", "event_refused",
                    "step_started", "task_opened", "task_reopened"})


def _iso(at: Any) -> Any:
    """The history's moment (epoch seconds) as the ISO text every other time on the page is."""
    return datetime.fromtimestamp(at, timezone.utc).isoformat(timespec="seconds") if isinstance(at, (int, float)) else at


def _who(actor_id: str) -> str | None:
    """A person's name from their id (`local:<name>`); None for the machine."""
    kind, _, name = actor_id.partition(":")
    return name if kind == "local" else None


def _detail(detail: Any) -> dict[str, Any]:
    """What an event's row says beyond its kind: a note, a task's kind, a person's answer, a timer's name; U1: a stopped
    step's reasons in a person's words."""
    if not isinstance(detail, dict):
        return {}
    out: dict[str, Any] = {k: detail[k] for k in ("note", "timer") if isinstance(detail.get(k), str)}
    if isinstance(detail.get("reasons"), list) and detail["reasons"]:
        out["reasons"] = detail["reasons"]
    if isinstance(detail.get("task"), str):
        out["task_kind"] = detail["task"].partition(":")[0]
    outcome = detail.get("outcome")
    answer = next((outcome[k] for k in ("outcome", "reply") if isinstance(outcome, dict) and isinstance(outcome.get(k), str)),
                  None)
    if answer:
        out["answer"] = answer
    return out


def _timeline(case_id: str, _step: str | None, shared: dict[str, Any]) -> dict[str, Any]:
    """The case's events in order: who did what and when, with the step's title; the core's own bookkeeping (a wait
    begun or ended, a handover recorded before it is sent, an event taken) is left out. Stage D0 (D0-e): its start
    names the versions the case keeps to its end (`process_runtime.kept_of`)."""
    pack = process_runtime.pack_for(case_id)
    titles = {s.id: s.title or s.id for s in pack.steps} if pack else {}
    rows = [{"at": _iso(h["at"]), "kind": h["kind"], "step": h["step_id"], "step_title": titles.get(h["step_id"] or ""),
             "who": _who(h["actor"]), "detail": _detail(h["detail"])}
            for h in cases.view(case_id)["history"] if h["kind"] not in _QUIET]
    start = next((r for r in rows if r["kind"] in ("started", "adopted")), None)
    if start is not None and (kept := process_runtime.kept_of(case_id)) is not None:
        start["detail"]["kept"] = kept  # D0-e: the versions the case keeps from its start
    return {"events": rows}


def _cost(case_id: str, _step: str | None, shared: dict[str, Any]) -> dict[str, Any]:
    """What the case's steps spent, by step and service: the live calls and their known cost, and the answers taken from
    an earlier one (free); a call without a known cost is held apart at its reserved maximum. Money as text."""
    pack = process_runtime.pack_for(case_id)
    lines, total = [], Decimal("0")
    for step in pack.steps if pack else ():
        by: dict[str, dict[str, Any]] = {}
        for scope in capabilities.step_scopes(case_id, step.id, step.uses):
            for call in calls.scope_journal(scope):
                line = by.setdefault(call["provider"], {"calls": 0, "reused": 0, "cost": Decimal("0"),
                                                        "open": Decimal("0")})
                if (call.get("note") or "").startswith(f"{calls.REUSED_NOTE}:"):
                    line["reused"] += 1
                    continue
                line["calls"] += 1
                if call["cost_usd"] is not None:
                    line["cost"] += Decimal(str(call["cost_usd"]))
                else:
                    line["open"] += Decimal(str(call["max_cost_usd"] or 0))
        for provider, line in by.items():
            total += line["cost"]
            lines.append({"step": step.id, "step_title": step.title or step.id, "provider": provider,
                          "calls": line["calls"], "reused": line["reused"], "cost_usd": str(line["cost"]),
                          "open_usd": str(line["open"])})
    return {"lines": lines, "total_usd": str(total)}


def _partner_brief(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in ("partner_id", "name", "tax_number", "email", "roles", "retired", "version")}


def _partner_link(case_id: str, _step: str | None, shared: dict[str, Any]) -> dict[str, Any]:
    """231 (B1): the partners the case is about, by its pack's partner links: the linked partner, or the values its
    record's fields give and the partner they seem to be (the same tax number or name)."""
    pack = process_runtime.pack_for(case_id)
    linked = ((package_scope.stored(case_id) or {}).get("parts") or {}).get(scopes.PARTNERS) or {}
    if "state" not in shared:
        shared["state"] = engine.state(case_id)
    labels = partners.roles()
    out = []
    for link in pack.partners if pack else ():
        row: dict[str, Any] = {"role": link.role, "role_label": labels.get(link.role, {}).get("label", link.role),
                               "partner": None, "proposal": None, "match": None}
        if pid := linked.get(link.role):
            try:
                row["partner"] = _partner_brief(partners.get(pid))
            except partners.UnknownPartner:
                pass
        else:
            fields = ((shared["state"]["steps"].get(link.from_step) or {}).get("result") or {}).get("fields") or {}
            proposal = {target: str(fields[source]) for target, source in link.fields.items()
                        if fields.get(source) not in (None, "")}
            if proposal.get("name"):
                row["proposal"] = proposal
                found = partners.match(proposal["name"], proposal.get("tax_number"))
                row["match"] = _partner_brief(found) if found else None
        out.append(row)
    return {"links": out}


def link_partner(case_id: str, role: str, partner_id: str, actor: identity.Who) -> dict[str, Any]:
    """231 (B1): a person links a partner to the case in one of its pack's partner roles; the case's scope names it.
    `CaseError` for a role the pack has no link for or a retired partner; an unknown partner is a `KeyError`."""
    pack = process_runtime.pack_for(case_id)
    if pack is None:
        raise KeyError(case_id)
    if role not in {link.role for link in pack.partners}:
        raise explained(CaseError, "the process names no partner role {{role}}", role=role)
    if partners.get(partner_id)["retired"]:
        raise explained(CaseError, "a retired partner is not linked to a case")
    with store.connect() as c:
        store.begin_immediate(c)
        stored = package_scope.stored(case_id, c) or {}
        parts = dict(stored.get("parts") or {})
        parts[scopes.PARTNERS] = scopes.of(scopes.PARTNERS).check({**(parts.get(scopes.PARTNERS) or {}), role: partner_id},
                                                                  CaseError)
        package_scope.save(c, case_id, party_id=stored.get("party_id"), period_start=stored.get("period_start"),
                           period_end=stored.get("period_end"), role=stored.get("role"), parts=parts, actor=actor)
    return view(case_id)


def _approval(case_id: str, step: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """D0-d: the shared approval element: the approval's state of the case's approving step (missing, approved, out of
    date, returned), its versions, its latest return and why it went out of date (`package_release.approval_state`)."""
    from jav.app import package_release  # lazy: the version store reads the packages, which this module serves

    return {"approval": package_release.approval_state(case_id, step=step)}


def _approves(capability: str) -> bool:
    """D0-d: whether a step of the capability (by name) is done with an approved version of its own."""
    return any(c.name == capability and c.own_version for c in capabilities.catalogue())


def return_step(case_id: str, step_id: str, reason: str, actor: identity.Who) -> dict[str, Any]:
    """D0-d: a person returns the case's approving step's result instead of approving it, with a reason; the step still
    waits for its approval. Returns the approval's state. `CaseError` for a step that approves nothing."""
    from jav.app import package_release, process_runtime

    if step_id not in process_runtime.own_version_steps(case_id):
        raise explained(CaseError, "the step {{step}} approves no version of its own", step=step_id)
    with store.connect() as c:
        store.begin_immediate(c)
        package_release.reject_own(c, case_id, step=step_id, reason=reason, actor=actor)
    return package_release.approval_state(case_id, step=step_id)


def _started_cases(case_id: str, _step: str | None, shared: dict[str, Any]) -> list[dict[str, Any]]:
    """231 (C1c): the cases started from an item of the work packages the case reads (its scope's `sources`): each with
    its process and state."""
    sources = set(((package_scope.stored(case_id) or {}).get("parts") or {}).get(scopes.SOURCES) or [])
    out = []
    for h in package_scope.holders(scopes.RECORD, lambda v: isinstance(v, dict) and v.get("workpackage_id") in sources):
        pinned = process_runtime.pack_of(h["id"])
        with store.connect() as c:
            case = cases.find_case_in(c, h["id"])
        out.append({"id": h["id"], "name": h["name"], "record": h["value"], "pack": pinned[0] if pinned else None,
                    "process": process_packs.load(pinned[0]).title if pinned else None,
                    "status": case["status"] if case else None})
    return out


_WAITS_ON = {"person_start": "start", "work": "waits", "person": "person"}  # U1: a step's wait, as the Overview names it


def _blockers(case_id: str, _step: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """D-f9: the shared blockers element: what holds an open case, step by step in the pack's order, each with the tab
    whose element shows that step (where it is resolved): a step that stopped (its note says why) or must run again, one
    that waits for a person's start, one that waits for a person's decision, and one that waits for something else (a
    task's deadline, a run, a handover). A step not reached yet, or working by itself, holds nothing."""
    pack = process_runtime.pack_for(case_id)
    if pack is None:
        raise KeyError(case_id)
    state = engine.state(case_id)
    if state["status"] != cases.OPEN:
        return {"status": state["status"], "items": []}
    where: dict[str, str] = {}
    for tab in pack.screens.tabs:
        for element in tab.elements:
            if element.step and element.step not in where:
                where[element.step] = tab.id
    items = []
    said = _reasons(state)
    for step in pack.steps:
        row = state["steps"].get(step.id, {})
        shown = _step_view(case_id, step, row, said.get(step.id))
        if row.get("state") in (cases.FAILED, cases.STALE):
            kind = "stopped" if row["state"] == cases.FAILED else "stale"
        elif row.get("state") != cases.RUNNING or not row.get("waiting_for"):
            continue
        elif shown.get("waits_on") in _WAITS_ON:  # U1: what the capability says its wait means
            kind = _WAITS_ON[shown["waits_on"]]
        elif shown["awaiting_start"]:
            kind = "start"
        elif shown["by_person"]:
            kind = "person"
        else:
            kind = "waits"
        items.append({"step": step.id, "kind": kind, "note": row.get("note"), "waiting_for": row.get("waiting_for"),
                      "tab": where.get(step.id)} | ({"reasons": shown["reasons"]} if shown.get("reasons") else {}))
    return {"status": state["status"], "items": items}


register(ElementData("blockers", None, __name__, _blockers))  # D-f9
register(ElementData("started_cases", None, __name__, _started_cases))
register(ElementData("timeline", None, __name__, _timeline))
register(ElementData("cost", None, __name__, _cost))
register(ElementData("partner_link", None, __name__, _partner_link))
register(ElementData("approval", None, __name__, _approval, applies=_approves))  # D0-d: shared, for approving steps
