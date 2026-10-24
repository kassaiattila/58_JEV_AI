"""The quote package's golden sets in the shared measurement command (204, plan G-process-core R1h; until 204 in
`jav/domains/quotes/quote_package.py` and `jav/domains/quotes/quote_pricing.py`).

Plain-language summary: the quote package has three golden sets, built on the invented quote requests
(`configs/golden_quotes.json`, read by `jav/domains/quotes/invented_golden.py`): the quotes' lines and totals priced by code, the price
list item proposed for each requested item, and the reply letter's paragraph GPT writes. The shared measurement
command (`python -m jav.cli measure`, `jav/evals/goldens.py`) measures them with every other golden set. They are described
here, beside the quote package, so the quote package and its pricing never import the measurement layer; the quotes
domain names this module (`jav/domains/quotes/__init__.py` `GOLDENS`) and the shared command finds it from there.

- `lines_outcome(golden)`: each invented request's expected matches priced by `quote_pricing.price`, compared with its
  expected quote (the code-only golden set `quote:lines`).

Layer: measurement of the quotes domain: it imports the quote package, its pricing, its reply letter and the shared
measurement registry; no business module imports it.
"""

from __future__ import annotations

from typing import Any

from jav.evals import goldens
from jav.domains.quotes import quote_letter, quote_pricing
from jav.domains.quotes.quote_package import KIND


def lines_outcome(golden: Any) -> goldens.Outcome:
    """Each invented request's expected matches priced by `quote_pricing.price`, compared with its expected quote: every
    line's item, quantity, unit, unit price, discount and net amount, and the three totals. One judgement per case."""
    prices = quote_pricing.golden_price_list(golden)
    cases = [c for c in golden.cases if c.expected.quote is not None]
    failures = []
    for case in cases:
        exp = case.expected
        lines = [quote_pricing.LineInput(sku=m.sku, quantity=exp.request.items[m.item].quantity)
                 for m in exp.matches if m.sku]
        got = quote_pricing.price(lines, prices)
        want = [(x.sku, x.quantity, x.unit, x.unit_price, x.discount_percent, x.net) for x in exp.quote.lines]
        have = [(x.sku, x.quantity, x.unit, x.unit_price, x.discount_percent, x.net) for x in got.lines]
        totals = (got.net_total, got.vat_total, got.gross_total) == (exp.quote.net_total, exp.quote.vat_total,
                                                                    exp.quote.gross_total)
        if have != want or not totals:
            failures.append(f"{case.id}: lines {have} != {want}" if have != want else f"{case.id}: totals differ")
    print(f"quote:lines - {len(cases) - len(failures)}/{len(cases)} invented quotes priced as expected")
    return goldens.Outcome(cases=len(cases), answered=len(cases), right=len(cases) - len(failures), scored=len(cases),
                           failures=tuple(failures))


def _measure_lines(_options: goldens.Options) -> goldens.Outcome:
    """B4a: the invented quotes priced from their expected matches; code only, free."""
    from jav.domains.quotes import invented_golden

    return lines_outcome(invented_golden.load())


def _count_quotes() -> int:
    from jav.domains.quotes import invented_golden

    return sum(1 for c in invented_golden.load().cases if c.expected.quote is not None)


def _count_matches() -> int:
    from jav.domains.quotes import invented_golden

    return sum(len(c.expected.matches) for c in invented_golden.load().cases)


def _measure_matches(options: goldens.Options) -> goldens.Outcome:
    """B4b: the invented requested items matched with the round's engine; without a budget, earlier answers only. A
    right item is one marked as expected; one a person would resolve (flagged), a missed and a silently wrong one are
    counted apart in the printed report."""
    from jav.domains.quotes import invented_golden, quote_match

    budget, refused = options.answering_budget("the quote matches")
    if refused:
        return goldens.Outcome(refused=refused)
    limits = {quote_match.PROVIDERS[options.engine]: budget} if budget is not None else {}
    g = quote_match.golden(invented_golden.load(), engine=options.engine, limits=limits, use_cache=options.use_cache,
                           **({} if limits else {"earlier_only": True}))
    quote_match.print_golden(g)
    answered = g["items"] - g["tally"].get("failed", 0)
    return goldens.Outcome(cases=g["items"], answered=answered, right=g["tally"].get("right", 0), scored=answered,
                           unit="items")


def _count_letters() -> int:
    from jav.domains.quotes import invented_golden

    return len(quote_letter.golden_cases(invented_golden.load()))


def _measure_letters(options: goldens.Options) -> goldens.Outcome:
    """196 W4: each invented request's reply letter paragraph asked of GPT and checked by code; without a budget,
    earlier answers only."""
    from jav.domains.quotes import invented_golden

    budget, refused = options.answering_budget("the reply letters")
    if refused:
        return goldens.Outcome(refused=refused)
    limits = {"openai": budget} if budget is not None else {}
    g = quote_letter.golden(invented_golden.load(), limits=limits, use_cache=options.use_cache, **({} if limits else {"earlier_only": True}))
    quote_letter.print_golden(g)
    answered = g["cases"] - g["tally"].get("failed", 0)
    return goldens.Outcome(cases=g["cases"], answered=answered, right=g["tally"].get("right", 0), scored=answered,
                           unit="cases")


# B4a: the quote package's golden sets, measured by the shared measurement command (`jav/evals/goldens.py`)
GOLDENS = (
    goldens.Golden(key=f"{KIND}:lines", layer="logic_pack", owner=KIND, engines=(), module=__name__,
                   what="the invented quotes' lines and totals priced by code from their expected matches "
                        "(configs/golden_quotes.json)", count=_count_quotes, measure=_measure_lines),
    goldens.Golden(key=f"{KIND}:matches", layer="logic_pack", owner=KIND, engines=goldens.ENGINES, module=__name__,
                   what="the price list item proposed for each invented requested item: sure, to check or not listed "
                        "(configs/golden_quotes.json)", count=_count_matches, measure=_measure_matches),
    # 196 W4: GPT only (JEV writes no text)
    goldens.Golden(key=f"{KIND}:letters", layer="logic_pack", owner=KIND, engines=("gpt",), module=__name__,
                   what="the reply letter's paragraph GPT writes for each invented request and an injection probe: it "
                        "passes the code's check (no number, link, address) in the request's language", count=_count_letters,
                   measure=_measure_letters),
)


__all__ = ["GOLDENS", "lines_outcome"]
