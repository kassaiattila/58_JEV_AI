"""264 (plan E, F5; the owner's decision of 2026-10-31): the data points table holds every field's value in one column,
so each row says its field's kind - an amount is shown as an amount and a date as a date, not as raw text
("1767500"). Synthetic records."""
from __future__ import annotations

from jav.app import datasets


def _record(item_id: str, fields: dict, kinds: dict) -> dict:
    return {"item_id": item_id, "file": f"{item_id}.pdf", "doc_type": "invoice_hu", "fields": fields, "kinds": kinds,
            "provenance": {}, "corrected": [], "open_reasons": []}


def test_each_data_point_row_says_its_field_s_kind(monkeypatch):
    records = [_record("i1", {"gross_total": "1767500", "issue_date": "2026-03-01", "supplier_name": "Synthetic Kft."},
                       {"gross_total": "money", "issue_date": "date", "supplier_name": "text"})]
    monkeypatch.setattr(datasets, "linked_records", lambda scope: (lambda item: {"_run": "run-1", "_wp": "wp-1"}, records))
    cols, rows = datasets._datapoints({"run_id": "run-1"})
    value = next(c for c in cols if c.key == "value")
    assert value.kind == "text" and value.extra.get("kind_from") == "_kind"
    assert {r["field"]: r["_kind"] for r in rows} == {"gross_total": "money", "issue_date": "date", "supplier_name": "text"}


def test_a_field_without_a_kind_is_text(monkeypatch):
    records = [_record("i1", {"note": "free text"}, {})]
    monkeypatch.setattr(datasets, "linked_records", lambda scope: (lambda item: {"_run": "run-1", "_wp": "wp-1"}, records))
    _cols, rows = datasets._datapoints({"run_id": "run-1"})
    assert [r["_kind"] for r in rows] == ["text"]
