"""Run result export (054 K4): CSV / XLSX / JSON from the effective data of the selected run.

Source: the machine data of the run's items merged with the human corrections (`corrections`), with each field's
effective source location (page, source text), whether it was corrected, and the open to-dos, so every number can be
traced back to its source.

Tables:
- `documents`: one row per document, with the type's fields (wide);
- `datapoints`: one row per document × field: value, page, source text, location status, corrected, to-do on the field;
- `line_items`: the rows of the itemised lists, with the page of each row.
On top of these, the XLSX has a separate sheet per type and the utility cost report (`jav/report_utility.py`).

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
from pathlib import Path
from typing import Any

from jav import card_numbers, cfg, corrections, duplicates, item_kinds, native_results, package_result, store, type_roles, typepack, work
from jav.outputs import builtin, contract

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
    run = work.get_run(run_id)
    subjects = _email_subjects(run["input"]["items"])
    split = work.items_reasons(run_id, run["input"]["items"])  # 153 (review B3): one query, not one per item
    out = []
    for item in work.released_items(run):  # 160-C: not the items removed from the package (decision 163 D7)
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
    # 126: the duplicate mark (a confirmed copy or modified version, a suspicion, the documents found different)
    found = duplicates.marks({r["item_id"]: r["open_reasons"] for r in out})
    for r in out:
        r["duplicate"] = found.get(r["item_id"])
    return out


def native_records(run_id: str) -> list[dict[str, Any]]:
    """Native review data, including empty or unsuccessful outcomes and original machine proposals."""
    return [{"file": Path(item["source_path"]).name, **corrections.item_result(run_id, item["item_id"])}
            for item in work.released_items(work.get_run(run_id))
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


def _email_subjects(items: list[dict[str, Any]]) -> dict[str, str]:
    """Subjects of the attachments' parent emails (only if the run has attachments)."""
    from jav.emails import message_version

    parents = {i.get("parent_item_id") for i in items if i.get("parent_item_id")}
    out = {}
    for i in items:
        if i["item_id"] in parents:
            msg, status = message_version(i)  # 086 N04: the version the run processed
            # data (a cell of the download), not a label
            out[i["item_id"]] = ("(a levél futáskori változata nem található)" if status == "changed"
                                 else msg.get("subject") or ("(tárgy nélkül)" if msg else "(a levél nem olvasható)"))
    return out


def email_records(run_id: str) -> list[dict[str, Any]]:
    """058 K5.1: the run's email items: the email's data, the recognised intent with the manual correction, the
    suggested next step (computed in code from the corrected intent), the recognition of the attachments, and how much
    of the email text the recognition saw. For an old run without its own result row, the email's latest result
    (`from_this_run=False`)."""
    from jav import emails, mailbox

    out = []
    items = work.released_items(work.get_run(run_id))  # 160-C: not the items removed from the package (decision 163 D7)
    split = work.items_reasons(run_id, [i for i in items if i.get("kind") == item_kinds.EMAIL])  # 153 (review B3): one query
    for item in items:
        if item.get("kind") != item_kinds.EMAIL:
            continue
        path = Path(item["source_path"])
        msg, source_status = emails.message_version(item)  # 086 N04: the version the run processed, not the latest
        raw, own = mailbox.email_result_for(work.flow_run_id(run_id, item["item_id"]), path.parent.name)
        corr = corrections.current(run_id, item["item_id"])
        res = mailbox.effective_email_result(raw, corr["fields"].get("intent")) if raw is not None else {}
        body = (raw or {}).get("body") if own else None
        if not body:
            body = emails.body_coverage(emails.EmailMessage(message_id=path.parent.name, body=msg.get("body") or ""))
        sender = msg.get("sender_name") or ""
        if msg.get("sender"):
            sender = f"{sender} <{msg['sender']}>" if sender else msg["sender"]
        out.append({"item_id": item["item_id"], "message_id": path.parent.name, "subject": msg.get("subject") or "",
                    "sender": sender, "received_at": msg.get("received_at"), "mailbox": msg.get("mailbox"),
                    "intent": res.get("intent"), "machine_intent": res.get("machine_intent"), "confidence": res.get("confidence"),
                    "corrected": bool(res.get("corrected")), "next_flow": res.get("next_flow"),
                    "attachments": res.get("attachments") or [], "from_this_run": own, "body": body,
                    "open_reasons": [r["reason"] for r in split[item["item_id"]]["run"]],
                    "tasks": mailbox.task_view(work.flow_run_id(run_id, item["item_id"]), raw) if own else None,
                    "source_status": source_status})
    return out


def task_rows(mails: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """058 K5.3: the task proposals, one per row (with the email, the evidence and the human decision)."""
    out = []
    for m in mails:
        for t in (m.get("tasks") or {}).get("tasks") or []:
            d = t.get("decision") or {}
            out.append({"item_id": m["item_id"], "subject": m["subject"], "index": t["index"], "action": t["action"], "title": t["title"],
                        "due_date": t.get("due_date"), "assignee_hint": t.get("assignee_hint"),
                        "evidence": " | ".join(e["quote"] for e in t.get("evidence") or []),
                        "decision": d.get("decision"), "decided_by": d.get("actor"), "decided_at": d.get("decided_at"),
                        "done_by": d.get("done_by"), "done_at": d.get("done_at")})  # 062: manual "done" mark
    return out


EMAIL_HEAD = ["Tárgy", "Feladó", "Érkezett", "Postafiók", "Szándék", "Gépi szándék", "Valószínűség", "Javítva",
              "Javasolt következő lépés", "Csatolmányok", "Levél szövege", "Levél hossza (karakter)", "Nyitott teendők", "Tétel-azonosító"]


def emails_table(records: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    """The email table with Hungarian captions (intent, next step, the part of the text seen, attachment type)."""
    from jav import mailbox

    flows = mailbox.next_flow_labels()
    body = cfg.load("datasets")["labels"]["body_status"]
    doc_types = cfg.load("field_labels")["doc_types"]
    shown = lambda a: a.get("shown_type") or a.get("doc_type")  # noqa: E731 - 126: the type the document was processed as
    att = lambda a: f"{a.get('filename')} ({doc_types.get(shown(a), shown(a)) or a.get('status') or '–'})"  # noqa: E731
    rows = [[r["subject"], r["sender"], r["received_at"], r["mailbox"], mailbox.intent_name(r["intent"]),
             mailbox.intent_name(r["machine_intent"]), r["confidence"], "igen" if r["corrected"] else "",
             flows.get(r["next_flow"] or "", r["next_flow"]), ", ".join(att(a) for a in r["attachments"]),
             body.get(r["body"]["status"], r["body"]["status"]), r["body"]["chars"], "; ".join(r["open_reasons"]), r["item_id"]]
            for r in records]
    return EMAIL_HEAD, rows


def _field_reason(reasons: list[str], field: str) -> bool:
    return any(len(r.split(":")) > 2 and r.split(":")[2] == field for r in reasons)


# --- tables ----------------------------------------------------------------------------------------------------

DOC_HEAD = ["Irat", "Tétel-azonosító", "Típus", "Út", "Állapot", "Nyitott teendők", "Forrás-levél", "Duplicate", "Duplicate of",
            "Direction"]


def duplicate_status(mark: dict[str, Any] | None) -> str | None:
    """126: the duplicate mark as one value: `copy` / `variant` when a person confirmed it, `suspected:<kind>` while the
    to-do is open; None without a mark (a pair found different has none)."""
    if not mark or "status" not in mark:
        return None
    return f"suspected:{mark['kind']}" if mark["status"] == "suspected" else mark["status"]


def _doc_row(r: dict[str, Any], direction: str | None) -> list[Any]:
    mark = r.get("duplicate")
    status = duplicate_status(mark)
    return [r["file"], r["item_id"], r["doc_type"], r["arm"], r["final_status"], "; ".join(r["open_reasons"]),
            r.get("source_email") or "", status, (mark or {}).get("other_file") if status else None, direction]


def _directions(recs: list[dict[str, Any]]) -> list[str | None]:
    """147: an invoice's direction from the own parties (`parties.direction`); None for a document of another kind."""
    from jav import parties

    kinds = {*type_roles.types("incoming_invoice"), *type_roles.types("outgoing_invoice")}
    if not any(r["doc_type"] in kinds for r in recs):
        return [None] * len(recs)
    res = parties.resolver()
    return [parties.direction(res, r["doc_type"], r["fields"])[0] if r["doc_type"] in kinds else None for r in recs]


def documents_table(records: list[dict[str, Any]], doc_type: str | None = None) -> tuple[list[str], list[list[Any]]]:
    """One row per document; the fields are the union of the types' fields (in order of first appearance)."""
    recs = [r for r in records if doc_type is None or r["doc_type"] == doc_type]
    fields: list[str] = []
    for r in recs:
        fields += [f for f in r["fields"] if f not in fields]
    return DOC_HEAD + fields, [_doc_row(r, d) + [r["fields"].get(f) for f in fields] for r, d in zip(recs, _directions(recs))]


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


STATUS_TEXT = {"missing": "hiányzik", "overlap": "átfedés", "partial": "részleges", "ok": ""}
GRAND_TOTAL_LABEL = "Mindösszesen (a tájékoztató sorok nélkül)"

# 178 (plan 170 L4): the column keys of the result's tables (`configs/outputs.json` `package_result`), in the order of
# their headers
NATIVE_READING_COLUMNS = ("file", "item_id", "reading_status", "interpretation_status", "result_version", "reading_details")
NATIVE_READING_HEAD = ("Document", "Item identifier", "Reading status", "Interpretation status", "Result version", "Reading details")
EMAIL_COLUMNS = ("subject", "sender", "received_at", "mailbox", "intent", "machine_intent", "confidence", "corrected", "next_flow",
                 "attachments", "body_status", "body_chars", "open_reasons", "item_id")
TASK_COLUMNS = ("subject", "action", "title", "due_date", "assignee_hint", "evidence", "decision", "decided_by", "done_at", "done_by",
                "item_id")
TASK_HEAD = ("Levél", "Akció", "Feladat", "Határidő", "Felelős", "Bizonyíték", "Döntés", "Döntött", "Elvégezve", "Elvégezte",
             "Tétel-azonosító")
DOC_COLUMNS = ("file", "item_id", "doc_type", "arm", "status", "open_reasons", "source_email", "duplicate", "duplicate_of", "direction")
DATAPOINT_COLUMNS = ("file", "item_id", "doc_type", "field", "value", "page", "quote", "location", "corrected", "field_todo")
LINE_COLUMNS = ("file", "item_id", "doc_type", "list", "row", "page")
UTILITY_COLUMNS = ("address", "utility", "suppliers", "summary_only", "total")
UTILITY_HEAD = ("Fogyasztási hely", "Közmű", "Szolgáltató", "Csak tájékoztató", "Összesen (bruttó)")
UTILITY_SOURCE_COLUMNS = ("address", "utility", "month", "status", "amount", "file", "item_id", "page", "field", "corrected",
                          "open_reasons")
UTILITY_SOURCE_HEAD = ("Fogyasztási hely", "Közmű", "Hónap", "Állapot", "Összeg (hónapra jutó)", "Irat", "Tétel-azonosító", "Oldal",
                       "Mező", "Javítva", "Nyitott teendők")


def _table(key: str, title: str, columns: tuple[str, ...], head: Any, rows: list[list[Any]],
           kinds: list[str | None] | None = None, **extra: Any) -> contract.Table:
    kinds = kinds or [None] * len(columns)
    return contract.Table(key=key, title=title, columns=tuple(columns), head=tuple(head),
                          kinds=tuple(contract.writer_kind(k) for k in kinds), rows=rows, **extra)


def _utility_tables(report: dict[str, Any]) -> list[contract.Table]:
    """The utility cost by month (a missing, overlapping or partly covered month marked) and its sources."""
    months = report["months"]
    rows, marks = [], {}
    for r_i, s in enumerate(report["series"]):
        rows.append([s["address"], s["utility"], ", ".join(s["suppliers"]), "igen" if s["summary_only"] else "", s["total"]]
                    + [(s["cells"].get(m) or {}).get("amount") or STATUS_TEXT.get((s["cells"].get(m) or {}).get("status", ""), "")
                       for m in months])
        for m_i, m in enumerate(months):
            st = (s["cells"].get(m) or {}).get("status")
            if st in ("missing", "overlap", "partial"):
                marks[(r_i, len(UTILITY_COLUMNS) + m_i)] = st
    footer = [[GRAND_TOTAL_LABEL, "", "", "", report["grand_total"]] + [""] * len(months)]
    series = _table("utility_cost", "Közmű-költség", UTILITY_COLUMNS + tuple(f"month_{m.replace('-', '_')}" for m in months),
                    UTILITY_HEAD + tuple(months), rows, [None, None, None, None, "money"] + ["money"] * len(months), marks=marks,
                    footer=footer)
    srows = [[s["address"], s["utility"], m, "elszámolás" if x.get("settlement") else c["status"], x["amount"], x["file"],
              x["item_id"], x["page"], x["field"], "igen" if x["corrected"] else "", x["open_reasons"] or ""]
             for s in report["series"] for m, c in s["cells"].items() for x in c["sources"]]
    srows += [[None, None, None, "nem vetíthető: " + u["reason"], None, u["file"], u["item_id"], None, None, "", ""] for u in report["unplaced"]]
    srows += [[None, None, None, f"ismétlődő (azonos: {d['same_as_file']})", None, d["file"], d["item_id"], None, None, "", ""]
              for d in report.get("duplicates", [])]
    return [series, _table("utility_sources", "Közmű-források", UTILITY_SOURCE_COLUMNS, UTILITY_SOURCE_HEAD, srows,
                           [None] * 4 + ["money"] + [None] * 6)]


def xlsx_bytes(run_id: str, records: list[dict[str, Any]] | None = None) -> bytes:
    records = run_records(run_id) if records is None else records
    return workbook_bytes(records, email_records(run_id), native_records(run_id))


def result_data(records: list[dict[str, Any]], mails: list[dict[str, Any]], native: list[dict[str, Any]],
                values: tuple[contract.Value, ...] = ()) -> contract.OutputData:
    """178 (plan 170 L4): the result's data as the output contract describes it (`package_result`): the native facts and
    readings, the emails and their tasks, the documents by type, the data points, the line items and the utility cost;
    `values`: the package's (`package_values`). The grand total of the utility cost is a value too."""
    from jav import report_utility

    tables: list[contract.Table] = []
    if native:
        head, rows = native_facts_table(native)
        tables.append(_table("native_facts", "Native facts", NATIVE_COLUMNS, head, rows))
        tables.append(_table("native_readings", "Native readings", NATIVE_READING_COLUMNS, NATIVE_READING_HEAD,
                             [[record["file"], record["item_id"], record["reading"]["status"],
                               record["interpretation_outcome"]["status"], record["result_version"],
                               json.dumps(record["reading"], ensure_ascii=False, sort_keys=True)] for record in native]))
    if mails:  # 058 K5.1: the email items on their own sheet
        head, rows = emails_table(mails)
        tables.append(_table("emails", "Levelek", EMAIL_COLUMNS, head, rows))
        tasks = task_rows(mails)
        if tasks:  # 058 K5.3: the task proposals on a separate sheet, with the decision
            actions = cfg.load("email_tasks")["actions"]
            decisions = {"accepted": "elfogadva", "rejected": "elvetve"}
            tables.append(_table("tasks", "Feladatok", TASK_COLUMNS, TASK_HEAD,
                                 [[t["subject"], actions.get(t["action"], t["action"]), t["title"], t["due_date"], t["assignee_hint"],
                                   t["evidence"], decisions.get(t["decision"] or "", "vár döntésre"), t["decided_by"], t["done_at"],
                                   t["done_by"], t["item_id"]] for t in tasks]))
        if not records:  # emails only: no empty document sheet
            return contract.OutputData("package_result", values, tuple(tables))
    for doc_type in sorted({r["doc_type"] for r in records}):
        head, rows = documents_table(records, doc_type)
        kinds = next(r["kinds"] for r in records if r["doc_type"] == doc_type)
        fields = head[len(DOC_HEAD):]
        tables.append(_table("documents", doc_type, DOC_COLUMNS + tuple(fields), head, rows,
                             [None] * len(DOC_HEAD) + [kinds.get(h) for h in fields], part=doc_type))
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
    report = report_utility.build(records)
    tables += _utility_tables(report)
    return contract.OutputData("package_result", (*values, _grand_total(report)), tuple(tables))


PERIOD_LABEL = "Időszak"


def _grand_total(report: dict[str, Any]) -> contract.Value:
    return contract.Value("grand_total", GRAND_TOTAL_LABEL, report["grand_total"])


def package_values(wp: dict[str, Any], version: dict[str, Any] | None = None) -> tuple[contract.Value, ...]:
    """178: the package's values of an output: its name, and for a released version its number, who released it and
    when (empty for the current result)."""
    v = version or {}
    at = (v.get("released_at") or "")[:16].replace("T", " ")
    return (contract.Value("package", "Csomag", wp["name"]), contract.Value("version", "Változat", str(v.get("version") or "")),
            contract.Value("released_by", "Kiadta", v.get("released_by") or ""), contract.Value("released_at", "Kiadva", at))


def utility_data(records: list[dict[str, Any]], values: tuple[contract.Value, ...] = ()) -> contract.OutputData:
    """178 (DECISIONS 178): the utility cost as an output of its own (`utility_cost`): the grid by month and its sources,
    the period (the first and the last month) and the grand total; `values`: the package's name."""
    from jav import report_utility

    report = report_utility.build(records)
    months = report["months"]
    period = contract.Value("period", PERIOD_LABEL, f"{months[0]} – {months[-1]}" if months else "")
    return contract.OutputData("utility_cost", (*values[:1], period, _grand_total(report)), tuple(_utility_tables(report)))


def workbook_bytes(records: list[dict[str, Any]], mails: list[dict[str, Any]], native: list[dict[str, Any]]) -> bytes:
    """The download workbook of documents, emails and native results (a run's, or a released package version's,
    171: `jav/package_release.py`), in the built-in layout (178: `jav/outputs/builtin.py`)."""
    return builtin.render(result_data(records, mails, native))


# --- JSON ------------------------------------------------------------------------------------------------------


def _json_export(run_id: str, records: list[dict[str, Any]] | None = None) -> tuple[bytes, int]:
    from jav import datasets, report_utility

    # Capture before every data read: an interleaved edit must make approval fail,
    # never give older exported values the version of an unseen correction.
    review_version = corrections.review_version(run_id)
    run = work.get_run(run_id)
    native_run = any(native_results.native_item(run_id, item) for item in run["input"]["items"])
    # Caller-supplied rows have no bound version. A native or mixed export must
    # reload them after the version capture, using the versioned dataset cache.
    records = datasets.run_records(run_id) if records is None or native_run else records
    body = {"run_id": run_id, "recipe_id": run["recipe_id"], "recipe_version": run["recipe_version"], "params": run["params"],
            "mode": run["mode"], "approval": run["approval"], "created_at": run["created_at"],
            "documents": [{k: v for k, v in r.items() if k != "kinds"} for r in records],
            "emails": email_records(run_id),
            "utility_cost": report_utility.build(records)}
    native = native_records(run_id)
    if native:
        body["native_items"] = native
        body["review_version"] = review_version
    body = card_numbers.mask_values(body)  # 160 (review S-2): a native result, and data saved before the masking of 153
    return json.dumps(body, ensure_ascii=False, indent=1, default=str).encode("utf-8"), len(records)


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


__all__ = ["TABLES", "csv_bytes", "datapoints_table", "documents_table", "email_records", "emails_table", "json_bytes",
           "line_items_table", "render", "run_records", "workbook_bytes", "xlsx_bytes"]
