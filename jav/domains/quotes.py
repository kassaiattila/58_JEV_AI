"""The quotes domain's registrations (191, plan F-quote-package B1).

Plain-language summary: the third domain, after finance and email. A quote request read from an email or a document
becomes a quote: the requested items are matched with the seller's price list, a person reviews and changes the quote,
and approves it. The shared reading of a quote request (its type pack, its detection type and its email intent, 190)
is configuration and needs no registration. What the domain adds to the shared code is registered here, in one call
(`register`, from `registrations.load_all`):
- (B3) the quote package as a logic pack, started from a request (`jav/quote_package.py`), and its kind of work in the
  new work wizard (`jav/workflow_steps.py`).
The seller's price lists (B2) are a store of the domain's own with addresses of the local service (`SERVICE`).

The work itself stays in the domain's own modules (`MODULES`): the price lists (`jav/price_lists.py`,
`jav/api_price_lists.py`), the request read from its parts (`jav/quote_request.py`), the pricing (`jav/quote_pricing.py`), the quote package
(`jav/quote_package.py`, `jav/api_quote_package.py`) and the invented golden set (`jav/quote_golden.py`).
"""

from __future__ import annotations

# the modules of the domain's addresses of the local service beyond its logic pack's own (`LogicPack.service`);
# `jav.api.service_modules` adds them by name
SERVICE = ("jav.api_price_lists",)
# the modules the domain is made of; the shared code imports none of them (`tests/test_domain_boundary_185.py`)
MODULES = frozenset({"api_price_lists", "api_quote_package", "price_lists", "quote_golden", "quote_package",
                     "quote_pricing", "quote_request", "domains.quotes"})


def register() -> None:
    """Every registration of the quotes domain (`registrations.load_all`): the quote package and its kind of work."""
    from jav import logic_packs, quote_package, workflow_steps

    logic_packs.register(quote_package.LOGIC)
    workflow_steps.register(quote_package.STEP)


__all__ = ["register"]
