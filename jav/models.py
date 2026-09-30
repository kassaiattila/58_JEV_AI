"""Pydantic modellek és normalizálók - a flow összes fix be-/kimeneti struktúrája.

Két réteg:
- `InvoiceLLM` / `LineItemLLM`: a régi invoice_hu/schema.json 1:1 tükre (nullable stringek, pénz decimális
  STRING ponttal, dátum ISO string). Ezt adja a generatív modell, és ezt hasonlítjuk a golden JSON-hoz.
- `InvoiceHU` / `LineItem`: normalizált réteg (`Decimal`, `date`), amit validátor, policy és eval fogyaszt.
  A konverzió (`llm_to_invoice`) az egyetlen hely, ahol parse-hiba review-okká válik kivétel helyett.

A Jev nyers kimenete (`FieldPick.probabilities`, `JevVerdicts.flags`) változatlanul tárolódik; a küszöbök
kizárólag a `policy` modulban élnek.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------------------
# Mezőlisták
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

# A golden `expected/*.json` datapoints-ában szereplő 13 fejléc-mező (a régi pontozási szerződés).
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
    "payment_iban",  # a régi szerződésben NEM pontozott, csak informatív - az eval külön kezeli
)

CandidateKind = Literal["tax_id", "date", "money", "iban", "invoice_number", "name", "address", "text"]  # text: címkés szöveg-mező (típus-csomag text_labels)

# --------------------------------------------------------------------------------------
# Normalizálók (kód birtokolja a formátumot - Jev soha)
# --------------------------------------------------------------------------------------

_CURRENCY_TOKENS = re.compile(r"(?i)\b(?:ft|huf|eur|usd|forint)\b\.?|[€$]")
_TRAILING_DASH = re.compile(r"[,.]\s*-\s*$")  # "12 000,-"
_NON_NUMERIC = re.compile(r"[^\d.,\-]")
_GROUPED_DOTS = re.compile(r"^-?\d{1,3}(?:\.\d{3})+$")


class MoneyParse(BaseModel):
    """Egy pénzösszeg-sztring feloldása. `ambiguous`: a pont tizedes VAGY ezres is lehet (pl. "12.34")."""

    value: Decimal | None
    ambiguous: bool = False


_GROUPED_COMMAS = re.compile(r"^-?\d{1,3}(?:,\d{3})+$")  # "1,600" / "1,234,567" - angol ezres vesszők (intl)
_DECIMAL_DOT_HINT = re.compile(r"[$€£]\s*-?\d|\d\s*(?:USD|EUR|GBP|AUD|CAD|CHF)\b", re.IGNORECASE)  # "$42.50" / "42.50 USD": a pont tizedes


def parse_money(raw: str | None, *, intl: bool = False) -> MoneyParse:
    """Magyar konvenció: vessző = tizedes, pont/szóköz = ezres. Angol "12,345.67" is felismerve.

    Nem számol és nem kerekít; csak a jelölést oldja fel. Bizonytalan esetben `ambiguous=True`.
    `intl=True` (nemzetközi jelölt-profil): a vessző + pontosan 3 jegy ezres ("1,600" = 1600, nem 1,6), és a
    pénznem-szimbólummal / -kóddal jelölt pontos tizedes ("$42.50", "42.50 USD") nem bizonytalan.
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
        # Az utolsó elválasztó a tizedes: "12.345,67" (HU) vagy "12,345.67" (EN).
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        if s.count(",") > 1 or (intl and _GROUPED_COMMAS.match(s)):
            s = s.replace(",", "")  # "1,234,567" - ezres vesszők; intl: "1,600" is
        else:
            s = s.replace(",", ".")
    elif has_dot:
        if _GROUPED_DOTS.match(s) and not dot_is_decimal:
            s = s.replace(".", "")  # "12.345" / "1.234.567" - HU ezres pontok
        elif s.count(".") == 1:
            ambiguous = not dot_is_decimal  # "12.34": angol tizedes vagy hibás ezres - kódban nem eldönthető (intl: a $ / USD eldönti)
        else:
            return MoneyParse(value=None)
    try:
        return MoneyParse(value=Decimal(s), ambiguous=ambiguous)
    except InvalidOperation:
        return MoneyParse(value=None)


def normalize_money(raw: str | None) -> Decimal | None:
    return parse_money(raw).value


def money_label(value: Decimal) -> str:
    """Kanonikus, összehasonlítható sztring: "127000", "20619.05" (felesleges nullák nélkül)."""
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

# Nemzetközi dátum-alakok (intl jelölt-profil). Konvenció: pont / kötőjel elválasztó = nap-először (07.03.2025 = márc. 7.,
# kontinentális); perjel = hónap-először (12/19/2022, US). Angol hónapnevek mindkét sorrendben.
_EN_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}  # fmt: skip
_EN_MONTH_ALT = "|".join(sorted(_EN_MONTHS, key=len, reverse=True))
DATE_EN_MDY_RE = re.compile(rf"\b({_EN_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.IGNORECASE)  # Dec 25, 2022
DATE_EN_DMY_RE = re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\.?\s+({_EN_MONTH_ALT})\.?,?\s+(\d{{4}})\b", re.IGNORECASE)  # 25 Dec 2022
DATE_DMY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{4})(?!\d)")  # 07.03.2025 / 07-03-2025 (nap-először)
DATE_MDY_SLASH_RE = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")  # 12/19/2022 (US, hónap-először)
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
    """`2022.02.10.`, `2022. 02. 10.`, `2022-02-10`, `2022/02/10`, `2022. február 10.` -> date. Kétjegyű év: nem.
    `intl=True`: emellett `Dec 25, 2022`, `25 Dec 2022`, `07.03.2025` (nap-először), `12/19/2022` (hónap-először)."""
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
    """Magyar adószám -> `########-#-##`; felismert uniós / nem uniós alak -> tömör írásmód („IE 8256796 U” ->
    „IE8256796U”); 069: a címke és a felesleges előtag levágva („HU VAT HU12345678” -> „HU12345678”, `jav/taxid.py`).
    Ami nem ismerhető fel, trimmelve marad (az ellenőrzés teendőt ad rá)."""
    from jav.taxid import clean

    return clean(raw)


def normalize_iban(raw: str | None) -> str | None:
    """Nyomtatott forma megtartva (csoportosítás is); csak trim + NBSP."""
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
# LLM-réteg: a régi schema.json 1:1 tükre
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
    """Magyar szállítói számla kivonata. Minden mező nullable; pénz decimális string ponttal; dátum ISO."""

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
# Normalizált réteg
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
    extra: dict[str, object] = Field(default_factory=dict)  # más típus-csomag tételsor-mezői (pl. period, meter_serial), normalizálva


class InvoiceHU(BaseModel):
    """Normalizált számla-rekord - a típus-csomagok közös rekordja (a név a magyar számlától örökölt; a külföldi számla
    ugyanezt használja `supplier_country`-val, a további típusok pack-mezői az `extra` szótárba kerülnek)."""

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
    supplier_country: str | None = None  # invoice_foreign: ISO 3166-1 alpha-2 (a régi séma mezője)
    extra: dict[str, object] = Field(default_factory=dict)  # a típus-csomag további fejléc-mezői (kód-oldali normalizálással)
    line_items: list[LineItem] = Field(default_factory=list)

    def get_field(self, name: str) -> object:
        return getattr(self, name) if name in type(self).model_fields and name != "extra" else self.extra.get(name)

    def to_datapoints(self, fields: tuple[str, ...] | None = None) -> dict[str, object]:
        """A golden `datapoints` formátuma (stringek), összehasonlításhoz és riporthoz. `fields`: a típus-csomag
        fejléc-mezői (alap: a magyar számla mezőlistája)."""
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


InvoiceRecord = InvoiceHU  # típus-független név ugyanarra a rekordra


def _plain(value: object) -> object:
    """A `datapoints` formátuma: pénz címke-stringként, dátum ISO-ként, listák és tételek rekurzívan (047)."""
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
    """Az LLM-réteg szerződése: sima decimális string PONT tizedessel, elválasztók nélkül ("1234.56").

    Itt a pont mindig tizedes (a HU forrás-parserrel ellentétben), mert a prompt ezt írja elő.
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
    """Egy mező normalizálása a típus-csomag FAJTÁJA szerint (a kód birtokolja a formátumot). Parse-hiba -> review-ok."""
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
        # mennyiség (kWh, m3, MJ, mérőállás): a generatív kivonat pont-tizedest ígér, de OCR-szövegről magyar alakot is ad ("143,00", "1 866")
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
    """047: tételes lista a csomag `list_fields` leírása szerint. `{"*": fajta}` = egyszerű értékek listája; különben
    objektumok, a tétel-mezők fajtája szerint normalizálva (ismeretlen tétel-mező: szövegként)."""
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
    """Generatív kivonat (szótár, a típus-csomag sémája szerint) -> normalizált rekord a csomag mező-fajtái alapján.
    A rekord ismert attribútumai közvetlenül, a csomag további mezői az `extra`-ba. Parse-hiba nem kivétel, hanem review-ok.
    047: `list` fajtájú mező a `list_fields` tétel-leírásával; felsorolt érték (`enums`, kulcs: `mező` vagy
    `mező[].tétel-mező`) megsértése review-ok, nem hiba."""
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
            continue  # a számla-tételsor a rekord saját `line_items` útján (fent), nem kétszer
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
    """LLM-réteg -> normalizált réteg (magyar számla). Parse-hiba nem kivétel, hanem review-ok."""
    from jav.typepack import get

    return record_from_llm(llm.model_dump(), get("invoice_hu").fields)


# --------------------------------------------------------------------------------------
# PDF elrendezés (szó-szintű rekonstrukció: sorok és oszlop-cellák)
# --------------------------------------------------------------------------------------


class CellLayout(BaseModel):
    text: str
    x0: float
    x1: float


class LineLayout(BaseModel):
    no: int  # 1-alapú, dokumentum-szintű
    page: int
    text: str  # cellák 3 szóközzel összefűzve - ez megy a Jev state-be
    cells: list[CellLayout] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Jelöltek és Jev-eredmények (S-kar)
# --------------------------------------------------------------------------------------


class Candidate(BaseModel):
    kind: CandidateKind
    label: str  # normalizált érték - ez a Choice-opció kulcsa (dedup-kulcs is)
    raw: str  # szó szerinti span, ahogy nyomtatva
    line_no: int  # 1-alapú sorindex az első előfordulásra
    context: str  # "L07: '<előző sor>' | '<saját sor>'" - a címke gyakran a fölötti sorban van
    ambiguous: bool = False  # csak money: a pont tizedes/ezres nem eldönthető
    occurrences: int = 1


class FieldPick(BaseModel):
    field: str
    label: str | None  # None = Jev "none"-t választott, vagy nem volt jelölt
    raw: str | None = None
    confidence: float | None  # 069 (Á11): None = nem volt jelölt, nincs Choice-ítélet (eddig 1,0)
    probabilities: dict[str, float] = Field(default_factory=dict)  # nyers, változatlan
    n_options: int
    request_id: str
    present_p: float | None = None  # jelenlét-Noul P(a mező szerepel a dokumentumon) - nyers; küszöb a policy-ban
    line_no: int | None = None  # a választott jelölt sora (kódból, a Candidate-ből) - forrás-hivatkozás a review-hoz


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
# Jev-ellenőrzés (G-kar)
# --------------------------------------------------------------------------------------


class JevVerdicts(BaseModel):
    flags: dict[str, dict[str, float]] = Field(default_factory=dict)  # mező -> {flag: P(igen)}
    doc_flags: dict[str, float] = Field(default_factory=dict)  # {"parties_swapped": p, ...}
    unsupported: list[str] = Field(default_factory=list)  # érték van, evidencia nincs (kód döntötte)
    model: str | None = None


class CheckResult(BaseModel):
    name: str
    ok: bool
    code: str
    detail: str | None = None
    advisory: bool = False  # 053: csak jelzés - a bukás a felületen látszik, de önmagában nem nyit teendőt (csomag: `"review": false`)


# --------------------------------------------------------------------------------------
# Burr állapot
# --------------------------------------------------------------------------------------

Arm = Literal["S", "G"]
Route = Literal["auto", "human", "ocr"]


class FlowState(BaseModel):
    # bemenet
    source_path: str
    case_id: str
    arm: Arm
    run_no: int = 1
    run_id: str = ""  # a gerinc: ledger, datapoints, review_queue mind erre hivatkozik
    doc_id: str = ""  # sha256 a fájl tartalmáról
    doc_type: str = "invoice_hu"
    use_cache: bool = True  # determinizmus-mérésnél False
    # pdf
    text: str = ""
    lines: list[str] = Field(default_factory=list)
    layout: list[LineLayout] = Field(default_factory=list)
    page_count: int = 0
    has_text_layer: bool = False
    text_source: str | None = None  # "pdf" (szövegréteg) | "ocr" (jav/ocr.py) | None (nincs használható szöveg -> needs_ocr)
    ocr_conf: float | None = None  # OCR átlagos szó-bizalom (0-1), nyersen; küszöb a policy.json `ocr` blokkjában
    ocr_low_conf_ratio: float | None = None  # gyenge (< 60) szavak aránya
    ocr_engine: str | None = None  # native / docker / azure_di (a szöveg forrása, ha OCR)
    ocr_escalated: bool = False  # a gyenge helyi OCR helyett a pontosabb, fizetős motor szövege ment tovább (policy ocr.escalate_*)
    source_layer_id: str | None = None  # 045: a szóréteg (jav/source_layer.py) hivatkozása; a szavak az adattárban vannak
    provenance: dict[str, Any] = Field(default_factory=dict)  # 045: mezőnkénti forráshely (jav/grounding.py), a mentés tárolja
    # S-kar
    candidates: dict[str, list[Candidate]] = Field(default_factory=dict)
    picks: dict[str, FieldPick] = Field(default_factory=dict)
    # G-kar - a kivonat szótárként (a típus-csomag sémája szerinti kulcsokkal; a magyar számlánál az InvoiceLLM dump-ja)
    llm_output: dict[str, Any] | None = None
    verdicts: JevVerdicts | None = None
    # közös
    invoice: InvoiceHU | None = None
    validation: list[CheckResult] = Field(default_factory=list)
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    route: Route | None = None
    jev_calls: list[JevCall] = Field(default_factory=list)
    final_status: str | None = None
