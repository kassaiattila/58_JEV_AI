"""Field correction on a run item (040 K2): the value corrected by a person, versioned, never silently overwritten.

A correction belongs to the run's result (run + item) and does not rewrite the machine-extracted data: the original
stays in the `datapoints` row, and the correction is a separate version series. Saving requires `expected_revision`;
if someone else saved in the meantime, `work.RevisionConflict` is raised (409 in the UI, where the client keeps its
working copy). Correcting an approved run is forbidden.

Validation on save: only fields of the item's type pack can be corrected; a money field must parse as a `Decimal`, a
date field as an ISO date (number and format checks happen in code, CLAUDE.md §4).

Itemised list (048 T1-lista): correcting a `list` field replaces the whole list (deleting and adding rows too), each
cell validated by the kind and enumerated values of its line-item field. The pack's checks (e.g. the running balance
of a statement) also run on the corrected data in the item result (`checks`), in code, without any paid call.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from jav import grounding, source_layer, store, typepack, validators, work

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


def current(run_id: str, item_id: str) -> dict[str, Any]:
    """The latest correction (version 0 = no correction yet)."""
    with store.connect() as c:
        row = c.execute("SELECT * FROM run_item_corrections WHERE run_id=? AND item_id=? ORDER BY revision DESC LIMIT 1",
                        (run_id, item_id)).fetchone()
    if row is None:
        return {"run_id": run_id, "item_id": item_id, "revision": 0, "fields": {}, "sources": {}, "actor": None, "note": None,
                "created_at": None}
    return {**dict(row), "fields": json.loads(row["fields"]), "sources": json.loads(row["sources"] or "{}")}


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
                             enums={k: list(v) for k, v in pack.enums.items()})
    lists = [f for f, k in pack.fields.items() if k == "list"]
    out = []
    for r in validators.run_checks(rec, pack.validators):
        entry: dict[str, Any] = r.model_dump()
        rows = sorted({int(n) for n in _LINE.findall(r.detail or "")})  # 053: a line check may name several rows
        if rows and not r.ok and len(lists) == 1:
            entry["rows"] = {lists[0]: rows}
        out.append(entry)
    return out


def item_result(run_id: str, item_id: str) -> dict[str, Any]:
    """The result of one item: the machine data, the correction and the two merged (the correction wins)."""
    run = work.get_run(run_id)
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id), None)
    if item is None:
        raise KeyError(item_id)
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
    from jav import isolated_pdf, page_image

    src = Path(item["source_path"])
    try:
        n_pages = page_image.page_count(src) if src.is_file() else None
    except (OSError, RuntimeError, isolated_pdf.PdfReaderError, isolated_pdf.PdfReaderLimit):
        # a damaged PDF (in-process pypdfium: RuntimeError) or one over the isolated reader's limits (077): the word
        # layer's page count is used
        n_pages = None
    return {"run_id": run_id, "item_id": item_id, "kind": "document", "page_count": n_pages, "extraction": dp, "correction": corr,
            "effective": effective, "lists": lists,
            "checks": effective_checks(pack, effective) if pack and pack.validators else [],
            "provenance": effective_provenance(dp, corr, layer), "source": source,
            "open_reasons": work.item_reasons(run_id, item_id)["run"],
            "earlier_open_reasons": work.item_reasons(run_id, item_id)["earlier"]}


def _insert_revision(run_id: str, item_id: str, fields: dict[str, Any], expected_revision: int, actor: str, note: str | None,
                     sources: dict[str, list[int]] | None) -> None:
    with store.connect() as c:
        c.commit()
        c.execute("BEGIN IMMEDIATE")
        cur = c.execute("SELECT MAX(revision) m FROM run_item_corrections WHERE run_id=? AND item_id=?",
                        (run_id, item_id)).fetchone()["m"] or 0
        if cur != expected_revision:
            raise work.RevisionConflict(f"correction of {item_id[:12]} is at revision {cur}, not {expected_revision}")
        c.execute("INSERT INTO run_item_corrections(run_id, item_id, revision, fields, actor, note, created_at, sources)"
                  " VALUES (?,?,?,?,?,?,?,?)",
                  (run_id, item_id, cur + 1, json.dumps(fields, ensure_ascii=False, sort_keys=True), actor, note,
                   datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(sources, sort_keys=True) if sources else None))


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
         note: str | None = None, sources: dict[str, list[int]] | None = None) -> dict[str, Any]:
    """Saves a new correction version. `fields` is the complete correction set (anything left out reverts to the machine
    value). `sources`: the words selected on the image per field (045); only for corrected fields, and only words of the
    item's word layer."""
    sources = dict(sources or {})
    run = work.get_run(run_id)
    if run["approval"]:
        raise work.RevisionConflict(f"run {run_id} is approved; corrections are frozen")
    item = next((i for i in run["input"]["items"] if i["item_id"] == item_id), None)
    if item is not None and item.get("kind") == "email":
        return _save_email(run_id, item, fields=fields, expected_revision=expected_revision, actor=actor, note=note, sources=sources)
    dp = datapoints_row(run_id, item_id)
    if dp is None:
        raise work.NotReady(f"item {item_id[:12]} has no extraction result in run {run_id}")
    pack = typepack.get(dp["doc_type"])
    unknown = sorted(set(fields) - set(pack.record_fields))
    if unknown:
        raise ValueError(f"not fields of {pack.key}: {unknown}")
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
    _insert_revision(run_id, item_id, fields, expected_revision, actor, note, sources)
    return current(run_id, item_id)
