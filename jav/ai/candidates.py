"""Deterministic candidate finders for the S path: code finds, JEV chooses.

Principle: the finders are tuned for recall (more candidates rather than fewer), JEV picks one of them with a Choice,
and code normalises the verbatim value that was picked. Whatever a finder misses, JEV cannot choose -
so the offline `candidate_recall` (evals) is the upper bound of the S path.

Order + masking: the value-like finders (`iban -> tax_id -> date -> invoice_number -> money`) replace each matched
span with `#` in the working copy of the line, so later finders do not find it again (e.g. the digits of a tax
number must not become money candidates). The name/address finders work on cells and do not mask.

Candidate profiles (type pack `candidate_profile`): `hu` is the original regex set for Hungarian invoices, unchanged;
`intl` is the international extension (EU / Turkish / Polish / US tax IDs, English and continental date forms,
`$1,600.00` money notation, foreign legal forms, English party labels, reverse charge = synthetic 0 VAT candidate).
231 (F2): the patterns, the limits and the profiles are data, `configs/candidate_profiles.json`; the finders are
the mechanism. When introduced, the `hu` profile was bit-identical to the previous behaviour; since then the invoice
number below the title (065) and the masking of invoice-number candidates (066: standalone occurrences only) are
shared by both profiles. A new profile is data alone: a type pack names it in `candidate_profile`.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field

from jav.core import cfg
from jav.core.dates import document_date_order, document_short_order, find_dates_in
from jav.ai.models import (
    DATE_NUMERIC_RE,
    Candidate,
    CandidateKind,
    account_key,
    money_label,
    normalize_tax_id,
    parse_money,
)
from jav.documents.layout import LineLayout
from jav.core.numbers import Convention, document_convention, has_decimal_dot_hint
from jav.core.taxid import recognize as recognize_tax_id
from jav.ai.validators import hu_tax_id

MAX_OPTIONS = 250  # the 255-option Choice limit, minus "none" and a margin
COLUMN_X_TOLERANCE = 15.0  # pt - x0 difference of cells in the same column

# --- the patterns, the limits and the profiles: data (231, F2) ----------------------------
# `configs/candidate_profiles.json` holds every pattern (with its note), the limits and the profiles; the finders below
# are the mechanism. The module keeps the names it always had, so its importers are unchanged.

_DATA = cfg.load("candidate_profiles")
_PATTERNS: dict[str, re.Pattern[str]] = {key: re.compile(spec["regex"]) for key, spec in _DATA["patterns"].items()}
_LIMITS: dict[str, int] = _DATA["limits"]

MAX_NAME_FALLBACK: int = _LIMITS["max_name_fallback"]
CONTEXT_MAX_CHARS: int = _LIMITS["context_max_chars"]
MAX_QUANTITY_OPTIONS: int = _LIMITS["max_quantity_options"]
TEXT_VALUE_MAX: int = _LIMITS["text_value_max"]
_TEXT_STRIP: str = _DATA["text_strip"]

IBAN_RES: tuple[re.Pattern[str], ...] = tuple(re.compile(p) for p in _DATA["iban"])
IBAN_INTL_RE = _PATTERNS["iban_intl"]
PARTIAL_HU_IBAN_RE = _PATTERNS["partial_hu_iban"]
IBAN_GROUP_RE = _PATTERNS["iban_group"]
TAXID_FORMATTED_RE = _PATTERNS["taxid_formatted"]
TAXID_CONTIGUOUS_RE = _PATTERNS["taxid_contiguous"]
TAXID_EU_RE = _PATTERNS["taxid_eu"]
TAXID_EU_INTL_RE = _PATTERNS["taxid_eu_intl"]
TAXID_LABEL_INTL_RE = _PATTERNS["taxid_label_intl"]
TAXID_LABEL_TOKEN_RE = _PATTERNS["taxid_label_token"]
TAXID_OCR_RE = _PATTERNS["taxid_ocr"]
TAXID_LABEL_HU_RE = _PATTERNS["taxid_label_hu"]
INVOICE_LABEL_RE = _PATTERNS["invoice_label"]
INVOICE_LABEL_INTL_RE = _PATTERNS["invoice_label_intl"]
INVOICE_LABEL_UTILITY_RE = _PATTERNS["invoice_label_utility"]
INVOICE_TITLE_RE = _PATTERNS["invoice_title"]
INVOICE_TOKEN_RE = _PATTERNS["invoice_token"]
AMOUNT_TOKEN_RE = _PATTERNS["amount_token"]
MONEY_RE = _PATTERNS["money"]
MONEY_INTL_RE = _PATTERNS["money_intl"]
QUANTITY_RE = _PATTERNS["quantity"]
QUANTITY_LINE_RE = _PATTERNS["quantity_line"]
PERCENT_AFTER_RE = _PATTERNS["percent_after"]
TOTAL_LINE_RE = _PATTERNS["total_line"]
REVERSE_CHARGE_RE = _PATTERNS["reverse_charge"]
CURRENCY_HINT_RE = _PATTERNS["currency_hint"]
LEGAL_FORM_RE = _PATTERNS["legal_form"]
LEGAL_FORM_INTL_RE = _PATTERNS["legal_form_intl"]
LEGAL_FORM_UTILITY_RE = _PATTERNS["legal_form_utility"]
PARTY_LABEL_RE = _PATTERNS["party_label"]
PARTY_LABEL_INTL_RE = _PATTERNS["party_label_intl"]
PARTY_LABEL_UTILITY_RE = _PATTERNS["party_label_utility"]
LABEL_ONLY_RE = _PATTERNS["label_only"]
LABEL_ONLY_INTL_RE = _PATTERNS["label_only_intl"]
LABEL_ONLY_UTILITY_RE = _PATTERNS["label_only_utility"]
ADDRESS_LABEL_UTILITY_RE = _PATTERNS["address_label_utility"]
NAME_TRAILING_ID_RE = _PATTERNS["name_trailing_id"]
NAME_STOP_RE = _PATTERNS["name_stop"]
ADDRESS_RE = _PATTERNS["address"]
ADDRESS_INTL_RE = _PATTERNS["address_intl"]
ADDRESS_STOP_INTL_RE = _PATTERNS["address_stop_intl"]
PAYMENT_METHOD_LINE_RE = _PATTERNS["payment_method_line"]
_LEADING_ARTICLE_RE = _PATTERNS["leading_article"]
_PAREN_WRAP_RE = _PATTERNS["paren_wrap"]
_GREETING_RE = _PATTERNS["greeting"]
_ADDRESS_TAIL_RE = _PATTERNS["address_tail"]
_INCOMPLETE_LEGAL_FORM_RE = _PATTERNS["incomplete_legal_form"]
_NAME_GOES_ON_RE = _PATTERNS["name_goes_on"]
_NAME_TAIL_SEPARATOR_RE = _PATTERNS["name_tail_separator"]

_CURRENCY_SETS: dict[str, dict[str, re.Pattern[str]]] = {
    name: {code: re.compile(p) for code, p in tokens.items()} for name, tokens in _DATA["currency_tokens"].items()}
CURRENCY_TOKENS = _CURRENCY_SETS["base"]
CURRENCY_TOKENS_INTL = _CURRENCY_SETS["intl"]


@dataclass(frozen=True)
class Profile:
    """The regex set of one candidate profile (data; the finders are the mechanism)."""

    name: str
    intl: bool  # international forms in parse_money
    legal_form_re: re.Pattern[str]
    party_label_re: re.Pattern[str]
    label_only_re: re.Pattern[str]
    invoice_label_re: re.Pattern[str]
    money_re: re.Pattern[str]
    currency_tokens: dict[str, re.Pattern[str]] = field(default_factory=dict)
    extra_iban_res: tuple[re.Pattern[str], ...] = ()
    extra_taxid_res: tuple[re.Pattern[str], ...] = ()
    taxid_label_re: re.Pattern[str] | None = None  # in a labelled line the identifier tokens after the label are tax-number candidates too
    name_cut_after_legal_form: bool = False  # "Microsoft Ireland Operations Ltd, One Microsoft Place, ..." -> the name ends at the legal form
    reverse_charge_zero: bool = False  # "reverse charge" printed and no 0 amount -> synthetic "0" money candidate (VAT)
    intl_addresses: bool = False
    ocr_dates: bool = False  # OCR tolerance: a comma separator in a year-first date is read as a dot ("2025,08.31")
    short_dates: bool = False  # 084: flagged all-number dates with a two-digit year ("04.12.22"); elsewhere such text is
    # mostly a code ("1-2-44"), so it is a candidate only when the document's own order resolves it
    address_label_re: re.Pattern[str] | None = None  # address labels ("Felhasználó címe:") cut from the address candidate; default: the party labels
    invoice_lookahead: int = 1  # lines after the invoice-number label searched for the value (OCR: a line may fall between label and value)
    ocr_taxid: bool = False  # OCR tolerance: a Hungarian tax number broken by a space is a candidate too if its check digit is correct
    max_money_options: int = MAX_OPTIONS  # upper limit of money candidates (smaller on number-heavy OCR-text utility bills: the request token limit)
    name_fallback_combined: bool = False  # 231 (F2): the name fallback's earlier, combined limit (the `hu` profile's)
    evidence_intl: bool = False  # 231 (F2): the G path's evidence reads numbers in the international forms


def _profile(name: str, spec: dict) -> Profile:
    """A profile from its description in `configs/candidate_profiles.json` (its patterns named by key)."""
    def pattern(key: str | None) -> re.Pattern[str] | None:
        return None if key is None else _PATTERNS[key]

    return Profile(
        name=name, intl=spec["intl"], legal_form_re=_PATTERNS[spec["legal_form"]], party_label_re=_PATTERNS[spec["party_label"]],
        label_only_re=_PATTERNS[spec["label_only"]], invoice_label_re=_PATTERNS[spec["invoice_label"]],
        money_re=_PATTERNS[spec["money"]], currency_tokens=_CURRENCY_SETS[spec["currency_tokens"]],
        extra_iban_res=tuple(_PATTERNS[k] for k in spec["extra_iban"]), extra_taxid_res=tuple(_PATTERNS[k] for k in spec["extra_taxid"]),
        taxid_label_re=pattern(spec["taxid_label"]), name_cut_after_legal_form=spec["name_cut_after_legal_form"],
        reverse_charge_zero=spec["reverse_charge_zero"], intl_addresses=spec["intl_addresses"], ocr_dates=spec["ocr_dates"],
        short_dates=spec["short_dates"], address_label_re=pattern(spec["address_label"]), invoice_lookahead=spec["invoice_lookahead"],
        ocr_taxid=spec["ocr_taxid"], max_money_options=spec["max_money_options"],
        name_fallback_combined=spec["name_fallback_combined"], evidence_intl=spec["evidence_intl"],
    )


PROFILES: dict[str, Profile] = {name: _profile(name, spec) for name, spec in _DATA["profiles"].items()}
HU, INTL, UTILITY = PROFILES["hu"], PROFILES["intl"], PROFILES["utility"]


def profile_of(profile: str | Profile | None) -> Profile:
    if isinstance(profile, Profile):
        return profile
    return PROFILES[profile or "hu"]


# --- helpers ---------------------------------------------------------------------------


def _context(lines: list[LineLayout], idx: int) -> str:
    prev = lines[idx - 1].text if idx > 0 else ""
    own = lines[idx].text
    return f"L{lines[idx].no:02d}: '{prev[:CONTEXT_MAX_CHARS]}' | '{own[:CONTEXT_MAX_CHARS]}'"


class _Bucket:
    """Collects candidates, deduplicated by normalised label, in document order."""

    def __init__(self, kind: CandidateKind) -> None:
        self.kind = kind
        self._items: OrderedDict[str, Candidate] = OrderedDict()

    def add(self, label: str, raw: str, lines: list[LineLayout], idx: int, *, ambiguous: bool = False) -> None:
        label = label.strip()
        if not label:
            return
        ctx = _context(lines, idx)
        if label in self._items:
            c = self._items[label]
            c.occurrences += 1
            if ctx not in c.context and len(c.context) < 600:
                c.context += " ; " + ctx
            return
        self._items[label] = Candidate(
            kind=self.kind, label=label, raw=raw.strip(), line_no=lines[idx].no, context=ctx, ambiguous=ambiguous
        )

    def items(self) -> list[Candidate]:
        return list(self._items.values())

    def has(self, label: str) -> bool:
        return label in self._items


def _mask(text: str, start: int, end: int) -> str:
    return text[:start] + "#" * (end - start) + text[end:]


# --- finders ---------------------------------------------------------------------------




def _account_merge_keys(raw: str) -> tuple[str, str | None]:
    """Two forms are one account when either key matches. The last 16 digits join a 24-digit number with its tail
    when the reader split the number across two cells; 156: the 24-digit domestic number of a Hungarian account joins
    its 16-digit form (eight trailing zeros) and its IBAN (without the country code and check digits)."""
    domestic = account_key(raw)
    return re.sub(r"\D", "", raw)[-16:], domestic if len(domestic) == 24 and domestic.isdigit() else None


def find_ibans(lines: list[LineLayout], work: list[str], profile: Profile = HU) -> list[Candidate]:
    bucket = _Bucket("iban")
    seen_tails: dict[str, str] = {}
    seen_domestic: dict[str, str] = {}

    def add(label_raw: str, i: int) -> None:
        tail, domestic = _account_merge_keys(label_raw)
        label = seen_tails.get(tail) or (seen_domestic.get(domestic) if domestic else None) or " ".join(label_raw.split())
        seen_tails.setdefault(tail, label)
        if domestic:
            seen_domestic.setdefault(domestic, label)
        bucket.add(label, label_raw, lines, i)

    # HU IBAN broken across lines (NAV Online Számlázó template): "HU82 1210 0028 4681 3574 0000" + "0000" below it
    for i, ln in enumerate(lines):
        for cell in ln.cells:
            if not PARTIAL_HU_IBAN_RE.match(cell.text):
                continue
            parts = cell.text.split()
            for j, text in _column_cells_below(lines, i, cell.x0, depth=3):
                if len(re.sub(r"\D", "", " ".join(parts))) >= 26:
                    break
                if IBAN_GROUP_RE.match(text):
                    parts.append(text)
                    pos = work[j].find(text)
                    if pos != -1:
                        work[j] = _mask(work[j], pos, pos + len(text))
            joined = " ".join(parts)
            if len(re.sub(r"\D", "", joined)) == 26:
                add(joined, i)
                pos = work[i].find(cell.text)
                if pos != -1:
                    work[i] = _mask(work[i], pos, pos + len(cell.text))

    for i, ln in enumerate(lines):
        for rx in IBAN_RES + profile.extra_iban_res:
            for m in list(rx.finditer(work[i])):
                if rx in profile.extra_iban_res and len(re.sub(r"[^A-Z0-9]", "", m.group(0))) < 15:
                    continue  # too short for an IBAN (e.g. the shape of an EU tax number)
                add(m.group(0), i)
                work[i] = _mask(work[i], m.start(), m.end())
    return bucket.items()


def find_tax_ids(lines: list[LineLayout], work: list[str], profile: Profile = HU) -> list[Candidate]:
    bucket = _Bucket("tax_id")
    for i, ln in enumerate(lines):
        for m in list(TAXID_FORMATTED_RE.finditer(work[i])):
            bucket.add(normalize_tax_id(m.group(0)) or "", m.group(0), lines, i)
            work[i] = _mask(work[i], m.start(), m.end())
        for m in list(TAXID_CONTIGUOUS_RE.finditer(work[i])):
            # 11 contiguous digits are a tax-number candidate only if the check digit is correct (filters out phone
            # numbers)
            if hu_tax_id(m.group(0)).ok:
                bucket.add(normalize_tax_id(m.group(0)) or "", m.group(0), lines, i)
                work[i] = _mask(work[i], m.start(), m.end())
        for m in list(TAXID_EU_RE.finditer(work[i])):
            bucket.add(m.group(0), m.group(0), lines, i)
            work[i] = _mask(work[i], m.start(), m.end())
        if profile.ocr_taxid and TAXID_LABEL_HU_RE.search(ln.text):  # only in a line with a tax-number label (not the table's number columns)
            for m in list(TAXID_OCR_RE.finditer(work[i])):
                compact = re.sub(r"[  ]", "", m.group(0))
                if hu_tax_id(compact).ok:  # only with a valid check digit: the spaced form is noisy
                    bucket.add(normalize_tax_id(compact) or "", m.group(0), lines, i)
                    work[i] = _mask(work[i], m.start(), m.end())
        for rx in profile.extra_taxid_res:
            for m in list(rx.finditer(work[i])):
                found = _recognized_prefix(m.group(0))
                if found is None:
                    continue
                label, length = found
                bucket.add(label, m.group(0)[:length], lines, i)
                work[i] = _mask(work[i], m.start(), m.start() + length)
        if profile.taxid_label_re:
            # labelled line (VAT ID / Tax ID / VKN / EIN ...): the identifier tokens (local forms) are candidates too,
            # but only in the label's cell and the next cell (069, 066 Á27: a phone number in a distant cell of the line
            # is not)
            for start, end in _label_spans(ln, profile.taxid_label_re):
                for m in list(TAXID_LABEL_TOKEN_RE.finditer(work[i], start, end)):
                    bucket.add(m.group(0), m.group(0), lines, i)
                    work[i] = _mask(work[i], m.start(), m.end())
    return bucket.items()


def _recognized_prefix(raw: str) -> tuple[str, int] | None:
    """The recognised part of an EU / international tax-number match (canonical form, length within the match). A
    separate trailing letter group may be part of an Irish tax number ("IE 8256796 U") or the next word ("DE123456789
    AG"): it is tried with it first, then without. The spaced "NO …" is a Norwegian tax number only with the MVA
    suffix."""
    if re.match(r"NO[ -]", raw) and not raw.endswith("MVA"):
        return None
    for length in (len(raw), raw.rfind(" ")):
        if length > 0:
            t = recognize_tax_id(raw[:length])
            if t is not None:
                return t.canonical, length
    return None


def _label_spans(ln: LineLayout, label_re: re.Pattern[str]) -> list[tuple[int, int]]:
    """The spans of the label matches in the line text: from the label to the end of the label's cell, or of the next
    cell. Without cells (or if the cells do not make up the line) from the label to the end of the line."""
    spans: list[tuple[int, int]] = []
    bounds: list[tuple[int, int]] = []
    pos = 0
    for cell in ln.cells:
        at = ln.text.find(cell.text, pos)
        if at < 0:
            bounds = []
            break
        bounds.append((at, at + len(cell.text)))
        pos = at + len(cell.text)
    for m in label_re.finditer(ln.text):
        k = next((n for n, (a, b) in enumerate(bounds) if a <= m.start() < b), None)
        if k is None:
            spans.append((m.start(), len(ln.text)))
        else:
            spans.append((m.start(), bounds[min(k + 1, len(bounds) - 1)][1]))
    return spans


def find_dates(lines: list[LineLayout], work: list[str], profile: Profile = HU) -> list[Candidate]:
    """084: every date of every line by the shared date reader (`jav/core/dates.py`), on every profile, with the document's
    own day/month order; a date whose day and month can be read two ways is a flagged candidate (picking it gives a
    to-do). A range like "11/25/2022 - 12/25/2022" stays two dates: the reader never lets one date overlap another.
    141: a document printing its two-digit-year dates year first ("26.06.24") has them read so, on every profile."""
    order = document_date_order(ln.text for ln in lines)
    short_order = document_short_order(ln.text for ln in lines)
    bucket = _Bucket("date")
    for i in range(len(lines)):
        for h in find_dates_in(work[i], order=order, ocr=profile.ocr_dates, short_order=short_order):
            if h.short and h.ambiguous and not profile.short_dates:
                continue
            bucket.add(h.value.isoformat(), h.raw, lines, i, ambiguous=h.ambiguous)
            work[i] = _mask(work[i], h.start, h.end)
    return bucket.items()


def _invoice_tokens(text: str) -> list[str]:
    out = []
    for m in INVOICE_TOKEN_RE.finditer(text):
        tok = m.group(0).strip(":;,.")
        if "#" in tok or not any(ch.isdigit() for ch in tok) or len(tok) < 2:
            continue
        if re.fullmatch(r"\d{1,2}/\d{1,2}", tok):  # "1/1" page number
            continue
        out.append(tok)
    return out


def _id_shaped(tok: str) -> bool:
    """066 Á03: the single token below the title must be identifier-shaped: it contains a letter or a separator (-, /),
    or at least 5 digits; a year ("2026") or an amount ("45.00") is not."""
    if AMOUNT_TOKEN_RE.fullmatch(tok):
        return False
    return any(ch.isalpha() or ch in "-/" for ch in tok) or sum(ch.isdigit() for ch in tok) >= 5


def _mask_label_everywhere(work: list[str], label: str) -> None:
    """Masks the invoice-number candidate in every line so the money finder does not see its digits; 066 Á03: only as a
    standalone occurrence, not inside a larger number ("15" in "1 150,00" or in "15 000")."""
    rx = re.compile(rf"(?<![\w.,/\-])(?<!\d[  ]){re.escape(label)}(?![\w/\-])(?![.,]\d)(?![  ]\d{{3}}(?!\d))")
    for j, text in enumerate(work):
        for m in list(rx.finditer(text)):
            work[j] = _mask(work[j], m.start(), m.end())


def find_invoice_numbers(lines: list[LineLayout], work: list[str], profile: Profile = HU) -> list[Candidate]:
    bucket = _Bucket("invoice_number")
    label_idx = [i for i, ln in enumerate(lines) if profile.invoice_label_re.search(ln.text)]
    for i in label_idx:
        # label line + neighbours (on the NAV template the "Sorszám:" label is BELOW the value); with OCR an
        # intermediate line may fall between label and value (Díjbeszedő: "Terhelési összesítő száma" / info line /
        # the number) -> `invoice_lookahead`
        for j in (i, i - 1, *range(i + 1, i + 1 + profile.invoice_lookahead)):
            if 0 <= j < len(lines):
                for tok in _invoice_tokens(work[j]):
                    if j > i + 1 and len(tok) < 5:
                        continue  # from a more distant line only identifier-length tokens (short numbers are money / quantity candidates, do not mask them)
                    if AMOUNT_TOKEN_RE.fullmatch(tok):
                        continue  # 066 Á03: an amount-shaped token is not an invoice number (the total stays a money-finder candidate)
                    bucket.add(tok, tok, lines, j)
    for i, ln in enumerate(lines[:-1]):
        # 065: the line below the title, if the whole line is a single identifier (a multi-word line is a name or an
        # address, not an invoice number)
        if INVOICE_TITLE_RE.match(ln.text):
            below = work[i + 1].strip()
            toks = _invoice_tokens(below)
            if len(toks) == 1 and toks[0] == below.strip(":;,.") and _id_shaped(toks[0]):
                bucket.add(toks[0], toks[0], lines, i + 1)
    for c in bucket.items():
        _mask_label_everywhere(work, c.label)
    return bucket.items()


def find_money(lines: list[LineLayout], work: list[str], profile: Profile = HU, convention: Convention | None = None) -> list[Candidate]:
    items = _money_items(lines, work, profile, convention)
    if len(items) > profile.max_money_options:
        # candidates of the summary lines (összesen / fizetendő / nettó / áfa / bruttó) come first, then document order
        priority = [c for c in items if TOTAL_LINE_RE.search(lines[c.line_no - 1].text)]
        rest = [c for c in items if c not in priority]
        items = (priority + rest)[: profile.max_money_options]
    return items


def _money_items(lines: list[LineLayout], work: list[str], profile: Profile, convention: Convention | None) -> list[Candidate]:
    """Every money candidate of the document, before `find_money` cuts the list to the profile's cap."""
    bucket = _Bucket("money")
    for i, ln in enumerate(lines):
        for m in profile.money_re.finditer(work[i]):
            if PERCENT_AFTER_RE.match(work[i][m.end() :]):
                continue
            raw = m.group(1)
            if profile.intl:
                # the currency sign / code around the number decides whether the dot is decimal ("$42.50", "42.50 USD");
                # 081: only the number itself is read (before, the surrounding text was parsed, and "€11.99 1 db" gave
                # 11.991 from the neighbouring quantity)
                around = work[i][max(0, m.start() - 3) : m.start()] + raw + work[i][m.end() : m.end() + 5]
                hint = bool(CURRENCY_HINT_RE.search(around)) and has_decimal_dot_hint(around)
                parsed = parse_money(raw, intl=True, convention=convention, dot_hint=hint)
            else:
                parsed = parse_money(raw, convention=convention)
            if parsed.value is None:
                continue
            bucket.add(money_label(parsed.value), raw, lines, i, ambiguous=parsed.ambiguous)
    if profile.reverse_charge_zero and not bucket.has("0"):
        # code rule: reverse charge printed but no 0 amount -> VAT is 0 (JEV can only choose an offered value)
        for i, ln in enumerate(lines):
            if REVERSE_CHARGE_RE.search(ln.text):
                bucket.add("0", "reverse charge", lines, i)
                break
    return bucket.items()


def find_quantities(lines: list[LineLayout], profile: Profile = HU, convention: Convention | None = None) -> list[Candidate]:
    """Quantity candidates (`number` kind: consumption in kWh / m3 / MJ, meter readings, calorific value, correction
    factor): the numbers of the quantity lines, normalised like the money candidates (`money_label`), but only from
    lines with a unit / meter label - so the request stays small and JEV chooses with the unit as context. 081: read
    whole by the shared number reader, with the document's notation (`convention`)."""
    return _quantity_items(lines, convention)[:MAX_QUANTITY_OPTIONS]


def _quantity_items(lines: list[LineLayout], convention: Convention | None) -> list[Candidate]:
    """Every quantity candidate of the document, before `find_quantities` cuts the list."""
    bucket = _Bucket("money")
    hit = [bool(QUANTITY_LINE_RE.search(ln.text)) for ln in lines]
    for i, ln in enumerate(lines):
        # the meter table header (Induló / Záró mérőállás, Fogyasztás) is ABOVE the value line: a neighbouring line's
        # label counts too
        if not (hit[i] or (i > 0 and hit[i - 1]) or (i + 1 < len(lines) and hit[i + 1])):
            continue
        for m in QUANTITY_RE.finditer(ln.text):
            if PERCENT_AFTER_RE.match(ln.text[m.end() :]):
                continue
            parsed = parse_money(m.group(1), kind="number", convention=convention)
            if parsed.value is None:
                continue
            bucket.add(money_label(parsed.value), m.group(1), lines, i, ambiguous=parsed.ambiguous)
    return bucket.items()


def found_before_cut(kind: str, lines: list[LineLayout], profile: str | Profile | None = None) -> int | None:
    """160 (review AI-2): how many distinct candidates a finder with its own cap found before it cut the list (money:
    the profile's `max_money_options`; quantity: `MAX_QUANTITY_OPTIONS`); None for a kind without such a cap. The cut
    list itself, and so what JEV is asked, does not change."""
    prof = profile_of(profile)
    work = [ln.text for ln in lines]
    if kind == "money":
        return len(_money_items(lines, work, prof, document_convention(work)))
    if kind == "quantity":
        return len(_quantity_items(lines, document_convention(work)))
    return None


def finder_cap(kind: str, profile: str | Profile | None = None) -> int | None:
    """The cap a finder cuts its own list at (see `found_before_cut`); None for a kind without one."""
    return {"money": profile_of(profile).max_money_options, "quantity": MAX_QUANTITY_OPTIONS}.get(kind)


def find_currencies(lines: list[LineLayout], profile: str | Profile | None = None) -> list[str]:
    text = "\n".join(ln.text for ln in lines)
    return [code for code, rx in profile_of(profile).currency_tokens.items() if rx.search(text)]


def _clean_name(text: str, profile: Profile = HU) -> str:
    s = profile.party_label_re.sub("", text.strip())
    greeted = _GREETING_RE.match(s)
    if greeted:
        s = s[greeted.end():].rstrip(" ,!")
    s = NAME_TRAILING_ID_RE.sub("", s)
    s = s.strip(" ,;:")
    if profile.name_cut_after_legal_form:
        # company name embedded in a sentence / in parentheses ("az MVM Next ... Zrt.", "(MVM Next ... Zrt.)"): the
        # article and the parentheses are not part of the name
        s = _LEADING_ARTICLE_RE.sub("", s)
        s = _PAREN_WRAP_RE.sub(r"\1", s)
    return " ".join(s.split())


def _cut_after_legal_form(text: str, profile: Profile) -> str:
    """"Microsoft Ireland Operations Ltd, One Microsoft Place, ..." -> "Microsoft Ireland Operations Ltd" (a
    continuation after the legal form introduced by a comma / hyphen / parenthesis is an address or a remark, not the
    name)."""
    matches = list(profile.legal_form_re.finditer(text))
    if not matches:
        return text
    for m in matches:  # "Díjbeszedő Holding Zrt. honlapján": after Holding comes Zrt., after Zrt. the sentence continues
        end = m.end() + (1 if text[m.end() : m.end() + 1] == "." else 0)  # the dot of the legal form belongs to the name ("Zrt.")
        rest = text[end:].lstrip(". ")
        # comma / hyphen / parenthesis / lower-case continuation (company name inside a sentence: "Zrt. honlapján
        # bankkártyával") = not part of the name
        if rest.startswith((",", "-", "–", "—", "(")) or (rest[:1].isalpha() and rest[:1].islower()):
            return text[:end]
    if len(text) > 120:
        m = matches[0]
        return text[: m.end() + (1 if text[m.end() : m.end() + 1] == "." else 0)]
    return text


def _column_cells_below(lines: list[LineLayout], i: int, x0: float, depth: int, max_skip: int = 2) -> list[tuple[int, str]]:
    """The same-column cells of the lines below line i (at most `depth`), skipping interposed lines of the other
    column."""
    found: list[tuple[int, str]] = []
    skipped = 0
    j = i
    while len(found) < depth and j + 1 < len(lines):
        j += 1
        cell = next((c for c in lines[j].cells if abs(c.x0 - x0) <= COLUMN_X_TOLERANCE), None)
        if cell is None:
            skipped += 1
            if skipped > max_skip:
                break
            continue
        skipped = 0
        found.append((j, cell.text))
    return found


def _column_join(lines: list[LineLayout], i: int, cell_idx: int, depth: int) -> list[tuple[str, int]]:
    """The cell text + variants joined step by step with the (same-column) cells below it."""
    base = lines[i].cells[cell_idx]
    texts = [base.text]
    out: list[tuple[str, int]] = [(base.text, i)]
    for _, text in _column_cells_below(lines, i, base.x0, depth):
        texts.append(text)
        out.append((" ".join(texts), i))
    return out


def _ends_with_legal_form(text: str, legal_form_re: re.Pattern[str]) -> bool:
    """127: the name is complete when its last word is a legal form ("Minta Kft.", "... Ltd"); a legal-form adjective
    at the end is not complete."""
    last = None
    for last in legal_form_re.finditer(text):
        pass
    if last is None or text[last.end():].strip(" .,;"):
        return False
    return not _INCOMPLETE_LEGAL_FORM_RE.match(" ".join(last.group(0).split()))


# 129: the legal forms of every profile, for the name-tail rule that runs after the choice on both paths (231, F2: of
# every profile the rule file describes, each once, in its order)
_ANY_LEGAL_FORM_RE = re.compile("|".join(f"(?:{rx.pattern.removeprefix('(?i)')})"
                                         for rx in dict.fromkeys(p.legal_form_re for p in PROFILES.values())), re.IGNORECASE)


def trim_after_legal_form(name: str) -> str:
    """129: "Minta Kft. <a shop's tagline>" -> "Minta Kft.": the text after a party name's last legal
    form is cut when it is clearly not part of a registered name - it has a digit (an address, a tax or registration
    number), it starts after a separator (a remark), or it is a phrase of two or more words with a lower-case word (a
    tagline). Kept: another legal form, a partner ("& Co."), a branch, a winding-up state ("f.a."), a trading name
    ("dba"), and a single capitalised word, which may be part of the name. Runs after the choice (the candidates sent
    to JEV are unchanged)."""
    last = None
    for last in _ANY_LEGAL_FORM_RE.finditer(name):
        pass
    if last is None or not name[: last.start()].strip():
        return name
    end = last.end() + (1 if name[last.end() : last.end() + 1] == "." else 0)  # the dot of the legal form belongs to the name
    rest = name[end:]
    tail = rest.strip(" .,;")
    if not tail or _NAME_GOES_ON_RE.match(rest.lstrip(" ,;")):
        return name
    words = tail.split()
    if (re.search(r"\d", tail) or _NAME_TAIL_SEPARATOR_RE.match(rest)
            or (len(words) >= 2 and any(w[:1].islower() for w in words))):
        return name[:end].rstrip(" ,;-–—")
    return name


def _cut_address_tail(text: str, legal_form_re: re.Pattern[str]) -> str:
    """127: "Minta Kft. Fo utca 82. 1141" -> "Minta Kft.": an address-shaped continuation right after a legal form is
    not part of the name (any other continuation stays, e.g. a branch name)."""
    for m in legal_form_re.finditer(text):
        end = m.end() + (1 if text[m.end() : m.end() + 1] == "." else 0)  # the dot of the legal form belongs to the name
        if end < len(text) and _ADDRESS_TAIL_RE.match(text[end:]):
            return text[:end]
    return text


def _name_join(lines: list[LineLayout], i: int, cell_idx: int, depth: int,
               legal_form_re: re.Pattern[str] | None = None) -> list[tuple[str, int]]:
    """Like `_column_join`, but stops when the next cell is already an address / label / identifier (not a name
    continuation), or (127) when the name so far already ends in its legal form."""
    base = lines[i].cells[cell_idx]
    texts = [base.text]
    out: list[tuple[str, int]] = [(base.text, i)]
    for _, text in _column_cells_below(lines, i, base.x0, depth):
        if NAME_STOP_RE.search(text.casefold()):
            break
        if legal_form_re is not None and _ends_with_legal_form(" ".join(texts), legal_form_re):
            break
        texts.append(text)
        out.append((" ".join(texts), i))
    return out


def find_names(lines: list[LineLayout], profile: Profile = HU) -> list[Candidate]:
    bucket = _Bucket("name")
    for i, ln in enumerate(lines):
        for ci, cell in enumerate(ln.cells):
            for text, at in _name_join(lines, i, ci, depth=2, legal_form_re=profile.legal_form_re):
                if profile.legal_form_re.search(text):
                    text = _cut_address_tail(text, profile.legal_form_re)
                    if profile.name_cut_after_legal_form:
                        text = _cut_after_legal_form(text, profile)
                    name = _clean_name(text, profile)
                    if 2 <= len(name) <= 120 and not profile.label_only_re.match(name):
                        bucket.add(name, text, lines, at)
    # Private individual (no legal form): the short, letter-dominated cells of the top block (at most
    # MAX_NAME_FALLBACK - the limit applies to the fallback names, not together with the names with a legal form: the
    # company names of a long informational text must not crowd out the private individual's name)
    fallback = 0
    for i, ln in enumerate(lines[: max(12, len(lines) // 2)]):
        for cell in ln.cells:
            if cell.text.rstrip().endswith(":"):
                continue
            name = _clean_name(cell.text, profile)
            if not (3 <= len(name) <= 80) or profile.label_only_re.match(name):
                continue
            alpha = sum(ch.isalpha() or ch.isspace() for ch in name)
            if alpha / len(name) < 0.85 or ":" in name:
                continue
            if profile.intl and (len(name.split()) > 6 or "!" in name):
                continue  # a sentence, not a name
            if DATE_NUMERIC_RE.search(name) or MONEY_RE.fullmatch(name):
                continue
            if fallback >= MAX_NAME_FALLBACK or (profile.name_fallback_combined and len(bucket.items()) >= MAX_NAME_FALLBACK):
                break  # the `hu` profile's behaviour is unchanged (the earlier, combined limit)
            if not bucket.has(name):
                fallback += 1
            bucket.add(name, cell.text, lines, i)
    return bucket.items()


def find_addresses(lines: list[LineLayout], profile: Profile = HU) -> list[Candidate]:
    bucket = _Bucket("address")
    label_re = profile.address_label_re or profile.party_label_re
    for i, ln in enumerate(lines):
        for ci, cell in enumerate(ln.cells):
            if not ADDRESS_RE.search(cell.text):
                continue
            for text, at in _column_join(lines, i, ci, depth=1):
                addr = label_re.sub("", profile.party_label_re.sub("", text)).strip(" ,;")
                if 5 <= len(addr) <= 160:
                    bucket.add(" ".join(addr.split()), text, lines, at)
    if not profile.intl_addresses:
        return bucket.items()
    # intl: (1) the comma continuation after the legal form within one line ("..., Ltd, One Microsoft Place, ...,
    # Dublin 18, D18 P521, Írország"); (2) postcode-shaped cells + the 1-2 same-column cells below them, stopping at
    # label-like cells
    for i, ln in enumerate(lines):
        for ci, cell in enumerate(ln.cells):
            m = profile.legal_form_re.search(cell.text)
            if m and cell.text[m.end() :].lstrip().startswith(","):
                addr = cell.text[m.end() :].strip(" ,;")
                if 5 <= len(addr) <= 200:
                    bucket.add(" ".join(addr.split()), cell.text, lines, i)
            if ADDRESS_INTL_RE.search(cell.text) and not ADDRESS_STOP_INTL_RE.search(cell.text) and not profile.legal_form_re.search(cell.text):
                texts = [cell.text]
                for _, below in _column_cells_below(lines, i, cell.x0, depth=2):
                    if ADDRESS_STOP_INTL_RE.search(below) or profile.legal_form_re.search(below):
                        break
                    texts.append(below)
                for k in range(len(texts)):
                    addr = profile.party_label_re.sub("", ", ".join(texts[: k + 1])).strip(" ,;")
                    if 5 <= len(addr) <= 200 and any(ch.isdigit() for ch in addr):
                        bucket.add(" ".join(addr.split()), " ".join(texts[: k + 1]), lines, i)
    return bucket.items()


def payment_method_lines(lines: list[LineLayout]) -> list[int]:
    return [i for i, ln in enumerate(lines) if PAYMENT_METHOD_LINE_RE.search(ln.text)]


def find_labelled_text(lines: list[LineLayout], field: str, labels: tuple[str, ...] | list[str]) -> list[Candidate]:
    """Candidates of a labelled text field (type pack `text_labels`): the text after the label in the same cell,
    otherwise the next cell of the line, otherwise the same-column cell below the line. A general mechanism (tariff,
    payment method, service name, reading method...); JEV chooses among the candidates, `none` is always an option."""
    bucket = _Bucket("text")
    regexes = [re.compile(p, re.IGNORECASE) for p in labels]
    for i, ln in enumerate(lines):
        for ci, cell in enumerate(ln.cells):
            for rx in regexes:
                m = rx.search(cell.text)
                if not m:
                    continue
                candidates: list[tuple[str, int]] = []
                rest = cell.text[m.end():].strip(_TEXT_STRIP)
                if len(rest) >= 2:
                    candidates.append((rest, i))
                elif ci + 1 < len(ln.cells):
                    candidates.append((ln.cells[ci + 1].text.strip(_TEXT_STRIP), i))
                if not candidates or len(candidates[0][0]) < 2:
                    for j, below in _column_cells_below(lines, i, cell.x0, depth=1):
                        candidates.append((below.strip(_TEXT_STRIP), j))
                for text, at in candidates:
                    text = " ".join(text.split())[:TEXT_VALUE_MAX].strip(_TEXT_STRIP)
                    if len(text) >= 2 and not any(r.match(text) for r in regexes):  # the value must not start with the label (it may occur inside it: "közszolgáltatás")
                        bucket.add(text, text, lines, at)
                break
    return bucket.items()


def find_line_text(lines: list[LineLayout], patterns: tuple[str, ...] | list[str]) -> list[Candidate]:
    """231 (F2c): candidates of a text field whose value is a whole printed cell (type pack `text_lines`), such as a
    document's title: every cell one of the patterns finds, as printed (spaces closed up, at most `TEXT_VALUE_MAX`)."""
    bucket = _Bucket("text")
    regexes = [re.compile(p, re.IGNORECASE) for p in patterns]
    for i, ln in enumerate(lines):
        for cell in ln.cells:
            if any(rx.search(cell.text) for rx in regexes):
                text = " ".join(cell.text.split())[:TEXT_VALUE_MAX].strip(_TEXT_STRIP)
                if len(text) >= 2:
                    bucket.add(text, cell.text, lines, i)
    return bucket.items()


# --- entry point -----------------------------------------------------------------------


def find_all(
    lines: list[LineLayout], profile: str | Profile | None = None, text_labels: dict[str, tuple[str, ...]] | None = None,
    text_lines: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, list[Candidate]]:
    """Every candidate kind according to the given profile (`hu` by default = the original Hungarian-invoice behaviour).
    `text_labels` (type pack): labelled text candidates per field under the key `text:<field>`; 231 (F2c) `text_lines`:
    whole cells as candidates of a field, after its labelled ones under the same key."""
    prof = profile_of(profile)
    work = [ln.text for ln in lines]
    convention = document_convention(work)  # 081: the document's own number notation
    out: dict[str, list[Candidate]] = {}
    out["iban"] = find_ibans(lines, work, prof)
    out["tax_id"] = find_tax_ids(lines, work, prof)
    out["date"] = find_dates(lines, work, prof)
    out["invoice_number"] = find_invoice_numbers(lines, work, prof)
    out["money"] = find_money(lines, work, prof, convention)
    out["name"] = find_names(lines, prof)
    out["address"] = find_addresses(lines, prof)
    out["quantity"] = find_quantities(lines, prof, convention)
    for key, labels in (text_labels or {}).items():
        out[f"text:{key}"] = find_labelled_text(lines, key, labels)
    for key, patterns in (text_lines or {}).items():
        found = out.get(f"text:{key}", [])
        seen = {c.label for c in found}
        out[f"text:{key}"] = found + [c for c in find_line_text(lines, patterns) if c.label not in seen]
    return out


def candidate_lines(lines: list[LineLayout], cands: dict[str, list[Candidate]], kinds: list[str], margin: int = 1) -> set[int]:
    """0-based indices of the lines holding candidates of the given kinds (± margin)."""
    idx: set[int] = set()
    by_no = {ln.no: i for i, ln in enumerate(lines)}
    for kind in kinds:
        for c in cands.get(kind, []):
            base = by_no.get(c.line_no)
            if base is None:
                continue
            for j in range(base - margin, base + margin + 1):
                if 0 <= j < len(lines):
                    idx.add(j)
            # also from the deduplicated contexts: "L12:" references
            for m in re.finditer(r"L(\d+):", c.context):
                base2 = by_no.get(int(m.group(1)))
                if base2 is not None:
                    for j in range(base2 - margin, base2 + margin + 1):
                        if 0 <= j < len(lines):
                            idx.add(j)
    return idx
