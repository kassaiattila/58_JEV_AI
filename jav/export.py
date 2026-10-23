"""Run result export (054 K4): CSV / XLSX / JSON from the effective data of the selected run.

Source: the machine data of the run's items merged with the human corrections (`corrections`), with each field's
effective source location (page, source text), whether it was corrected, and the open to-dos, so every number can be
traced back to its source.

Tables:
- `documents`: one row per document, with the type's fields (wide);
- `datapoints`: one row per document × field: value, page, source text, location status, corrected, to-do on the field;
- `line_items`: the rows of the itemised lists, with the page of each row.
On top of these, the XLSX has a separate sheet per type. 180 (plan 170 E7): the parts a domain adds - the duplicate mark
and an invoice's direction as columns of the documents table, the utility cost's sheets and JSON section - come from
the output parts registry (`jav/outputs/parts.py`, registered by `jav/domains/finance/__init__.py`); this module names no domain.

Reuse: the legacy project's `orchestrator/framework/tabular.py` helpers (sheet-name cleaning, header formatting,
BOM + CRLF CSV) and the formula guard of `ui/src/utils/csv.ts` are ported; the old database loader is not (we read
from SQLite).
Formula guard: in the CSV, text starting with `=`, `+`, `-`, `@`, TAB or CR gets a leading `'` (a number is not text
and stays as it is); in the XLSX every text is written as text, never as a formula.
"""

from __future__ import annotations

import csv
import io
import json
import re
import threading
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jav import corrections, item_kinds, native_results, package_result, typepack, work_runs
from jav.core import card_numbers, cfg, store
from jav.outputs import builtin, contract, parts

NUMBER = re.compile(r"^-?\d[\d\s.,]*$")


# --- the run's records ---------------------------------------------------------------------------------------


def run_records(run_id: str) -> list[dict[str, Any]]:
    """Effective data of the run's documents with source locations. Email items are skipped (they have no extracted
    data); for an email attachment, `source_email` is the email's subject (058 K5.2: the attachment's origin)."""
    with store.session():  # 061: one connection for the queries of all items
        return _run_records(run_id)


# 153 (review B3): an item's source locations kept until its machine result or its correction changes. During a large
# run every finished item rebuilt every document's locations (the word layer and its grounding index: about 0.9 s of a
# 468-document run's 1.1 s), and the word-layer cache holds fewer layers than such a run has.
_provenance: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
_provenance_lock = threading.Lock()
_PROVENANCE_MAX = 5000


def _item_provenance(run_id: str, item_id: str, dp: dict[str, Any], corr: dict[str, Any]) -> dict[str, Any]:
    key = (str(store.active_path()), run_id, item_id, dp.get("run_id"), dp.get("created_at"), corr.get("revision"),
           corr.get("created_at"))
    with _provenance_lock:
        hit = _provenance.get(key)
        if hit is not None:
            _provenance.move_to_end(key)
            return hit
    prov = corrections.effective_provenance(dp, corr, corrections.layer_for(dp))
    with _provenance_lock:
        _provenance[key] = prov
        while len(_provenance) > _PROVENANCE_MAX:
            _provenance.popitem(last=False)
    return prov


def _run_records(run_id: str) -> list[dict[str, Any]]:
    run = work_runs.get_run(run_id)
    subjects = _parent_labels(run["input"]["items"])
    split = work_runs.items_reasons(run_id, run["input"]["items"])  # 153 (review B3): one query, not one per item
    out = []
    for item in work_runs.released_items(run):  # 160-C: not the items removed from the package (decision 163 D7)
        if not item_kinds.of(item).record:  # 177: an email has no document record
            continue
        dp = corrections.datapoints_row(run_id, item["item_id"])
        if dp is None:
            continue
        corr = corrections.current(run_id, item["item_id"])
        effective = package_result.effective_values(dp.get("datapoints"), corr["fields"])
        prov = _item_provenance(run_id, item["item_id"], dp, corr)
        pack = typepack.get(dp["doc_type"])
        reasons = [r["reason"] for r in split[item["item_id"]]["run"]]
        out.append({
            "item_id": item["item_id"], "file": Path(item["source_path"]).name, "doc_type": dp["doc_type"], "arm": dp.get("arm"),
            "final_status": dp.get("final_status"),
            "fields": {f: effective.get(f) for f in pack.header_fields},
            "kinds": {f: pack.kind(f) for f in pack.fields},
            "lists": {f: effective.get(f) or [] for f in pack.fields if pack.kind(f) == "list"},
            "provenance": {f: {k: v for k, v in (p or {}).items() if k in ("status", "page", "quote", "method", "multiple")}
                           for f, p in prov.items() if (p or {}).get("status") != "list"},
            "row_pages": {f: [r.get("page") for r in (p.get("rows") or [])] for f, p in prov.items() if (p or {}).get("status") == "list"},
            "pages": {f: (p or {}).get("page") for f, p in prov.items()},
            "corrected": sorted(corr["fields"]),
            "open_reasons": reasons,
            "source_email": subjects.get(item.get("parent_item_id") or ""),
        })
    for part in parts.record_marks():  # 126: the duplicate mark (180: the finance domain's, `jav/domains/finance/__init__.py`)
        part.mark(out)
    return out


def native_records(run_id: str) -> list[dict[str, Any]]:
    """Native review data, including empty or unsuccessful outcomes and original machine proposals."""
    return [{"file": Path(item["source_path"]).name, **corrections.item_result(run_id, item["item_id"])}
            for item in work_runs.released_items(work_runs.get_run(run_id))
            if native_results.native_item(run_id, item)]


NATIVE_COLUMNS = ("file", "item_id", "fact_id", "entity", "property", "effective_value", "source", "unit", "role",
                  "related_entity", "machine_state", "machine_grounding", "corrected", "confirmed", "source_citations",
                  "reading_status", "reading_gaps", "interpretation_status", "correctness", "result_version", "proposal")
NATIVE_HEAD = ("Document", "Item identifier", "Fact identifier", "Entity", "Property", "Value", "Source", "Unit", "Role",
               "Related entity", "Machine claim", "Machine grounding", "Corrected", "Confirmed", "Source citations",
               "Reading status", "Reading gaps", "Interpretation status", "Correctness", "Result version", "Original proposal")


def _citation_place(citation: dict[str, Any]) -> str:
    """120: a short, language-neutral place of a citation (`Sheet1!B4`, `p. 2`, a pilcrow and the block number); the
    full locator stays in the technical `source_citations` column."""
    loc = citation.get("locator") or {}
    kind = loc.get("kind")
    if kind == "cell":
        return f"{loc['sheet']}!{loc['cell']}"
    if kind == "sheet":
        return str(loc["sheet"])
    if kind == "pdf":
        return f"p. {loc['page']}"
    if kind == "word":
        return f"\u00b6 {loc['block_index'] + 1}"
    if kind == "image":
        return f"img {loc.get('frame', 1)}"
    span = citation.get("quote_span") or loc
    return f"{span['start']}\u2013{span['end']}" if "start" in span else ""


def _source_text(citations: list[dict[str, Any]], limit: int = 80) -> str:
    """120: the cited text with its place, one citation per line, for reading the table without the JSON."""
    lines = []
    for citation in citations:
        quote = " ".join(str(citation.get("quote") or "").split())
        quote = quote if len(quote) <= limit else quote[: limit - 1] + "\u2026"
        place = _citation_place(citation)
        lines.append(f"{quote} [{place}]" if place else quote)
    return "\n".join(lines)


def native_facts_table(records: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    """One native fact per row; text and null remain distinct in the full JSON export."""
    rows = []
    for record in records:
        gaps = json.dumps(record["reading"]["results"], ensure_ascii=False, sort_keys=True)
        for fact in record["native_facts"]:
            proposal = fact["proposal"]
            rows.append([record["file"], record["item_id"], fact["fact_id"], proposal["entity"], proposal["property"],
                         fact["effective_value"], _source_text(fact["native_citations"]), proposal["unit"],
                         proposal["role"], proposal["related_entity"],
                         proposal["state"], fact["grounding"], fact["fact_id"] in record["correction"]["fields"],
                         fact["confirmed"], json.dumps(fact["native_citations"], ensure_ascii=False, sort_keys=True),
                         record["reading"]["status"], gaps, record["interpretation_outcome"]["status"],
                         (record["interpretation"] or {}).get("correctness"), record["result_version"],
                         json.dumps(proposal, ensure_ascii=False, sort_keys=True)])
    return list(NATIVE_HEAD), rows


def _parent_labels(items: list[dict[str, Any]]) -> dict[str, str]:
    """The label of each item an attachment came from (185: its kind's handler, the email's subject; until then
    `_email_subjects`)."""
    out: dict[str, str] = {}
    for own in item_kinds.handlers():
        out.update(own.parent_labels(items))
    return out


def _field_reason(reasons: list[str], field: str) -> bool:
    return any(len(r.split(":")) > 2 and r.split(":")[2] == field for r in reasons)


# --- tables ----------------------------------------------------------------------------------------------------

# the documents table's general columns; the columns a domain adds follow them (`document_head`, `document_columns`)
DOC_HEAD = ["Irat", "Tétel-azonosító", "Típus", "Út", "Állapot", "Nyitott teendők", "Forrás-levél"]


def document_head() -> list[str]:
    """The documents table's fixed headers: the general ones, then each domain part's (180: the duplicate mark and the
    direction, `jav/domains/finance/__init__.py`); the type's fields follow them."""
    return DOC_HEAD + [c.head for part in parts.document_columns() for c in part.columns]


def document_columns() -> tuple[str, ...]:
    """The column keys of `document_head`, in the same order."""
    return DOC_COLUMNS + tuple(c.key for part in parts.document_columns() for c in part.columns)


def _doc_row(r: dict[str, Any]) -> list[Any]:
    return [r["file"], r["item_id"], r["doc_type"], r["arm"], r["final_status"], "; ".join(r["open_reasons"]),
            r.get("source_email") or ""]


def documents_table(records: list[dict[str, Any]], doc_type: str | None = None) -> tuple[list[str], list[list[Any]]]:
    """One row per document; the fields are the union of the types' fields (in order of first appearance)."""
    recs = [r for r in records if doc_type is None or r["doc_type"] == doc_type]
    fields: list[str] = []
    for r in recs:
        fields += [f for f in r["fields"] if f not in fields]
    added = [part.values(recs) for part in parts.document_columns()]  # one value tuple per record, per part
    rows = [_doc_row(r) + [v for values in added for v in values[i]] + [r["fields"].get(f) for f in fields]
            for i, r in enumerate(recs)]
    return document_head() + fields, rows


DATAPOINT_HEAD = ("Irat", "Tétel-azonosító", "Típus", "Mező", "Érték", "Oldal", "Forrásszöveg", "Hely", "Javítva", "Teendő a mezőn")
LINE_HEAD = ("Irat", "Tétel-azonosító", "Típus", "Lista", "Sor", "Oldal")
LIST_VALUE = "érték"  # the column of a list whose rows are single values


def datapoints_table(records: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    head = list(DATAPOINT_HEAD)
    rows = []
    for r in records:
        for f, v in r["fields"].items():
            p = r["provenance"].get(f) or {}
            rows.append([r["file"], r["item_id"], r["doc_type"], f, v, p.get("page"), p.get("quote"), p.get("status"),
                         "igen" if f in r["corrected"] else "", "igen" if _field_reason(r["open_reasons"], f) else ""])
    return head, rows


def line_items_table(records: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    cols: list[str] = []
    for r in records:
        for rows in r["lists"].values():
            for row in rows:
                cols += [c for c in (row if isinstance(row, dict) else {LIST_VALUE: row}) if c not in cols]
    head = list(LINE_HEAD) + cols
    out = []
    for r in records:
        for lst, rows in r["lists"].items():
            pages = r["row_pages"].get(lst) or []
            for i, row in enumerate(rows):
                row = row if isinstance(row, dict) else {LIST_VALUE: row}
                out.append([r["file"], r["item_id"], r["doc_type"], lst, i + 1, pages[i] if i < len(pages) else None]
                           + [row.get(c) for c in cols])
    return head, out


def _masked_table(build: Any) -> Any:
    """153 (review C4): a table's text cells with full card numbers masked (data saved before the masking at saving)."""
    def table(records: list[dict[str, Any]], *args: Any, **kwargs: Any) -> tuple[list[str], list[list[Any]]]:
        head, rows = build(records, *args, **kwargs)
        return head, [[card_numbers.mask_text(v) if isinstance(v, str) else v for v in row] for row in rows]
    return table


documents_table = _masked_table(documents_table)
datapoints_table = _masked_table(datapoints_table)
line_items_table = _masked_table(line_items_table)
native_facts_table = _masked_table(native_facts_table)  # 160 (review S-2): its CSV, Excel sheet and dataset too

TABLES = {"documents": documents_table, "datapoints": datapoints_table, "line_items": line_items_table}


# --- CSV -------------------------------------------------------------------------------------------------------


def _safe_text(v: Any) -> str:
    if v is None:
        return ""
    s = str(v)
    prefixes = tuple(cfg.load("reports")["export"]["formula_prefixes"])
    # 153 (review C8): a spreadsheet also reads a formula after leading spaces or line breaks (" =1+1")
    if s.lstrip(" \t\r\n").startswith(prefixes) and not NUMBER.match(s):
        return "'" + s  # guards against formula injection (OWASP CSV injection; the rule of the legacy csv.ts)
    return s


def csv_bytes(head: list[str], rows: list[list[Any]]) -> bytes:
    """With a UTF-8 BOM, `;` as separator and CRLF line endings: Hungarian Excel then opens it split into columns."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=cfg.load("reports")["export"]["csv_delimiter"], lineterminator="\r\n")
    w.writerow([_safe_text(h) for h in head])  # 153 (review C8): the header row is guarded too
    for row in rows:
        w.writerow([_safe_text(v) for v in row])
    return b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8")


# --- XLSX ------------------------------------------------------------------------------------------------------


# 178 (plan 170 L4): the column keys of the result's tables (`configs/outputs.json` `package_result`), in the order of
# their headers
NATIVE_READING_COLUMNS = ("file", "item_id", "reading_status", "interpretation_status", "result_version", "reading_details")
NATIVE_READING_HEAD = ("Document", "Item identifier", "Reading status", "Interpretation status", "Result version", "Reading details")
DOC_COLUMNS = ("file", "item_id", "doc_type", "arm", "status", "open_reasons", "source_email")
DATAPOINT_COLUMNS = ("file", "item_id", "doc_type", "field", "value", "page", "quote", "location", "corrected", "field_todo")
LINE_COLUMNS = ("file", "item_id", "doc_type", "list", "row", "page")
_table = contract.table


def item_rows(run_id: str) -> dict[str, list[dict[str, Any]]]:
    """185 (plan G-full-move T1e): each item kind's part of the run's result (the emails), by its name."""
    return {part.name: part.read(run_id) for part in parts.item_parts()}


def xlsx_bytes(run_id: str, records: list[dict[str, Any]] | None = None) -> bytes:
    records = run_records(run_id) if records is None else records
    return workbook_bytes(records, item_rows(run_id), native_records(run_id))


def result_data(records: list[dict[str, Any]], items: Mapping[str, list[dict[str, Any]]], native: list[dict[str, Any]],
                values: tuple[contract.Value, ...] = ()) -> contract.OutputData:
    """178 (plan 170 L4): the result's data as the output contract describes it (`package_result`): the native facts and
    readings, each item kind's part (185: `items`, by the part's name; the emails and their tasks, `jav/domains/email/email_export.py`),
    the documents by type, the data points, the line items, then each domain's result part (180: the utility cost's
    sheets and its grand total, `jav/domains/finance/__init__.py`); `values`: the package's (`package_values`)."""
    tables: list[contract.Table] = []
    if native:
        head, rows = native_facts_table(native)
        tables.append(_table("native_facts", "Native facts", NATIVE_COLUMNS, head, rows))
        tables.append(_table("native_readings", "Native readings", NATIVE_READING_COLUMNS, NATIVE_READING_HEAD,
                             [[record["file"], record["item_id"], record["reading"]["status"],
                               record["interpretation_outcome"]["status"], record["result_version"],
                               json.dumps(record["reading"], ensure_ascii=False, sort_keys=True)] for record in native]))
    lead = [(part, items.get(part.name) or []) for part in parts.item_parts()]
    for part, rows in lead:  # 058 K5.1, K5.3: the email items and their tasks on their own sheets
        if rows:
            tables += part.data(rows)
    if any(rows for _part, rows in lead) and not records:  # emails only: no empty document sheet
        return contract.OutputData("package_result", values, tuple(tables))
    for doc_type in sorted({r["doc_type"] for r in records}):
        head, rows = documents_table(records, doc_type)
        kinds = next(r["kinds"] for r in records if r["doc_type"] == doc_type)
        fixed = document_columns()
        fields = head[len(fixed):]
        tables.append(_table("documents", doc_type, fixed + tuple(fields), head, rows,
                             [None] * len(fixed) + [kinds.get(h) for h in fields], part=doc_type))
    head, rows = datapoints_table(records)
    tables.append(_table("datapoints", "Adatpontok", DATAPOINT_COLUMNS, head, rows))
    head, rows = line_items_table(records)
    list_kinds: dict[str, str] = {}
    for r in records:
        pack = typepack.get(r["doc_type"])
        for lf in pack.list_fields.values():
            for c, k in lf.items():
                list_kinds.setdefault(c, k)
    tables.append(_table("line_items", "Tételsorok", LINE_COLUMNS + tuple("value" if c == LIST_VALUE else c for c in head[6:]), head, rows,
                         [None] * 6 + [list_kinds.get(h) for h in head[6:]]))
    added: list[contract.Value] = []
    for part in parts.result_parts():
        part_tables, part_values = part.data(records)
        tables += part_tables
        added += part_values
    return contract.OutputData("package_result", (*values, *added), tuple(tables))


def package_values(wp: dict[str, Any], version: dict[str, Any] | None = None) -> tuple[contract.Value, ...]:
    """178: the package's values of an output: its name, and for a released version its number, who released it and
    when (empty for the current result)."""
    v = version or {}
    at = (v.get("released_at") or "")[:16].replace("T", " ")
    return (contract.Value("package", "Csomag", wp["name"]), contract.Value("version", "Változat", str(v.get("version") or "")),
            contract.Value("released_by", "Kiadta", v.get("released_by") or ""), contract.Value("released_at", "Kiadva", at))


def workbook_bytes(records: list[dict[str, Any]], items: Mapping[str, list[dict[str, Any]]], native: list[dict[str, Any]]) -> bytes:
    """The download workbook of documents, emails and native results (a run's, or a released package version's,
    171: `jav/package_release.py`), in the built-in layout (178: `jav/outputs/builtin.py`)."""
    return builtin.render(result_data(records, items, native))


# --- JSON ------------------------------------------------------------------------------------------------------


def _json_export(run_id: str, records: list[dict[str, Any]] | None = None) -> tuple[bytes, int]:
    from jav import datasets

    # Capture before every data read: an interleaved edit must make approval fail,
    # never give older exported values the version of an unseen correction.
    review_version = corrections.review_version(run_id)
    run = work_runs.get_run(run_id)
    native_run = any(native_results.native_item(run_id, item) for item in run["input"]["items"])
    # Caller-supplied rows have no bound version. A native or mixed export must
    # reload them after the version capture, using the versioned dataset cache.
    records = datasets.run_records(run_id) if records is None or native_run else records
    body = {"run_id": run_id, "recipe_id": run["recipe_id"], "recipe_version": run["recipe_version"], "params": run["params"],
            "mode": run["mode"], "approval": run["approval"], "created_at": run["created_at"],
            "documents": [{k: v for k, v in r.items() if k != "kinds"} for r in records],
            **{part.json_key: part.read(run_id) for part in parts.item_parts()},  # 185: the emails
            **json_parts(records)}
    native = native_records(run_id)
    if native:
        body["native_items"] = native
        body["review_version"] = review_version
    body = card_numbers.mask_values(body)  # 160 (review S-2): a native result, and data saved before the masking of 153
    return json.dumps(body, ensure_ascii=False, indent=1, default=str).encode("utf-8"), len(records)


def json_parts(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Each domain's section of a result's JSON, after its emails (180: the utility cost, `jav/domains/finance/__init__.py`)."""
    return {part.json_key: part.json(records) for part in parts.result_parts()}


def json_bytes(run_id: str, records: list[dict[str, Any]] | None = None) -> bytes:
    return _json_export(run_id, records)[0]


def render(run_id: str, fmt: str, table: str = "documents") -> tuple[bytes, str, str, int]:
    """(content, media type, file name, row count): what the service's download endpoint returns."""
    from jav import datasets

    if fmt == "json":
        content, count = _json_export(run_id)
        return content, "application/json", f"{run_id}.json", count
    records = datasets.run_records(run_id)  # 056: cache shared with the tables and the utility report
    if fmt == "csv":
        head, rows = native_facts_table(native_records(run_id)) if table == "native_facts" else TABLES[table](records)
        return csv_bytes(head, rows), "text/csv; charset=utf-8", f"{run_id}-{table}.csv", len(rows)
    if fmt == "xlsx":
        return (xlsx_bytes(run_id, records), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                f"{run_id}.xlsx", len(records))
    raise ValueError(f"unknown export format: {fmt}")


__all__ = ["TABLES", "csv_bytes", "datapoints_table", "document_columns", "document_head", "documents_table", "item_rows",
           "json_bytes", "json_parts", "line_items_table", "render", "result_data", "run_records", "workbook_bytes", "xlsx_bytes"]
