"""092: source boxes for values the G path extracts in a different form than the document prints.

The owner's report: on some invoices the field's source was not framed on the image, sometimes not even for a field
with 100% confidence. A replay of the search on a real run found the causes reproduced here, on synthetic word layers
(the `layer_of` geometry: 6 pt per character, 20 pt line pitch, 600 x 800 pt page): an address on several lines of a
two-column header, punctuation or a different order in the extracted address, several identifiers in one field, an
identifier glued to a label word, a currency sign glued to the amount, a country code against the printed country name,
and a label with its own value on its line counted as the heading of the lines below it.
"""

from __future__ import annotations

from jav import grounding
from tests.test_grounding import layer_of

LEFT, RIGHT = 20, 320

TWO_COLUMN_HEADER = [
    [("ELADO", LEFT), ("VEVO", RIGHT)],
    [("Minta", LEFT), ("Kft.", LEFT + 36), ("Pelda", RIGHT), ("Bt.", RIGHT + 36)],
    [("Szeged", LEFT), ("Debrecen", RIGHT)],
    [("Fo", LEFT), ("utca", LEFT + 16), ("1.", LEFT + 46), ("2.", LEFT + 62), ("em.", LEFT + 78), ("Kossuth", RIGHT), ("ter", RIGHT + 46), ("5.", RIGHT + 68)],
    [("6720", LEFT), ("4024", RIGHT)],
    [("Magyarorszag", LEFT), ("Magyarorszag", RIGHT)],
]


def test_an_address_on_four_lines_of_a_two_column_header_is_found():
    layer = layer_of(TWO_COLUMN_HEADER)
    seller = grounding.locate_value(layer, "address", "Szeged Fo utca 1. 2. em. 6720 Magyarorszag", field="supplier_address")
    assert seller["status"] == "located" and len(seller["boxes"]) == 4
    assert seller["quote"] == "Szeged Fo utca 1. 2. em. 6720 Magyarorszag"
    assert all(b[0] < 0.3 for b in seller["boxes"])  # the left column only
    buyer = grounding.locate_value(layer, "address", "Debrecen Kossuth ter 5. 4024 Magyarorszag", field="buyer_address")
    assert buyer["status"] == "located" and all(b[0] > 0.5 for b in buyer["boxes"])


def test_punctuation_added_to_an_address_does_not_matter():
    layer = layer_of(TWO_COLUMN_HEADER)
    r = grounding.locate_value(layer, "address", "Debrecen, Kossuth ter 5., 4024, Magyarorszag", field="buyer_address")
    assert r["status"] == "located" and r["quote"] == "Debrecen Kossuth ter 5. 4024 Magyarorszag"


def test_a_reordered_address_is_found_in_its_column_block():
    layer = layer_of([
        [("Bill", RIGHT), ("to", RIGHT + 28)],
        [("Pelda", RIGHT), ("Bt.", RIGHT + 36)],
        [("Kossuth", RIGHT), ("ter", RIGHT + 46), ("5", RIGHT + 68)],
        [("4024", RIGHT), ("Debrecen", RIGHT + 28)],
        [("Hungary", RIGHT)],
    ])
    r = grounding.locate_value(layer, "address", "Debrecen Kossuth ter 5 4024 Hungary", field="buyer_address")
    assert r["status"] == "located" and len(r["boxes"]) == 3
    assert sorted(r["quote"].split()) == sorted("Kossuth ter 5 4024 Debrecen Hungary".split())


def test_a_reordered_address_is_not_assembled_from_far_apart_words():
    layer = layer_of([
        [("Debrecen", LEFT)],
        [("Kossuth", LEFT), ("ter", LEFT + 46)],
        [("Lorem", LEFT), ("ipsum", LEFT + 34)],
        [("Dolor", LEFT), ("sit", LEFT + 34)],
        [("Amet", LEFT)],
        [("Consectetur", LEFT)],
        [("4024", LEFT), ("5", LEFT + 28)],
    ])
    assert grounding.locate_value(layer, "address", "Debrecen Kossuth ter 5 4024", field="buyer_address")["status"] == "not_found"


def test_identifiers_listed_in_one_field_are_located_part_by_part():
    layer = layer_of([
        [("Minta", LEFT), ("Pty.", LEFT + 34), ("Ltd.ABN", LEFT + 64), ("12", LEFT + 110), ("345", LEFT + 126), ("678", LEFT + 148),
         ("901,", LEFT + 170), ("VAT", LEFT + 198), ("EU123456789", LEFT + 220)],
    ])
    r = grounding.locate_value(layer, "tax_id", "ABN 12 345 678 901, VAT EU123456789", field="supplier_tax_id")
    assert r["status"] == "located" and r["quote"] == "Ltd.ABN 12 345 678 901, VAT EU123456789"  # one run on its line
    apart = layer_of([[("ABN", LEFT), ("12", LEFT + 22), ("345", LEFT + 38), ("678", LEFT + 60), ("901", LEFT + 82)],
                      [("Minta", LEFT), ("utca", LEFT + 34)], [("VAT", LEFT), ("EU123456789", LEFT + 22)]])
    r = grounding.locate_value(apart, "tax_id", "ABN 12 345 678 901; VAT EU123456789", field="supplier_tax_id")
    assert r["status"] == "located" and r["method"] == "search_parts" and len(r["boxes"]) == 2
    assert "Minta" not in r["quote"] and r["quote"].endswith("EU123456789")
    missing = grounding.locate_value(apart, "tax_id", "ABN 12 345 678 901, VAT EU999999999", field="supplier_tax_id")
    assert missing["status"] == "not_found"  # every part must be found


def test_an_identifier_glued_to_a_label_word_is_found_but_not_inside_a_longer_number():
    layer = layer_of([[("Adoszam:", LEFT), ("Ltd.ABN", LEFT + 60), ("12", LEFT + 106), ("345", LEFT + 122)], [("99123459", LEFT)]])
    assert grounding.locate_value(layer, "tax_id", "ABN 12 345", field="supplier_tax_id")["quote"] == "Ltd.ABN 12 345"
    assert grounding.locate_value(layer, "tax_id", "123459", field="supplier_tax_id")["status"] == "not_found"


def test_a_currency_sign_glued_to_the_amount_gives_the_currency():
    euro = layer_of([[("Total", LEFT), ("€20.00", 400)]])
    assert grounding.locate_value(euro, "currency", "EUR", field="currency")["quote"] == "€20.00"
    dollar = layer_of([[("Teljes", LEFT), ("terheles", LEFT + 40), ("14,99", 400), ("US$", 434)]])
    assert grounding.locate_value(dollar, "currency", "USD", field="currency")["quote"] == "US$"
    plain = layer_of([[("Total", LEFT), ("$20.00", 400)]])
    assert grounding.locate_value(plain, "currency", "USD", field="currency")["quote"] == "$20.00"
    assert grounding.locate_value(euro, "currency", "USD", field="currency")["status"] == "not_found"


def test_a_country_code_matches_the_printed_country_name():
    layer = layer_of([[("110", LEFT), ("Minta", LEFT + 22), ("St.", LEFT + 56)], [("Sydney", LEFT), ("Australia", LEFT + 40)],
                      [("Meet", LEFT), ("us", LEFT + 28), ("at", LEFT + 44), ("the", LEFT + 60), ("fair", LEFT + 82)]])
    r = grounding.locate_value(layer, "country", "AU", field="supplier_country")
    assert r["status"] == "located" and r["quote"] == "Australia"
    assert grounding.locate_value(layer, "country", "AT", field="supplier_country")["status"] == "not_found"  # "at" is a word
    us = layer_of([[("United", LEFT), ("States", LEFT + 40)]])
    assert grounding.locate_value(us, "country", "US", field="supplier_country")["quote"] == "United States"


def test_a_label_with_its_own_value_on_its_line_does_not_label_the_lines_below():
    layer = layer_of([
        [("Invoice", LEFT), ("number", LEFT + 46), ("AB12-0001", LEFT + 88)],
        [("Date", LEFT), ("of", LEFT + 28), ("payment", LEFT + 44), ("June", LEFT + 92), ("30,", LEFT + 120), ("2025", LEFT + 142)],
        [("Minta,", LEFT), ("LLC", LEFT + 40)],
    ])
    r = grounding.locate_value(layer, "name", "Minta, LLC", field="supplier_name")
    assert r["status"] == "located"


def test_a_column_header_still_labels_a_total_several_rows_below():
    """A table's column header stands alone in its segment and labels every row of its column, the total too."""
    layer = layer_of([
        [("Tetel", LEFT), ("Brutto", 480)],
        [("Energia", LEFT), ("11.890", 480)],
        [("Rendszer", LEFT), ("14.241", 480)],
        [("Osszesen", LEFT), ("26.130", 480)],
        [("Csekk", LEFT), ("<000026130>", 300)],
    ])
    r = grounding.locate_value(layer, "money", "26130", field="gross_total")
    assert r["status"] == "located" and r["quote"] == "26.130" and r["label"] is True


def test_the_billing_address_label_belongs_to_the_buyer():
    layer = layer_of([
        [("Szamla", RIGHT), ("szama", RIGHT + 40)],
        [("12345-678", RIGHT)],
        [("Szamlazasi", RIGHT), ("cim", RIGHT + 64)],
        [("Hungary", RIGHT)],
    ])
    r = grounding.locate_value(layer, "address", "Hungary", field="buyer_address")
    assert r["status"] == "located" and r["label"] is True


def _line_layout(layer):
    from jav.grounding import _lines, _segments
    from jav.models import LineLayout

    return [LineLayout(no=n, page=1, text="   ".join(" ".join(w.text for w in seg) for seg in _segments(line)))
            for n, line in enumerate(_lines(layer), 1)]


def test_a_value_with_a_box_gets_no_not_printed_to_do_without_jev():
    """The code's own source check (G path without JEV) and the box use the same rules: an address found on four lines
    of a two-column header is printed, so no `source:not_found` to-do."""
    from jav.jev_verify import code_verdicts
    from jav.typepack import get as get_pack

    layer = layer_of(TWO_COLUMN_HEADER)
    llm = {"supplier_address": "Szeged Fo utca 1. 2. em. 6720 Magyarorszag", "buyer_address": "Sopron Varkerulet 9."}
    pack = get_pack("invoice_hu")
    assert "supplier_address" in code_verdicts(_line_layout(layer), llm, pack=pack).unsupported  # whole lines only
    verdicts = code_verdicts(_line_layout(layer), llm, pack=pack, layer=layer)
    assert "supplier_address" not in verdicts.unsupported and "buyer_address" in verdicts.unsupported
    assert grounding.printed(layer, "address", "Sopron Varkerulet 9.") is False
