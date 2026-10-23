"""178 (plan 170 L4, DECISIONS 178): characterisation of today's Excel downloads before the output layer.

The output layer replaces the two hand-written table writers (`export._write_sheet`, `reconcile_statement._sheet`) with
one shared writer and built-in templates; the files people download must stay the same. These tests pin each workbook
part by part (each sheet, the styles, the workbook's own parts), with a short digest per part, so a difference names
the part that changed. Only the workbook's timestamps (`docProps/core.xml`) are left out.

Pinned on `5b4ca9c` (v1.22.1): the result workbook of a run or a released package version (documents of two types,
line items, the utility-cost sheets, emails with their tasks), the reconciliation statement (draft and approved
version) and a dataset download. The native sheets go through the same writer; their content is pinned by
`tests/test_native_datasets_109.py`. Synthetic records and made-up values only; no AI call, no network.
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from decimal import Decimal

import pytest

from jav.app import datasets, export, package_release
from jav.ai import typepack
from jav.core import store
from jav.domains.finance import reconcile_statement as rs
from jav.app.datasets import Column
from jav.app.tablequery import Query
from tests.test_reconcile_statement_145 import _world


def _parts(data: bytes) -> dict[str, str]:
    """Each part of the workbook with the first 16 hexadecimal digits of its sha256; the timestamps left out."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: hashlib.sha256(z.read(n)).hexdigest()[:16] for n in sorted(z.namelist()) if n != "docProps/core.xml"}


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "c178.sqlite"):
        yield


# --- the result workbook --------------------------------------------------------------------------------------------


def _record(item_id: str, doc_type: str, fields: dict, *, lists=None, provenance=None, open_reasons=(), corrected=(),
            duplicate=None, source_email=None) -> dict:
    """A document record as `export.run_records` builds it."""
    pack = typepack.get(doc_type)
    return {"item_id": item_id, "file": f"{item_id}.pdf", "doc_type": doc_type, "arm": "S", "final_status": "done",
            "fields": {f: fields.get(f) for f in pack.header_fields}, "kinds": {f: pack.kind(f) for f in pack.fields},
            "lists": {f: (lists or {}).get(f) or [] for f in pack.fields if pack.kind(f) == "list"},
            "provenance": provenance or {}, "row_pages": {f: [1] * len(rows) for f, rows in (lists or {}).items()},
            "pages": {f: (p or {}).get("page") for f, p in (provenance or {}).items()},
            "corrected": sorted(corrected), "open_reasons": list(open_reasons), "source_email": source_email,
            "duplicate": duplicate}


def _records() -> list[dict]:
    invoice = _record(
        "item-invoice-1", "invoice_hu",
        {"supplier_name": "Minta Szolgáltató Kft.", "buyer_name": "Példa Vevő Bt.", "invoice_number": "=HYPERLINK(\"x\")",
         "issue_date": "2026-04-02", "due_date": "2026-04-17", "currency": "HUF", "net_total": "1000.00",
         "vat_total": "270.00", "gross_total": "1270.00", "payment_method": "átutalás\x07"},
        lists={"line_items": [{"description": "Szolgáltatás", "quantity": "2", "unit_price": "500.00", "net_amount": "1000.00",
                               "vat_rate": "27%", "gross_amount": "1270.00"},
                              {"description": "Kerekítés", "quantity": "1", "unit_price": "0.4", "net_amount": "0.4"}]},
        provenance={"invoice_number": {"status": "found", "page": 1, "quote": "Sorszám: 2026/001"},
                    "gross_total": {"status": "found", "page": 1, "quote": "Fizetendő: 1 270 Ft"}},
        open_reasons=["jev:off_target:invoice_number:0.82"], corrected=["due_date"], source_email="Számla április")
    copy = _record("item-invoice-2", "invoice_hu", {"supplier_name": "Minta Szolgáltató Kft.", "gross_total": "1270",
                                                    "invoice_number": "2026/001"},
                   duplicate={"status": "copy", "kind": "copy", "other_file": "item-invoice-1.pdf"})
    power = [_record(f"item-power-{n}", "villamos_energia_szamla",
                     {"supplier_name": "Áram Zrt.", "consumption_address": "1111 Budapest, Minta utca 11",
                      "billing_period_start": start, "billing_period_end": end, "gross_total": amount, "consumption_kwh": kwh},
                     provenance={"gross_total": {"status": "found", "page": 2, "quote": amount}})
             for n, (start, end, amount, kwh) in enumerate([("2026-01-01", "2026-01-31", "10000", "300"),
                                                            ("2026-03-01", "2026-03-31", "12000", "350"),
                                                            ("2026-03-15", "2026-04-30", "9000", None)], 1)]
    return [invoice, copy, *power]


def _mails() -> list[dict]:
    task = {"index": 0, "action": "review_invoice", "title": "Számla ellenőrzése", "due_date": "2026-04-20",
            "assignee_hint": "pénzügy", "evidence": [{"quote": "kérem, nézzék át"}, {"quote": "határidő: 20-a"}],
            "decision": {"decision": "accepted", "actor": "Reviewer", "decided_at": "2026-04-03T09:00:00+00:00",
                         "done_by": None, "done_at": None}}
    attachment = {"filename": "szamla.pdf", "doc_type": "invoice_hu", "shown_type": "invoice_hu", "status": "done"}
    return [{"item_id": "item-mail-1", "message_id": "msg-1", "subject": "Számla április", "sender": "Minta <minta@example.com>",
             "received_at": "2026-04-02T08:00:00+00:00", "mailbox": "teszt", "intent": "szamlakuldes",
             "machine_intent": "szamlakuldes", "confidence": 0.97, "corrected": False, "next_flow": "human:inbox",
             "attachments": [attachment], "from_this_run": True, "body": {"status": "full", "chars": 120},
             "open_reasons": [], "tasks": {"tasks": [task]}, "source_status": "same"}]


# The parts of each workbook on 5b4ca9c.
RESULT_PARTS = {
    "[Content_Types].xml": "8920c6c45c2b4be7",
    "_rels/.rels": "c545941ba36c15fc",
    "docProps/app.xml": "209fca6b00afe72a",
    "xl/_rels/workbook.xml.rels": "7676081832cc25e3",
    "xl/styles.xml": "ca53ed8b0e5efbbd",
    "xl/theme/theme1.xml": "d15e8ebf78ef7b97",
    "xl/workbook.xml": "28c40aaa5d422190",
    "xl/worksheets/sheet1.xml": "39103a698d1e3b0b",
    "xl/worksheets/sheet2.xml": "cb612e42da98d5a3",
    "xl/worksheets/sheet3.xml": "4fbc06eab5937150",
    "xl/worksheets/sheet4.xml": "77395c2030bfac0d",
    "xl/worksheets/sheet5.xml": "633d372acc7b0dbd",
    "xl/worksheets/sheet6.xml": "503809b154a30e2d",
    "xl/worksheets/sheet7.xml": "9127cbfb5c0aaf38",
    "xl/worksheets/sheet8.xml": "e556104a1b129927",
}

MAILS_ONLY_PARTS = {
    "[Content_Types].xml": "31376d16cf444bfe",
    "_rels/.rels": "c545941ba36c15fc",
    "docProps/app.xml": "209fca6b00afe72a",
    "xl/_rels/workbook.xml.rels": "d3b58263f0f6fe71",
    "xl/styles.xml": "49c67c060102a5df",
    "xl/theme/theme1.xml": "d15e8ebf78ef7b97",
    "xl/workbook.xml": "d4a87a4dac3bdfd4",
    "xl/worksheets/sheet1.xml": "39103a698d1e3b0b",
    "xl/worksheets/sheet2.xml": "cb612e42da98d5a3",
}


def test_the_result_workbook_is_written_as_before(db):
    data = export.workbook_bytes(_records(), {"emails": _mails()}, [])  # 185: by the item part's name
    assert _parts(data) == RESULT_PARTS


def test_an_emails_only_workbook_is_written_as_before(db):
    data = export.workbook_bytes([], {"emails": _mails()}, [])
    assert _parts(data) == MAILS_ONLY_PARTS


# --- the reconciliation statement -----------------------------------------------------------------------------------


# The statement's sheets and its filter's name changed on purpose after 5b4ca9c (178, K20): the header row below the
# heading block is now styled, frozen and filtered, not the empty row above it (`tests/test_outputs_178.py`).
STATEMENT_DRAFT_PARTS = {
    "[Content_Types].xml": "31376d16cf444bfe",
    "_rels/.rels": "c545941ba36c15fc",
    "docProps/app.xml": "209fca6b00afe72a",
    "xl/_rels/workbook.xml.rels": "d3b58263f0f6fe71",
    "xl/styles.xml": "a1a8b77453642715",
    "xl/theme/theme1.xml": "d15e8ebf78ef7b97",
    "xl/workbook.xml": "e3c722d32e88fb26",
    "xl/worksheets/sheet1.xml": "0e54ea29aea80840",
    "xl/worksheets/sheet2.xml": "4672d4424f516dee",
}

STATEMENT_APPROVED_PARTS = {
    "[Content_Types].xml": "31376d16cf444bfe",
    "_rels/.rels": "c545941ba36c15fc",
    "docProps/app.xml": "209fca6b00afe72a",
    "xl/_rels/workbook.xml.rels": "d3b58263f0f6fe71",
    "xl/styles.xml": "a1a8b77453642715",
    "xl/theme/theme1.xml": "d15e8ebf78ef7b97",
    "xl/workbook.xml": "e3c722d32e88fb26",
    "xl/worksheets/sheet1.xml": "62c3c39e24c7917b",
    "xl/worksheets/sheet2.xml": "4e1daa1634865193",
}


def test_the_reconciliation_statement_is_written_as_before(db, monkeypatch):
    wp_id, _inv, _ids = _world()
    data, name = rs.xlsx(wp_id)
    assert name == "egyeztetes-April-tervezet.xlsx"
    assert _parts(data) == STATEMENT_DRAFT_PARTS
    monkeypatch.setattr(rs, "_now", lambda: "2026-05-02T10:30:00+00:00")  # the heading shows when it was approved
    monkeypatch.setattr(package_release, "_now", lambda: "2026-05-02T10:30:00+00:00")  # 186: the shared version store's time
    rs.approve(wp_id, fingerprint=rs.current(wp_id)["fingerprint"], actor="Reviewer")
    data, name = rs.xlsx(wp_id, version=1)  # 178: the file stored at the approval
    assert name == "egyeztetes-April-v1.xlsx"
    assert _parts(data) == STATEMENT_APPROVED_PARTS


# --- a dataset download ---------------------------------------------------------------------------------------------


DATASET_PARTS = {
    "[Content_Types].xml": "ba5af858089dd335",
    "_rels/.rels": "c545941ba36c15fc",
    "docProps/app.xml": "209fca6b00afe72a",
    "xl/_rels/workbook.xml.rels": "26ad8fcc38d41229",
    "xl/styles.xml": "1c7601ca5c26ec5b",
    "xl/theme/theme1.xml": "d15e8ebf78ef7b97",
    "xl/workbook.xml": "84ed37fc805de41f",
    "xl/worksheets/sheet1.xml": "e6d8a496f87a46a0",
}


def test_a_dataset_download_is_written_as_before(db, monkeypatch):
    cols = [Column(key="file", label="Irat", kind="text"), Column(key="amount", label="Összeg", kind="money"),
            Column(key="count", label="Darab", kind="number"), Column(key="note", label="Megjegyzés", kind="text")]
    rows = [{"file": "a.pdf", "amount": Decimal("1270.00"), "count": 2, "note": "=1+1"},
            {"file": "b.pdf", "amount": "12 000", "count": None, "note": "rendben"}]
    monkeypatch.setattr(datasets, "rows", lambda name, scope: (cols, rows))
    data, media, name, count = datasets.export_file("documents", {"run_id": "run-000000000001"}, Query(), "all", "xlsx")
    assert (media, count) == (datasets.MEDIA["xlsx"], 2)
    assert _parts(data) == DATASET_PARTS
