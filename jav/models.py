"""Pydantic models and normalisers: every fixed input/output structure of the flow.

Two layers:
- `InvoiceLLM` / `LineItemLLM`: a 1:1 mirror of the legacy invoice_hu/schema.json (nullable strings, money as a
  decimal STRING with a dot, date as an ISO string). The generative model returns this, and it is what we compare
  with the golden JSON.
- `InvoiceHU` / `LineItem`: the normalised layer (`Decimal`, `date`) consumed by validators, policy and evals.
  The conversion (`llm_to_invoice`) is the only place where a parse error becomes review reasons instead of an
  exception.

JEV's raw output (`FieldPick.probabilities`, `JevVerdicts.flags`) is stored unchanged; the thresholds live only in
the `policy` module.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

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

# text: a labelled text field (the type pack's text_labels)
CandidateKind = Literal["tax_id", "date", "money", "iban", "invoice_number", "name", "address", "text"]

# --------------------------------------------------------------------------------------
# Normalisers (code owns the format, never JEV)
# --------------------------------------------------------------------------------------

_CURRENCY_TOKENS = re.compile(r"(?i)\b(?:ft|huf|eur|usd|forint)\b\.?|[€$]")
_TRAILING_DASH = re.compile(r"[,.]\s*-\s*$")  # "12 000,-"
_NON_NUMERIC = re.compile(r"[^\d.,\-]")
_GROUPED_DOTS = re.compile(r"^-?\d{1,3}(?:\.\d{3})+$")


class MoneyParse(BaseModel):
    """Resolves a money string. `ambiguous`: the dot may be a decimal OR a thousands separator (e.g. "12.34")."""

    value: Decimal | None
    ambiguous: bool = False


_GROUPED_COMMAS = re.compile(r"^-?\d{1,3}(?:,\d{3})+$")  # "1,600" / "1,234,567": English thousands commas (intl)
# "$42.50" / "42.50 USD": the dot is a decimal point
_DECIMAL_DOT_HINT = re.compile(r"[$€£]\s*-?\d|\d\s*(?:USD|EUR|GBP|AUD|CAD|CHF)\b", re.IGNORECASE)


def parse_money(raw: str | None, *, intl: bool = False) -> MoneyParse:
    """Hungarian convention: comma = decimal, dot/space = thousands. English "12,345.67" is recognised too.

    Neither computes nor rounds; it only resolves the notation. When unsure, `ambiguous=True`.
    `intl=True` (international candidate profile): a comma + exactly 3 digits is a thousands separator ("1,600" = 1600,
    not 1.6), and a decimal dot marked by a currency symbol / code ("$42.50", "42.50 USD") is not ambiguous.
    """
    if raw is None:
        return MoneyParse(value=None)
    s = str(raw).replace(" ", " ").strip()
    dot_is_decimal = intl and bool(_DECIMAL_DOT_HINT.search(s))
    s = _CURRENCY_TOKENS.sub("", s)
    s = _TRAILING_DASH.sub("", s).strip()
    s = _NON_NUMERIC.sub("", s.replace(" ", ""))
    if not s or s in {"-", ".", ","}:
        return MoneyParse(value=None)

    ambiguous = False
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        # The last separator is the decimal one: "12.345,67" (HU) or "12,345.67" (EN).
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        if s.count(",") > 1 or (intl and _GROUPED_COMMAS.match(s)):
            s = s.replace(",", "")  # "1,234,567": thousands commas; intl: "1,600" too
        else:
            s = s.replace(",", ".")
    elif has_dot:
        if _GROUPED_DOTS.match(s) and not dot_is_decimal:
            s = s.replace(".", "")  # "12.345" / "1.234.567": HU thousands dots
        elif s.count(".") == 1:
            # "12.34": English decimal or malformed thousands, undecidable in code (intl: the $ / USD decides)
            ambiguous = not dot_is_decimal
        else:
            return MoneyParse(value=None)
    try:
        return MoneyParse(value=Decimal(s), ambiguous=ambiguous)
    except InvalidOperation:
        return MoneyParse(value=None)


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

DATE_NUMERIC_RE = re.compile(r"(?<!\d)(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\.?(?!\d)")
DATE_TEXT_RE = re.compile(rf"(?<!\d)(\d{{4}})\.?\s+({_MONTH_ALT})\.?\s+(\d{{1,2}})\.?(?!\d)", re.IGNORECASE)

# International date forms (intl candidate profile). Convention: a dot / hyphen separator = day first (07.03.2025 =
# 7 March, continental); a slash = month first (12/19/2022, US). English month names in both orders.
_EN_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}  # fmt: skip
_EN_MONTH_ALT = "|".join(sorted(_EN_MONTHS, key=len, reverse=True))
DATE_EN_MDY_RE = re.compile(rf"\b({_EN_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE)  # Dec 25, 2022
DATE_EN_DMY_RE = re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\.?\s+({_EN_MONTH_ALT})\.?,?\s+(\d{{4}})\b", re.IGNORECASE)  # 25 Dec 2022
DATE_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{4})(?!\d)")  # 07.03.2025 / 07-03-2025 (day first)
DATE_MDY_SLASH_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")  # 12/19/2022 (US, month first)
INTL_DATE_RES: tuple[re.Pattern[str], ...] = (DATE_EN_MDY_RE, DATE_EN_DMY_RE, DATE_DMY_RE, DATE_MDY_SLASH_RE)


def _intl_date(m: re.Match[str], rx: re.Pattern[str]) -> tuple[int, int, int]:
    if rx is DATE_EN_MDY_RE:
        return int(m.group(3)), _EN_MONTHS[m.group(1).lower()], int(m.group(2))
    if rx is DATE_EN_DMY_RE:
        return int(m.group(3)), _EN_MONTHS[m.group(2).lower()], int(m.group(1))
    if rx is DATE_DMY_RE:
        return int(m.group(3)), int(m.group(2)), int(m.group(1))
    return int(m.group(3)), int(m.group(1)), int(m.group(2))  # MDY slash


def normalize_date(raw: str | None, *, intl: bool = False) -> date | None:
    """`2022.02.10.`, `2022. 02. 10.`, `2022-02-10`, `2022/02/10`, `2022. február 10.` -> date. Two-digit year: no.
    `intl=True`: also `Dec 25, 2022`, `25 Dec 2022`, `07.03.2025` (day first), `12/19/2022` (month first)."""
    if raw is None:
        return None
    s = str(raw).replace(" ", " ").strip()
    m = DATE_NUMERIC_RE.search(s)
    if m:
        y, mo, d = (int(g) for g in m.groups())
    else:
        m = DATE_TEXT_RE.search(s)
        if m:
            y, d = int(m.group(1)), int(m.group(3))
            mo = _HU_MONTHS[m.group(2).lower()]
        elif intl:
            for rx in INTL_DATE_RES:
                m = rx.search(s)
                if m:
                    y, mo, d = _intl_date(m, rx)
                    break
            else:
                return None
        else:
            return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


_DIGITS = re.compile(r"\D")


def normalize_tax_id(raw: str | None) -> str | None:
    """Hungarian tax number -> `########-#-##`; a recognised EU / non-EU form -> compact spelling ("IE 8256796 U" ->
    "IE8256796U"); 069: the label and the superfluous prefix are cut off ("HU VAT HU12345678" -> "HU12345678",
    `jav/taxid.py`). Anything unrecognised stays trimmed (the check raises a to-do for it)."""
    from jav.taxid import clean

    return clean(raw)


def normalize_iban(raw: str | None) -> str | None:
    """Keeps the printed form (grouping included); only trim + NBSP."""
    if raw is None:
        return None
    s = str(raw).replace(" ", " ").strip()
    return s or None


def normalize_text(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = " ".join(str(raw).replace(" ", " ").split())
    return s or None


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


class InvoiceHU(BaseModel):
    """Normalised invoice record, shared by the type packs (the name is inherited from the Hungarian invoice; the
    foreign invoice uses it too, with `supplier_country`, and the pack fields of further types go into `extra`)."""

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


InvoiceRecord = InvoiceHU  # type-neutral name for the same record


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


def parse_money_contract(raw: str | None) -> Decimal | None:
    """The LLM layer's contract: a plain decimal string with a DOT as the decimal point, no separators ("1234.56").

    Here the dot is always the decimal point (unlike the HU source parser), because the prompt prescribes it.
    """
    if raw is None:
        return None
    s = str(raw).strip().replace(" ", "")
    if not s:
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _money_or_reason(field: str, raw: str | None, reasons: list[str]) -> Decimal | None:
    if raw is None:
        return None
    value = parse_money_contract(raw)
    if value is None:
        reasons.append(f"{field}:unparseable:{raw!r}")
    return value


def _date_or_reason(field: str, raw: str | None, reasons: list[str]) -> date | None:
    if raw is None:
        return None
    value = normalize_date(raw)
    if value is None:
        reasons.append(f"{field}:unparseable:{raw!r}")
    return value


_LINE_ITEM_MONEY = ("unit_price", "net_amount", "gross_amount", "vat_amount")
_LINE_ITEM_TEXT = ("description", "vat_rate", "unit", "product_code", "note")


def normalize_value(kind: str, raw: object, field: str, reasons: list[str]) -> object:
    """Normalises one field by its KIND in the type pack (code owns the format). Parse error -> review reasons."""
    if raw is None:
        return None
    if kind == "money":
        return _money_or_reason(field, str(raw), reasons)
    if kind == "date":
        return _date_or_reason(field, str(raw), reasons)
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
    if kind == "number":
        # quantity (kWh, m3, MJ, meter reading): the generative extract promises a decimal dot, but from OCR text it
        # also returns the Hungarian form ("143,00", "1 866")
        value = parse_money(str(raw)).value
        if value is None:
            reasons.append(f"{field}:unparseable:{raw!r}")
        return value
    return normalize_text(str(raw))


def _check_enum(path: str, value: object, enums: dict[str, list[Any]], reasons: list[str], key: str) -> None:
    allowed = enums.get(key)
    if allowed is not None and value is not None and value not in allowed:
        reasons.append(f"{path}:not_in_enum:{value!r}")


def _list_value(field: str, raw: object, item_kinds: dict[str, str], enums: dict[str, list[Any]], reasons: list[str]) -> list[Any]:
    """047: an itemised list as described by the pack's `list_fields`. `{"*": kind}` = a list of plain values;
    otherwise objects, normalised by the kind of each item field (unknown item field: as text)."""
    out: list[Any] = []
    for i, item in enumerate(raw if isinstance(raw, list) else []):
        path = f"{field}[{i}]"
        if "*" in item_kinds:
            value = normalize_value(item_kinds["*"], item, path, reasons)
            _check_enum(path, value, enums, reasons, f"{field}[]")
            out.append(value)
            continue
        obj = item if isinstance(item, dict) else {}
        norm: dict[str, Any] = {}
        for sub in (*item_kinds, *(k for k in obj if k not in item_kinds)):
            value = normalize_value(item_kinds.get(sub, "text"), obj.get(sub), f"{path}.{sub}", reasons)
            _check_enum(f"{path}.{sub}", value, enums, reasons, f"{field}[].{sub}")
            norm[sub] = value
        out.append(norm)
    return out


def record_from_llm(data: dict[str, object], fields: dict[str, str], *, list_fields: dict[str, dict[str, str]] | None = None,
                    enums: dict[str, list[Any]] | None = None) -> tuple[InvoiceHU, list[str]]:
    """Generative extract (a dict following the type pack's schema) -> normalised record by the pack's field kinds.
    Known attributes of the record are set directly, further pack fields go into `extra`. A parse error is not an
    exception but review reasons. 047: a `list` field uses the item description in `list_fields`; a violated
    enumerated value (`enums`, key: `field` or `field[].item_field`) gives review reasons, not an error."""
    list_fields, enums = list_fields or {}, enums or {}
    reasons: list[str] = []
    items: list[LineItem] = []
    for i, raw_li in enumerate(data.get("line_items") or []):
        li = raw_li if isinstance(raw_li, dict) else dict(raw_li)
        p = f"line_items[{i}]"
        q = li.get("quantity")
        known = {
            "quantity": Decimal(str(q)) if q is not None else None,
            **{k: _money_or_reason(f"{p}.{k}", li.get(k), reasons) for k in _LINE_ITEM_MONEY},
            **{k: normalize_text(li.get(k)) for k in _LINE_ITEM_TEXT},
        }
        extra = {k: normalize_text(str(v)) if isinstance(v, str) else v for k, v in li.items() if k not in known}
        items.append(LineItem(**known, extra=extra))
    values: dict[str, object] = {}
    extra_fields: dict[str, object] = {}
    own = set(InvoiceHU.model_fields) - {"extra", "line_items"}
    for field, kind in fields.items():
        if kind == "list" and field == "line_items":
            continue  # the invoice line items take the record's own `line_items` path (above), not twice
        if kind == "list":
            extra_fields[field] = _list_value(field, data.get(field), list_fields.get(field, {"*": "text"}), enums, reasons)
            continue
        value = normalize_value(kind, data.get(field), field, reasons)
        _check_enum(field, value, enums, reasons, field)
        if field in own:
            values[field] = value
        else:
            extra_fields[field] = value
    return InvoiceHU(**values, extra=extra_fields, line_items=items), reasons


def llm_to_invoice(llm: InvoiceLLM) -> tuple[InvoiceHU, list[str]]:
    """LLM layer -> normalised layer (Hungarian invoice). A parse error is not an exception but review reasons."""
    from jav.typepack import get

    return record_from_llm(llm.model_dump(), get("invoice_hu").fields)


# --------------------------------------------------------------------------------------
# PDF layout (word-level reconstruction: lines and column cells)
# --------------------------------------------------------------------------------------


class CellLayout(BaseModel):
    text: str
    x0: float
    x1: float


class LineLayout(BaseModel):
    no: int  # 1-based, document-wide
    page: int
    text: str  # cells joined with 3 spaces; this goes into the JEV state
    cells: list[CellLayout] = Field(default_factory=list)


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
    # (the cap of 250, or the request size budget), and `n_candidates - n_options` were skipped. None: not recorded
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
    doc_type: str = "invoice_hu"
    use_cache: bool = True  # False when measuring determinism
    # pdf
    text: str = ""
    lines: list[str] = Field(default_factory=list)
    layout: list[LineLayout] = Field(default_factory=list)
    page_count: int = 0
    has_text_layer: bool = False
    text_source: str | None = None  # "pdf" (text layer) | "ocr" (jav/ocr.py) | None (no usable text -> needs_ocr)
    ocr_conf: float | None = None  # OCR mean word confidence (0-1), raw; threshold in the `ocr` block of policy.json
    ocr_low_conf_ratio: float | None = None  # share of weak (< 60) words
    ocr_engine: str | None = None  # native / docker / azure_di (the text's source, if OCR)
    ocr_escalated: bool = False  # the more accurate paid engine's text replaced weak local OCR (policy ocr.escalate_*)
    source_layer_id: str | None = None  # 045: word layer reference (jav/source_layer.py); the words live in the store
    provenance: dict[str, Any] = Field(default_factory=dict)  # 045: per-field source location (jav/grounding.py), saved
    # S path
    candidates: dict[str, list[Candidate]] = Field(default_factory=dict)
    picks: dict[str, FieldPick] = Field(default_factory=dict)
    # G path: the extract as a dict (keys per the type pack's schema; for the Hungarian invoice, the InvoiceLLM dump)
    llm_output: dict[str, Any] | None = None
    verdicts: JevVerdicts | None = None
    # shared
    invoice: InvoiceHU | None = None
    validation: list[CheckResult] = Field(default_factory=list)
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    route: Route | None = None
    jev_calls: list[JevCall] = Field(default_factory=list)
    final_status: str | None = None
