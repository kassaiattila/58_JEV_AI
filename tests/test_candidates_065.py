"""065: the candidate finder's gaps found in the joint trial (68 real incoming invoices), as general rules, on synthetic
lines.

The real documents do not go into the test; the identifiers are made up, only their shape follows the pattern seen in
the trial."""

from jav.candidates import find_all
from jav.models import CellLayout, LineLayout
from jav.pdf import fix_lost_glyphs


def _lines(*rows: str) -> list[LineLayout]:
    out = []
    for no, text in enumerate(rows, 1):
        cells = [CellLayout(text=t, x0=30 + 200 * k, x1=30 + 200 * k + 6 * len(t)) for k, t in enumerate(text.split("   "))]
        out.append(LineLayout(no=no, page=1, text=text, cells=cells))
    return out


def _labels(layout: list[LineLayout], kind: str, profile: str) -> list[str]:
    return [c.label for c in find_all(layout, profile)[kind]]


def test_lost_glyph_between_letters_or_digits_is_a_hyphen():
    # the PDF's font emits the hyphen as NUL (Stripe invoices): the invoice number fell into two pieces
    assert fix_lost_glyphs("AB12CD34\x000008") == "AB12CD34-0008"
    assert fix_lost_glyphs("91000\x004477") == "91000-4477"
    # at a word boundary (a lost letter, or a "+" sign before the number) we do not guess
    assert fix_lost_glyphs("Minta\x00") == "Minta\x00" and fix_lost_glyphs("\x001") == "\x001"


def test_title_line_followed_by_a_single_identifier_is_an_invoice_number_candidate():
    layout = _lines("Elektronikus számla", "mintaklub-2026-15", "ELADÓ   VEVŐ", "Minta Kft.   Vevő Kft.",
                    "SZÁMLA KELTE : 2026. 01. 05.   FIZETÉSI HATÁRIDŐ: 2026. 01. 05.")
    assert "mintaklub-2026-15" in _labels(layout, "invoice_number", "hu")
    # a multi-word line after the title (name, address) is not an invoice-number candidate
    layout = _lines("Számla", "Minta Kft. 1111 Budapest", "Eladó adatai", "Sorszám: MINTA-001")
    assert _labels(layout, "invoice_number", "hu") == ["MINTA-001"]


def test_intl_order_transaction_credit_note_and_billing_number_labels():
    layout = _lines("RECEIPT", "Order Number: 400000001", "Transaction ID   21X50000LL1000001",
                    "Credit Note   AB12CD34-0008-CN-01", "Számlázási szám   G100000001")
    labels = _labels(layout, "invoice_number", "intl")
    for want in ("400000001", "21X50000LL1000001", "AB12CD34-0008-CN-01", "G100000001"):
        assert want in labels, labels


def test_account_number_pattern_does_not_split_a_hyphenated_identifier():
    layout = _lines("Invoice number: 6300000000000001-4", "Bankszámla: 1234567812345678")
    assert "6300000000000001-4" in _labels(layout, "invoice_number", "intl")
    assert _labels(layout, "iban", "intl") == ["1234567812345678"]  # the lone 16-digit account number stays a candidate


def test_eu_oss_and_dutch_vat_ids_are_tax_id_candidates():
    layout = _lines("EU OSS VAT EU372000001", "NL VAT NL123456789B01", "HU VAT HU12345678")
    labels = _labels(layout, "tax_id", "intl")
    assert {"EU372000001", "NL123456789B01", "HU12345678"} <= set(labels), labels
