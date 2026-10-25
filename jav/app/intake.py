"""How a case of a process pack starts from what arrives (231, plan stage C, C1a; DECISIONS 231).

Plain-language summary: a process pack says what starts its cases (`intake`): an email whose intent fits it (a quote
request starts an IT quote), or a person by hand. When an email arrives, every process whose intake takes emails is
asked whether the email holds what its cases start from: the step that reads its record from the case's scope
(a capability with a `preview`) reads the email as it would at the case's start. Each process that finds it is an
offer on the email's page: what the record holds, what it lacks, the cases already started from it, and how its case
starts (a person starts it, or, by the owner's decision of 2026-10-25, it starts by itself).

- `offers(wp_id, item_id)`: the processes an email item may start a case of, each with its record's preview, its
  gaps, a name for the case, and the cases already started from it.
- `start_due()`, `tick()` (C1b; the owner's decision of 2026-10-25): a process whose intake starts its case by itself
  (`starts: case`) gets one case per email read with its intent (by a run or a person's correction), once: each email
  is remembered (`intake_starts`), and an email a case was started from by hand is left alone. Only the case's free
  steps run; a paid step waits for a person's start, as the pack says. The emails already there when a process's
  intake first starts cases are remembered without a case (only new emails start one). The worker calls `tick` (at
  most every `TICK_EVERY_S`).

Layer: application, the shared library; it uses the process packs, the capabilities, the scope parts and the package
scopes. It names no process and no domain: the record's reading is the capability's.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from jav.app import capabilities, item_kinds, package_scope, process_packs, scopes
from jav.core import identity, store
from jav.core.clock import utc_stamp as _now

__all__ = ["EMAIL_INTENT", "MANUAL", "PACKAGE", "STARTS_CASE", "TICK_EVERY_S", "offers", "package_offers", "start_due",
           "tick"]

log = logging.getLogger(__name__)

EMAIL_INTENT, MANUAL, PACKAGE = "email_intent", "manual", "package"
STARTS_CASE = "case"  # C1b: the intake starts the case by itself
TICK_EVERY_S = 60.0
MACHINE = identity.machine("email intake")
SINCE = "*"  # the row that says from when a process's intake starts cases: the emails before it are remembered as seen
STARTING, STARTED, HAD_CASE, BEFORE = "starting", "started", "had_case", "before"

store.register_schema("intake", """
-- 231 (C1b): the emails a process's intake took (a case started from it, one already there, or one from before)
CREATE TABLE IF NOT EXISTS intake_starts (
    pack_id         TEXT NOT NULL,
    workpackage_id  TEXT NOT NULL,
    item_id         TEXT NOT NULL,
    state           TEXT NOT NULL,     -- starting | started | had_case | before (and the * row: since)
    case_id         TEXT,
    at              TEXT NOT NULL,
    PRIMARY KEY (pack_id, workpackage_id, item_id)
);
""")


def _label(pack: process_packs.ProcessPack, record: dict[str, Any] | None) -> str | None:
    """What the case is about, for its name: the value its first partner link's name field reads, else the record's
    title."""
    fields = (record or {}).get("fields") or {}
    for link in pack.partners:
        name = fields.get(link.fields.get("name", ""))
        if isinstance(name, str) and name.strip():
            return name.strip()
    title = (record or {}).get("title")
    return title.strip() if isinstance(title, str) and title.strip() else None


def offers(wp_id: str, item_id: str) -> list[dict[str, Any]]:
    """The processes whose intake takes emails and whose record step finds its record in this email: each with how its
    case starts, the record (`{"workpackage_id", "item_id"}`), the preview its capability gives, the record's gaps, a
    name for the case and the cases already started from this record. Empty when no process takes it."""
    record = {"workpackage_id": wp_id, "item_id": item_id}
    out = []
    for pack in process_packs.packs():
        entries = [e for e in pack.intake if e.on == EMAIL_INTENT]
        reader = _record_step(pack) if entries and scopes.RECORD in pack.scope.parts else None
        if reader is None:
            continue
        shown = reader[0].preview(record, reader[1])
        if shown is None:
            continue
        out.append({"pack": pack.id, "title": pack.title, "starts": entries[0].starts, "record": record,
                    "preview": shown.get("record"), "list_field": shown.get("list_field"),
                    "record_type": shown.get("record_type"),
                    "gaps": list(shown.get("gaps") or []),
                    "label": _label(pack, shown.get("record")),
                    "cases": package_scope.holding(scopes.RECORD, record)})
    return out


def package_offers(wp: dict[str, Any]) -> list[dict[str, Any]]:
    """C1c: the processes whose intake takes a work package of this kind (an email package offers the email routing):
    each with a name for its case and the cases already reading the package (scope part `sources`)."""
    out = []
    for pack in process_packs.packs():
        if any(e.on == PACKAGE and wp.get("source_kind") in e.package_kinds for e in pack.intake):
            reading = [h for h in package_scope.holders(scopes.SOURCES, lambda v, wp_id=wp["id"]: wp_id in (v or []))
                       if process_runtime_pack(h["id"]) == pack.id]
            out.append({"pack": pack.id, "title": pack.title, "name": f"{pack.title}: {wp.get('name') or wp['id']}"[:200],
                        "sources": [wp["id"]], "cases": [{"id": h["id"], "name": h["name"]} for h in reading]})
    return out


def process_runtime_pack(case_id: str) -> str | None:
    from jav.app import process_runtime

    pinned = process_runtime.pack_of(case_id)
    return pinned[0] if pinned else None


def _record_step(pack: process_packs.ProcessPack) -> tuple[Any, dict[str, Any]] | None:
    """The step that reads the case's record (its capability has a `preview`) with its parameters as the pack's
    current values make them; None when the pack has none."""
    from jav.app import process_settings

    step = next((s for s in pack.steps if capabilities.of(s.uses).preview is not None), None)
    if step is None:
        return None
    resources = process_settings.effective_resources(pack)
    params = process_packs.definition(pack.model_copy(update={"resources": resources})).step(step.id).params
    return capabilities.of(step.uses), {k: v for k, v in params.items() if not k.startswith("_")}


def _emails_read_as(intent: str) -> list[tuple[str, str]]:
    """Every (package, email item) a run read, or a person corrected, as `intent`."""
    own = item_kinds.handler(item_kinds.EMAIL)
    with store.connect() as c:
        found = list(own.found_as(intent, c)) if own is not None else []
        found += [(r[0], r[1]) for r in c.execute(
            "SELECT DISTINCT r.workpackage_id, k.item_id FROM run_item_corrections k JOIN runs r ON r.run_id = k.run_id"
            " WHERE json_extract(k.fields, '$.intent') = ?", (intent,))]
    return sorted(set(found))


def _remember(pack_id: str, wp_id: str, item_id: str, state: str, case_id: str | None = None) -> None:
    with store.connect() as c:
        c.execute("INSERT INTO intake_starts(pack_id, workpackage_id, item_id, state, case_id, at) VALUES (?,?,?,?,?,?)"
                  " ON CONFLICT(pack_id, workpackage_id, item_id) DO UPDATE SET state=excluded.state,"
                  " case_id=excluded.case_id, at=excluded.at", (pack_id, wp_id, item_id, state, case_id, _now()))


def start_due() -> list[dict[str, Any]]:
    """C1b: a case of each process whose intake starts its case by itself, for every email read with its intent that
    no case was started from yet: [{pack, record, case_id}]. An email is taken once: it is remembered before its case
    starts, so an interrupted start is never repeated (the email still offers the case on its page)."""
    from jav.app import process_runtime

    started = []
    for pack in process_packs.packs():
        entries = [e for e in pack.intake if e.on == EMAIL_INTENT and e.starts == STARTS_CASE and e.intent]
        reader = _record_step(pack) if entries and scopes.RECORD in pack.scope.parts else None
        if reader is None:
            continue
        cap, params = reader
        with store.connect() as c:
            taken = {(r["workpackage_id"], r["item_id"]) for r in c.execute(
                "SELECT workpackage_id, item_id FROM intake_starts WHERE pack_id=?", (pack.id,))}
        first = (SINCE, SINCE) not in taken
        for entry in entries:
            for wp_id, item_id in _emails_read_as(str(entry.intent)):
                if (wp_id, item_id) in taken:
                    continue
                record = {"workpackage_id": wp_id, "item_id": item_id}
                if first:
                    _remember(pack.id, wp_id, item_id, BEFORE)
                elif package_scope.holding(scopes.RECORD, record):
                    _remember(pack.id, wp_id, item_id, HAD_CASE)
                elif (shown := cap.preview(record, params)) is not None:
                    _remember(pack.id, wp_id, item_id, STARTING)
                    name = f"{pack.title}: {_label(pack, shown.get('record')) or item_id}"[:200]
                    case_id = process_runtime.start_case(pack.id, {scopes.RECORD: record}, name=name, actor=MACHINE)
                    _remember(pack.id, wp_id, item_id, STARTED, case_id)
                    started.append({"pack": pack.id, "record": record, "case_id": case_id})
                taken.add((wp_id, item_id))
        if first:
            _remember(pack.id, SINCE, SINCE, "since")
    return started


_last_tick: dict[str, float] = {}  # per store: a worker serves one store, a test each its own


def tick(now: float | None = None) -> int:
    """The worker's turn (at most every `TICK_EVERY_S` per store): the cases due to start by themselves; how many
    started."""
    now = time.monotonic() if now is None else now
    key = str(store.current_path())
    if key in _last_tick and now - _last_tick[key] < TICK_EVERY_S:
        return 0
    _last_tick[key] = now
    started = start_due()
    for s in started:
        log.info("intake: case %s of %s started from %s", s["case_id"], s["pack"], s["record"])
    return len(started)
