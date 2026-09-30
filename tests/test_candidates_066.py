"""066 audit (Á03): side effects of the 065 invoice-number labels, on synthetic lines.

Without a word boundary, the new labels of 065 (order number, transaction id, credit note) also matched the advert line
("Order now…"), picked up amounts from the surrounding lines as invoice-number candidates, and masking the
invoice-number candidate also hid a short number inside larger amounts: the grand total dropped out of the money
candidates. Every number is made up."""

from tests.test_candidates_065 import _labels, _lines


def test_order_number_label_does_not_swallow_the_total_below():
    layout = _lines("Order number: 12345", "Total   $45.00")
    assert "45" in _labels(layout, "money", "intl")
    assert _labels(layout, "invoice_number", "intl") == ["12345"]


def test_advertising_line_is_not_an_order_label():
    layout = _lines("Subtotal   40.00 EUR", "Order now and save 10%!", "Total   45.00 EUR")
    assert {"40", "45"} <= set(_labels(layout, "money", "intl"))
    assert _labels(layout, "invoice_number", "intl") == []


def test_word_ending_in_order_is_not_an_order_label():
    layout = _lines("Digital recorder Number 2   99.90 EUR")
    assert "99.9" in _labels(layout, "money", "intl")


def test_credit_note_amount_line_keeps_its_amounts():
    layout = _lines("Credit Note Amount   45.00 EUR", "VAT   0.00")
    assert {"45", "0"} <= set(_labels(layout, "money", "intl"))


def test_purchase_order_line_does_not_mask_the_grand_total():
    layout = _lines("Invoice No: INV-0042", "Purchase Order Number: PO-7781", "Total   1,250.00 EUR")
    assert "1250" in _labels(layout, "money", "intl")
    assert "INV-0042" in _labels(layout, "invoice_number", "intl")


def test_short_invoice_number_is_not_masked_inside_amounts():
    layout = _lines("Számla sorszáma: 15", "Kelt: 2026.01.05.", "Vevő: Minta Kft.", "Nettó összesen   1 150,00 Ft", "Fizetendő   15 000 Ft")
    money = _labels(layout, "money", "hu")
    assert {"1150", "15000"} <= set(money), money
    assert "15" in _labels(layout, "invoice_number", "hu")


def test_bare_year_or_amount_below_a_title_is_not_an_invoice_number():
    layout = _lines("SZÁMLA", "2026", "Összesen   2026 Ft")
    assert "2026" in _labels(layout, "money", "hu")
    assert _labels(layout, "invoice_number", "hu") == []
    layout = _lines("Receipt", "45.00", "Total paid   45.00 USD")
    assert "45" in _labels(layout, "money", "intl")
    assert _labels(layout, "invoice_number", "intl") == []
