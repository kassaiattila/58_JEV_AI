"""A quote request read from the store, its parts put together (191, plan F-quote-package B3).

Plain-language summary (DECISIONS 191): a quote request arrives as an email, and its data can be in the email's own
text, in an attached request form (PDF) or request list (Excel, CSV), or in a document added on its own. Each part was
extracted on its own by its package's processing (190), and each may lack what another part has: the text names the
customer but not the items, the list has the items but not the customer. This module reads each part's counted result
(`jav/package_result.py`; a document's latest correction over it) and puts the parts together into one request, saying
which part each value came from: a header field's first value, the email's text first, then the attachments in their
order; the items of the first attachment that has rows, else the text's (the rule the measurement has used since 190).
Whether a request has a gap is judged on the whole request, not on each part (backlog Q-quote-part-to-dos).

- `read(wp_id, item_id)`: the request of an email item (its text and its attachments) or of a document item;
  `RequestNotFound` when the item is no quote request or has no counted result.
- `found()`: every item a quote can start from: an email whose intent is a quote request (a person's correction
  counts) or that has an attachment read as one, and a document read as one that came on its own.
- `merge(parts)`, `merged(readings)`: the putting together.

Layer: business module of the quotes domain; it reads the store and calls no AI.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any

from jav import corrections, package_result, work
from jav.core import store
from jav.typepack import get as get_pack

TYPE = "quote_request"  # the type pack, the detection type and the email intent (190)
ITEMS = "requested_items"
TEXT_STAGE = "invoice"  # the follow-up stage that extracts an email's own text (`jav/runtime/worker.py`, 190)


class RequestNotFound(LookupError):
    """The item is no quote request, is not in the package (any more), or no run has finished it."""


@dataclass(frozen=True)
class Part:
    """One part of a request: the email's own text (`email_text`), an attachment, or a document on its own; `values`:
    its fields as they count now."""

    kind: str
    name: str
    item_id: str | None
    doc_id: str
    values: dict[str, Any]


@dataclass(frozen=True)
class Request:
    """A request put together: its header fields (`sources`: the index of the part each came from), its requested
    items (`items_from`: the part they came from) and its parts."""

    workpackage_id: str
    item_id: str
    kind: str  # email or document
    title: str
    sender: str | None
    received_at: str | None
    parts: tuple[Part, ...]
    fields: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, int] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)
    items_from: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _present(value: Any) -> bool:
    return value not in (None, "", [])


def merge(parts: list[Part]) -> tuple[dict[str, Any], dict[str, int], list[dict[str, Any]], int | None]:
    """(header fields, the part each came from, the requested items, the part they came from)."""
    fields: dict[str, Any] = {}
    sources: dict[str, int] = {}
    for name in get_pack(TYPE).header_fields:
        at = next((n for n, p in enumerate(parts) if _present(p.values.get(name))), None)
        fields[name] = None if at is None else parts[at].values[name]
        if at is not None:
            sources[name] = at
    attached = [n for n, p in enumerate(parts) if p.kind != "email_text" and p.values.get(ITEMS)]
    texts = [n for n, p in enumerate(parts) if p.kind == "email_text" and p.values.get(ITEMS)]
    items_from = (attached or texts or [None])[0]
    items = list(parts[items_from].values[ITEMS]) if items_from is not None else []
    return fields, sources, items, items_from


def merged(readings: list[dict[str, Any]]) -> dict[str, Any]:
    """The readings of an email's parts (its text first, then its attachments) put together, as `merge` does: the
    header fields and the requested items (the measurement's comparison, `jav/evals_quotes.py`)."""
    parts = [Part("email_text" if n == 0 else "attachment", "", None, "", r or {}) for n, r in enumerate(readings)]
    fields, _sources, items, _items_from = merge(parts)
    return {**fields, ITEMS: items}


# --- reading the store -----------------------------------------------------------------------------------------------


def _values(c: sqlite3.Connection, flow_run_id: str, doc_id: str | None = None) -> tuple[str, dict[str, Any]] | None:
    """(the document, its fields) of a quote request result row of the flow run; None if it has none."""
    query = "SELECT doc_id, datapoints FROM datapoints WHERE run_id=? AND doc_type=?"
    args: tuple[Any, ...] = (flow_run_id, TYPE)
    if doc_id is not None:
        query, args = query + " AND doc_id=?", (*args, doc_id)
    row = c.execute(query + " ORDER BY rowid DESC LIMIT 1", args).fetchone()
    return (row["doc_id"], json.loads(row["datapoints"] or "{}")) if row is not None else None


def _document_part(c: sqlite3.Connection, kind: str, item: dict[str, Any], counted: package_result.Counted | None) -> Part | None:
    if counted is None or counted.flow_run_id is None:
        return None
    got = _values(c, counted.flow_run_id, item["item_id"])
    if got is None:
        return None
    correction = corrections.current(counted.run_id, item["item_id"], c)["fields"]
    name = item["source_path"].replace("\\", "/").rsplit("/", 1)[-1]
    return Part(kind, name, item["item_id"], got[0], package_result.effective_values(got[1], correction))


def _table_parts(c: sqlite3.Connection, flow_run_id: str) -> list[Part]:
    """192 (B6c): the email's table attachments read in its follow-up (stages `<flow>-invoice-a<n>`), in their order,
    each named by its file."""
    prefix = f"{flow_run_id}-{TEXT_STAGE}-a"
    rows = c.execute("SELECT d.run_id, d.doc_id, d.datapoints, m.source_path FROM datapoints d LEFT JOIN documents m"
                     " ON m.doc_id = d.doc_id WHERE d.doc_type=? AND substr(d.run_id, 1, ?) = ?",
                     (TYPE, len(prefix), prefix)).fetchall()

    def stage(row: Any) -> int:  # the attachment's number in its email
        n = row["run_id"][len(prefix):]
        return int(n) if n.isdigit() else 0

    return [Part("attachment", str(r["source_path"] or "").replace("\\", "/").rsplit("/", 1)[-1], None, r["doc_id"],
                 json.loads(r["datapoints"] or "{}")) for r in sorted(rows, key=stage)]


def _email(c: sqlite3.Connection, counted: package_result.Counted) -> tuple[dict[str, Any], str | None]:
    """The email's stored result and its intent as it counts now (a person's correction over the machine's)."""
    row = c.execute("SELECT e.message_id, e.intent, m.subject, m.sender, m.received_at FROM email_results e"
                    " LEFT JOIN emails m ON m.message_id = e.message_id WHERE e.run_id=?", (counted.flow_run_id,)).fetchone()
    if row is None:
        return {}, None
    corrected = corrections.current(counted.run_id, counted.item_id, c)["fields"].get("intent")
    return dict(row), corrected or row["intent"]


def read(wp_id: str, item_id: str) -> Request:
    try:
        wp = work.get(wp_id)
    except KeyError as exc:
        raise RequestNotFound(f"no work package {wp_id}") from exc
    item = next((i for i in wp["items"] if i["item_id"] == item_id), None)
    if item is None:
        raise RequestNotFound(f"{wp_id} has no item {item_id[:12]}")
    with store.connect() as c:
        counted = package_result.counted_results(wp_id, c)
        if item["kind"] != "email":
            part = _document_part(c, "document", item, counted.get(item_id))
            if part is None or item.get("parent_item_id"):
                raise RequestNotFound(f"{item_id[:12]} is not read as a quote request on its own")
            parts: list[Part] = [part]
            head: dict[str, Any] = {"title": part.name, "sender": None, "received_at": None}
        else:
            own = counted.get(item_id)
            if own is None or own.flow_run_id is None:
                raise RequestNotFound(f"{item_id[:12]} has no counted result")
            email, intent = _email(c, own)
            text = _values(c, f"{own.flow_run_id}-{TEXT_STAGE}")
            parts = [Part("email_text", email.get("subject") or "", None, text[0], text[1])] if text else []
            parts += _table_parts(c, own.flow_run_id)  # 192 (B6c): an Excel or CSV request list read in the follow-up
            for attachment in wp["items"]:
                if attachment.get("parent_item_id") == item_id:
                    part = _document_part(c, "attachment", attachment, counted.get(attachment["item_id"]))
                    if part is not None:
                        parts.append(part)
            if intent != TYPE and not any(p.kind == "attachment" for p in parts):
                raise RequestNotFound(f"{item_id[:12]} is not a quote request")
            head = {"title": email.get("subject") or "", "sender": email.get("sender"), "received_at": email.get("received_at")}
    fields, sources, items, items_from = merge(parts)
    return Request(workpackage_id=wp_id, item_id=item_id, kind="email" if item["kind"] == "email" else "document",
                   parts=tuple(parts), fields=fields, sources=sources, items=items, items_from=items_from, **head)


def found() -> list[tuple[str, str]]:
    """Every (package, item) a quote may start from, as its package's processing left it: an email whose intent was
    read or corrected as a quote request, an email with an attachment read as one, and a document read as one that came
    on its own. The caller reads each one (`read`), which also leaves out what no longer counts."""
    with store.connect() as c:
        out = [(r[0], r[1]) for r in c.execute(
            "SELECT DISTINCT r.workpackage_id, ri.item_id FROM email_results e JOIN run_items ri ON ri.flow_run_id = e.run_id"
            " JOIN runs r ON r.run_id = ri.run_id WHERE e.intent = ?", (TYPE,))]
        out += [(r[0], r[1]) for r in c.execute(
            "SELECT DISTINCT r.workpackage_id, c.item_id FROM run_item_corrections c JOIN runs r ON r.run_id = c.run_id"
            " WHERE json_extract(c.fields, '$.intent') = ?", (TYPE,))]
        for r in c.execute("SELECT DISTINCT r.workpackage_id, ri.item_id, wi.parent_item_id FROM datapoints d"
                           " JOIN run_items ri ON ri.flow_run_id = d.run_id AND ri.item_id = d.doc_id"
                           " JOIN runs r ON r.run_id = ri.run_id JOIN workpackage_items wi"
                           " ON wi.workpackage_id = r.workpackage_id AND wi.item_id = ri.item_id"
                           " WHERE d.doc_type = ? AND wi.removed_revision IS NULL", (TYPE,)):
            out.append((r[0], r[2] or r[1]))  # an attachment stands for its email
    return list(dict.fromkeys(out))


__all__ = ["ITEMS", "TYPE", "Part", "Request", "RequestNotFound", "found", "merge", "merged", "read"]
