"""A quote's numbers, computed by code from one price list version (191, plan F-quote-package B4a).

Plain-language summary (the 189 A1 judgement, DECISIONS 191): a quote's amounts are never a model's. Each line names a
price list item (or is a line of a person's own, outside the list) and a quantity; its unit price is the list's, its
discount the largest percent of the rules of its category whose quantity the line reaches, and its net amount is
unit price x quantity x (100 - discount) / 100, rounded on each line. The VAT is the list's rate on the net total,
rounded once; the gross total is their sum. In forints the rounding is to whole forints, in any other currency to cents
(`configs/price_lists.json` `rounding`, half up). A person may give a line a unit price or a discount of their own (the
editor records the note, B5); such a line says so, and a line outside the list always has a price of its own.

- `price(lines, price_list)`: the priced quote; `PricingError` when a line cannot be priced;
- `price_line(line, price_list)`, `totals(lines, price_list)`: one line, and the totals of priced lines (192, the editor);
- `golden_price_list(golden)`: the invented golden set's price list as a version; 204 (R1h): its quotes are priced and
  compared in the quotes domain's measurement module (`jav/domains/quotes/goldens.py`, the code-only golden set `quote:lines`).

Layer: business module of the quotes domain; pure code, no store, no AI call.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from jav.domains.quotes import price_lists

HUNDRED = Decimal(100)


class PricingError(ValueError):
    """A line that cannot be priced: an item the list does not have, a line outside the list without a price, a
    quantity of zero or less, a negative price, or a discount of 100 percent or more."""


@dataclass(frozen=True)
class LineInput:
    """One line as a person (or the proposal) gives it: a price list item (`sku`) or a line of its own (`sku` None, with
    its `description`, `unit` and `unit_price`), its quantity, and optionally a unit price or a discount of its own."""

    quantity: Decimal
    sku: str | None = None
    description: str | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    discount_percent: Decimal | None = None


@dataclass(frozen=True)
class PricedLine:
    sku: str | None
    name: str
    quantity: Decimal
    unit: str
    list_price: Decimal | None  # the price list's unit price; None outside the list
    unit_price: Decimal  # the price the line is priced at
    manual_price: bool  # a price of a person's own (outside the list, or over the list's)
    discount_percent: Decimal
    discount_from: str | None  # "rule", "manual", or None without a discount
    net: Decimal


@dataclass(frozen=True)
class PricedQuote:
    lines: tuple[PricedLine, ...]
    currency: str
    vat_percent: Decimal
    net_total: Decimal
    vat_total: Decimal
    gross_total: Decimal
    price_list: str
    version: int
    fingerprint: str


def rounding_unit(currency: str) -> Decimal:
    rules = price_lists.config()["rounding"]
    return Decimal(rules.get(currency, rules["default"]))


def _round(value: Decimal, unit: Decimal) -> Decimal:
    return value.quantize(unit, rounding=ROUND_HALF_UP)


def rule_discount(item: price_lists.Item, quantity: Decimal, rules: tuple[price_lists.Discount, ...]) -> Decimal:
    """The largest percent of the rules of the item's category whose quantity the line reaches (0 without one)."""
    return max((r.percent for r in rules if item.category and r.category == item.category and quantity >= r.min_quantity),
               default=Decimal(0))


def _line(line: LineInput, prices: price_lists.PriceList, unit: Decimal) -> PricedLine:
    if line.quantity <= 0:
        raise PricingError(f"the quantity must be more than zero: {line.quantity}")
    if line.unit_price is not None and line.unit_price < 0:
        raise PricingError(f"a unit price is not negative: {line.unit_price}")
    if line.discount_percent is not None and not 0 <= line.discount_percent < HUNDRED:
        raise PricingError(f"a discount is from 0 to less than 100 percent: {line.discount_percent}")
    if line.sku is None:
        if line.unit_price is None:
            raise PricingError("a line outside the price list needs a unit price")
        name, item_unit, list_price, rule = (line.description or "").strip(), (line.unit or "").strip(), None, Decimal(0)
        price = line.unit_price
    else:
        item = prices.item(line.sku)
        if item is None:
            raise PricingError(f"the item {line.sku} is not in the price list {prices.name} version {prices.version}")
        name, item_unit, list_price = item.name, item.unit, item.unit_price
        rule = rule_discount(item, line.quantity, prices.discounts)
        price = line.unit_price if line.unit_price is not None else item.unit_price
    percent = line.discount_percent if line.discount_percent is not None else rule
    source = "manual" if line.discount_percent is not None else ("rule" if rule else None)
    net = _round(price * line.quantity * (HUNDRED - percent) / HUNDRED, unit)
    return PricedLine(sku=line.sku, name=name, quantity=line.quantity, unit=item_unit, list_price=list_price,
                      unit_price=price, manual_price=line.unit_price is not None, discount_percent=percent,
                      discount_from=source, net=net)


def price_line(line: LineInput, prices: price_lists.PriceList) -> PricedLine:
    """One line priced on its own (192, B5: the editor prices each line, so a line that cannot be priced yet does not
    hide the others); `PricingError` when it cannot be priced."""
    return _line(line, prices, rounding_unit(prices.currency))


def totals(lines: Iterable[PricedLine], prices: price_lists.PriceList) -> tuple[Decimal, Decimal, Decimal]:
    """(net, VAT, gross) of priced lines: the VAT is the list's rate on the net total, rounded once."""
    net = sum((p.net for p in lines), Decimal(0))
    vat = _round(net * prices.vat_percent / HUNDRED, rounding_unit(prices.currency))
    return net, vat, net + vat


def price(lines: list[LineInput], prices: price_lists.PriceList) -> PricedQuote:
    priced = tuple(price_line(line, prices) for line in lines)
    net, vat, gross = totals(priced, prices)
    return PricedQuote(lines=priced, currency=prices.currency, vat_percent=prices.vat_percent, net_total=net,
                       vat_total=vat, gross_total=gross, price_list=prices.price_list, version=prices.version,
                       fingerprint=prices.fingerprint)


# --- the golden set ----------------------------------------------------------------------------------------------------


def golden_price_list(golden: Any) -> price_lists.PriceList:
    """The invented golden set's price list as a price list version (`jav/domains/quotes/invented_golden.py`)."""
    p = golden.price_list
    return price_lists.PriceList(
        price_list="golden", name="golden", version=1, state="active", currency=p.currency, vat_percent=p.vat_percent,
        items=tuple(price_lists.Item(sku=i.sku, name=i.name, unit=i.unit, unit_price=i.unit_price, category=i.category)
                    for i in p.items),
        discounts=tuple(price_lists.Discount(category=d.category, min_quantity=d.min_quantity, percent=d.percent)
                        for d in p.discounts),
        fingerprint="golden")


__all__ = ["LineInput", "PricedLine", "PricedQuote", "PricingError", "golden_price_list", "price", "rounding_unit",
           "rule_discount"]
