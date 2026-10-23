"""The quotes domain's registrations (191, plan F-quote-package B1).

Plain-language summary: the third domain, after finance and email. A quote request read from an email or a document
becomes a quote: the requested items are matched with the seller's price list, a person reviews and changes the quote,
and approves it. The shared reading of a quote request (its type pack, its detection type and its email intent, 190)
is configuration and needs no registration. What the domain adds to the shared code is registered here, in one call
(`register`, from `registrations.load_all`):
- (B3) the quote package as a logic pack, started from a request (`jav/domains/quotes/quote_package.py`), and its kind of work in the
  new work wizard (`jav/app/workflow_steps.py`);
- (B4c) the worker's job that makes a quote's proposal (`jav/domains/quotes/quote_proposal.py`, `jav/runtime/job_kinds.py`);
- (192, B6a) the quote request under its email in a mailbox package (`jav/app/item_kinds.py` item part);
- (196) the approved quote's Word document: its built-in template and its labels for a template's markers
  (`jav/domains/quotes/quote_document.py`, `jav/app/outputs/builtin.py`, `jav/app/outputs/parts.py`); the worker's job that asks GPT for the
  reply letter's paragraph (`jav/domains/quotes/quote_letter.py`).
The seller's price lists (B2) are a store of the domain's own with addresses of the local service (`SERVICE`).

The work itself stays in the domain's own modules, in this folder (208, plan G-process-core R2; until then `MODULES`
named them): the price lists (`price_lists.py`, `api_price_lists.py`), the request read from its parts
(`quote_request.py`), the pricing (`quote_pricing.py`), the match with the price list (`quote_match.py`), the quote
package (`quote_package.py`, `api_quote_package.py`), the quote's draft and approval (`quote_draft.py`, 192), its Word
document and reply letter (`quote_document.py`, `quote_letter.py`, 196), the invented golden set
(`invented_golden.py`; until 208 `jav/quote_golden.py`) and (204) the quote package's golden sets in the shared
measurement (`goldens.py`; until 208 `jav/quote_goldens.py`), named in `GOLDENS`. The shared code imports none of them
(`tests/test_dependency_direction.py`).
"""

from __future__ import annotations

# the modules of the domain's addresses of the local service beyond its logic pack's own (`LogicPack.service`);
# `jav.api.service_modules` adds them by name
SERVICE = ("jav.domains.quotes.api_price_lists",)
# 204 (plan G-process-core R1h): the modules of the domain's golden sets (the quote package's), by name; the shared measurement
# command imports them (`jav.goldens.logic_pack_goldens`), so the quote package imports no measurement code
GOLDENS = ("jav.domains.quotes.goldens",)


def register() -> None:
    """Every registration of the quotes domain (`registrations.load_all`): the quote package and its kind of work."""
    from jav.app import item_kinds, logic_packs, workflow_steps
    from jav.domains.quotes import quote_document, quote_letter, quote_package, quote_proposal
    from jav.app.outputs import builtin, parts
    from jav.runtime import job_kinds

    logic_packs.register(quote_package.LOGIC)
    workflow_steps.register(quote_package.STEP)
    item_kinds.register_item_part(quote_package.EMAIL_PART)  # 192 B6a: the request under its email
    job_kinds.register(quote_proposal.JOB)  # B4c: the worker's proposal job
    job_kinds.register(quote_letter.JOB)  # 196: the reply letter's paragraph
    builtin.register_word(quote_document.OUTPUT, quote_document.builtin_template)  # 196: the quote's Word document
    parts.register_output_labels(parts.OutputLabels(quote_document.OUTPUT, __name__, quote_document.sample_heads,
                                                    quote_document.sample_values))


__all__ = ["register"]
