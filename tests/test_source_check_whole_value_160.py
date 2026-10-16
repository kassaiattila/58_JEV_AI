"""160 (review AI-1): the code's own source check (the G path without JEV, and the fallback when JEV is unavailable)
counts a value as printed only if the whole value stands on the document. It used to accept a part: a truncated
invoice number inside the printed one, a tax number missing its last digit, or an amount whose digits match a
printed amount with another decimal place ("1250" for "12,50"). On the JEV path a separate question catches a
truncated value; without JEV nothing did. A value found only in part now opens the same "not printed" to-do.
Synthetic documents only."""

from jav import typepack
from jav.jev_verify import code_verdicts, find_evidence
from jav.models import LineLayout
from jav.numbers import document_convention
from tests.pdfgen import INVOICE_LINES

GOOD = {"supplier_name": "Minta Kereskedelmi Kft.", "supplier_tax_id": "13570008-1-13", "buyer_name": "Proba Szolgaltato Bt.",
        "invoice_number": "MINTA-2026-001", "issue_date": "2026-09-01", "fulfillment_date": "2026-09-01",
        "due_date": "2026-09-15", "currency": "HUF", "net_total": "10000", "vat_total": "2700", "gross_total": "12700"}


def _lines(texts):
    return [LineLayout(no=i + 1, page=1, text=t) for i, t in enumerate(texts)]


def test_the_whole_printed_values_are_still_found():
    v = code_verdicts(_lines(INVOICE_LINES), GOOD, pack=typepack.get("invoice_hu"))
    assert v.unsupported == []


def test_a_truncated_invoice_number_is_not_printed():
    v = code_verdicts(_lines(INVOICE_LINES), {**GOOD, "invoice_number": "MINTA-2026-00"}, pack=typepack.get("invoice_hu"))
    assert v.unsupported == ["invoice_number"]


def test_a_tax_number_missing_its_last_digit_is_not_printed():
    v = code_verdicts(_lines(INVOICE_LINES), {**GOOD, "supplier_tax_id": "13570008-1-1"}, pack=typepack.get("invoice_hu"))
    assert v.unsupported == ["supplier_tax_id"]


def test_an_iban_missing_its_last_group_is_not_printed():
    lines = _lines([*INVOICE_LINES, "Bankszamla: HU42 1177 3016 1111 1018 0000 0000"])
    assert find_evidence("payment_iban", "HU42117730161111101800000000", lines, kind="iban")
    assert find_evidence("payment_iban", "HU421177301611111018", lines, kind="iban") == []


def test_an_amount_with_a_shifted_decimal_place_is_not_printed():
    pack = typepack.get("invoice_foreign")
    texts = ["Example GmbH", "Invoice no. RE-2026-17", "Net 10,00 EUR   VAT 2,50 EUR", "Total 12,50 EUR"]
    lines, conv = _lines(texts), document_convention(texts)
    assert find_evidence("gross_total", "12.50", lines, kind="money", intl=True, convention=conv) == ["L04: Total 12,50 EUR"]
    assert find_evidence("gross_total", "1250", lines, kind="money", intl=True, convention=conv) == []


def test_a_whole_extraction_scaled_by_a_hundred_is_not_printed():
    pack = typepack.get("invoice_foreign")
    texts = ["Example GmbH", "Invoice no. RE-2026-17", "Net 10,00 EUR   VAT 2,50 EUR", "Total 12,50 EUR"]
    v = code_verdicts(_lines(texts), {"net_total": "1000", "vat_total": "250", "gross_total": "1250"}, pack=pack)
    assert {"net_total", "vat_total", "gross_total"} <= set(v.unsupported)


def test_a_thousands_dot_amount_is_still_found_by_its_digits():
    # 054: "1.153" printed with a Hungarian thousands dot is the amount 1153
    lines = _lines(["Fizetendo: 1.153 Ft"])
    assert find_evidence("gross_total", "1153", lines, kind="money")


def _native_fact(tmp_path, monkeypatch, value):
    """The native path without JEV: one fact citing the quote "Order code: 0012"."""
    from jav import native_processing, native_results, store
    from jav.runtime import calls
    from tests.native_fixtures_109 import runtime_source, synthetic_gpt

    payload = {"facts": [{"entity": "order", "property": "code", "value": value, "state": "stated",
                          "citations": [{"occurrence_id": "o0", "element_id": "e0", "quote": "Order code: 0012"}]}], "gaps": []}
    with store.use_store(tmp_path / "native.sqlite"):
        _, ref = runtime_source(tmp_path, monkeypatch)
        synthetic_gpt(monkeypatch, payload=payload)
        limits = native_processing.estimate_limits({"jev": "off"})
        with calls.measurement("native-run", limits.provider_limits_usd):
            outcome_id = native_processing.interpret(work_run_id="native-run", item_id="native-item", graph_id="g-sub",
                                                     reading_id=ref.reading_id, jev=False, use_cache=False, limits=limits)
        _, _, interpretation = native_results.load_outcome(outcome_id)
    return interpretation.facts[0]


def test_native_value_standing_whole_in_its_quote_is_a_literal_match(tmp_path, monkeypatch):
    assert _native_fact(tmp_path, monkeypatch, "0012").grounding == "literal_match"


def test_native_value_that_is_part_of_a_longer_number_is_rejected(tmp_path, monkeypatch):
    fact = _native_fact(tmp_path, monkeypatch, "001")
    assert fact.grounding == "rejected"
    assert "Proposed literal value is absent from its citations" in fact.reasons
