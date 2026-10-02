"""090 (backlog Q-G-decimal): a unit price with four or more decimals from GPT is a plain decimal, not an ambiguous
separator. Utility tariffs are printed per kWh or m3 with four decimals ("37,4510 Ft/kWh"); GPT returns them in the
contract form, "37.4510". Four or more digits after one separator can never be a copied thousands group, so the value
was always read right; only the to-do was wrong. In the no-JEV measurement of 2026-10-02 every one of the 77
"ambiguous decimal" to-dos on the electricity and gas golden invoices was such a unit price.

Three decimals stay what they were: a copied thousands group ("28.000" = 28 000) or, without a group, a to-do.
Synthetic values only.
"""

from decimal import Decimal

import pytest

from jav import numbers
from jav.models import normalize_value, record_from_llm


@pytest.mark.parametrize("raw", ["37.4510", "1.2345", "123.4567", "0.98531"])
@pytest.mark.parametrize("convention", [None, "comma", "dot"])
def test_a_gpt_unit_price_with_four_or_more_decimals_is_read_without_a_to_do(raw, convention):
    rec, reasons = record_from_llm({"line_items": [{"description": "Energia", "quantity": "882", "unit_price": raw}]},
                                   {"line_items": "list"}, convention=convention)
    assert rec.line_items[0].unit_price == Decimal(raw)
    assert reasons == []


def test_any_gpt_amount_in_the_contract_form_with_four_decimals_is_plain():
    reasons: list[str] = []
    assert normalize_value("money", "54732.1250", "amount_due", reasons) == Decimal("54732.1250")
    assert reasons == []


@pytest.mark.parametrize("raw, expected", [("28.000", Decimal("28000")), ("1.234.567", Decimal("1234567"))])
def test_a_copied_thousands_group_is_still_read_whole(raw, expected):
    reasons: list[str] = []
    assert normalize_value("money", raw, "net_total", reasons) == expected
    assert reasons == []


def test_three_decimals_without_a_group_are_still_a_to_do():
    reasons: list[str] = []
    assert normalize_value("money", "1234.567", "net_total", reasons) == Decimal("1234.567")
    assert reasons == ["money:separator_ambiguous:net_total:'1234.567'"]


def test_printed_text_is_read_as_before():
    """Only the contract form of a GPT value changed; printed text keeps its rules (S path, selection on the image)."""
    assert numbers.read_number("37,4510", kind="money").ambiguous
    assert numbers.read_number("37,4510", kind="money").value == Decimal("37.4510")
