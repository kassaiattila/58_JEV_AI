"""Source location boxes (053, decision of 2026-09-28): a value that appears in several places gets its box at the most
likely place, the currency also matches the printed "Ft", and the rows of the itemised list get their place on the
image. Synthetic word layer, no AI call."""

from jav import grounding
from jav.reground import reground_provenance
from tests.test_grounding import layer_of


# --- value appearing in several places ----------------------------------------------------------------


def test_repeated_value_without_label_gets_the_first_place_and_the_rest_as_alternatives():
    layer = layer_of([
        [("Sorszam", 20), ("800087654321", 200)],
        [("Csekk", 20), ("800087654321", 300)],
        [("Hivatkozas", 20), ("800087654321", 400)],
    ])
    r = grounding.locate_value(layer, "invoice_number", "800087654321", field="invoice_number")
    assert r["status"] == "located" and r["multiple"] == 3
    assert r["quote"] == "800087654321" and r["bbox"][1] < 0.1  # the first (topmost) occurrence
    assert len(r["alternatives"]) == 2


def test_repeated_value_prefers_the_place_next_to_its_own_label():
    layer = layer_of([
        [("Tetel", 20), ("12", 200), ("700", 218)],
        [("Brutto", 20), ("osszeg:", 64), ("12", 200), ("700", 218)],
        [("Mas", 20), ("12", 200), ("700", 218)],
    ])
    r = grounding.locate_value(layer, "money", "12700", field="gross_total")
    assert r["status"] == "located" and r["label"] is True and r["quote"] == "12 700"
    assert r["bbox"][1] > 0.07  # the second line, next to the label


def test_value_only_next_to_other_fields_labels_still_gets_no_frame():
    layer = layer_of([[("Teljesites", 20), ("datuma:", 90), ("2026.09.01.", 200)]])
    assert grounding.locate_value(layer, "date", "2026-09-01", field="issue_date")["status"] == "context_rejected"


def test_currency_matches_the_printed_forint_sign():
    layer = layer_of([[("Fizetendo:", 20), ("43", 200), ("543", 218), ("Ft", 242)]])
    r = grounding.locate_value(layer, "currency", "HUF", field="currency")
    assert r["status"] == "located" and r["quote"] == "Ft"
    eur = layer_of([[("Total:", 20), ("12.00", 200), ("EUR", 240)]])
    assert grounding.locate_value(eur, "currency", "EUR", field="currency")["status"] == "located"


# --- line items ------------------------------------------------------------------------------------------

KINDS = {"description": "text", "quantity": "number", "unit_price": "money", "net_amount": "money", "gross_amount": "money"}


def _table():
    return layer_of([
        [("Tetelek", 20)],
        [("Alapdij", 20), ("1", 200), ("261", 260), ("261", 320), ("331", 380)],
        [("Energiadij", 20), ("38", 200), ("172,40", 260), ("6", 320), ("551", 332), ("8", 380), ("320", 392)],
        [("Rendszerhasznalat", 20), ("1", 200), ("261", 260), ("261", 320), ("331", 380)],  # the same amounts
        [("Osszesen:", 20), ("7", 320), ("073", 332)],
    ])


def test_rows_are_located_by_their_amounts_in_document_order():
    rows = [
        {"description": "Alapdij", "quantity": 1, "unit_price": "261", "net_amount": "261", "gross_amount": "331"},
        {"description": "Energiadij", "quantity": 38, "unit_price": "172.40", "net_amount": "6551", "gross_amount": "8320"},
        {"description": "Rendszerhasznalat", "quantity": 1, "unit_price": "261", "net_amount": "261", "gross_amount": "331"},
    ]
    out = grounding.locate_rows(_table(), rows, KINDS)
    assert [r["status"] for r in out] == ["located", "located", "located"]
    tops = [r["bbox"][1] for r in out]
    assert tops == sorted(tops) and len(set(tops)) == 3  # the row with repeated amounts lands on the next line
    assert out[1]["quote"].startswith("Energiadij")


def test_a_statement_row_is_found_by_its_amount_printed_with_a_minus_sign():
    # 138: a statement prints a debit as "-44.970,00" while the extraction keeps the amount unsigned with its direction;
    # without the amount both lines hold only the two dates, and the first one would win
    layer = layer_of([
        [("2026.06.08.", 20), ("2026.06.06.", 90), ("Example", 160), ("Shop", 210), ("-29.764,00", 300)],
        [("2026.06.08.", 20), ("2026.06.06.", 90), ("Example", 160), ("Store", 210), ("-44.970,00", 300)],
    ])
    kinds = {"booking_date": "date", "value_date": "date", "amount": "money", "counterparty_name": "text"}
    rows = [{"booking_date": "2026-06-08", "value_date": "2026-06-06", "amount": "44970", "counterparty_name": "Example Store"}]
    [found] = grounding.locate_rows(layer, rows, kinds)
    assert found["status"] == "located" and found["quote"].endswith("-44.970,00")


def test_row_without_findable_values_has_no_frame():
    out = grounding.locate_rows(_table(), [{"description": "Nincs ilyen", "net_amount": "999999"}, {}], KINDS)
    assert [r["status"] for r in out] == ["not_found", "no_value"]


def test_ground_lists_wraps_rows_per_list_field():
    out = grounding.ground_lists(_table(), lists={"line_items": [{"net_amount": "6551", "gross_amount": "8320"}]},
                                 kinds={"line_items": KINDS})
    assert out["line_items"]["status"] == "list" and out["line_items"]["rows"][0]["status"] == "located"


# --- recomputing the source locations of an existing run ---------------------------------------------------


def test_reground_keeps_exact_picks_and_recomputes_searches_and_rows():
    layer = _table()
    old = {
        "net_total": {"status": "ambiguous", "method": "search", "alternatives": [], "confidence": 0.8},
        "gross_total": {"status": "located", "method": "pick", "page": 1, "bbox": [0, 0, 0.1, 0.1], "alternatives": [], "confidence": 0.9},
    }
    fields = {"net_total": "money", "gross_total": "money", "line_items": "list"}
    values = {"net_total": "261", "gross_total": "7073",
              "line_items": [{"description": "Alapdij", "net_amount": "261", "gross_amount": "331"}]}
    new = reground_provenance(layer, old, fields=fields, values=values, list_kinds={"line_items": KINDS})
    assert new["gross_total"] == old["gross_total"]  # the chosen candidate's exact location stays
    assert new["net_total"]["status"] == "located" and new["net_total"]["confidence"] == 0.8
    assert new["line_items"]["rows"][0]["status"] == "located"


def test_reground_keeps_the_basis_of_a_gpt_confidence():
    """092: a recomputed box keeps the field's GPT confidence together with its basis (091), so the review still shows
    it in GPT's own band."""
    layer = _table()
    basis = {"source": "gpt", "measure": "joint", "token": 0.97, "failed_check": False}
    old = {"net_total": {"status": "not_found", "method": "search", "alternatives": [], "confidence": 0.97, "confidence_basis": basis}}
    new = reground_provenance(layer, old, fields={"net_total": "money"}, values={"net_total": "261"}, list_kinds={})
    assert new["net_total"]["status"] == "located"
    assert new["net_total"]["confidence"] == 0.97 and new["net_total"]["confidence_basis"] == basis
