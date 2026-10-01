"""081 number reading (the owner's report of 2026-10-01): one shared, safe number reader.

A Billzone invoice printed in English notation ("28,000.00") was read as net 28 / VAT 7.56 / gross 35.56 on the S path:
the Hungarian candidate pattern cut "28,000" to "28,00". Every path now reads numbers through `jav/numbers.py`:

- a number is never cut apart;
- money never has three decimals, so "28.000" and "28,000" are both 28 000;
- a quantity (kWh, meter reading, correction factor) follows the document's own notation, and is flagged when that is
  unknown;
- manual input follows the Hungarian habit and refuses an ambiguous form.

Synthetic lines only, no model calls.
"""

from decimal import Decimal

import pytest

from jav import numbers
from jav.candidates import find_all
from jav.models import CellLayout, LineLayout, normalize_value, parse_money, record_from_llm
from jav.runtime import worker
from tests.test_api import HUMAN, _ready_wp, _start, env  # noqa: F401 - the shared service fixture (`service` below)


def _lines(*texts: str) -> list[LineLayout]:
    out = []
    for no, text in enumerate(texts, 1):
        cells = [CellLayout(text=c, x0=30 + 200 * k, x1=30 + 200 * k + 6 * len(c)) for k, c in enumerate(text.split("   "))]
        out.append(LineLayout(no=no, page=1, text=text, cells=cells))
    return out


# --- the reader ------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    ("28,000", Decimal("28000")),
    ("28.000", Decimal("28000")),
    ("28,000.00", Decimal("28000")),
    ("1,600.00", Decimal("1600")),
    ("1,234,567", Decimal("1234567")),
    ("12.345,67", Decimal("12345.67")),
    ("20 619,05", Decimal("20619.05")),
    ("28,5", Decimal("28.5")),
    ("$1,600", Decimal("1600")),
])
def test_money_is_never_read_with_three_decimals(raw, expected):
    got = numbers.read_number(raw, kind="money")
    assert (got.value, got.ambiguous) == (expected, False)


@pytest.mark.parametrize("raw", ["28.000 EUR", "€28.000", "28.000 USD"])
def test_a_currency_sign_does_not_turn_a_thousands_dot_into_a_decimal_point(raw):
    got = numbers.read_number(raw, kind="money", intl=True)
    assert (got.value, got.ambiguous) == (Decimal("28000"), False)


@pytest.mark.parametrize("raw, value", [("1234.567", "1234.567"), ("1234,567", "1234.567"), ("0,500", "0.500")])
def test_money_with_three_decimals_that_is_no_grouping_is_flagged(raw, value):
    got = numbers.read_number(raw, kind="money")
    assert (got.value, got.ambiguous) == (Decimal(value), True)


def test_the_unchanged_cases_keep_their_reading():
    assert numbers.read_number("12.34", kind="money").ambiguous is True  # undecidable, as before
    assert numbers.read_number("1 234 567", kind="money").value == Decimal("1234567")
    assert numbers.read_number("-19 556", kind="money").value == Decimal("-19556")
    assert numbers.read_number("12 000,-", kind="money").value == Decimal("12000")
    assert numbers.read_number("n/a", kind="money").value is None


@pytest.mark.parametrize("raw, convention, value, ambiguous", [
    ("1.153", "comma", "1153", False),  # Hungarian document: the dot groups thousands
    ("1.153", "dot", "1.153", False),  # English document: the dot is the decimal point
    ("1.153", None, "1153", True),  # unknown notation: the Hungarian reading, flagged
    ("1,153", "comma", "1.153", False),
    ("1,153", "dot", "1153", False),
    ("1,153", None, "1.153", True),
    ("1.0000", None, "1.0000", False),  # four decimals cannot be a thousands group
    ("143,00", None, "143.00", False),
    ("30.201", "comma", "30201", False),
])
def test_a_quantity_follows_the_documents_notation(raw, convention, value, ambiguous):
    got = numbers.read_number(raw, kind="number", convention=convention)
    assert (got.value, got.ambiguous) == (Decimal(value), ambiguous)


@pytest.mark.parametrize("texts, expected", [
    (["Megnevezés   Nettó érték", "Billzone   28,000.00   7,560.00", "Sum   28,000   7,560   35,560"], "dot"),
    (["Összesen:   1 234,56 Ft", "ÁFA 27%   333,33"], "comma"),
    (["143,00   34,92   3,3900 Ft/kWh", "Korrekciós tényező 1.0000"], "comma"),
    (["Kelt: 2024.01.09.", "Fizetendő   12.345 Ft"], None),  # a date and a lone group decide nothing
    ([], None),
])
def test_the_documents_notation_is_read_from_its_decisive_numbers(texts, expected):
    assert numbers.document_convention(texts) == expected


# --- manual input (the owner's decision: the Hungarian habit, an ambiguous form is refused) ---------------------------


@pytest.mark.parametrize("raw, kind, expected", [
    ("28.000", "money", "28000"),
    ("28 000", "money", "28000"),
    ("28000", "money", "28000"),
    ("28,5", "money", "28.5"),
    ("28 000,50", "money", "28000.5"),
    ("28.000,50", "money", "28000.5"),
    ("-1 234,5", "money", "-1234.5"),
    ("28,000.00", "money", "28000"),
    ("1.153", "number", "1153"),
    ("1,153", "number", "1.153"),
    ("0.9853", "number", "0.9853"),
])
def test_manual_input_follows_the_hungarian_habit(raw, kind, expected):
    assert numbers.read_input(raw, kind=kind) == expected


@pytest.mark.parametrize("raw, kind", [("28.5", "money"), ("35.56", "money"), ("28,000", "money"), ("1.5", "number")])
def test_an_ambiguous_manual_input_is_refused(raw, kind):
    with pytest.raises(numbers.AmbiguousNumber):
        numbers.read_input(raw, kind=kind)


def test_text_that_is_not_a_number_is_refused():
    with pytest.raises(ValueError):
        numbers.read_input("huszonnyolc", kind="money")


# --- whole tokens ----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw, line, whole", [
    ("28,00", "Billzone   28,000.00   7,560.00", False),
    ("28,000.00", "Billzone   28,000.00   7,560.00", True),
    ("28", "Sum   28,000", False),
    ("1 234,56", "Összesen: 1 234,56 Ft", True),
    ("2", "ÁFA 2 db", True),
])
def test_a_candidate_must_be_a_whole_token_of_its_line(raw, line, whole):
    assert numbers.is_whole_token(raw, line) is whole


# --- the S path: candidates ------------------------------------------------------------------------------------------


def test_english_notation_on_a_hungarian_invoice_gives_whole_amounts():
    lines = _lines(
        "Megnevezés   Mennyiség   Nettó egységár   Nettó érték   ÁFA   ÁFA érték   Bruttó érték",
        "Billzone.eu - BASIC   1   Darab   28,000.00   28,000.00   27%   7,560.00   35,560.00",
        "27%   28,000   7,560   35,560",
        "Invoice total   35,560 HUF",
    )
    labels = {c.label for c in find_all(lines, "hu")["money"]}
    assert {"28000", "7560", "35560"} <= labels
    assert not labels & {"28", "7.56", "35.56"}


def test_hungarian_notation_is_unchanged():
    lines = _lines("Nettó összesen:   127 000", "ÁFA 27%:   34 290", "Fizetendő:   161 290 Ft", "Kerekítés   20 619,05")
    labels = {c.label for c in find_all(lines, "hu")["money"]}
    assert {"127000", "34290", "161290", "20619.05"} <= labels


def test_a_quantity_with_four_decimals_is_a_candidate_and_not_a_thousand():
    lines = _lines("Mérő   Induló   Záró   Fogyasztás   Korrekciós tényező", "1801175889   143,00   34,92   1.0000   4994")
    labels = {c.label for c in find_all(lines, "hu")["quantity"]}
    assert "1" in labels and "1000" not in labels


def test_meter_readings_with_a_thousands_dot_on_a_hungarian_bill():
    lines = _lines("Fogyasztás összesen:   1.153 kWh", "9902741612   30.201   31.354   Leol   1.153", "Átviteli díj   1.153 kWh   3,3900 Ft/kWh")
    labels = {c.label for c in find_all(lines, "hu")["quantity"]}
    assert {"1153", "30201", "31354"} <= labels


# --- the G path: GPT values ------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    ("28000.00", Decimal("28000.00")),
    ("28.000", Decimal("28000")),
    ("28,000.00", Decimal("28000")),
    ("1 234,56", Decimal("1234.56")),
    ("12.34", Decimal("12.34")),  # the contract form: a decimal point with two decimals
])
def test_a_gpt_amount_copied_in_the_documents_notation_is_read_whole(raw, expected):
    reasons: list[str] = []
    assert normalize_value("money", raw, "net_total", reasons) == expected
    assert reasons == []


def test_a_gpt_quantity_follows_the_documents_notation():
    reasons: list[str] = []
    assert normalize_value("number", "1.153", "consumption_kwh", reasons, convention="comma") == Decimal("1153")
    assert normalize_value("number", 1.153, "consumption_kwh", reasons, convention="dot") == Decimal("1.153")
    assert reasons == []
    assert normalize_value("number", 1.153, "consumption_kwh", reasons) == Decimal("1153")
    assert reasons == ["money:separator_ambiguous:consumption_kwh:'1.153'"]


def test_a_gpt_line_item_quantity_is_read_like_a_quantity():
    rec, reasons = record_from_llm({"line_items": [{"description": "Áram", "quantity": "1.153", "net_amount": "3.909"}]},
                                   {"line_items": "list"}, convention="comma")
    assert rec.line_items[0].quantity == Decimal("1153")
    assert rec.line_items[0].net_amount == Decimal("3909")
    assert reasons == []


def test_stored_values_are_read_as_stored():
    reasons: list[str] = []
    assert normalize_value("number", "1.153", "consumption_kwh", reasons, origin="canonical") == Decimal("1.153")
    assert normalize_value("money", "35.56", "gross_total", reasons, origin="canonical") == Decimal("35.56")
    assert reasons == []


def test_parse_money_keeps_its_old_signature():
    assert parse_money("28,000").value == Decimal("28000")
    assert parse_money("12.345").value == Decimal("12345")


# --- the S path's safety net -----------------------------------------------------------------------------------------


def test_a_picked_amount_that_is_a_piece_of_a_longer_number_gets_a_to_do():
    from jav.jev_select import site_for
    from jav.models import Candidate, FieldPick

    lines = _lines("Megnevezés   Nettó érték", "Billzone   28,000.00   7,560.00")
    cut = Candidate(kind="money", label="28", raw="28,00", line_no=2, context="L02")
    picks = {"net_total": FieldPick(field="net_total", label="28", raw="28,00", confidence=0.9, n_options=1, request_id="money")}
    inv, reasons = site_for("invoice_hu").picks_to_invoice(picks, {"money": [cut]}, lines)
    assert inv.net_total == Decimal("28")
    assert "money:token_cut:net_total:'28,00'" in reasons


def test_a_whole_picked_amount_passes_the_safety_net():
    from jav.jev_select import site_for
    from jav.models import Candidate, FieldPick

    lines = _lines("Megnevezés   Nettó érték", "Billzone   28,000.00   7,560.00")
    whole = Candidate(kind="money", label="28000", raw="28,000.00", line_no=2, context="L02")
    picks = {"net_total": FieldPick(field="net_total", label="28000", raw="28,000.00", confidence=0.9, n_options=1, request_id="money")}
    _inv, reasons = site_for("invoice_hu").picks_to_invoice(picks, {"money": [whole]}, lines)
    assert not [r for r in reasons if r.startswith("money:")]


# --- manual correction and the image selection over the local service -------------------------------------------------

@pytest.fixture()
def service(request):
    """The local service over synthetic invoices (the `env` fixture of the service tests)."""
    return request.getfixturevalue("env")


def _corrected(service):
    c = service["client"]
    wp = _ready_wp(c, service["folder"])
    run_id = _start(c, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    return c, run_id, wp["items"][0]["item_id"]


def test_a_typed_amount_is_read_the_hungarian_way_and_stored_canonically(service):
    c, run_id, item_id = _corrected(service)
    url = f"/api/runs/{run_id}/items/{item_id}/correction"
    r = c.post(url, headers=HUMAN, json={"fields": {"net_total": "28.000", "gross_total": "35 560,50"}, "expected_revision": 0})
    assert r.status_code == 200, r.text
    assert r.json()["correction"]["fields"] == {"net_total": "28000", "gross_total": "35560.5"}
    assert r.json()["kinds"]["net_total"] == "money"
    # the stored canonical value sent back unchanged is accepted; a new ambiguous one is refused
    again = c.post(url, headers=HUMAN, json={"fields": {"net_total": "28000", "gross_total": "35560.5", "vat_total": "7560"},
                                              "expected_revision": 1})
    assert again.status_code == 200, again.text
    bad = c.post(url, headers=HUMAN, json={"fields": {"net_total": "28000", "vat_total": "7.56"}, "expected_revision": 2})
    assert bad.status_code == 422 and bad.json()["error"] == "ambiguous_number"


def test_a_selection_on_the_page_image_is_read_whole(service):
    c = service["client"]
    r = c.post("/api/normalize", json={"doc_type": "invoice_hu", "field": "net_total", "text": "28,000.00"})
    assert r.status_code == 200, r.text
    assert (r.json()["ok"], r.json()["value"]) == (True, "28000.00")
    r = c.post("/api/normalize", json={"doc_type": "invoice_hu", "field": "net_total", "text": "28.000 Ft"})
    assert (r.json()["ok"], r.json()["value"]) == (True, "28000")


def test_a_foreign_amount_is_not_read_together_with_its_neighbour():
    lines = _lines("Description   Unit price   Qty", "Hosting   €11.99 1 pc   €11.99")
    labels = {c.label for c in find_all(lines, "intl")["money"]}
    assert "11.99" in labels
    assert not labels & {"11.991", "11991"}
