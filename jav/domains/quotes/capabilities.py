"""The general capabilities of the quote's back half (231, plan stage A, A3c; DECISIONS 231).

Plain-language summary: the owner's rule is that every process is built only from general capabilities. The quote's
back half is six such building blocks, described here with what a process sets for each: putting a record together
from an email and its attachments, matching requested items with a catalogue (a price list), pricing lines from a
catalogue, a person's line-by-line draft with its approval, a priced document from an output template, and a letter
draft around a model's paragraph. They are described but cannot run as a process pack's step yet: they run as the quote
package's parts until the IT quote becomes a process pack (A5), and their code moves to general domains (A3d). Their
parameters' defaults are not the quote's: a process names them.

Layer: domain (quotes); it registers into the application's capability registry.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jav.app.capabilities import Capability


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecordAssembly(_Params):
    """The record type an email's text, its table attachments and its attachments were read as, and its list field."""

    record_type: str = Field(min_length=1)
    items_field: str = Field(min_length=1)


class CatalogueMatch(_Params):
    """Which catalogue the items are matched with (`newest_active` or a named price list), and the call site that asks."""

    catalogue: str = Field(min_length=1)
    callsite: str = Field(min_length=1)


class LinePricing(_Params):
    catalogue: str = Field(min_length=1)


class LineDraft(_Params):
    """A person composes the lines from the match; the approval is the record's own version."""

    catalogue: str = Field(min_length=1)
    approval: Literal["own_version"] = "own_version"


class PricedDocument(_Params):
    output: str = Field(min_length=1)


class LetterDraft(_Params):
    """The letter frame's key and the call site that asks for the paragraph."""

    frame: str = Field(min_length=1)
    callsite: str = Field(min_length=1)


_OWNER = __name__
CAPABILITIES = (
    Capability(name="record_assembly", version=1, module=_OWNER, kind="machine", params=RecordAssembly, effects="pure",
               summary="Puts a record together from an email's text, its table attachments and its attachments."),
    Capability(name="catalogue_match", version=1, module=_OWNER, kind="machine", params=CatalogueMatch,
               providers=("jev", "openai"), rule_files=("callsite:quote_match", "gpt_quote_match", "quotes", "price_lists"),
               summary="Matches each requested item with a catalogue item: sure, to check, or not listed."),
    Capability(name="line_pricing", version=1, module=_OWNER, kind="machine", params=LinePricing, effects="pure",
               rule_files=("price_lists",), summary="Prices lines from a catalogue: unit price, discount rules, totals."),
    Capability(name="line_draft", version=1, module=_OWNER, kind="human", params=LineDraft,
               rule_files=("quotes", "price_lists"),
               summary="A person composes the lines from the match, gives own prices with a note, and approves."),
    Capability(name="priced_document", version=1, module=_OWNER, kind="machine", params=PricedDocument,
               rule_files=("quote_documents", "outputs"), summary="Fills a priced document from an output template."),
    Capability(name="letter_draft", version=1, module=_OWNER, kind="machine", params=LetterDraft, providers=("openai",),
               rule_files=("gpt_quote_letter", "quote_documents", "quotes"),
               summary="Drafts a reply letter: the frame written by code around a model's checked paragraph."),
)


def register() -> None:
    from jav.app import capabilities

    for cap in CAPABILITIES:
        capabilities.register(cap)


__all__ = ["CAPABILITIES", "CatalogueMatch", "LetterDraft", "LineDraft", "LinePricing", "PricedDocument", "RecordAssembly",
           "register"]
