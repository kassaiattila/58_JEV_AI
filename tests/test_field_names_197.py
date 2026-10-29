"""197 (plan 197 K0): a type's own name for a shared field.

The quote request (190) renamed the shared `customer_name` to "Ajánlatkérő neve", so the six utility bill types showed
their consumer as the requester. The shared name is the utility bills' again; the quote request keeps its own name
where the type is known: a column only that type fills, an output template's sample rows of that type, and the review
page (the interface's test). Synthetic records only."""

import pytest

from jav.app import datasets
from jav.ai import typepack
from jav.core import cfg, field_names
from jav.app.outputs import parts, samples


def test_a_type_names_a_shared_field_its_own_way():
    assert field_names.field_label("customer_name") == "Customer name"
    assert field_names.field_label("customer_name", "viz_szamla") == "Customer name"
    assert field_names.field_label("customer_name", "quote_request") == "Requesting customer"
    assert field_names.field_label("contact_name", "quote_request") == "Contact"  # the shared name
    # 231 (D4): the English sources, shown in the request's language (Hungarian by default)
    assert field_names.field_name("customer_name", "viz_szamla") == "Felhasználó neve"
    assert field_names.field_name("customer_name", "quote_request") == "Ajánlatkérő neve"
    assert field_names.field_label("no_such_field", "quote_request") == "no_such_field"


def test_every_own_name_belongs_to_a_field_of_its_type():
    own = cfg.load("field_labels")["by_type"]
    stray = sorted(f"{t}.{f}" for t, names in own.items() for f in names
                   if t not in typepack.keys() or f not in typepack.get(t).fields)
    assert stray == []


def test_a_field_of_one_type_reads_as_that_types_name():
    quote = {"doc_type": "quote_request", "fields": {"customer_name": "Példa Kft."}}
    bill = {"doc_type": "viz_szamla", "fields": {"customer_name": "Minta Péter"}}
    assert field_names.shared_type("customer_name", [quote]) == "quote_request"
    assert field_names.shared_type("customer_name", [quote, bill]) is None
    assert field_names.shared_type("customer_name", []) is None


def _record(doc_type: str, fields: dict) -> dict:
    return {"file": f"{doc_type}.pdf", "item_id": f"it-{doc_type}", "doc_type": doc_type, "arm": "G", "final_status": "done",
            "open_reasons": [], "fields": fields, "kinds": {f: "text" for f in fields}}


@pytest.mark.parametrize(("types", "label"), [(["quote_request"], "Requesting customer"), (["viz_szamla"], "Customer name"),
                                              (["quote_request", "viz_szamla"], "Customer name")])
def test_the_documents_column_of_the_field(monkeypatch, types, label):
    records = [_record(t, {"customer_name": "Példa"}) for t in types]
    monkeypatch.setattr(datasets, "linked_records", lambda scope: (lambda item: {"_run": "run-1", "_wp": "wp-1"}, records))
    monkeypatch.setattr(parts, "document_columns", lambda: ())
    cols, _rows = datasets._documents({"run_id": "run-1"})
    assert {c.key: c.label for c in cols}["f:customer_name"] == label


def test_an_output_templates_sample_rows_use_the_types_names():
    assert samples.field_label("customer_name", "quote_request") == "Requesting customer"
    assert samples.field_label("customer_name", "viz_szamla") == "Customer name"
    assert samples.field_label("*") == "Value"  # a list column keeps its own name
