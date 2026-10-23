"""Invented IT quote requests as a golden set (189, plan F-IT-quote-request A1).

Plain-language summary: the framework's second logic pack will turn an emailed IT quote request into a quote. There is
no real quote request in the store, so its golden set is invented (`configs/golden_quotes.json`): emails to an invented
IT company, its price list, and for each email what a careful person would make of it - whether it asks for a quote,
the customer and the deadline, the requested items, which price list item each one is (or why none can be chosen),
and the quote's lines and totals. This module reads the set, checks that it holds together, and lays its emails out as
mailbox folders with their PDF and Excel attachments, so the processing reads them like downloaded mail. It computes
nothing: the expected numbers are in the file, and the tests check them against the price list independently.

Layer: business module (a config read, files written); no AI call, no store.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from openpyxl import Workbook
from pydantic import BaseModel, ConfigDict, model_validator

from jav import cfg
from jav.synthetic_pdf import write_unicode_pdf

CONFIG = "golden_quotes"
QUOTE_REQUEST = "quote_request"  # the intent the requests expect (registered with the logic pack's intent, A2)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PriceItem(_Model):
    sku: str
    name: str
    unit: str
    unit_price: Decimal  # net, in the price list's currency
    category: Literal["hardware", "licence", "service"]


class Discount(_Model):
    """A price list rule: a line of this category from `min_quantity` on costs `percent` less."""

    category: str
    min_quantity: Decimal
    percent: Decimal


class PriceList(_Model):
    version: str
    currency: str
    vat_percent: Decimal
    columns: dict[str, str]  # the Excel header of each column, in the price list's own language
    discounts: tuple[Discount, ...]
    items: tuple[PriceItem, ...]

    def item(self, sku: str) -> PriceItem:
        return next(i for i in self.items if i.sku == sku)


class Seller(_Model):
    name: str
    tax_number: str
    email: str
    phone: str
    address: str


class SampleAttachment(_Model):
    """A PDF written from `rows` (three spaces separate its columns) or an Excel sheet written from `table`."""

    filename: str
    format: Literal["pdf", "xlsx"]
    rows: tuple[str, ...] = ()
    sheet: str | None = None
    table: tuple[tuple[str | int | float, ...], ...] = ()

    @model_validator(mode="after")
    def _content(self) -> SampleAttachment:
        if self.format == "pdf" and not self.rows:
            raise ValueError(f"{self.filename}: a PDF attachment needs its rows")
        if self.format == "xlsx" and not (self.sheet and self.table):
            raise ValueError(f"{self.filename}: an Excel attachment needs its sheet and table")
        if Path(self.filename).suffix.lower() != f".{self.format}":
            raise ValueError(f"{self.filename}: the file name does not end in .{self.format}")
        return self


class SampleMessage(_Model):
    message_id: str
    sender: str
    sender_name: str
    subject: str
    received_at: str
    body: str
    attachments: tuple[SampleAttachment, ...] = ()


class RequestedItem(_Model):
    written: str  # as the request puts it; informative, a person accepts the reading
    quantity: Decimal
    unit: str  # the matched price list item's unit, or the request's own when none is matched


class Request(_Model):
    customer_name: str
    customer_tax_number: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    deadline: date | None = None
    reference: str | None = None
    items: tuple[RequestedItem, ...]


class Match(_Model):
    """Which price list item a requested item is; without one, why not (`blocker`) and, if several fit, which."""

    item: int
    sku: str | None
    blocker: Literal["not_in_price_list", "ambiguous"] | None = None
    candidates: tuple[str, ...] = ()


class QuoteLine(_Model):
    item: int
    sku: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    discount_percent: Decimal
    net: Decimal


class Quote(_Model):
    lines: tuple[QuoteLine, ...]
    net_total: Decimal
    vat_total: Decimal
    gross_total: Decimal


class Expected(_Model):
    intent: str
    request: Request | None = None
    matches: tuple[Match, ...] = ()
    quote: Quote | None = None

    @model_validator(mode="after")
    def _whole(self) -> Expected:
        parts = (self.request is not None, bool(self.matches), self.quote is not None)
        if self.intent == QUOTE_REQUEST and not all(parts):
            raise ValueError("a quote request expects its request, its matches and its quote")
        if self.intent != QUOTE_REQUEST and any(parts):
            raise ValueError(f"an email of intent {self.intent!r} expects no request")
        return self


class Case(_Model):
    id: str
    language: Literal["hu", "en"]
    why: str
    message: SampleMessage
    expected: Expected


class QuoteGolden(_Model):
    seller: Seller
    price_list: PriceList
    cases: tuple[Case, ...]

    @model_validator(mode="after")
    def _consistent(self) -> QuoteGolden:
        skus = {i.sku for i in self.price_list.items}
        if len(skus) != len(self.price_list.items):
            raise ValueError("a price list item number appears twice")
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("a case id appears twice")
        for case in self.cases:
            exp = case.expected
            if exp.request is None:
                continue
            named = [m.sku for m in exp.matches if m.sku] + [s for m in exp.matches for s in m.candidates]
            named += [line.sku for line in exp.quote.lines]
            if set(named) - skus:
                raise ValueError(f"{case.id}: not in the price list: {sorted(set(named) - skus)}")
            if [m.item for m in exp.matches] != list(range(len(exp.request.items))):
                raise ValueError(f"{case.id}: every requested item needs one match, in order")
            if any((m.sku is None) != (m.blocker is not None) for m in exp.matches):
                raise ValueError(f"{case.id}: a match has either a price list item or a blocker")
        return self


def load() -> QuoteGolden:
    """The golden set, checked (`configs/golden_quotes.json`)."""
    data = cfg.load(CONFIG)
    return QuoteGolden.model_validate({k: v for k, v in data.items() if k != "meta"})


def _write_attachment(attachment: SampleAttachment, folder: Path) -> Path:
    path = folder / attachment.filename
    if attachment.format == "pdf":
        return write_unicode_pdf(path, list(attachment.rows))
    book = Workbook()
    sheet = book.active
    sheet.title = attachment.sheet
    for row in attachment.table:
        sheet.append(list(row))
    book.save(path)
    return path


def lay_out(case: Case, root: Path, *, mailbox: str) -> Path:
    """The case as a downloaded email's folder (`<root>/<case id>/`): its attachments and the `message.json` the mailbox
    reader reads (`jav.domains.email.emails.load_message_dir`). Returns the folder."""
    folder = root / case.id
    folder.mkdir(parents=True, exist_ok=True)
    for attachment in case.message.attachments:
        _write_attachment(attachment, folder)
    msg = case.message
    meta = {"message_id": msg.message_id, "mailbox": mailbox, "sender": msg.sender, "sender_name": msg.sender_name,
            "subject": msg.subject, "received_at": msg.received_at, "body": msg.body,
            "attachments": [{"filename": a.filename} for a in msg.attachments]}
    (folder / "message.json").write_bytes(json.dumps(meta, ensure_ascii=False, indent=1).encode("utf-8"))
    return folder


def lay_out_all(root: Path, golden: QuoteGolden | None = None) -> list[Path]:
    """Every case under `root`, as the invented seller's mailbox; returns the folders in the set's order."""
    golden = golden or load()
    return [lay_out(case, root, mailbox=golden.seller.email) for case in golden.cases]


def write_price_list(path: Path, golden: QuoteGolden | None = None) -> Path:
    """The price list as the seller would keep it: one Excel sheet, a header row from `columns`, one row per item."""
    golden = golden or load()
    prices = golden.price_list
    book = Workbook()
    sheet = book.active
    sheet.title = prices.version
    keys = ("sku", "name", "unit", "unit_price", "category")
    sheet.append([prices.columns[k] for k in keys])
    for item in prices.items:
        sheet.append([item.sku, item.name, item.unit, item.unit_price, item.category])
    book.save(path)
    return path


__all__ = ["CONFIG", "QUOTE_REQUEST", "Case", "Expected", "Match", "PriceItem", "PriceList", "Quote", "QuoteGolden",
           "QuoteLine", "Request", "RequestedItem", "SampleAttachment", "SampleMessage", "Seller", "lay_out",
           "lay_out_all", "load", "write_price_list"]
