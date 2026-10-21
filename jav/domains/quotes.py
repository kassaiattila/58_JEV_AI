"""The quotes domain's registrations (191, plan F-quote-package B1).

Plain-language summary: the third domain, after finance and email. A quote request read from an email or a document
becomes a quote: the requested items are matched with the seller's price list, a person reviews and changes the quote,
and approves it. The shared reading of a quote request (its type pack, its detection type and its email intent, 190)
is configuration and needs no registration. What the domain adds to the shared code is registered here, in one call
(`register`, from `registrations.load_all`); for now nothing, as its price lists and its logic pack come with the
next steps of the plan.

The work itself stays in the domain's own modules (`MODULES`): for now the invented golden set (`jav/quote_golden.py`).
"""

from __future__ import annotations

# the modules of the domain's addresses of the local service beyond its logic pack's own (`LogicPack.service`); none
# yet
SERVICE: tuple[str, ...] = ()
# the modules the domain is made of; the shared code imports none of them (`tests/test_domain_boundary_185.py`)
MODULES = frozenset({"quote_golden", "domains.quotes"})


def register() -> None:
    """Every registration of the quotes domain (`registrations.load_all`); none yet."""


__all__ = ["register"]
