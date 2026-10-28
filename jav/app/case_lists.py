"""The lists of the process packs' cases (231, plan stage A, A7e; DECISIONS 231).

Plain-language summary: two tables of the uniform data view. The case list shows every case of every process pack:
its name (which opens its page), its process, whether it is open, the step it is at and what that step waits for (a
person's start, a person's decision, the other side's reply, the machine's work; 231 U2c: its sub-case, the case of
another process the step runs), its owner and when it started and last changed. The handovers to check show the
cases whose last attempt to send something failed or has an unknown outcome: the person sees where it went wrong and
opens the case to try again or to say whether it arrived.

Layer: application view, read only; it uses the process core's public reads, the process packs and the work packages.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jav.app import capabilities, datasets, process_runtime
from jav.app.datasets import Dataset, LabelSet, Rows, col
from jav.core import store
from jav.core.process import cases, outbox, tasks

__all__ = ["register"]

PERSON_START, PERSON, REPLY, WORK, FAILED = "person_start", "person", "reply", "work", "failed"
SUB_CASE = "sub_case"  # 231 (U2c): a step that waits for the case of another process it runs
_STATUS = {"open": "Open", "closed": "Closed"}
_WAITS = {PERSON_START: "A person's start", PERSON: "A person's decision", REPLY: "The reply", WORK: "The machine's work",
          FAILED: "A failed step", SUB_CASE: "Its sub-case"}
_HANDOVER = {outbox.FAILED: "Failed", outbox.UNCERTAIN: "Arrival unknown"}


def _containers(c: Any, *, closed: bool) -> list[dict[str, Any]]:
    """The process packs' case containers, newest first (an archived one only with the closed cases)."""
    rows = [dict(r) for r in c.execute("SELECT id, name, owner, status, created_at FROM workpackages WHERE source_kind=?"
                                       " ORDER BY created_at DESC, id", (process_runtime.CONTAINER,))]
    return [r for r in rows if closed or r["status"] != "archived"]


def _at(case: dict[str, Any], steps: dict[str, dict[str, Any]],
        order: list[tuple[str, str, Mapping[str, str]]]) -> tuple[str | None, str | None]:
    """The step the case is at (its title) and what it waits for: the first step of the pack's order not done; 231
    (C3b4): its capability may say what an event it waits for means (`Capability.waits`)."""
    if case["status"] != cases.OPEN:
        return None, None
    for step_id, title, waits in order:
        row = steps.get(step_id) or {}
        state = row.get("state")
        if state == cases.DONE:
            continue
        if state == cases.FAILED:
            return title, FAILED
        if row.get("phase") == capabilities.AWAITING_START:
            return title, PERSON_START
        if row.get("waiting_for") in waits:
            return title, waits[row["waiting_for"]]
        if row.get("waiting_for") == tasks.EVENT:
            return title, PERSON
        if row.get("waiting_for") == "reply":
            return title, REPLY
        return title, WORK
    return None, None


def _cases(scope: dict[str, str]) -> Rows:
    """Every process pack's case; the closed ones only on request (`include_closed`)."""
    closed = scope.get("include_closed") == "1"
    cols = [
        col("name", "Case", link="case"),  # U2a: the case opens at its own address
        col("process", "Process", "enum"),
        col("status", "Status", "enum", labels="case_status", badge=True, hidden=not closed),  # all open otherwise
        col("step", "Current step"),
        col("waits_for", "Waits for", "enum", labels="case_wait"),
        col("owner", "Owner"),
        col("created_at", "Started", "datetime"),
        col("updated_at", "Last change", "datetime"),
        col("version", "Process version", hidden=True),
        col("id", "Identifier", "id", hidden=True),
    ]
    out = []
    with store.connect() as c:
        for wp in _containers(c, closed=closed):
            case = cases.find_case_in(c, wp["id"])
            pack = process_runtime.pack_for(wp["id"]) if case is not None else None
            if case is None or pack is None or (case["status"] != cases.OPEN and not closed):
                continue
            step, waits = _at(case, cases.step_rows(c, wp["id"]), [(s.id, s.title or s.id, capabilities.of(s.uses).waits) for s in pack.steps])
            out.append({"id": wp["id"], "name": wp["name"], "process": pack.title, "version": pack.version,
                        "status": case["status"], "step": step, "waits_for": waits, "owner": wp["owner"],
                        "created_at": wp["created_at"], "updated_at": case["updated_at"], "_key": wp["id"],
                        "_wp": wp["id"]})
    return cols, out


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


_MODES = {"output_folder": "Output folder", "outlook_draft": "Outlook draft", "outlook_send": "Outlook send"}
# made once, so a repeated registration gives the same label sets
_LABEL_SETS = tuple(LabelSet(name, __name__, labels.copy) for name, labels in (
    ("case_status", _STATUS), ("case_wait", _WAITS), ("handover_status", _HANDOVER), ("send_mode", _MODES)))


def register() -> None:
    for labels in _LABEL_SETS:
        datasets.register_labels(labels)
    datasets.register(Dataset("cases", "Cases", (), _cases, optional_scope=("include_closed",),
                              natural_sort=(("created_at", True),)), after="waiting", module=__name__)
    datasets.register(Dataset("handovers", "Handovers to check", (), _handovers), after="cases", module=__name__)
