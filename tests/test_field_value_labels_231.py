"""231 (stage U, U1; finding 7 of the walkthrough): an enumerated field's values read by their names in the result table.

A bank statement's kind was shown as its code ("bank_account", "credit_card") in the documents table. Every value a
type pack enumerates for a field has a Hungarian name in `configs/field_labels.json` (`values`, keyed `field=value`, as
the list columns' `direction=debit`); the documents table's column of such a field is enumerated with those names, so
the table shows the name and the download writes it. A field without enumerated values keeps its text column. 231
(U3): the data points table shows the name too, in its value column of every field. Synthetic records only.
"""

from __future__ import annotations

from jav.ai import typepack
from jav.app import datasets
from jav.app.outputs import parts
from jav.app.tablequery import shown
from jav.core import cfg, field_names


def test_every_enumerated_value_of_a_field_has_a_name() -> None:
    values = cfg.load("field_labels")["values"]
    missing = sorted({f"{key}.{f}={v}" for key in typepack.keys() for f, allowed in typepack.get(key).enums.items()
                      if "[" not in f for v in allowed if v is not None and str(v) != "None" and f"{f}={v}" not in values})
    assert missing == []


def test_a_fields_value_names() -> None:
    assert field_names.value_labels("statement_type") == {"bank_account": "bank account", "credit_card": "credit card"}
    assert field_names.value_labels("supplier_name") == {}


def _record(fields: dict) -> dict:
    return {"file": "s.pdf", "item_id": "it-1", "doc_type": "statement_cib", "arm": "G", "final_status": "done",
            "open_reasons": [], "fields": fields, "kinds": {f: "text" for f in fields}}


def test_the_documents_column_of_an_enumerated_field_names_its_values(monkeypatch) -> None:
    records = [_record({"statement_type": "credit_card", "account_no": "10700000-00000000"})]
    monkeypatch.setattr(datasets, "linked_records", lambda scope: (lambda item: {"_run": "run-1", "_wp": "wp-1"}, records))
    monkeypatch.setattr(parts, "document_columns", lambda: ())
    cols, rows = datasets._documents({"run_id": "run-1"})
    by_key = {c.key: c for c in cols}
    kind = by_key["f:statement_type"]
    assert (kind.kind, kind.labels) == ("enum", {"bank_account": "bank account", "credit_card": "credit card"})
    assert shown(kind, "credit_card") == "hitelkártya"  # 231 (D4): the name is shown in the request's language
    assert rows[0]["f:statement_type"] == "credit_card"  # the code stays the value; the name is its label
    assert (by_key["f:account_no"].kind, by_key["f:account_no"].labels) == ("text", None)


def test_the_data_points_value_of_an_enumerated_field_is_its_name(monkeypatch) -> None:
    record = {**_record({"statement_type": "credit_card", "account_no": "10700000-00000000"}), "provenance": {},
              "corrected": [], "open_reasons": []}
    monkeypatch.setattr(datasets, "linked_records", lambda scope: (lambda item: {"_run": "run-1", "_wp": "wp-1"}, [record]))
    cols, rows = datasets._datapoints({"run_id": "run-1"})
    values = {r["field"]: r["value"] for r in rows}
    assert values == {"statement_type": "credit card", "account_no": "10700000-00000000"}
    value = next(c for c in cols if c.key == "value")
    assert value.labels == {"bank account": "bank account", "credit card": "credit card"}
    assert shown(value, "credit card") == "hitelkártya"  # 231 (D4): shown in the request's language
