"""Field correction on a run item (040 K2): the value corrected by a person, versioned, never silently overwritten.

A correction belongs to the run's result (run + item) and does not rewrite the machine-extracted data: the original
stays in the `datapoints` row, and the correction is a separate version series. Saving requires `expected_revision`;
if someone else saved in the meantime, `work.RevisionConflict` is raised (409 in the UI, where the client keeps its
working copy). Correcting an approved run is forbidden.

Validation on save: only fields of the item's type pack can be corrected; a money field must parse as a `Decimal`, a
date field as an ISO date (number and format checks happen in code, CLAUDE.md §4). 081: a typed amount or quantity is
read by the Hungarian habit ("28.000" and "28 000" are 28 000, "28,5" is 28.5) and stored canonically ("28000"); a
form that can be read two ways ("28.5" for money) is refused (`numbers.AmbiguousNumber`), never guessed. 084: a typed
date is read by the shared date reader in every unambiguous form ("04-DEC-22", "2022. dec. 4.", "04.12.2022") and
stored as an ISO date; a date whose day and month can be read two ways ("04/12/2022") is refused
(`dates.AmbiguousDate`).

Itemised list (048 T1-lista): correcting a `list` field replaces the whole list (deleting and adding rows too), each
cell validated by the kind and enumerated values of its line-item field. The pack's checks (e.g. the running balance
of a statement) also run on the corrected data in the item result (`checks`), in code, without any paid call.

Confirmed fields (083): a save may confirm simple fields (`confirm`): the version records each such field's value as
checked by a person (`confirmed`: field -> value), and the open to-dos on those fields of the document are resolved:
the run's own ones and those left by earlier runs (the resolution names the run where the field was checked). A
confirmation lasts while the field's value stays the same; a later version that changes the value drops it. Each to-do
of a document carries the field it is about (`field`, see `reason_field`), so the UI shows it at the field.

Approval (085, re-audit A01): the writing transaction checks the approval again, so a correction checked before a
concurrent approval is refused instead of being written after it; and an approval may name the reviewed version of the
result (`review_version`), so a correction saved meanwhile (in another tab) cannot be approved unseen.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from jav import (activity_kinds, dates, grounding, item_kinds, native_results, numbers, package_result, source_layer, store,
                 typepack, validators, work, work_readiness, work_runs)
from jav.native_contracts import Publication
from jav.policy import reason_field
from jav.user_messages import explained

store.register_schema("corrections", """
CREATE TABLE IF NOT EXISTS run_item_corrections (
    run_id      TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    revision    INTEGER NOT NULL,
    fields      TEXT NOT NULL,                 -- JSON: mező -> javított érték (a teljes javításhalmaz, nem különbség)
    actor       TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (run_id, item_id, revision)
);
""")


def _migrate(conn) -> None:
    store.add_columns(conn, "run_item_corrections", {
        "sources": "TEXT",  # 045: field -> ids of the words selected on the image
        "confirmed": "TEXT",  # 083: field -> the value a person confirmed
        "native_sources": "TEXT", "result_version": "TEXT",
    })


store.register_migration("corrections", _migrate)


def datapoints_row(run_id: str, item_id: str) -> dict[str, Any] | None:
    with store.connect() as c:
        item = c.execute("SELECT flow_run_id FROM run_items WHERE run_id=? AND item_id=?", (run_id, item_id)).fetchone()
        if item is None or item["flow_run_id"] is None:
            return None
        row = c.execute("SELECT * FROM datapoints WHERE run_id=? AND doc_id=?", (item["flow_run_id"], item_id)).fetchone()
    if row is None:
        return None
    out = dict(row)
    for k in ("datapoints", "field_conf", "validation", "review_reasons", "evidence", "provenance"):
        out[k] = json.loads(out[k]) if out[k] is not None else None
    return out


def review_version(run_id: str, c: sqlite3.Connection | None = None) -> str:
    """085 (re-audit A01): the version of a run's reviewed result, from the latest correction version of each item. The
    machine result of a finished run does not change, so the corrections (confirmations included) are what can change
    under a reviewer. `c`: read inside the caller's transaction (the approval).

    086 (audit of 2026-10-02, N02): the decisions on an email's task proposals are part of the reviewed result too (the
    flow runs of a run are `<run_id>:<item_id>`). A run without task decisions keeps the version computed as before.

    126: so are the duplicate decisions on pairs that include one of the run's documents; a run without any keeps its
    earlier version. 129: and so are the reconciliation decisions on pairs one of the run's documents is a side of.
    139: and so are the choices between two statements of the same days that include one of the run's documents.

    175 (plan 170 E4): the parts are the decision kinds of the activity registry (`jav/activity_kinds.py`), registered
    below in this order; each part present wraps the earlier ones, so a run without it keeps its earlier version, and a
    logic pack's own decision kind joins the same way."""
    if c is None:
        with store.connect() as own:
            return review_version(run_id, own)
    items = [r["item_id"] for r in c.execute("SELECT item_id FROM run_items WHERE run_id=?", (run_id,))]
    payload: Any = None
    for kind in activity_kinds.decisions():
        rows = kind.rows(run_id, items, c)
        if kind.wraps is None:
            payload = rows
        elif rows:
            payload = {kind.wraps: payload, kind.name: rows}
    return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()[:16]


# --- the decisions a run's reviewed version is made of, in the order they nest (175, plan 170 E4) ---------------------

def _correction_rows(run_id: str, items: list[str], c: sqlite3.Connection) -> list[Any]:
    """The latest correction version of each item (confirmations included)."""
    return [[r["item_id"], r["r"]] for r in c.execute(
        "SELECT item_id, MAX(revision) r FROM run_item_corrections WHERE run_id=? GROUP BY item_id ORDER BY item_id", (run_id,))]


def _task_rows(run_id: str, items: list[str], c: sqlite3.Connection) -> list[Any]:
    """086: the decisions on an email's task proposals (the flow runs of a run are `<run_id>:<item_id>`)."""
    prefix = f"{run_id}:"
    return [[d["run_id"], d["task_index"], d["decision"]] for d in c.execute(
        "SELECT run_id, task_index, decision FROM email_task_decisions WHERE substr(run_id, 1, ?) = ?"
        " ORDER BY run_id, task_index", (len(prefix), prefix))]


def _native_rows(run_id: str, items: list[str], c: sqlite3.Connection) -> list[Any]:
    return native_results.version_parts(run_id, c)


# 185 (plan G-full-move T1d): the finance domain's parts (the duplicate, reconciliation and statement decisions) are
# registered by its domain module after "native" (`jav/domains/finance.py` `DECISIONS`)
for _kind in (activity_kinds.DecisionKind("corrections", _correction_rows),
              activity_kinds.DecisionKind("tasks", _task_rows, wraps="corrections"),
              activity_kinds.DecisionKind("native", _native_rows, wraps="review")):
    activity_kinds.register_decision(_kind)


def current(run_id: str, item_id: str, c: sqlite3.Connection | None = None) -> dict[str, Any]:
    """The latest correction (version 0 = no correction yet)."""
    if c is None:
        with store.connect() as own:
            return current(run_id, item_id, own)
    row = c.execute("SELECT * FROM run_item_corrections WHERE run_id=? AND item_id=? ORDER BY revision DESC LIMIT 1",
                    (run_id, item_id)).fetchone()
    if row is None:
        return {"run_id": run_id, "item_id": item_id, "revision": 0, "fields": {}, "sources": {}, "confirmed": {}, "actor": None,
                "note": None, "created_at": None, "native_sources": {}, "result_version": None}
    return {**dict(row), "fields": json.loads(row["fields"]), "sources": json.loads(row["sources"] or "{}"),
            "confirmed": json.loads(row["confirmed"] or "{}"), "native_sources": json.loads(row["native_sources"] or "{}")}


def _with_fields(reasons: list[dict[str, Any]], fields: set[str]) -> list[dict[str, Any]]:
    return [{**r, "field": reason_field(r["reason"], fields)} for r in reasons]


def _same_value(a: Any, b: Any) -> bool:
    """Whether a confirmed value still holds: an empty text and a missing value are the same (no value)."""
    a = None if a == "" else a
    b = None if b == "" else b
    return (a is None and b is None) or (a is not None and b is not None and str(a) == str(b))


def layer_for(dp: dict[str, Any] | None) -> source_layer.SourceLayer | None:
    return source_layer.load(dp["source_layer_id"]) if dp and dp.get("source_layer_id") else None


def effective_provenance(dp: dict[str, Any] | None, corr: dict[str, Any],
                         layer: source_layer.SourceLayer | None) -> dict[str, dict[str, Any]]:
    """The valid source location per field: manual selection > a search for the corrected value > the machine location.

    The old (machine) box of a corrected field must not show as evidence (the V4 "stale box" rule): if the corrected
    value cannot be found unambiguously, the field stays without a box and the machine location is offered only as an
    alternative."""
    machine = dict((dp or {}).get("provenance") or {})
    if not dp:
        return {}
    pack = typepack.get(dp["doc_type"])
    out = dict(machine)
    labels = grounding.Labels(layer) if layer is not None else None
    for field, value in corr["fields"].items():
        before = machine.get(field, {})
        if pack.kind(field) == "list":  # 053: the rows of the corrected list are located again
            rows = grounding.locate_rows(layer, value if isinstance(value, list) else [], dict(pack.list_fields.get(field, {})))
            out[field] = {"status": "list", "method": "rows", "alternatives": [], "rows": rows, "corrected": True}
            continue
        if field in corr.get("sources", {}):
            try:
                entry = grounding.manual(layer, corr["sources"][field])
            except ValueError:
                entry = {"status": "not_found", "method": "manual"}
        else:
            entry = grounding.locate_value(layer, pack.kind(field), value, field=field, labels=labels)
            if entry["status"] != "located" and before.get("status") in ("located", "approximate"):
                entry.setdefault("alternatives", [])
                entry["alternatives"] = [{"value": None, "p": None, "machine": True,
                                          **{k: before[k] for k in ("page", "bbox", "boxes", "word_ids", "quote")}}] + entry["alternatives"]
        out[field] = {"alternatives": [], **entry, "corrected": True, "confidence": before.get("confidence")}
    return out


class InvalidValue(ValueError):
    """153 (review): a typed value of a field that is no number or no date (`field`: the field, `kind`: money, number or
    date), so the interface can name the field instead of showing the reader's English text."""

    def __init__(self, field: str, kind: str, value: Any) -> None:
        super().__init__(f"{field}: not a {'date' if kind == 'date' else 'number'}: {value!r}")
        self.field, self.kind = field, kind


def _typed_value(kind: str, value: Any, known: set[str], field: str = "") -> Any:
    """081: a typed amount or quantity by the Hungarian habit (`numbers.read_input`), as canonical text ("28000"); 084: a
    typed date by the shared date reader (`dates.read_date_input`), as an ISO date. A value sent back unchanged (the
    machine value or the previous correction, already canonical) is kept as it is."""
    if kind not in ("money", "number", "date") or value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and kind != "date":
        return str(value)
    if not isinstance(value, str) or value in known or not value.strip():
        return value
    try:
        if kind == "date":
            return dates.read_date_input(value)
        return numbers.read_input(value, kind=kind)  # type: ignore[arg-type]
    except (numbers.AmbiguousNumber, dates.AmbiguousDate) as exc:
        exc.field = field  # type: ignore[attr-defined]  # 153: the interface names the field
        raise
    except ValueError as exc:
        raise InvalidValue(field, kind, value) from exc


def _known(*values: Any) -> set[str]:
    return {str(v) for v in values if v is not None and not isinstance(v, (list, dict))}


def _row_cell(rows: Any, i: int, name: str) -> Any:
    if not isinstance(rows, list) or i >= len(rows):
        return None
    row = rows[i]
    return row if name == "*" else row.get(name) if isinstance(row, dict) else None


def read_typed_values(pack: typepack.TypePack, fields: dict[str, Any], machine: dict[str, Any],
                      previous: dict[str, Any]) -> dict[str, Any]:
    """081: every amount and quantity of a correction set (header fields and list cells) read by `_typed_value`; 084:
    every date too."""
    out: dict[str, Any] = {}
    for name, value in fields.items():
        kind = pack.kind(name)
        if kind != "list":
            out[name] = _typed_value(kind, value, _known(machine.get(name), previous.get(name)), name)
            continue
        if not isinstance(value, list):
            out[name] = value
            continue
        cols = {c["name"]: c["kind"] for c in list_columns(pack, name, machine.get(name))}
        rows = []
        for i, row in enumerate(value):
            if "*" in cols:
                rows.append(_typed_value(cols["*"], row, _known(_row_cell(machine.get(name), i, "*"), _row_cell(previous.get(name), i, "*")),
                                         name))
            elif isinstance(row, dict):
                rows.append({c: _typed_value(cols.get(c, "text"), v, _known(_row_cell(machine.get(name), i, c), _row_cell(previous.get(name), i, c)),
                                             name)
                             for c, v in row.items()})
            else:
                rows.append(row)
        out[name] = rows
    return out


def _check_value(pack: typepack.TypePack, field: str, value: Any) -> None:
    if pack.kind(field) == "list":
        _check_list(pack, field, value)
        return
    if isinstance(value, (list, dict)):
        raise explained(ValueError, "{{field}}: a single value is expected, not a list", field=field)
    _check_cell(field, pack.kind(field), value)


def _check_cell(path: str, kind: str, value: Any, allowed: tuple[Any, ...] | None = None) -> None:
    if value is None:
        return
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise explained(ValueError, "{{path}}: the value must be text, an integer or null", path=path)
    if kind in ("money", "number"):
        try:
            Decimal(str(value))
        except InvalidOperation as exc:
            raise explained(ValueError, "{{path}}: not a number: {{value}}", path=path, value=repr(value)) from exc
    elif kind == "date":
        try:
            date.fromisoformat(str(value))
        except ValueError as exc:
            raise explained(ValueError, "{{path}}: not an ISO date (YYYY-MM-DD): {{value}}",
                            path=path, value=repr(value)) from exc
    if allowed is not None and value not in allowed:
        raise explained(ValueError, "{{path}}: {{value}} is not one of {{allowed}}",
                        path=path, value=repr(value), allowed=list(allowed))


def list_columns(pack: typepack.TypePack, field: str, machine_rows: Any = None) -> list[dict[str, Any]]:
    """The columns of an itemised list: the pack's line-item description, then any further line-item fields found in the
    machine rows (as text, the way extraction handles them). A simple list (`{"*": kind}`) has a single `*` column."""
    kinds = pack.list_fields.get(field, {"*": "text"})
    names = list(kinds)
    if "*" not in kinds:
        for row in machine_rows if isinstance(machine_rows, list) else []:
            names += [k for k in (row if isinstance(row, dict) else {}) if k not in names and k != "extra"]
    out = []
    for name in names:
        options = pack.enums.get(f"{field}[]" if name == "*" else f"{field}[].{name}")
        out.append({"name": name, "kind": kinds.get(name, "text"), **({"options": list(options)} if options else {})})
    return out


def _check_list(pack: typepack.TypePack, field: str, rows: Any, machine_rows: Any = None) -> None:
    if not isinstance(rows, list):
        raise explained(ValueError, "{{field}}: a list of rows is expected", field=field)
    cols = {c["name"]: c for c in list_columns(pack, field, machine_rows)}
    simple = "*" in cols
    for i, row in enumerate(rows):
        path = f"{field}[{i + 1}]"
        if simple:
            _check_cell(path, cols["*"]["kind"], row, tuple(cols["*"].get("options", ())) or None)
            continue
        if not isinstance(row, dict):
            raise explained(ValueError, "{{path}}: a row must be an object of columns", path=path)
        unknown = sorted(set(row) - set(cols))
        if unknown:
            raise explained(ValueError, "{{path}}: not columns of {{field}}: {{unknown}}",
                            path=path, field=field, unknown=unknown)
        for name, value in row.items():
            _check_cell(f"{path}.{name}", cols[name]["kind"], value, tuple(cols[name].get("options", ())) or None)


_LINE = re.compile(r"\bline (\d+)\b")


def effective_checks(pack: typepack.TypePack, effective: dict[str, Any]) -> list[dict[str, Any]]:
    """The pack's checks on the corrected (effective) data. A result pointing at rows (`line N`, possibly several) is
    also attached to the itemised list as `rows` if the pack has exactly one list (this is how the statement and
    line-item rules mark the faulty row)."""
    from jav.models import record_from_llm

    rec, _ = record_from_llm(effective, pack.fields, list_fields=pack.list_fields,
                             enums={k: list(v) for k, v in pack.enums.items()}, origin="canonical")
    lists = [f for f, k in pack.fields.items() if k == "list"]
    out = []
    for r in validators.run_checks(rec, pack.validators):
        entry: dict[str, Any] = r.model_dump()
        rows = sorted({int(n) for n in _LINE.findall(r.detail or "")})  # 053: a line check may name several rows
        if rows and not r.ok and len(lists) == 1:
            entry["rows"] = {lists[0]: rows}
        out.append(entry)
    return out


def native_publication(run_id: str, item_id: str, *, expected_result_version: str | None = None,
                       c: sqlite3.Connection | None = None) -> Publication:
    """Load and verify the exact published native result, inside a caller's transaction if supplied."""
    publication = native_results.get_publication(run_id, item_id, c=c)
    if publication is None:
        raise explained(work.NotReady, "The native result has not been published")
    if expected_result_version is not None and publication.result_version != expected_result_version:
        raise explained(work.RevisionConflict, "The native result changed; review the current version")
    native_results.verify_publication(publication, c=c)
    return publication


def _native_item_result(run: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Merge manual values without changing the original proposal or its machine grounding claim."""
    from jav.native_contracts import NativeItemResult

    run_id, item_id = run["run_id"], item["item_id"]
    reasons = work_runs.item_reasons(run_id, item_id, item)
    with store.connect() as c:
        c.execute("BEGIN")
        version = review_version(run_id, c)
        publication = native_results.get_publication(run_id, item_id, c=c)
        corr = current(run_id, item_id, c)
        if publication is not None and corr["revision"] and corr["result_version"] != publication.result_version:
            raise explained(work.RevisionConflict, "The correction belongs to a different published result")
    common = {"run_id": run_id, "item_id": item_id, "review_version": version,
              "correction": {k: corr[k] for k in ("revision", "fields", "native_sources", "confirmed")},
              "source_file": {"copy": bool(item.get("instance")), "original": work.original_state(item, verify=True)},
              "open_reasons": reasons["run"], "earlier_open_reasons": reasons["earlier"]}
    if publication is None:
        progress = native_results.unpublished_state(run_id, item_id)
        data = {**common, "result_version": None, "result_ready": False, "native_source": None,
                "reading": progress.reading.model_dump(mode="json"),
                "interpretation_outcome": progress.interpretation_outcome.model_dump(mode="json"),
                "interpretation": None, "native_facts": []}
    else:
        native_results.verify_publication(publication)
        facts = []
        for machine in native_results.machine_facts(publication):
            fact = machine.model_dump(mode="json")
            key = fact["fact_id"]
            effective = corr["fields"].get(key, fact["proposal"]["value"])
            citations = fact["native_citations"]
            if key in corr["native_sources"]:
                citations = [value.model_dump(mode="json") for value in native_results.resolve_citations(
                    publication, corr["native_sources"][key])]
            elif effective != fact["proposal"]["value"]:
                citations = []
            facts.append({**fact, "effective_value": effective, "native_citations": citations,
                          "confirmed": key in corr["confirmed"] and corr["confirmed"][key] == effective})
        interpretation = publication.interpretation
        data = {**common, "result_version": publication.result_version, "result_ready": True,
                "native_source": {k: getattr(publication, k) for k in
                                  ("reading_id", "bundle_sha256", "publication_id", "source_sha256")},
                "reading": publication.reading.model_dump(mode="json"),
                "interpretation_outcome": publication.interpretation_outcome.model_dump(mode="json"),
                "interpretation": ({"interpretation_id": publication.interpretation_id,
                    "payload_sha256": publication.payload_sha256, "status": "completed" if interpretation.facts else "empty",
                    **interpretation.model_dump(mode="json", include={"provider", "model", "execution", "gaps", "review_status", "correctness", "discarded_facts"})}
                    if interpretation is not None else None), "native_facts": facts}
    return NativeItemResult.model_validate_json(json.dumps(data)).model_dump(mode="json")


def save_native(run_id: str, item_id: str, *, values: dict[str, str | None], native_sources: dict[str, Any],
                expected_revision: int, expected_result_version: str, actor: str,
                confirm: list[str] | None = None, note: str | None = None) -> dict[str, Any]:
    """Validate and save a full native override set against immutable result identity under one write lock."""
    if not isinstance(expected_result_version, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_result_version):
        raise explained(ValueError, "Native corrections require an exact published result version")
    if any(not isinstance(value, str) and value is not None for value in values.values()):
        raise explained(ValueError, "Native values must be text or null")
    if any(isinstance(value, str) and len(value) > 100_000 for value in values.values()):
        raise explained(ValueError, "Native values exceed the supported text limit")
    confirmed_now = set(confirm or [])
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        run = c.execute("SELECT approval, input FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise KeyError(run_id)
        if run["approval"]:
            raise explained(work.RevisionConflict, "The approved result is frozen")
        item = next((i for i in json.loads(run["input"])["items"] if i["item_id"] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        if not native_results.native_item(run_id, item, c):
            raise explained(ValueError, "Native corrections require a native document result")
        publication = native_publication(run_id, item_id, expected_result_version=expected_result_version, c=c)
        if publication.interpretation_outcome.status != "succeeded":
            raise explained(work.NotReady, "An unsuccessful interpretation has no facts to correct")
        previous = current(run_id, item_id, c)
        if previous["revision"] != expected_revision:
            raise explained(work.RevisionConflict, "The correction changed; your draft has not been saved")
        facts = {fact.fact_id: fact for fact in native_results.machine_facts(publication, c=c)}
        unknown = (set(values) | set(native_sources) | confirmed_now) - set(facts)
        if unknown:
            raise explained(ValueError, "Unknown native fact identifier")
        if set(native_sources) - set(values):
            raise explained(ValueError, "Manual sources require a matching value override")
        validated_sources = native_results.validate_sources(publication, native_sources, c=c)
        native_sources = {key: [cite.model_dump(mode="json") for cite in citations]
                          for key, citations in validated_sources.items()}
        effective = {key: values.get(key, fact.proposal.value) for key, fact in facts.items()}
        confirmed = {key: value for key, value in previous["confirmed"].items()
                     if key in effective and effective[key] == value
                     and previous["native_sources"].get(key) == native_sources.get(key)}
        confirmed.update({key: effective[key] for key in confirmed_now})
        c.execute("INSERT INTO run_item_corrections(run_id,item_id,revision,fields,actor,note,created_at,"
                  "native_sources,result_version,confirmed) VALUES (?,?,?,?,?,?,?,?,?,?)",
                  (run_id, item_id, expected_revision + 1, json.dumps(values, ensure_ascii=False, sort_keys=True),
                   actor, note, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   json.dumps(native_sources, ensure_ascii=False, sort_keys=True), publication.result_version,
                   json.dumps(confirmed, ensure_ascii=False, sort_keys=True)))
    # Native confirmations are value decisions, not a resolution of reading gaps or unsupported claims.
    return current(run_id, item_id)


@store.one_connection
def item_result(run_id: str, item_id: str) -> dict[str, Any]:
    """The result of one item: the machine data, the correction and the two merged (the correction wins)."""
    run = work_runs.get_run(run_id)
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id), None)
    if item is None:
        raise KeyError(item_id)
    engine = work_readiness.run_engine(run)  # 160-D: the engine of the run that produced the result shown
    if native_results.native_item(run_id, item):  # 120: a continuing PDF too, by its publication
        return {**_native_item_result(run, item), "engine": engine}
    if (own := item_kinds.handler(item)) is not None:  # 048 T2 (185: the email domain's): no extraction or page image
        result = own.result(run, item, engine)
        # 192: what other domains add to this kind's item (the quote request under an email), by name
        parts = {p.name: built for p in item_kinds.item_parts(item["kind"]) if (built := p.build(run, item)) is not None}
        return {**result, "parts": parts} if parts else result
    dp = datapoints_row(run_id, item_id)
    corr = current(run_id, item_id)
    machine = (dp or {}).get("datapoints") or {}
    layer = layer_for(dp)
    source = {"layer_id": layer.layer_id, "text_source": layer.text_source, "pages": [p.model_dump() for p in layer.pages]} if layer else None
    effective = package_result.effective_values(machine, corr["fields"])
    pack = typepack.get(dp["doc_type"]) if dp else None
    lists = {f: {"columns": list_columns(pack, f, machine.get(f))} for f, k in pack.fields.items() if k == "list"} if pack else {}
    simple = {f for f, k in pack.fields.items() if k != "list"} if pack else set()
    reasons = work_runs.item_reasons(run_id, item_id)
    from jav import isolated_pdf, page_image

    src = work.source_file(item)  # the source instance if the item has one
    kind = item_kinds.of(item)  # 136: a statement read from a tabular export has no page image (177: the kind says)
    try:
        n_pages = page_image.page_count(src) if src.is_file() and kind.page_image else None
    except (OSError, RuntimeError, isolated_pdf.PdfReaderError, isolated_pdf.PdfReaderLimit):
        # a damaged PDF (in-process pypdfium: RuntimeError) or one over the isolated reader's limits (077): the word
        # layer's page count is used
        n_pages = None
    return {"run_id": run_id, "item_id": item_id, "kind": kind.name, "page_count": n_pages,
            "extraction": dp, "correction": corr, "engine": None if kind.by_code else engine,  # 136: a statement read by code
            "effective": effective, "lists": lists,
            # 081: the field kinds, so the UI shows amounts and quantities for editing the Hungarian way ("35,56")
            "kinds": {f: k for f, k in pack.fields.items() if k != "list"} if pack else {},
            "checks": effective_checks(pack, effective) if pack and pack.validators else [],
            "provenance": effective_provenance(dp, corr, layer), "source": source,
            # whether the document is shown from the copy kept when it was added, and the original file's state since
            "source_file": {"copy": bool(item.get("instance")), "original": work.original_state(item, verify=True)},
            "open_reasons": _with_fields(reasons["run"], simple),
            "earlier_open_reasons": _with_fields(reasons["earlier"], simple),
            # 126, 139 (185: the finance domain's parts, `item_kinds.record_parts`): the document's duplicate pairs, and
            # the statement that replaced this one, the ones it replaced and the undecided ones of the same days
            **{part.name: part.build(item_id, reasons["run"] + reasons["earlier"]) for part in item_kinds.record_parts()}}


def insert_revision(run_id: str, item_id: str, fields: dict[str, Any], expected_revision: int, actor: str, note: str | None,
                    sources: dict[str, list[int]] | None, confirmed: dict[str, Any] | None = None) -> None:
    """A new correction version, checked against the run's approval and the version the person saw, in one writing
    transaction. 185: public, an item kind's own correction writes through it (`item_kinds.ItemHandler`)."""
    with store.connect() as c:
        c.commit()
        c.execute("BEGIN IMMEDIATE")
        # 085 (re-audit A01): the approval is checked again in the writing transaction; a correction checked before a
        # concurrent approval must not be written after it
        run = c.execute("SELECT approval FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is not None and run["approval"]:
            raise explained(work.RevisionConflict, "run {{run_id}} is approved; corrections are frozen", run_id=run_id)
        cur = c.execute("SELECT MAX(revision) m FROM run_item_corrections WHERE run_id=? AND item_id=?",
                        (run_id, item_id)).fetchone()["m"] or 0
        if cur != expected_revision:
            raise explained(work.RevisionConflict, "correction of {{item_id_12}} is at revision {{cur}}, not {{expected_revision}}",
                            item_id_12=item_id[:12], cur=cur, expected_revision=expected_revision)
        c.execute("INSERT INTO run_item_corrections(run_id, item_id, revision, fields, actor, note, created_at, sources, confirmed)"
                  " VALUES (?,?,?,?,?,?,?,?,?)",
                  (run_id, item_id, cur + 1, json.dumps(fields, ensure_ascii=False, sort_keys=True), actor, note,
                   datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(sources, sort_keys=True) if sources else None,
                   json.dumps(confirmed, ensure_ascii=False, sort_keys=True) if confirmed else None))


def save(run_id: str, item_id: str, *, fields: dict[str, Any], expected_revision: int, actor: str,
         note: str | None = None, sources: dict[str, list[int]] | None = None, confirm: list[str] | None = None) -> dict[str, Any]:
    """Saves a new correction version. `fields` is the complete correction set (anything left out reverts to the machine
    value). `sources`: the words selected on the image per field (045); only for corrected fields, and only words of the
    item's word layer. `confirm` (083): simple fields a person checked; their values are recorded as confirmed and the
    document's open to-dos on them are resolved (this run's and the earlier runs')."""
    sources = dict(sources or {})
    confirm = list(dict.fromkeys(confirm or []))
    run = work_runs.get_run(run_id)
    if run["approval"]:
        raise explained(work.RevisionConflict, "run {{run_id}} is approved; corrections are frozen", run_id=run_id)
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id), None)
    if item is not None and (own := item_kinds.handler(item)) is not None:  # 185: the email domain's correction
        return own.correct(run_id, item, fields=fields, expected_revision=expected_revision, actor=actor, note=note,
                           sources=sources, confirm=confirm)
    dp = datapoints_row(run_id, item_id)
    if dp is None:
        raise explained(work.NotReady, "item {{item_id_12}} has no extraction result in run {{run_id}}",
                        item_id_12=item_id[:12], run_id=run_id)
    pack = typepack.get(dp["doc_type"])
    unknown = sorted(set(fields) - set(pack.record_fields))
    if unknown:
        raise explained(ValueError, "not fields of {{key}}: {{unknown}}", key=pack.key, unknown=unknown)
    fields = read_typed_values(pack, fields, dp.get("datapoints") or {}, current(run_id, item_id)["fields"])
    for name, value in fields.items():
        if pack.kind(name) == "list":
            _check_list(pack, name, value, (dp.get("datapoints") or {}).get(name))
        else:
            _check_value(pack, name, value)
    listed = sorted(f for f in sources if pack.kind(f) == "list")
    if listed:
        raise explained(ValueError, "source selection is not supported for lists: {{listed}}", listed=listed)
    stray = sorted(set(sources) - set(fields))
    if stray:
        raise explained(ValueError, "source selection for fields without a corrected value: {{stray}}", stray=stray)
    if sources:
        layer = layer_for(dp)
        for ids in sources.values():
            grounding.manual(layer, list(ids))  # unknown word or missing layer: ValueError
    simple = {f for f in pack.record_fields if pack.kind(f) != "list"}
    odd = sorted(set(confirm) - simple)
    if odd:
        raise explained(ValueError, "only simple fields of {{key}} can be confirmed: {{odd}}", key=pack.key, odd=odd)
    effective = package_result.effective_values(dp.get("datapoints"), fields)
    # the earlier confirmations whose value did not change stay; the fields confirmed now are added with their value
    confirmed = {f: v for f, v in current(run_id, item_id)["confirmed"].items() if _same_value(effective.get(f), v)}
    confirmed.update({f: effective.get(f) for f in confirm})
    insert_revision(run_id, item_id, fields, expected_revision, actor, note, sources, confirmed)
    if confirm:
        # the run's own to-dos on the confirmed fields, and (the owner's decision, 083) the earlier runs' to-dos on the same
        # fields of the same document: a person has now checked the field; the resolution names the run where it was
        reasons = work_runs.item_reasons(run_id, item_id, item)
        for r in reasons["run"] + reasons["earlier"]:
            f = reason_field(r["reason"], simple)
            if f in confirm:
                work_runs.resolve_reason(r["id"], actor=actor, note="field checked by hand",
                                    resolution={"field": f, "verdict": "confirmed", "value": confirmed[f], "run_id": run_id,
                                                "revision": expected_revision + 1})
    return current(run_id, item_id)
