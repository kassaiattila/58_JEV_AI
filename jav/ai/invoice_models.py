"""The Hungarian invoice's own models: its field lists and its hand-written G-path output model.

Plain-language summary: the Hungarian invoice was the first document type, and some of its data still has a shape of
its own: the order of its header fields, the fields scored against the legacy golden set, and the output model GPT
fills on the G path (`InvoiceLLM`, a 1:1 mirror of the legacy invoice_hu/schema.json: nullable strings, money as a
decimal STRING with a dot, date as an ISO string). 209 (plan G-process-core R2d): they moved here from the general data
model (`jav/ai/models.py`), which every type pack shares; its record still lists the invoice fields by default.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------------------
# Field lists
# --------------------------------------------------------------------------------------

HEADER_FIELDS: tuple[str, ...] = (
    "supplier_name",
    "supplier_tax_id",
    "buyer_name",
    "buyer_tax_id",
    "invoice_number",
    "issue_date",
    "fulfillment_date",
    "due_date",
    "currency",
    "net_total",
    "vat_total",
    "gross_total",
    "payment_iban",
    "supplier_address",
    "buyer_address",
    "payment_method",
    "order_number",
    "amount_due",
)

MONEY_FIELDS: tuple[str, ...] = ("net_total", "vat_total", "gross_total", "amount_due")
DATE_FIELDS: tuple[str, ...] = ("issue_date", "fulfillment_date", "due_date")
TAX_ID_FIELDS: tuple[str, ...] = ("supplier_tax_id", "buyer_tax_id")

# The 13 header fields in the datapoints of the golden `expected/*.json` (the legacy scoring contract).
SCORED_FIELDS: tuple[str, ...] = (
    "supplier_name",
    "supplier_tax_id",
    "buyer_name",
    "buyer_tax_id",
    "invoice_number",
    "issue_date",
    "fulfillment_date",
    "due_date",
    "currency",
    "net_total",
    "vat_total",
    "gross_total",
    "payment_iban",  # NOT scored in the legacy contract, informative only; the eval handles it separately
)


# --------------------------------------------------------------------------------------
# LLM layer: a 1:1 mirror of the legacy schema.json
# --------------------------------------------------------------------------------------


class LineItemLLM(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = None
    quantity: float | None = None
    unit_price: str | None = None
    net_amount: str | None = None
    vat_rate: str | None = None
    gross_amount: str | None = None
    unit: str | None = None
    product_code: str | None = None
    vat_amount: str | None = None
    note: str | None = None


class InvoiceLLM(BaseModel):
    """Hungarian supplier invoice extract. Every field nullable; money = decimal string with a dot; date = ISO."""

    model_config = ConfigDict(extra="forbid")

    supplier_name: str | None = None
    supplier_tax_id: str | None = None
    buyer_name: str | None = None
    buyer_tax_id: str | None = None
    invoice_number: str | None = None
    issue_date: str | None = None
    fulfillment_date: str | None = None
    due_date: str | None = None
    currency: str | None = None
    net_total: str | None = None
    vat_total: str | None = None
    gross_total: str | None = None
    payment_iban: str | None = None
    line_items: list[LineItemLLM] = Field(default_factory=list)
    supplier_address: str | None = None
    buyer_address: str | None = None
    payment_method: str | None = None
    order_number: str | None = None
    amount_due: str | None = None


HAND_WRITTEN_OUTPUT: dict[str, type[BaseModel]] = {"invoice_hu": InvoiceLLM}
"""202: the type packs whose G-path output model is written by hand (`TypePack.llm_model`). The output schema is part of
the GPT request; the model generated from the Hungarian invoice's schema file differs from `InvoiceLLM` in its field
descriptions and titles, so replacing it would change every request and need a paid re-measurement."""


__all__ = ["DATE_FIELDS", "HAND_WRITTEN_OUTPUT", "HEADER_FIELDS", "InvoiceLLM", "LineItemLLM", "MONEY_FIELDS",
           "SCORED_FIELDS", "TAX_ID_FIELDS"]
