"""Pydantic models and normalisers: every fixed input/output structure of the flow.

- `DocumentRecord` / `LineItem`: the normalised layer (`Decimal`, `date`) consumed by validators, policy and evals.
  The conversion (`record_from_llm`, by the type pack's field kinds) is the only place where a parse error becomes review reasons instead of an
  exception.
- 209 (plan G-process-core R2d): the Hungarian invoice's own models (its field lists and the G path's hand-written
  output model `InvoiceLLM`) are in `jav/ai/invoice_models.py`, the page layout (`LineLayout`, `CellLayout`) in the
  documents layer (`jav/documents/layout.py`); a saved flow state that names them here is read at their new place.

JEV's raw output (`FieldPick.probabilities`, `JevVerdicts.flags`) is stored unchanged; the thresholds live only in
the `policy` module.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field

from jav.ai.invoice_models import HEADER_FIELDS
from jav.core.dates import DateOrder, read_date
from jav.core.numbers import Convention, Kind, NumberRead, read_number
from jav.documents.layout import LineLayout

# text: a labelled text field (the type pack's text_labels)
CandidateKind = Literal["tax_id", "date", "money", "iban", "invoice_number", "name", "address", "text"]

# --------------------------------------------------------------------------------------
# Normalisers (code owns the format, never JEV)
# --------------------------------------------------------------------------------------

MoneyParse = NumberRead  # the earlier name of the reader's result


def parse_money(raw: str | None, *, intl: bool = False, kind: Kind = "money", convention: Convention | None = None,
                dot_hint: bool | None = None) -> NumberRead:
    """A printed amount (or, with `kind="number"`, a quantity) read whole by the shared number reader
    (`jav/core/numbers.py`, 081): the Hungarian and the English notations, money never with three decimals, a quantity by the
    document's notation. Neither computes nor rounds; when unsure, `ambiguous=True`. `intl=True` (international
    candidate profile): a decimal dot marked by a currency symbol / code ("$42.50", "42.50 USD") is not ambiguous."""
    return read_number(raw, kind=kind, convention=convention, intl=intl, dot_hint=dot_hint)


def normalize_money(raw: str | None) -> Decimal | None:
    return parse_money(raw).value


def money_label(value: Decimal) -> str:
    """Canonical, comparable string: "127000", "20619.05" (without superfluous zeros)."""
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


_HU_MONTHS = {
    "január": 1, "jan": 1,
    "február": 2, "febr": 2, "feb": 2,
    "március": 3, "márc": 3, "marc": 3,
    "április": 4, "ápr": 4, "apr": 4,
    "május": 5, "máj": 5, "maj": 5,
    "június": 6, "jún": 6, "jun": 6,
    "július": 7, "júl": 7, "jul": 7,
    "augusztus": 8, "aug": 8,
    "szeptember": 9, "szept": 9, "szep": 9,
    "október": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}  # fmt: skip
_MONTH_ALT = "|".join(sorted(_HU_MONTHS, key=len, reverse=True))

# 084: kept unchanged: the type recognition request counts their matches (`detect.build_state`, `features.dates`), so a
# change would make every recognition a new, paid call. Dates are read by the shared reader (`jav/core/dates.py`).
DATE_NUMERIC_RE = re.compile(r"(?<!\d)(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\.?(?!\d)")
DATE_TEXT_RE = re.compile(rf"(?<!\d)(\d{{4}})\.?\s+({_MONTH_ALT})\.?\s+(\d{{1,2}})\.?(?!\d)", re.IGNORECASE)


def normalize_date(raw: str | None) -> date | None:
    """084: the shared date reader (`jav/core/dates.py`), value only: every common form ("2022.02.10.", "2022. február 10.",
    "04-DEC-22", "Dec 25, 2022", "07.03.2025"...), and None for text that is no date or whose day and month can be read
    two ways ("04/12/2022", "22.02.10"). A caller that can raise a to-do uses `dates.read_date` instead."""
    got = read_date(raw)
    return None if got.ambiguous else got.value


_DIGITS = re.compile(r"\D")


def normalize_tax_id(raw: str | None) -> str | None:
    """Hungarian tax number -> `########-#-##`; a recognised EU / non-EU form -> compact spelling ("IE 8256796 U" ->
    "IE8256796U"); 069: the label and the superfluous prefix are cut off ("HU VAT HU12345678" -> "HU12345678",
    `jav/core/taxid.py`). Anything unrecognised stays trimmed (the check raises a to-do for it)."""
    from jav.core.taxid import clean

    return clean(raw)


def normalize_iban(raw: str | None) -> str | None:
    """Keeps the printed form (grouping included); only trim + NBSP."""
    if raw is None:
        return None
    s = str(raw).replace(" ", " ").strip()
    return s or None


def account_key(value: Any) -> str:
    """One key for one account: a Hungarian IBAN and its 24-digit domestic number are the same, and a 16-digit domestic
    number is its 24-digit form; anything shorter than 16 characters is no account."""
    text = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if re.fullmatch(r"HU\d{26}", text):
        return text[4:]
    if re.fullmatch(r"\d{16}", text):
        return text + "00000000"
    return text if len(text) >= 16 else ""


def normalize_text(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = " ".join(str(raw).replace(" ", " ").split())
    return s or None


# --------------------------------------------------------------------------------------
# Normalised layer
# --------------------------------------------------------------------------------------


class LineItem(BaseModel):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    net_amount: Decimal | None = None
    vat_rate: str | None = None
    gross_amount: Decimal | None = None
    unit: str | None = None
    product_code: str | None = None
    vat_amount: Decimal | None = None
    note: str | None = None
    # line-item fields of other type packs (e.g. period, meter_serial), normalised
    extra: dict[str, object] = Field(default_factory=dict)


class DocumentRecord(BaseModel):
    """The normalised record of a document's data points, shared by the type packs: the invoice fields as its own
    fields (most packs are invoices; the foreign invoice adds `supplier_country`), every other field of a pack in
    `extra`, and the line items. 188 (plan 185 T3b): named `InvoiceHU` before, after the Hungarian invoice it began
    with."""

    supplier_name: str | None = None
    supplier_tax_id: str | None = None
    buyer_name: str | None = None
    buyer_tax_id: str | None = None
    invoice_number: str | None = None
    issue_date: date | None = None
    fulfillment_date: date | None = None
    due_date: date | None = None
    currency: str | None = None
    net_total: Decimal | None = None
    vat_total: Decimal | None = None
    gross_total: Decimal | None = None
    payment_iban: str | None = None
    supplier_address: str | None = None
    buyer_address: str | None = None
    payment_method: str | None = None
    order_number: str | None = None
    amount_due: Decimal | None = None
    supplier_country: str | None = None  # invoice_foreign: ISO 3166-1 alpha-2 (a legacy schema field)
    extra: dict[str, object] = Field(default_factory=dict)  # the type pack's other header fields (normalised in code)
    line_items: list[LineItem] = Field(default_factory=list)

    def get_field(self, name: str) -> object:
        return getattr(self, name) if name in type(self).model_fields and name != "extra" else self.extra.get(name)

    def to_datapoints(self, fields: tuple[str, ...] | None = None) -> dict[str, object]:
        """The golden `datapoints` format (strings), for comparison and reports. `fields`: the type pack's header
        fields (default: the Hungarian invoice field list)."""
        out: dict[str, object] = {}
        for name in fields or HEADER_FIELDS:
            out[name] = _plain(self.get_field(name))
        out["line_items"] = [
            {
                "description": li.description,
                "quantity": float(li.quantity) if li.quantity is not None else None,
                "unit_price": money_label(li.unit_price) if li.unit_price is not None else None,
                "net_amount": money_label(li.net_amount) if li.net_amount is not None else None,
                "vat_rate": li.vat_rate,
                "gross_amount": money_label(li.gross_amount) if li.gross_amount is not None else None,
                "unit": li.unit,
                "product_code": li.product_code,
                "vat_amount": money_label(li.vat_amount) if li.vat_amount is not None else None,
                "note": li.note,
                **{k: v for k, v in li.extra.items()},
            }
            for li in self.line_items
        ]
        return out


def _plain(value: object) -> object:
    """The `datapoints` format: money as a label string, dates as ISO, lists and items recursively (047)."""
    if isinstance(value, Decimal):
        return money_label(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


Origin = Literal["llm", "printed", "canonical"]
# the generative contract: a plain decimal with a DOT ("1234.56"), with one or two decimals or with four or more (a
# correction factor "0.9853"; 090: a unit price "37.4510" Ft/kWh too, which four digits after one separator make a
# decimal, never a thousands group); three decimals are what a copied thousands group looks like ("28.000"), so they
# are read with the document's notation
_CONTRACT = re.compile(r"-?\d+(?:\.\d{1,2}|\.\d{4,})?")


def _number_or_reason(kind: Kind, field: str, raw: object, reasons: list[str], *, origin: Origin = "llm",
                      convention: Convention | None = None) -> Decimal | None:
    """One amount or quantity of a record (081, the shared number reader). `origin`:
    - "llm": a generative value. The contract is a plain decimal with a dot ("1234.56"); a value copied in the
      document's own notation ("28.000", "28,000.00", "1 234,56") is read whole with the document's notation
      (`convention`), so "28.000" is 28 000, never 28. A JSON number with three decimals is read the same way;
    - "printed": text selected on the page image, read like a printed number;
    - "canonical": a stored value ("28000", "1.153"), taken as it is.
    An unreadable value, or a reading that could go two ways, gives a review reason."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        reasons.append(f"{field}:unparseable:{raw!r}")
        return None
    if isinstance(raw, int):
        return Decimal(raw)
    text = str(raw)
    s = text if origin == "printed" else text.strip().replace(" ", "")
    if origin == "canonical" or (origin == "llm" and _CONTRACT.fullmatch(s)):
        try:
            return Decimal(s)
        except InvalidOperation:
            reasons.append(f"{field}:unparseable:{text!r}")
            return None
    got = read_number(s, kind=kind, convention=convention)
    if got.value is None:
        reasons.append(f"{field}:unparseable:{text!r}")
    elif got.ambiguous and got.value != 0:  # 152: "0.00" is zero whichever separator is the decimal one
        reasons.append(f"money:separator_ambiguous:{field}:{text!r}")
    return got.value


def _date_or_reason(field: str, raw: str | None, reasons: list[str], date_order: DateOrder | None = None) -> date | None:
    """084: the shared date reader with the document's `date_order`; a date whose day and month can be read two ways
    keeps its reading and gets a to-do (`date:order_ambiguous`), never a silent guess."""
    if raw is None:
        return None
    got = read_date(raw, order=date_order)
    if got.value is None:
        reasons.append(f"{field}:unparseable:{raw!r}")
    elif got.ambiguous:
        reasons.append(f"date:order_ambiguous:{field}:{raw!r}")
    return got.value


_LINE_ITEM_MONEY = ("unit_price", "net_amount", "gross_amount", "vat_amount")
_LINE_ITEM_TEXT = ("description", "vat_rate", "unit", "product_code", "note")


def normalize_value(kind: str, raw: object, field: str, reasons: list[str], *, origin: Origin = "llm",
                    convention: Convention | None = None, date_order: DateOrder | None = None) -> object:
    """Normalises one field by its KIND in the type pack (code owns the format). Parse error -> review reasons. An
    amount or a quantity is read by the shared number reader (`_number_or_reason`: `origin`, the document's
    `convention`); 084: a date by the shared date reader with the document's `date_order`."""
    if raw is None:
        return None
    if kind in ("money", "number"):
        # quantity (kWh, m3, MJ, meter reading): the generative extract promises a decimal dot, but from OCR text it
        # also returns the Hungarian form ("143,00", "1 866", "1.153")
        return _number_or_reason(kind, field, raw, reasons, origin=origin, convention=convention)  # type: ignore[arg-type]
    if kind == "date":
        return _date_or_reason(field, str(raw), reasons, date_order)
    if kind == "tax_id":
        return normalize_tax_id(str(raw))
    if kind == "iban":
        return normalize_iban(str(raw))
    if kind in ("currency", "country"):
        t = normalize_text(str(raw))
        return t.upper() if t else None
    if kind == "boolean":
        t = str(raw).strip().lower()
        if t in ("true", "igen", "yes", "1"):
            return True
        if t in ("false", "nem", "no", "0"):
            return False
        reasons.append(f"{field}:unparseable:{raw!r}")
        return None
    if kind == "name":  # 129: a party name ends at its legal form (a tagline, an address or an ID after it is cut)
        from jav.ai.candidates import trim_after_legal_form

        text = normalize_text(str(raw))
        return trim_after_legal_form(text) if text else text
    return normalize_text(str(raw))


def _check_enum(path: str, value: object, enums: dict[str, list[Any]], reasons: list[str], key: str) -> None:
    allowed = enums.get(key)
    if allowed is not None and value is not None and value not in allowed:
        reasons.append(f"{path}:not_in_enum:{value!r}")


def _list_value(field: str, raw: object, item_kinds: dict[str, str], enums: dict[str, list[Any]], reasons: list[str],
                origin: Origin = "llm", convention: Convention | None = None,
                date_order: DateOrder | None = None) -> list[Any]:
    """047: an itemised list as described by the pack's `list_fields`. `{"*": kind}` = a list of plain values;
    otherwise objects, normalised by the kind of each item field (unknown item field: as text)."""
    out: list[Any] = []
    for i, item in enumerate(raw if isinstance(raw, list) else []):
        path = f"{field}[{i}]"
        if "*" in item_kinds:
            value = normalize_value(item_kinds["*"], item, path, reasons, origin=origin, convention=convention,
                                    date_order=date_order)
            _check_enum(path, value, enums, reasons, f"{field}[]")
            out.append(value)
            continue
        obj = item if isinstance(item, dict) else {}
        norm: dict[str, Any] = {}
        for sub in (*item_kinds, *(k for k in obj if k not in item_kinds)):
            value = normalize_value(item_kinds.get(sub, "text"), obj.get(sub), f"{path}.{sub}", reasons, origin=origin,
                                    convention=convention, date_order=date_order)
            _check_enum(f"{path}.{sub}", value, enums, reasons, f"{field}[].{sub}")
            norm[sub] = value
        out.append(norm)
    return out


def record_from_llm(data: dict[str, object], fields: dict[str, str], *, list_fields: dict[str, dict[str, str]] | None = None,
                    enums: dict[str, list[Any]] | None = None, origin: Origin = "llm",
                    convention: Convention | None = None, date_order: DateOrder | None = None) -> tuple[DocumentRecord, list[str]]:
    """Generative extract (a dict following the type pack's schema) -> normalised record by the pack's field kinds.
    Known attributes of the record are set directly, further pack fields go into `extra`. A parse error is not an
    exception but review reasons. 047: a `list` field uses the item description in `list_fields`; a violated
    enumerated value (`enums`, key: `field` or `field[].item_field`) gives review reasons, not an error. 081: amounts and
    quantities are read by the shared number reader: `origin` ("llm" for a generative extract, "canonical" for stored
    values) and the document's `convention`; 084: dates by the shared date reader with the document's `date_order`."""
    list_fields, enums = list_fields or {}, enums or {}
    reasons: list[str] = []
    items: list[LineItem] = []
    for i, raw_li in enumerate(data.get("line_items") or []):
        li = raw_li if isinstance(raw_li, dict) else dict(raw_li)
        p = f"line_items[{i}]"
        known = {
            "quantity": _number_or_reason("number", f"{p}.quantity", li.get("quantity"), reasons, origin=origin, convention=convention),
            **{k: _number_or_reason("money", f"{p}.{k}", li.get(k), reasons, origin=origin, convention=convention)
               for k in _LINE_ITEM_MONEY},
            **{k: normalize_text(li.get(k)) for k in _LINE_ITEM_TEXT},
        }
        extra = {k: normalize_text(str(v)) if isinstance(v, str) else v for k, v in li.items() if k not in known}
        items.append(LineItem(**known, extra=extra))
    values: dict[str, object] = {}
    extra_fields: dict[str, object] = {}
    own = set(DocumentRecord.model_fields) - {"extra", "line_items"}
    for field, kind in fields.items():
        if kind == "list" and field == "line_items":
            continue  # the invoice line items take the record's own `line_items` path (above), not twice
        if kind == "list":
            extra_fields[field] = _list_value(field, data.get(field), list_fields.get(field, {"*": "text"}), enums, reasons,
                                              origin, convention, date_order)
            continue
        value = normalize_value(kind, data.get(field), field, reasons, origin=origin, convention=convention,
                                date_order=date_order)
        _check_enum(field, value, enums, reasons, field)
        if field in own:
            values[field] = value
        else:
            extra_fields[field] = value
    return DocumentRecord(**values, extra=extra_fields, line_items=items), reasons


# --------------------------------------------------------------------------------------
# Candidates and JEV results (S path)
# --------------------------------------------------------------------------------------


class Candidate(BaseModel):
    kind: CandidateKind
    label: str  # normalised value: the Choice option key (also the dedup key)
    raw: str  # verbatim span, as printed
    line_no: int  # 1-based line index of the first occurrence
    context: str  # "L07: '<previous line>' | '<own line>'": the label is often on the line above
    ambiguous: bool = False  # money only: the dot as decimal or thousands is undecidable
    occurrences: int = 1


class FieldPick(BaseModel):
    field: str
    label: str | None  # None = JEV chose "none", or there was no candidate
    raw: str | None = None
    confidence: float | None  # 069 (Á11): None = no candidate, no Choice verdict (formerly 1.0)
    probabilities: dict[str, float] = Field(default_factory=dict)  # raw, unchanged
    n_options: int
    request_id: str
    present_p: float | None = None  # presence Noul P(the field is on the document), raw; threshold in the policy
    line_no: int | None = None  # line of the chosen candidate (from code, the Candidate): source reference for review
    # 076: the distinct candidates code found for the field; more than `n_options` means the list sent to JEV was cut
    # (the cap of 250, the request size budget, or since 160 the finder's own cap: 100 amounts on a utility bill, 80
    # quantities), and `n_candidates - n_options` were skipped. None: not recorded
    n_candidates: int | None = None

    @property
    def truncated(self) -> bool:
        return self.n_candidates is not None and self.n_candidates > self.n_options


class JevCall(BaseModel):
    request_id: str
    n_questions: int
    state_chars: int
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    seconds: float | None = None
    cached: bool = False
    cost_usd: float = 0.0


# --------------------------------------------------------------------------------------
# JEV verification (G path)
# --------------------------------------------------------------------------------------


class JevVerdicts(BaseModel):
    flags: dict[str, dict[str, float]] = Field(default_factory=dict)  # field -> {flag: P(yes)}
    doc_flags: dict[str, float] = Field(default_factory=dict)  # {"parties_swapped": p, ...}
    unsupported: list[str] = Field(default_factory=list)  # value present, no evidence (decided by code)
    model: str | None = None
    # 085: "code" = the code's own source check only (the G path without JEV, or after a JEV outage): no flags
    source: Literal["jev", "code"] = "jev"
    # 167 (review AI-10): the list fields left out of the request to fit its size (their rows were never checked)
    omitted: list[str] = Field(default_factory=list)


class CheckResult(BaseModel):
    name: str
    ok: bool
    code: str
    detail: str | None = None
    # 053: notice only: a failure shows in the interface but opens no to-do on its own (pack: `"review": false`)
    advisory: bool = False


# --------------------------------------------------------------------------------------
# Burr state
# --------------------------------------------------------------------------------------

Arm = Literal["S", "G"]
Route = Literal["auto", "human", "ocr"]


class FlowState(BaseModel):
    # input
    source_path: str  # the original path: file name, year hint and the stored path come from it
    read_path: str | None = None  # where the bytes are read from (the source instance); None: `source_path`
    case_id: str
    arm: Arm
    run_no: int = 1
    run_id: str = ""  # the backbone: ledger, datapoints and review_queue all refer to it
    doc_id: str = ""  # sha256 of the file content
    doc_type: str  # the type pack (202: always named; every saved state carries it)
    use_cache: bool = True  # False when measuring determinism
    jev: bool = True  # 085: False = processing without JEV (the G path with the code's own check)
    detail_probabilities: dict[str, float] = Field(default_factory=dict)  # 149: the detection's detailed-type answer
    # 190 (plan 189 A2b): a document given as text (an email's own text), read by `load_text` instead of the file
    source_text: str | None = None
    # pdf
    text: str = ""
    lines: list[str] = Field(default_factory=list)
    layout: list[LineLayout] = Field(default_factory=list)
    page_count: int = 0
    has_text_layer: bool = False
    text_source: str | None = None  # "pdf" (text layer) | "ocr" (jav/documents/ocr.py) | "text" (190) | None (no usable text -> needs_ocr)
    ocr_conf: float | None = None  # OCR mean word confidence (0-1), raw; threshold in the `ocr` block of policy.json
    ocr_low_conf_ratio: float | None = None  # share of weak (< 60) words
    ocr_engine: str | None = None  # native / docker / azure_di (the text's source, if OCR)
    ocr_escalated: bool = False  # the more accurate paid engine's text replaced weak local OCR (policy ocr.escalate_*)
    # 218 (plan P3 P3b): what the escalation's decision read (`ocr.escalation_rule`), traced with the save
    ocr_escalation: dict[str, Any] | None = None
    source_layer_id: str | None = None  # 045: word layer reference (jav/documents/source_layer.py); the words live in the store
    provenance: dict[str, Any] = Field(default_factory=dict)  # 045: per-field source location (jav/ai/grounding.py), saved
    # S path
    candidates: dict[str, list[Candidate]] = Field(default_factory=dict)
    picks: dict[str, FieldPick] = Field(default_factory=dict)
    # G path: the extract as a dict (keys per the type pack's schema; for the Hungarian invoice, the InvoiceLLM dump)
    llm_output: dict[str, Any] | None = None
    # 091: the token probabilities of its top-level values (jav/ai/token_confidence.py); None: not measurable
    llm_token_p: dict[str, dict[str, float | int]] | None = None
    verdicts: JevVerdicts | None = None
    # shared
    # 188 (plan 185 T3b): `invoice` before; a state saved under the old key is still read (also
    # `jav/flows/persistence.py`, for the saved flow states)
    record: DocumentRecord | None = Field(default=None, validation_alias=AliasChoices("record", "invoice"))
    validation: list[CheckResult] = Field(default_factory=list)
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    route: Route | None = None
    # 218 (plan P3 P3b): what the route's decision read (`policy.decision_inputs`), traced with the save; None: a state
    # decided before the trace
    route_inputs: dict[str, Any] | None = None
    # 218 (P3b): the cross-document checks' decisions ({point, inputs, keys}: a duplicate, an own tax number), traced
    # with the save
    check_traces: list[dict[str, Any]] = Field(default_factory=list)
    jev_calls: list[JevCall] = Field(default_factory=list)
    final_status: str | None = None
