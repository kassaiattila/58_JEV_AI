"""190 (plan 189 A2c): checks of any list field by its name, and a list of plain values in the G path's output model.

A quote request's requested items are a list like an invoice's line items, but with other columns, so the line-item
checks (sums, VAT) do not fit them. Three general checks name the list in the pack's `validators`: how many rows it has,
whether the named columns have a value in every row, and whether a quantity is above zero. A failure is a to-do at the
list field, its rows named as the line-item checks name theirs. Separately, a pack's list of plain values (strings) was
a list of empty objects in the output model, so GPT could never fill it; the pack's `plain_list_items` switch makes it
a list of strings (off for every existing pack, whose request stays the same). Synthetic records; no AI call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from jav import policy, typepack, validators
from jav.models import FlowState, record_from_llm

FIELDS = {"customer_name": "name", "requested_items": "list"}
ITEMS = {"description": "text", "quantity": "number", "unit": "text"}
SPECS = [{"check": "list_rows", "field": "requested_items", "min": 1},
         {"check": "list_values", "field": "requested_items", "columns": ["description", "quantity"]},
         {"check": "list_positive", "field": "requested_items", "columns": ["quantity"]}]


def _record(rows):
    record, reasons = record_from_llm({"customer_name": "Minta Kft.", "requested_items": rows}, FIELDS,
                                      list_fields={"requested_items": ITEMS})
    assert reasons == []
    return record


def _checks(rows):
    return {r.name: (r.ok, r.code, r.detail) for r in validators.run_checks(_record(rows), SPECS)}


def test_a_complete_list_passes_every_check():
    rows = [{"description": "Uzleti laptop", "quantity": "5", "unit": "db"}, {"description": "Telepites", "quantity": 2, "unit": None}]
    assert _checks(rows) == {"list_rows:requested_items": (True, "lines.count_ok", "rows=2"),
                             "list_values:requested_items": (True, "lines.values_ok", None),
                             "list_positive:requested_items": (True, "lines.positive_ok", None)}


def test_an_empty_list_has_too_few_rows():
    assert _checks([])["list_rows:requested_items"] == (False, "lines.too_few", "rows=0 min=1")


def test_a_row_without_a_named_value_is_named_by_its_number():
    rows = [{"description": "Monitor", "quantity": "2"}, {"description": None, "quantity": None, "unit": "db"}]
    assert _checks(rows)["list_values:requested_items"] == (False, "lines.value_missing",
                                                           "line 2: description; line 2: quantity")
    assert _checks(rows)["list_positive:requested_items"][0] is True  # an empty quantity is the other check's concern


def test_a_quantity_of_zero_or_below_is_not_positive():
    rows = [{"description": "Eger", "quantity": "0"}, {"description": "Billentyuzet", "quantity": "-1"}]
    assert _checks(rows)["list_positive:requested_items"] == (False, "lines.not_positive",
                                                             "line 1: quantity=0; line 2: quantity=-1")


def test_a_failed_list_check_is_a_to_do_at_the_list_field():
    state = FlowState(source_path="x.pdf", case_id="c", arm="G", doc_type="invoice_hu")
    state.validation = validators.run_checks(_record([]), SPECS)
    policy.apply_validation_policy(state)
    assert state.review_reasons == ["validator:lines.too_few:requested_items"]


def test_the_invoice_line_items_can_be_named_too():
    record, _ = record_from_llm({"line_items": [{"description": "Szolgaltatas", "quantity": "1", "net_amount": "100"}]},
                                typepack.get("invoice_hu").fields)
    assert validators.list_values(record, "line_items", ["description", "unit_price"]).detail == "line 1: unit_price"
    assert validators.list_positive(record, "line_items", ["quantity"]).ok
    assert record.line_items[0].quantity == Decimal("1")


# --- a list of plain values in the output model ----------------------------------------------------------------------


def test_without_the_switch_a_plain_list_is_still_a_list_of_empty_objects():
    """The behaviour every existing pack keeps (its request is pinned in tests/test_request_keys_190.py)."""
    pack = typepack.get("meeting_minutes")
    assert pack.plain_list_items is False
    with pytest.raises(ValidationError):
        pack.llm_model().model_validate({"attendees": ["Kiss Peter"]})
    assert pack.llm_model().model_validate({"attendees": [{}]}).attendees[0].model_dump() == {}


def test_with_the_switch_a_plain_list_holds_its_values():
    pack = typepack.get("meeting_minutes").model_copy(update={"plain_list_items": True})
    model = pack.llm_model()
    out = model.model_validate({"attendees": ["Kiss Peter", "Nagy Anna"], "agenda_items": ["Beszamolo"],
                                "resolutions": [{"number": "1/2026", "summary": "Elfogadva", "votes_for": 12}]})
    assert out.attendees == ["Kiss Peter", "Nagy Anna"] and out.agenda_items == ["Beszamolo"]
    assert out.resolutions[0].number == "1/2026"  # a list of objects is unchanged
    items = model.model_json_schema()["properties"]["attendees"]["items"]
    assert {t.get("type") for t in items["anyOf"]} == {"string", "null"}
    record, reasons = pack.normalize(out.model_dump())
    assert record.extra["attendees"] == ["Kiss Peter", "Nagy Anna"] and reasons == []
