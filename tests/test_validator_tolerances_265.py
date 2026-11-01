"""265 (code review AI-09): the arithmetic checks' tolerances come from configs/policy.json, with the values the code had.

A document without a currency is checked as before: its totals as another currency's (within 0.02), its line items' sum
as forints (within 2 or half a forint per item). Unifying the two is the owner's decision; the file names both. Synthetic
records, offline.
"""

from __future__ import annotations

from decimal import Decimal

from jav.ai import validators
from jav.ai.models import DocumentRecord, LineItem
from jav.core import cfg


def _totals(currency: str | None, gross: str) -> str:
    inv = DocumentRecord(currency=currency, net_total=Decimal("100.00"), vat_total=Decimal("27.00"), gross_total=Decimal(gross))
    return validators.vat_consistency(inv).code


def _line_sum(currency: str | None, net_total: str) -> bool:
    items = [LineItem(net_amount=Decimal("50.00")), LineItem(net_amount=Decimal("50.00"))]
    inv = DocumentRecord(currency=currency, line_items=items, net_total=Decimal(net_total))
    return validators.line_items_total(inv).ok


def test_the_tolerances_are_the_policy_files() -> None:
    assert cfg.load("policy")["validators"] == {
        "totals": {"huf": "1", "other": "0.02"},
        "line_sum": {"huf_min": "2", "huf_per_item": "0.5", "other_min": "0.02", "other_per_item": "0.005"},
        "line_arithmetic": {"min": "1", "percent": "1"},
        "missing_currency": {"totals": "other", "line_sum": "huf"},
    }


def test_the_totals_keep_their_tolerances_and_a_missing_currency_is_another_currencys() -> None:
    assert _totals("HUF", "128.00") == "totals.ok" and _totals("HUF", "128.01") == "totals.mismatch"
    assert _totals("EUR", "127.02") == "totals.ok" and _totals("EUR", "127.03") == "totals.mismatch"
    assert _totals(None, "127.02") == "totals.ok" and _totals(None, "127.50") == "totals.mismatch"


def test_the_line_sum_keeps_its_tolerances_and_a_missing_currency_is_forints() -> None:
    assert _line_sum("HUF", "102.00") and not _line_sum("HUF", "102.01")
    assert _line_sum("EUR", "100.02") and not _line_sum("EUR", "100.03")
    assert _line_sum(None, "101.50") and not _line_sum(None, "102.01")


def test_a_lines_arithmetic_is_within_one_or_one_percent() -> None:
    assert validators._line_tolerance(Decimal("50")) == Decimal("1")
    assert validators._line_tolerance(Decimal("-250")) == Decimal("2.5")
