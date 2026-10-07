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
from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from jav import dates, grounding, native_results, numbers, source_layer, store, typepack, validators, work
from jav.native_contracts import Publication

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
    cols = {r[1] for r in conn.execute("PRAGMA table_info(run_item_corrections)")}
    if cols and "sources" not in cols:  # 045: field -> ids of the words selected on the image
        conn.execute("ALTER TABLE run_item_corrections ADD COLUMN sources TEXT")
    if cols and "confirmed" not in cols:  # 083: field -> the value a person confirmed
        conn.execute("ALTER TABLE run_item_corrections ADD COLUMN confirmed TEXT")
    if cols and "native_sources" not in cols:
        conn.execute("ALTER TABLE run_item_corrections ADD COLUMN native_sources TEXT")
    if cols and "result_version" not in cols:
        conn.execute("ALTER TABLE run_item_corrections ADD COLUMN result_version TEXT")


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
    flow runs of a run are `<run_id>:<item_id>`). A run without task decisions keeps the version computed as before."""
    query = "SELECT item_id, MAX(revision) r FROM run_item_corrections WHERE run_id=? GROUP BY item_id ORDER BY item_id"
    tasks_query = ("SELECT run_id, task_index, decision FROM email_task_decisions WHERE substr(run_id, 1, ?) = ?"
                   " ORDER BY run_id, task_index")
    prefix = f"{run_id}:"
    if c is None:
        with store.connect() as own:
            rows = own.execute(query, (run_id,)).fetchall()
            decisions = own.execute(tasks_query, (len(prefix), prefix)).fetchall()
            native = native_results.version_parts(run_id, own)
    else:
        rows = c.execute(query, (run_id,)).fetchall()
        decisions = c.execute(tasks_query, (len(prefix), prefix)).fetchall()
        native = native_results.version_parts(run_id, c)
    payload: Any = [[r["item_id"], r["r"]] for r in rows]
    if decisions:
        payload = {"corrections": payload, "tasks": [[d["run_id"], d["task_index"], d["decision"]] for d in decisions]}
    if native:
        payload = {"review": payload, "native": native}
    return hashlib.sha256(json.dumps(payload).encode("utf-8")).hexdigest()[:16]


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


def reason_field(code: str, fields: set[str]) -> str | None:
    """083: the simple field a to-do is about, or None when it is about the document (or a line item). The field stands
    third in most codes (`pick:low_conf:payment_iban:0.53`) and first in a parse error (`meter_reading_start:unparseable`);
    only a simple field of the item's type pack counts."""
    parts = code.split(":")
    for part in (parts[2] if len(parts) > 2 else None, parts[0]):
        if part in fields:
            return part
    return None


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


def _typed_value(kind: str, value: Any, known: set[str]) -> Any:
    """081: a typed amount or quantity by the Hungarian habit (`numbers.read_input`), as canonical text ("28000"); 084: a
    typed date by the shared date reader (`dates.read_date_input`), as an ISO date. A value sent back unchanged (the
    machine value or the previous correction, already canonical) is kept as it is."""
    if kind not in ("money", "number", "date") or value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and kind != "date":
        return str(value)
    if not isinstance(value, str) or value in known or not value.strip():
        return value
    if kind == "date":
        return dates.read_date_input(value)
    return numbers.read_input(value, kind=kind)  # type: ignore[arg-type]


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
            out[name] = _typed_value(kind, value, _known(machine.get(name), previous.get(name)))
            continue
        if not isinstance(value, list):
            out[name] = value
            continue
        cols = {c["name"]: c["kind"] for c in list_columns(pack, name, machine.get(name))}
        rows = []
        for i, row in enumerate(value):
            if "*" in cols:
                rows.append(_typed_value(cols["*"], row, _known(_row_cell(machine.get(name), i, "*"), _row_cell(previous.get(name), i, "*"))))
            elif isinstance(row, dict):
                rows.append({c: _typed_value(cols.get(c, "text"), v, _known(_row_cell(machine.get(name), i, c), _row_cell(previous.get(name), i, c)))
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
        raise ValueError(f"{field}: a single value is expected, not a list")
    _check_cell(field, pack.kind(field), value)


def _check_cell(path: str, kind: str, value: Any, allowed: tuple[Any, ...] | None = None) -> None:
    if value is None:
        return
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise ValueError(f"{path}: the value must be text, an integer or null")
    if kind in ("money", "number"):
        try:
            Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"{path}: not a number: {value!r}") from exc
    elif kind == "date":
        try:
            date.fromisoformat(str(value))
        except ValueError as exc:
            raise ValueError(f"{path}: not an ISO date (YYYY-MM-DD): {value!r}") from exc
    if allowed is not None and value not in allowed:
        raise ValueError(f"{path}: {value!r} is not one of {list(allowed)}")


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
        raise ValueError(f"{field}: a list of rows is expected")
    cols = {c["name"]: c for c in list_columns(pack, field, machine_rows)}
    simple = "*" in cols
    for i, row in enumerate(rows):
        path = f"{field}[{i + 1}]"
        if simple:
            _check_cell(path, cols["*"]["kind"], row, tuple(cols["*"].get("options", ())) or None)
            continue
        if not isinstance(row, dict):
            raise ValueError(f"{path}: a row must be an object of columns")
        unknown = sorted(set(row) - set(cols))
        if unknown:
            raise ValueError(f"{path}: not columns of {field}: {unknown}")
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
        raise work.NotReady("The native result has not been published")
    if expected_result_version is not None and publication.result_version != expected_result_version:
        raise work.RevisionConflict("The native result changed; review the current version")
    native_results.verify_publication(publication, c=c)
    return publication


def _native_item_result(run: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Merge manual values without changing the original proposal or its machine grounding claim."""
    from jav.native_contracts import NativeItemResult

    run_id, item_id = run["run_id"], item["item_id"]
    reasons = work.item_reasons(run_id, item_id, item)
    with store.connect() as c:
        c.execute("BEGIN")
        version = review_version(run_id, c)
        publication = native_results.get_publication(run_id, item_id, c=c)
        corr = current(run_id, item_id, c)
        if publication is not None and corr["revision"] and corr["result_version"] != publication.result_version:
            raise work.RevisionConflict("The correction belongs to a different published result")
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
        raise ValueError("Native corrections require an exact published result version")
    if any(not isinstance(value, str) and value is not None for value in values.values()):
        raise ValueError("Native values must be text or null")
    if any(isinstance(value, str) and len(value) > 100_000 for value in values.values()):
        raise ValueError("Native values exceed the supported text limit")
    confirmed_now = set(confirm or [])
    with store.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        run = c.execute("SELECT approval, input FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            raise KeyError(run_id)
        if run["approval"]:
            raise work.RevisionConflict("The approved result is frozen")
        item = next((i for i in json.loads(run["input"])["items"] if i["item_id"] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        if not native_results.native_item(run_id, item, c):
            raise ValueError("Native corrections require a native document result")
        publication = native_publication(run_id, item_id, expected_result_version=expected_result_version, c=c)
        if publication.interpretation_outcome.status != "succeeded":
            raise work.NotReady("An unsuccessful interpretation has no facts to correct")
        previous = current(run_id, item_id, c)
        if previous["revision"] != expected_revision:
            raise work.RevisionConflict("The correction changed; your draft has not been saved")
        facts = {fact.fact_id: fact for fact in native_results.machine_facts(publication, c=c)}
        unknown = (set(values) | set(native_sources) | confirmed_now) - set(facts)
        if unknown:
            raise ValueError("Unknown native fact identifier")
        if set(native_sources) - set(values):
            raise ValueError("Manual sources require a matching value override")
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


def item_result(run_id: str, item_id: str) -> dict[str, Any]:
    """The result of one item: the machine data, the correction and the two merged (the correction wins)."""
    run = work.get_run(run_id)
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id), None)
    if item is None:
        raise KeyError(item_id)
    if native_results.native_item(run_id, item):  # 120: a continuing PDF too, by its publication
        return _native_item_result(run, item)
    if item.get("kind") == "email":  # 048 T2: email item: no extraction or page image; shows the email and intent
        from jav import mailbox

        reasons = work.item_reasons(run_id, item_id, item)
        corr = current(run_id, item_id)
        # 058 K5.2: the email's attachments that ran as documents in the run (the UI refers to them)
        attachment_items = [{"item_id": i["item_id"], "filename": Path(i["source_path"]).name}
                            for i in run["input"]["items"] if i.get("parent_item_id") == item_id]
        return {"run_id": run_id, "item_id": item_id, "kind": "email", "extraction": None, "correction": corr,
                "effective": {}, "lists": {}, "checks": [], "provenance": {}, "source": None,
                "attachment_items": attachment_items,
                "email": mailbox.email_item_view(item, work.flow_run_id(run_id, item_id), corr["fields"].get("intent")),
                "open_reasons": reasons["run"], "earlier_open_reasons": reasons["earlier"]}
    dp = datapoints_row(run_id, item_id)
    corr = current(run_id, item_id)
    machine = (dp or {}).get("datapoints") or {}
    layer = layer_for(dp)
    source = {"layer_id": layer.layer_id, "text_source": layer.text_source, "pages": [p.model_dump() for p in layer.pages]} if layer else None
    effective = {**machine, **corr["fields"]}
    pack = typepack.get(dp["doc_type"]) if dp else None
    lists = {f: {"columns": list_columns(pack, f, machine.get(f))} for f, k in pack.fields.items() if k == "list"} if pack else {}
    simple = {f for f, k in pack.fields.items() if k != "list"} if pack else set()
    reasons = work.item_reasons(run_id, item_id)
    from jav import isolated_pdf, page_image

    src = work.source_file(item)  # the source instance if the item has one
    try:
        n_pages = page_image.page_count(src) if src.is_file() else None
    except (OSError, RuntimeError, isolated_pdf.PdfReaderError, isolated_pdf.PdfReaderLimit):
        # a damaged PDF (in-process pypdfium: RuntimeError) or one over the isolated reader's limits (077): the word
        # layer's page count is used
        n_pages = None
    return {"run_id": run_id, "item_id": item_id, "kind": "document", "page_count": n_pages, "extraction": dp, "correction": corr,
            "effective": effective, "lists": lists,
            # 081: the field kinds, so the UI shows amounts and quantities for editing the Hungarian way ("35,56")
            "kinds": {f: k for f, k in pack.fields.items() if k != "list"} if pack else {},
            "checks": effective_checks(pack, effective) if pack and pack.validators else [],
            "provenance": effective_provenance(dp, corr, layer), "source": source,
            # whether the document is shown from the copy kept when it was added, and the original file's state since
            "source_file": {"copy": bool(item.get("instance")), "original": work.original_state(item, verify=True)},
            "open_reasons": _with_fields(reasons["run"], simple),
            "earlier_open_reasons": _with_fields(reasons["earlier"], simple)}


def _insert_revision(run_id: str, item_id: str, fields: dict[str, Any], expected_revision: int, actor: str, note: str | None,
                     sources: dict[str, list[int]] | None, confirmed: dict[str, Any] | None = None) -> None:
    with store.connect() as c:
        c.commit()
        c.execute("BEGIN IMMEDIATE")
        # 085 (re-audit A01): the approval is checked again in the writing transaction; a correction checked before a
        # concurrent approval must not be written after it
        run = c.execute("SELECT approval FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is not None and run["approval"]:
            raise work.RevisionConflict(f"run {run_id} is approved; corrections are frozen")
        cur = c.execute("SELECT MAX(revision) m FROM run_item_corrections WHERE run_id=? AND item_id=?",
                        (run_id, item_id)).fetchone()["m"] or 0
        if cur != expected_revision:
            raise work.RevisionConflict(f"correction of {item_id[:12]} is at revision {cur}, not {expected_revision}")
        c.execute("INSERT INTO run_item_corrections(run_id, item_id, revision, fields, actor, note, created_at, sources, confirmed)"
                  " VALUES (?,?,?,?,?,?,?,?,?)",
                  (run_id, item_id, cur + 1, json.dumps(fields, ensure_ascii=False, sort_keys=True), actor, note,
                   datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(sources, sort_keys=True) if sources else None,
                   json.dumps(confirmed, ensure_ascii=False, sort_keys=True) if confirmed else None))


EMAIL_FIELDS = ("intent",)  # 058 K5.1: an email's intent is correctable (the email is the source, not extracted)


def _save_email(run_id: str, item: dict[str, Any], *, fields: dict[str, Any], expected_revision: int, actor: str,
                note: str | None, sources: dict[str, list[int]]) -> dict[str, Any]:
    """Manual correction of an email's intent (versioned, like a document's fields). The corrected intent settles the
    run's own intent to-dos (uncertain / unrecognised intent): the decision closes them; a to-do with another reason
    (e.g. suspicious content) stays open."""
    from jav import intents

    unknown = sorted(set(fields) - set(EMAIL_FIELDS))
    if unknown:
        raise ValueError(f"only {', '.join(EMAIL_FIELDS)} can be corrected on an email: {unknown}")
    if sources:
        raise ValueError("source selection is not supported for emails")
    key = fields.get("intent")
    if key is not None and key not in intents.BY_KEY:
        raise ValueError(f"unknown intent: {key}")
    item_id = item["item_id"]
    _insert_revision(run_id, item_id, fields, expected_revision, actor, note, None)
    if key is not None:
        for r in work.item_reasons(run_id, item_id, item)["run"]:
            if r["reason"].startswith("intent:"):
                work.resolve_reason(r["id"], actor=actor, resolution={"intent": key}, note="a szándék kézzel javítva")
    return current(run_id, item_id)


def save(run_id: str, item_id: str, *, fields: dict[str, Any], expected_revision: int, actor: str,
         note: str | None = None, sources: dict[str, list[int]] | None = None, confirm: list[str] | None = None) -> dict[str, Any]:
    """Saves a new correction version. `fields` is the complete correction set (anything left out reverts to the machine
    value). `sources`: the words selected on the image per field (045); only for corrected fields, and only words of the
    item's word layer. `confirm` (083): simple fields a person checked; their values are recorded as confirmed and the
    document's open to-dos on them are resolved (this run's and the earlier runs')."""
    sources = dict(sources or {})
    confirm = list(dict.fromkeys(confirm or []))
    run = work.get_run(run_id)
    if run["approval"]:
        raise work.RevisionConflict(f"run {run_id} is approved; corrections are frozen")
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id), None)
    if item is not None and item.get("kind") == "email":
        if confirm:
            raise ValueError("fields cannot be confirmed on an email; correct its intent instead")
        return _save_email(run_id, item, fields=fields, expected_revision=expected_revision, actor=actor, note=note, sources=sources)
    dp = datapoints_row(run_id, item_id)
    if dp is None:
        raise work.NotReady(f"item {item_id[:12]} has no extraction result in run {run_id}")
    pack = typepack.get(dp["doc_type"])
    unknown = sorted(set(fields) - set(pack.record_fields))
    if unknown:
        raise ValueError(f"not fields of {pack.key}: {unknown}")
    fields = read_typed_values(pack, fields, dp.get("datapoints") or {}, current(run_id, item_id)["fields"])
    for name, value in fields.items():
        if pack.kind(name) == "list":
            _check_list(pack, name, value, (dp.get("datapoints") or {}).get(name))
        else:
            _check_value(pack, name, value)
    listed = sorted(f for f in sources if pack.kind(f) == "list")
    if listed:
        raise ValueError(f"source selection is not supported for lists: {listed}")
    stray = sorted(set(sources) - set(fields))
    if stray:
        raise ValueError(f"source selection for fields without a corrected value: {stray}")
    if sources:
        layer = layer_for(dp)
        for ids in sources.values():
            grounding.manual(layer, list(ids))  # unknown word or missing layer: ValueError
    simple = {f for f in pack.record_fields if pack.kind(f) != "list"}
    odd = sorted(set(confirm) - simple)
    if odd:
        raise ValueError(f"only simple fields of {pack.key} can be confirmed: {odd}")
    effective = {**(dp.get("datapoints") or {}), **fields}
    # the earlier confirmations whose value did not change stay; the fields confirmed now are added with their value
    confirmed = {f: v for f, v in current(run_id, item_id)["confirmed"].items() if _same_value(effective.get(f), v)}
    confirmed.update({f: effective.get(f) for f in confirm})
    _insert_revision(run_id, item_id, fields, expected_revision, actor, note, sources, confirmed)
    if confirm:
        # the run's own to-dos on the confirmed fields, and (the owner's decision, 083) the earlier runs' to-dos on the same
        # fields of the same document: a person has now checked the field; the resolution names the run where it was
        reasons = work.item_reasons(run_id, item_id, item)
        for r in reasons["run"] + reasons["earlier"]:
            f = reason_field(r["reason"], simple)
            if f in confirm:
                work.resolve_reason(r["id"], actor=actor, note="field checked by hand",
                                    resolution={"field": f, "verdict": "confirmed", "value": confirmed[f], "run_id": run_id,
                                                "revision": expected_revision + 1})
    return current(run_id, item_id)
