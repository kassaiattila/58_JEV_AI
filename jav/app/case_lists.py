"""The lists of the process packs' cases (231, plan stage A, A7e; DECISIONS 231).

Plain-language summary: two tables of the uniform data view. The case list shows every case of every process pack:
its name (which opens its page), its process, whether it is open, the step it is at and what that step waits for (a
person's start, a person's decision, the other side's reply, the machine's work; 231 U2c: its sub-case, the case of
another process the step runs), its owner and when it started and last changed. The handovers to check show the
cases whose last attempt to send something failed or has an unknown outcome: the person sees where it went wrong and
opens the case to try again or to say whether it arrived.

263 (plan E, F3; the owner's decisions of 2026-10-30: views, groups and a period grid): only the main cases have a
row; a sub-case's work shows in its main case's row (the step it is at and what that waits for), with the case's own
party and period and its steps' states (`_track`). The step shown is the first a person must act on, else the first
not done. The views - waiting for the person, the person's own, every open one, the closed ones, by process - are the
list's `view` scope, and `view_counts` gives their counts at once.

Layer: application view, read only; it uses the process core's public reads, the process packs and the work packages.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jav.app import capabilities, datasets, package_scope, parties, process_runtime
from jav.app.datasets import Dataset, LabelSet, Rows, col
from jav.core import store
from jav.core.process import cases, outbox, tasks

__all__ = ["VIEWS", "register", "view_counts"]

PERSON_START, PERSON, REPLY, WORK, FAILED = "person_start", "person", "reply", "work", "failed"
SUB_CASE = "sub_case"  # 231 (U2c): a step that waits for the case of another process it runs
_STATUS = {"open": "Open", "closed": "Closed"}
_WAITS = {PERSON_START: "A person's start", PERSON: "A person's decision", REPLY: "The reply", WORK: "The machine's work",
          FAILED: "A failed step", SUB_CASE: "Its sub-case"}
_HANDOVER = {outbox.FAILED: "Failed", outbox.UNCERTAIN: "Arrival unknown"}
# 263 (F3): what a person must act on; a case waiting for one of these is "waiting for me" when it is the person's or
# no one's
TURNS = (FAILED, PERSON_START, PERSON)
VIEWS = ("waiting", "mine", "open", "closed")


def _containers(c: Any, *, closed: bool) -> list[dict[str, Any]]:
    """The process packs' case containers, newest first (an archived one only with the closed cases)."""
    rows = [dict(r) for r in c.execute("SELECT id, name, owner, status, created_at FROM workpackages WHERE source_kind=?"
                                       " ORDER BY created_at DESC, id", (process_runtime.CONTAINER,))]
    return [r for r in rows if closed or r["status"] != "archived"]


def _waits(row: dict[str, Any], waits: Mapping[str, str]) -> str:
    """What a step not done waits for: a failure, a person's start or decision, the other side's reply, the machine; 231
    (C3b4): its capability may say what an event it waits for means (`Capability.waits`)."""
    if row.get("state") == cases.FAILED:
        return FAILED
    if row.get("phase") == capabilities.AWAITING_START:
        return PERSON_START
    if row.get("waiting_for") in waits:
        return waits[row["waiting_for"]]
    if row.get("waiting_for") == tasks.EVENT:
        return PERSON
    if row.get("waiting_for") == "reply":
        return REPLY
    return WORK


def _open_steps(case: dict[str, Any], steps: dict[str, dict[str, Any]],
                order: list[tuple[str, str, Mapping[str, str]]]) -> list[tuple[str, str, str]]:
    """The steps of a case not done yet, in the pack's order: (id, title, what it waits for); none for a closed case."""
    if case["status"] != cases.OPEN:
        return []
    out = []
    for step_id, title, waits in order:
        row = steps.get(step_id) or {}
        if row.get("state") != cases.DONE:
            out.append((step_id, title, _waits(row, waits)))
    return out


_TRACK = {cases.DONE: "done", cases.FAILED: "failed", cases.RUNNING: "running"}


def _case_rows(c: Any, *, closed: bool) -> list[dict[str, Any]]:
    """263 (F3): each main case's row, newest first: its party and period, its steps' states, and the step it is at - a
    sub-case's step shows in its main case's row as the main case's step's own ("Incoming invoices › Processing")."""
    party_names = {pid: row["name"] for pid, row in parties.party_rows(c).items()}
    found: dict[str, dict[str, Any]] = {}
    subs: dict[tuple[str, str], str] = {}  # (main case, its step) -> the sub-case running it now
    for wp in _containers(c, closed=True):  # a closed main case may hold an open sub-case's place
        case = cases.find_case_in(c, wp["id"])
        pack = process_runtime.pack_for(wp["id"]) if case is not None else None
        if case is None or pack is None:
            continue
        steps = cases.step_rows(c, wp["id"])
        order = [(st.id, st.title or st.id, capabilities.of(st.uses).waits) for st in pack.steps]
        parent = (case.get("data") or {}).get(process_runtime.PARENT)
        if parent:
            subs.setdefault((parent["case"], parent["step"]), wp["id"])  # newest first: the step's current one
        scope = package_scope.stored(wp["id"], c) or {}
        start, end = scope.get("period_start"), scope.get("period_end")
        found[wp["id"]] = {
            "wp": wp, "case": case, "pack": pack, "parent": parent, "open": _open_steps(case, steps, order),
            "row": {"id": wp["id"], "name": wp["name"], "process": pack.title, "version": pack.version, "pack": pack.id,
                    "status": case["status"], "owner": wp["owner"], "created_at": wp["created_at"],
                    "updated_at": case["updated_at"],
                    "party": party_names.get(scope.get("party_id") or "") if scope.get("party_id") else None,
                    "period": f"{start} – {end}" if start and end else start or None, "_key": wp["id"], "_wp": wp["id"],
                    "_track": [{"title": title, "state": _TRACK.get((steps.get(sid) or {}).get("state") or "", "waiting")}
                               for sid, title, _w in order],
                    "steps": f"{sum(1 for sid, _t, _w in order if (steps.get(sid) or {}).get('state') == cases.DONE)}/{len(order)}"}}
    out = []
    for case_id, info in found.items():
        if info["parent"] and info["parent"]["case"] in found:
            continue  # 263 (F3): a sub-case is its main case's step, not a row of its own
        if info["case"]["status"] != cases.OPEN and not closed:
            continue
        shown: list[tuple[str, str]] = []  # (the step's title, what it waits for), a sub-case's own resolved
        for step_id, title, waits in info["open"]:
            sub = found.get(subs.get((case_id, step_id), ""))
            if waits == SUB_CASE and sub is not None and sub["open"]:
                _sid, sub_title, sub_waits = next((x for x in sub["open"] if x[2] in TURNS), sub["open"][0])
                shown.append((f"{title} › {sub_title}", sub_waits))
            else:
                shown.append((title, waits))
        first = next((x for x in shown if x[1] in TURNS), shown[0] if shown else (None, None))
        out.append({**info["row"], "step": first[0], "waits_for": first[1]})
    return out


def _cases(scope: dict[str, str]) -> Rows:
    """The process packs' main cases in a view (`view`: waiting for `actor`, `actor`'s own, every open one - the default
    - or the closed ones), of one process (`pack`) or every one; `include_closed`: the open and the closed ones."""
    view = scope.get("view") or "open"
    every = scope.get("include_closed") == "1"
    closed = every or view == "closed"
    cols = [
        col("name", "Case", link="case"),  # U2a: the case opens at its own address
        col("process", "Process", "enum", group=True),
        col("party", "Party", group=True),
        col("period", "Period"),
        col("steps", "Steps"),  # 263 (F3): the steps' states as marks (`_track`)
        col("step", "Current step"),
        col("waits_for", "Waits for", "enum", labels="case_wait", group=True),
        col("owner", "Owner", group=True),
        col("status", "Status", "enum", labels="case_status", badge=True, hidden=not closed, group=True),
        col("created_at", "Started", "datetime"),
        col("updated_at", "Last change", "datetime"),
        col("version", "Process version", hidden=True),
        col("id", "Identifier", "id", hidden=True),
    ]
    with store.connect() as c:
        rows = _case_rows(c, closed=closed)
    return cols, [r for r in rows if _in_view(r, view if not every else "all", scope.get("actor"), scope.get("pack"))]


def _in_view(row: dict[str, Any], view: str, actor: str | None, pack: str | None) -> bool:
    if pack and row["pack"] != pack:
        return False
    is_open = row["status"] == cases.OPEN
    if view == "all":
        return True
    if view == "closed":
        return not is_open
    if not is_open:
        return False
    if view == "mine":
        return bool(actor) and row["owner"] == actor
    if view == "waiting":
        return row["waits_for"] in TURNS and (not row["owner"] or row["owner"] == actor)
    return True


def view_counts(actor: str | None) -> dict[str, Any]:
    """263 (F3): how many cases each view of the case list holds for the person, and the open ones of each process
    (with whether it repeats by period, which gives it a period grid)."""
    with store.connect() as c:
        rows = _case_rows(c, closed=True)
    counts = {v: sum(1 for r in rows if _in_view(r, v, actor, None)) for v in VIEWS}
    by: dict[str, dict[str, Any]] = {}
    for r in rows:
        entry = by.setdefault(r["pack"], {"pack": r["pack"], "title": r["process"], "open": 0, "all": 0, "repeats": False})
        entry["all"] += 1
        entry["open"] += r["status"] == cases.OPEN
    from jav.app import process_packs  # lazy: the packs read their files once

    for entry in by.values():
        try:
            entry["repeats"] = process_packs.load(entry["pack"]).repeats
        except process_packs.PackError:
            entry["repeats"] = False
    return {"views": counts, "processes": sorted(by.values(), key=lambda e: e["title"])}


def _handovers(scope: dict[str, str]) -> Rows:
    """The open cases whose step's last handover failed or has an unknown outcome, oldest first."""
    cols = [
        col("name", "Case", link="case"),  # U2a: the case opens at its own address
        col("step", "Step"),
        col("status", "Outcome", "enum", labels="handover_status", badge=True),
        col("attempt", "Attempt", "number"),
        col("mode", "Mode", "enum", labels="send_mode"),
        col("file_name", "File"),
        col("to", "Recipient", wrap="anywhere"),
        col("error", "What went wrong", clamp=2),
        col("updated_at", "When", "datetime"),
    ]
    out = []
    with store.connect() as c:
        for wp in _containers(c, closed=False):
            case = cases.find_case_in(c, wp["id"])
            if case is None or case["status"] != cases.OPEN:
                continue
            titles = {s.id: s.title or s.id for s in cases.definition_of(case).steps}
            last: dict[str, tuple[int, dict[str, Any]]] = {}
            for h in outbox.of_case(c, wp["id"]):
                n = last.get(h["step_id"], (0, {}))[0] + 1
                last[h["step_id"]] = (n, h)
            for step_id, (n, h) in last.items():
                if h["status"] not in _HANDOVER:
                    continue
                full = outbox.get(h["handover_id"]) or {}
                payload = full.get("payload") or {}
                out.append({"name": wp["name"], "step": titles.get(step_id, step_id), "status": h["status"], "attempt": n,
                            "mode": payload.get("mode"), "file_name": payload.get("file_name"), "to": payload.get("to"),
                            "error": h["error"], "updated_at": full.get("updated_at"), "_key": h["handover_id"],
                            "_wp": wp["id"]})
    return cols, sorted(out, key=lambda r: r["updated_at"] or "")


def _events(scope: dict[str, str]) -> Rows:
    """263 (plan E, F3; the owner's decision of 2026-10-30: every list the one list): a case's events, oldest first -
    when, the step, what happened (its kind; the interface words it from its detail, `_detail`) and who - searchable,
    sortable and grouped by the step or by who."""
    from jav.app import case_views  # lazy: the case page reads the registered capabilities

    cols = [
        col("at", "When", "datetime"),
        col("step_title", "Step", group=True),
        col("kind", "What happened"),
        col("who", "Who", group=True),
    ]
    rows = [{"_key": f"{e['at']}|{n}", "at": e["at"], "step_title": e["step_title"], "kind": e["kind"], "who": e["who"],
             "_detail": e["detail"]} for n, e in enumerate(case_views.events(scope["case_id"]))]
    return cols, rows


_MODES = {"output_folder": "Output folder", "outlook_draft": "Outlook draft", "outlook_send": "Outlook send"}
# made once, so a repeated registration gives the same label sets
_LABEL_SETS = tuple(LabelSet(name, __name__, labels.copy) for name, labels in (
    ("case_status", _STATUS), ("case_wait", _WAITS), ("handover_status", _HANDOVER), ("send_mode", _MODES)))


def register() -> None:
    for labels in _LABEL_SETS:
        datasets.register_labels(labels)
    datasets.register(Dataset("cases", "Cases", (), _cases, optional_scope=("include_closed", "view", "actor", "pack"),
                              natural_sort=(("created_at", True),)), after="waiting", module=__name__)
    datasets.register(Dataset("handovers", "Handovers to check", (), _handovers), after="cases", module=__name__)
    datasets.register(Dataset("case_events", "A case's events", ("case_id",), _events, natural_sort=(("at", False),)),
                      after="handovers", module=__name__)  # 263 (F3)
