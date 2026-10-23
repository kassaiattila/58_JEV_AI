"""191 (plan F-quote-package B4a, DECISIONS 189 A1 and 191): a quote's numbers are computed by code from a price list
version, never by a model.

The rules (the 189 A1 judgement, the owner's decisions of 2026-10-21): a line's unit price is the list's, its discount
the largest percent of the rules of its category whose quantity the line reaches, its net amount rounded per line, the
VAT on the net total rounded once; in forints to whole forints, in another currency to cents. A person may give a line a
price of their own or a discount of their own (B5, always with a note), and a line not in the price list has a price of
its own. The invented golden set's ten quotes follow from its price list; the shared measurement command measures them
as the quote package's code-only golden set. No AI call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav.evals import goldens
from jav.domains.quotes import invented_golden, goldens as quote_goldens, quote_pricing
from jav.domains.quotes.price_lists import Discount, Item, PriceList


def _list(currency: str = "HUF", vat: str = "27", rules: tuple[Discount, ...] = ()) -> PriceList:
    items = (Item(sku="HW-1", name="Laptop", unit="pc", unit_price=Decimal("379000"), category="hardware"),
             Item(sku="SV-1", name="Installation", unit="hour", unit_price=Decimal("12500.50"), category="service"))
    return PriceList(price_list="pl-0123456789", name="Invented", version=3, state="active", currency=currency,
                     vat_percent=Decimal(vat), items=items, discounts=rules, fingerprint="f" * 64)


HW_5, HW_10 = (Discount(category="hardware", min_quantity=Decimal(n), percent=Decimal(p)) for n, p in ((5, 3), (10, 5)))


def test_the_largest_discount_reached_counts_and_each_line_rounds_on_its_own():
    quote = quote_pricing.price([quote_pricing.LineInput(sku="HW-1", quantity=Decimal(12)),
                                 quote_pricing.LineInput(sku="SV-1", quantity=Decimal(3))], _list(rules=(HW_5, HW_10)))
    laptop, hours = quote.lines
    assert (laptop.unit_price, laptop.discount_percent, laptop.discount_from, laptop.net) == (
        Decimal("379000"), Decimal("5"), "rule", Decimal("4320600"))
    assert (hours.discount_percent, hours.discount_from, hours.net) == (Decimal(0), None, Decimal("37502"))  # 37501.5 up
    assert (quote.net_total, quote.vat_total, quote.gross_total) == (Decimal("4358102"), Decimal("1176688"), Decimal("5534790"))
    assert (quote.price_list, quote.version, quote.currency) == ("pl-0123456789", 3, "HUF")
    assert quote_pricing.price([quote_pricing.LineInput(sku="HW-1", quantity=Decimal(6))], _list(rules=(HW_5, HW_10))).lines[0].discount_percent == 3


def test_another_currency_rounds_to_cents():
    quote = quote_pricing.price([quote_pricing.LineInput(sku="SV-1", quantity=Decimal(3))], _list(currency="EUR", vat="20"))
    assert (quote.lines[0].net, quote.net_total, quote.vat_total, quote.gross_total) == (
        Decimal("37501.50"), Decimal("37501.50"), Decimal("7500.30"), Decimal("45001.80"))


def test_a_price_or_discount_of_a_persons_own_and_a_line_not_in_the_list():
    lines = [quote_pricing.LineInput(sku="HW-1", quantity=Decimal(10), unit_price=Decimal("350000"), discount_percent=Decimal(0)),
             quote_pricing.LineInput(sku=None, description="Delivery to the office", unit="occasion", quantity=Decimal(1),
                                     unit_price=Decimal("15000"))]
    laptop, delivery = quote_pricing.price(lines, _list(rules=(HW_10,))).lines
    assert (laptop.list_price, laptop.unit_price, laptop.manual_price, laptop.discount_percent, laptop.discount_from) == (
        Decimal("379000"), Decimal("350000"), True, Decimal(0), "manual")
    assert (delivery.sku, delivery.name, delivery.unit, delivery.list_price, delivery.manual_price, delivery.net) == (
        None, "Delivery to the office", "occasion", None, True, Decimal("15000"))


@pytest.mark.parametrize("line, message", [
    (quote_pricing.LineInput(sku="NOPE", quantity=Decimal(1)), "not in the price list"),
    (quote_pricing.LineInput(sku=None, description="x", unit="pc", quantity=Decimal(1)), "needs a unit price"),
    (quote_pricing.LineInput(sku="HW-1", quantity=Decimal(0)), "more than zero"),
    (quote_pricing.LineInput(sku="HW-1", quantity=Decimal(1), discount_percent=Decimal(100)), "less than 100"),
    (quote_pricing.LineInput(sku="HW-1", quantity=Decimal(1), unit_price=Decimal(-1)), "not negative"),
])
def test_a_line_that_cannot_be_priced_is_refused(line, message):
    with pytest.raises(quote_pricing.PricingError, match=message):
        quote_pricing.price([line], _list())


def test_the_invented_quotes_follow_from_their_price_list():
    golden = invented_golden.load()
    outcome = quote_goldens.lines_outcome(golden)  # 204 (R1h): the quotes domain's measurement module
    assert (outcome.cases, outcome.right, outcome.scored, outcome.failures) == (10, 10, 10, ())
    registered = {g.key: g for g in goldens.sets()}["quote:lines"]
    assert (registered.layer, registered.owner, registered.engines, registered.count()) == ("logic_pack", "quote", (), 10)
