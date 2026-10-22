"""The quotes domain's registrations (191, plan F-quote-package B1).

Plain-language summary: the third domain, after finance and email. A quote request read from an email or a document
becomes a quote: the requested items are matched with the seller's price list, a person reviews and changes the quote,
and approves it. The shared reading of a quote request (its type pack, its detection type and its email intent, 190)
is configuration and needs no registration. What the domain adds to the shared code is registered here, in one call
(`register`, from `registrations.load_all`):
- (B3) the quote package as a logic pack, started from a request (`jav/quote_package.py`), and its kind of work in the
  new work wizard (`jav/workflow_steps.py`);
- (B4c) the worker's job that makes a quote's proposal (`jav/quote_proposal.py`, `jav/runtime/job_kinds.py`);
- (192, B6a) the quote request under its email in a mailbox package (`jav/item_kinds.py` item part);
- (196) the approved quote's Word document: its built-in template and its labels for a template's markers
  (`jav/quote_document.py`, `jav/outputs/builtin.py`, `jav/outputs/parts.py`).
The seller's price lists (B2) are a store of the domain's own with addresses of the local service (`SERVICE`).

The work itself stays in the domain's own modules (`MODULES`): the price lists (`jav/price_lists.py`,
`jav/api_price_lists.py`), the request read from its parts (`jav/quote_request.py`), the pricing (`jav/quote_pricing.py`), the
match with the price list (`jav/quote_match.py`), the quote package
(`jav/quote_package.py`, `jav/api_quote_package.py`), the quote's draft and approval (`jav/quote_draft.py`, 192) and
the invented golden set (`jav/quote_golden.py`).
"""

from __future__ import annotations

# the modules of the domain's addresses of the local service beyond its logic pack's own (`LogicPack.service`);
# `jav.api.service_modules` adds them by name
SERVICE = ("jav.api_price_lists",)
# the modules the domain is made of; the shared code imports none of them (`tests/test_domain_boundary_185.py`)
MODULES = frozenset({"api_price_lists", "api_quote_package", "price_lists", "quote_document", "quote_draft",
                     "quote_golden", "quote_package", "quote_match", "quote_pricing", "quote_proposal", "quote_request",
                     "domains.quotes"})


def register() -> None:
    """Every registration of the quotes domain (`registrations.load_all`): the quote package and its kind of work."""
    from jav import item_kinds, logic_packs, quote_document, quote_package, quote_proposal, workflow_steps
    from jav.outputs import builtin, parts
    from jav.runtime import job_kinds

    logic_packs.register(quote_package.LOGIC)
    workflow_steps.register(quote_package.STEP)
    item_kinds.register_item_part(quote_package.EMAIL_PART)  # 192 B6a: the request under its email
    job_kinds.register(quote_proposal.JOB)  # B4c: the worker's proposal job
    builtin.register_word(quote_document.OUTPUT, quote_document.builtin_template)  # 196: the quote's Word document
    parts.register_output_labels(parts.OutputLabels(quote_document.OUTPUT, __name__, quote_document.sample_heads,
                                                    quote_document.sample_values))


__all__ = ["register"]
