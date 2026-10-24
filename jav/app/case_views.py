"""A case's page as data (231, plan stage A, A6; DECISIONS 231): its tabs and elements from its process pack.

Plain-language summary: a case's page has the tabs its process pack describes, each made of registered screen elements
(`configs/screen_elements.json`). The interface renders an element by its type; what the element shows comes from the
capability of the step it shows: an element's data is registered once for the pair (element type, capability), or for
the element type alone when it is the same for every capability. So the quote's line editor is the `line_draft`
capability's, and any process whose step uses that capability gets it. The page also says each step's state and which
steps wait for a person's start; starting one decides its start task, and the worker moves the case on.

- `register(ElementData(...))`: what an element of a type shows for a step of a capability (or for any).
- `view(case_id)`: the case, its steps and its tabs with each element's data.
- `start_step(case_id, step_id, actor)`: a person starts a step that waits for its start (`CaseError` otherwise; an
  unknown case is a `KeyError`).

Layer: application; it uses the process packs, the capability registry, the process runtime and the process core's
public operations.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jav.app import capabilities, process_packs, process_runtime
from jav.core import completion, identity
from jav.core.process import engine, tasks
from jav.core.user_messages import explained

__all__ = ["CaseError", "ElementData", "next_of", "register", "start_step", "view"]


class CaseError(ValueError):
    """A case that cannot be shown as it is, or a step that does not wait for a start (an unknown case is a KeyError)."""


@dataclass(frozen=True)
class ElementData:
    """What an element of `element` type shows for a step of `capability` (None: for any step): `data(case_id, step,
    shared)` returns it; `shared` is one dict per page view, for data several elements read (computed once)."""

    element: str
    capability: str | None
    module: str
    data: Callable[[str, str | None, dict[str, Any]], Any]


_DATA: dict[tuple[str, str | None], ElementData] = {}


def register(entry: ElementData) -> None:
    prior = _DATA.get((entry.element, entry.capability))
    if prior is not None and prior.module != entry.module:
        raise ValueError(f"element data {entry.element}/{entry.capability} is registered by {prior.module}")
    _DATA[(entry.element, entry.capability)] = entry


def _provider(element: str, capability: str | None) -> ElementData | None:
    if not _DATA:
        completion.complete("element data")
    return _DATA.get((element, capability)) or _DATA.get((element, None))


def _step_view(step: process_packs.Step, row: dict[str, Any]) -> dict[str, Any]:
    return {"title": step.title, "uses": step.uses, "start": step.start, "state": row.get("state"),
            "phase": row.get("phase"), "waiting_for": row.get("waiting_for"),
            "awaiting_start": row.get("phase") == capabilities.AWAITING_START, "note": row.get("note"),
            "result": row.get("result")}


def view(case_id: str) -> dict[str, Any]:
    """The case's page: the case, its steps and its tabs, each element with its data."""
    pinned = process_runtime.pack_of(case_id)
    if pinned is None:
        raise KeyError(case_id)
    pack = process_packs.load(pinned[0])
    if pack.version != pinned[1]:  # an older version's screens come with the first change of a pack (A7)
        raise explained(CaseError, "the case runs on an older version of its process pack")
    state = engine.state(case_id)
    rows = state["steps"]
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
                     "name": state.get("data", {}).get("name"), "status": state["status"]},
            "steps": {s.id: _step_view(s, rows.get(s.id, {})) for s in pack.steps}, "tabs": tabs,
            "next": _next(tabs)}


def _next(tabs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The case's next step: the first element whose data names one, with the tab of the element it is done on."""
    for tab in tabs:
        for element in tab["elements"]:
            nxt = element["data"].get("next") if isinstance(element["data"], dict) else None
            if nxt:
                where = next((x["id"] for x in tabs if any(e["type"] == nxt.get("element") for e in x["elements"])), tab["id"])
                return {k: v for k, v in nxt.items() if k != "element"} | {"tab": where}
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
