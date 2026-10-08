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
The profile is data (`PROFILES`), the finders are the mechanism. When introduced, the `hu` profile was bit-identical to
the previous behaviour; since then the invoice number below the title (065) and the masking of invoice-number
candidates (066: standalone occurrences only) are shared by both profiles.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field

from jav.dates import document_date_order, find_dates_in
from jav.models import (
    DATE_NUMERIC_RE,
    Candidate,
    CandidateKind,
    LineLayout,
    money_label,
    normalize_tax_id,
    parse_money,
)
from jav.numbers import Convention, document_convention, has_decimal_dot_hint
from jav.taxid import recognize as recognize_tax_id
from jav.validators import hu_tax_id

MAX_OPTIONS = 250  # the 255-option Choice limit, minus "none" and a margin
MAX_NAME_FALLBACK = 60
CONTEXT_MAX_CHARS = 140

# --- regular expressions ----------------------------------------------------------------

IBAN_RES = (
    re.compile(r"\bHU\d{2}(?:[  ]?\d{4}){6}\b"),
    re.compile(r"(?<!\d)\d{8}[- ]\d{8}[- ]\d{8}(?!\d)"),
    re.compile(r"(?<!\d)\d{8}[- ]\d{8}(?!\d)"),
    # 065: the unseparated form must be a standalone token (part of a hyphenated identifier is not a bank account
    # number: "6300001234567890-4" is an invoice number)
    re.compile(r"(?<![\w-])\d{24}(?![\w-])"),
    re.compile(r"(?<![\w-])\d{16}(?![\w-])"),
)
# Foreign IBAN (not HU): country code + 2 check digits + 11-30 alphanumerics, also in space-separated groups
IBAN_INTL_RE = re.compile(r"\b(?!HU)[A-Z]{2}\d{2}(?:[  ]?[A-Z0-9]{4}){2,7}(?:[  ]?[A-Z0-9]{1,4})?\b")
TAXID_FORMATTED_RE = re.compile(r"(?<!\d)\d{8}-\d-\d{2}(?!\d)")
TAXID_CONTIGUOUS_RE = re.compile(r"(?<![\d-])\d{11}(?![\d-])")
TAXID_EU_RE = re.compile(r"\bHU\d{8}\b")
# EU / UK / Swiss tax number (not HU): country code + 8-12 alphanumerics; also the Irish form (IE + 7 digits +
# 1-2 letters)
# 065: also the EU OSS registration number (EU + 9 digits, e.g. the EU VAT of US providers) and the Dutch "…B01" suffix
_EU_CC = "AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|GB|XI|NO|CH|TR|UA|RS|EU"  # real country-code prefixes ("ID 512345678" is not a tax number)
# 069 (066 Á27): the spaced Norwegian form with the MVA suffix; the separate trailing letter of the Irish form
# ("IE 8256796 U") is part of the candidate. A match is a candidate only as a recognised form (jav/taxid.py), in its
# canonical spelling; the spaced "NO …" without MVA is not ("INVOICE NO 123456789" is a serial number, not a Norwegian
# tax number).
TAXID_EU_INTL_RE = re.compile(
    rf"\b(?:NO[ ]?\d{{3}}[ ]?\d{{3}}[ ]?\d{{3}}[ ]?MVA"
    rf"|(?:{_EU_CC})[- ]?\d{{7,12}}(?:[A-Z]{{1,2}}\d{{0,2}})?(?: [A-Z]{{1,2}}(?!\w))?"
    rf"|IE\d[A-Z0-9+*]\d{{5}}[A-Z]{{1,2}}|CHE[- ]?\d{{3}}\.?\d{{3}}\.?\d{{3}})\b")
# 069 (066 Á27): EIN is a label only in capitals (the German article "ein" is not)
TAXID_LABEL_INTL_RE = re.compile(r"(?i)\b(?:vat\s*(?:id|no|number|reg)|tax\s*(?:id|number|no)|(?-i:EIN)|vkn|tckn|nip|ust[-.]?\s?idnr|steuernummer|abn|gstin|vergi\s*no|áfaazonosító|adószám)\b")
TAXID_LABEL_TOKEN_RE = re.compile(r"(?<![\w-])(?:\d{2}-\d{7}|\d{9,11}|\d{3}[- ]\d{3}[- ]\d{3}[- ]\d{2,3})(?![\w-])")  # EIN 12-3456789, VKN 10 digits, ABN 11 digits

# 127: the own number of a credit note or corrective invoice is labelled by the document's own name; the referenced
# original stays a candidate too, the Choice text tells them apart
CREDIT_NOTE_LABEL_HU = (r"|jóváír\w*\s*(?:számla\s*)?(?:száma|sorszáma|dokumentum)|helyesbítő\s*számla|sztornó\s*számla"
                        r"|érvénytelenítő\s*számla")
INVOICE_LABEL_RE = re.compile(
    r"(?i)számla\s*sorszám|sorszám|számlaszám|számla\s*száma|bizonylatszám|invoice\s*(?:no|number|#)|számla\s*azonosító"
    + CREDIT_NOTE_LABEL_HU
)
INVOICE_LABEL_INTL_RE = re.compile(
    r"(?i)számla\s*sorszám|sorszám|számlaszám|számla\s*száma|bizonylatszám|invoice\s*(?:no|number|#|id)|számla\s*azonosító"
    r"|fatura\s*no|belge\s*no|bilet\s*no|rechnungs?-?(?:nr|nummer)|faktura(?:\s*(?:nr|vat|no))?|document\s*(?:no|number)|receipt\s*(?:no|number|#)|invoice\s*$"
    # 065: on a receipt the order / transaction ID is the document number; credit note; Microsoft's billing summary
    # 066 Á03: with word boundaries ("Order now…" advertising line, "recorder Number" are not labels)
    r"|\border\s*(?:no|number|id)\b|\border\s*#|\btransaction\s*id\b|\bcredit\s*note\b|számlázási\s*szám"
    # 127: credit memo, a receipt's payment / receipt id and transaction number (owner's decision of 2026-10-07: on a
    # receipt without an invoice number its own identifier is the invoice number)
    r"|\bcredit\s*memo\b|\bpayment\s*id\b|\breceipt\s*id\b|\btransaction\s*(?:no|number)\b|\btransaction\s*#"
    + CREDIT_NOTE_LABEL_HU
)
# 065: title line ("Elektronikus számla", "Invoice") with a single identifier below it (Billingo: the number stands
# below the title without a label)
INVOICE_TITLE_RE = re.compile(r"(?i)^\s*(?:elektronikus\s+|e-)?(?:számla|invoice|tax\s+invoice|receipt|credit\s+note)\s*[:：]?\s*$")
INVOICE_TOKEN_RE = re.compile(r"(?<![\w/\-])[A-Za-z0-9][A-Za-z0-9\-/._]{1,}(?![\w/\-])")
# 066 Á03: amount-shaped token (1 250,00 / 45.00 / 1,250.00): not an invoice-number candidate, the money finder's job
AMOUNT_TOKEN_RE = re.compile(r"-?\d{1,3}(?:[,.  ]\d{3})*[.,]\d{2}|-?\d+[.,]\d{2}")

# 081 (number reading): a number is matched whole, never a piece of it. The English thousands group ("28,000",
# "28,000.00") is matched as one number in the Hungarian profile too (it was cut to "28,00" = 28), and no match may be
# followed by a further digit of the same number. The reading itself is `jav/numbers.py`.
MONEY_RE = re.compile(
    r"(?<![\d.,])"
    r"(-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"  # 28,000 / 28,000.00 (English notation on a Hungarian document)
    r"|-?\d{1,3}(?:[  .]\d{3})+(?:,\d{1,2})?"  # 1 234 567 / 1.234.567 / 400 000,00
    r"|-?\d+,\d{1,2}"  # 20619,05
    r"|-?\d+\.\d{1,2}"  # 12.34 (ambiguous)
    r"|-?\d+)"  # 1000000 / 0
    r"(?![\d.,]\d)(?!\d)"
)
# intl: also English thousands comma + decimal point ("1,600.00", "12,345", "$42.50") as one match
MONEY_INTL_RE = re.compile(
    r"(?<![\d.,])"
    r"(-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"  # 1,600.00 / 12,345
    r"|-?\d{1,3}(?:[  .]\d{3})+(?:,\d{1,2})?"  # 1 234 567 / 1.234.567 / 400 000,00
    r"|-?\d+,\d{1,2}"  # 20619,05
    r"|-?\d+\.\d{1,2}"  # 12.34
    r"|-?\d+)"  # 1000000 / 0
    r"(?![\d.,]\d)(?!\d)"
)
# 081: quantities also take a fraction of three or more digits ("1.0000" correction factor, "0,9853"), which money never
# has; before 081 "1.0000" was cut to "1.000" and read as a thousand
QUANTITY_RE = re.compile(
    r"(?<![\d.,])"
    r"(-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"
    r"|-?\d{1,3}(?:[  .]\d{3})+(?:,\d{1,2})?"
    r"|-?\d+[.,]\d{3,6}"  # 1.0000 / 0,9853 / 3,3900
    r"|-?\d+,\d{1,2}"
    r"|-?\d+\.\d{1,2}"
    r"|-?\d+)"
    r"(?![\d.,]\d)(?!\d)"
)
PERCENT_AFTER_RE = re.compile(r"^\s*%")
TOTAL_LINE_RE = re.compile(r"(?i)összesen|fizetendő|végösszeg|nettó|áfa|bruttó|total|adóalap|számla érték|ellenérték")
REVERSE_CHARGE_RE = re.compile(r"(?i)reverse\s*charge|fordított\s*áfa|fordított\s*adóz|steuerschuldnerschaft|odwrotne\s*obciążenie|KDV\s*muaf")
CURRENCY_HINT_RE = re.compile(r"(?i)[$€£₺]|\b(?:USD|EUR|GBP|TRY|PLN|CZK|CHF|AUD|CAD|HUF)\b")

CURRENCY_TOKENS = {
    "HUF": re.compile(r"(?i)\bHUF\b|\bFt\b|\bforint\b"),
    "EUR": re.compile(r"(?i)\bEUR\b|€"),
    "USD": re.compile(r"(?i)\bUSD\b|\$"),
}
CURRENCY_TOKENS_INTL = {
    **CURRENCY_TOKENS,
    "GBP": re.compile(r"(?i)\bGBP\b|£"),
    "TRY": re.compile(r"(?i)\bTRY\b|\bTL\b|₺"),
    "PLN": re.compile(r"(?i)\bPLN\b|zł"),
    "CZK": re.compile(r"(?i)\bCZK\b|Kč"),
    "CHF": re.compile(r"(?i)\bCHF\b"),
    "AUD": re.compile(r"(?i)\bAUD\b|A\$"),
    "CAD": re.compile(r"(?i)\bCAD\b|C\$"),
}

LEGAL_FORM_RE = re.compile(
    r"(?i)(?:\bkft\b|\bzrt\b|\bbt\b|\bnyrt\b|\bkkt\b|\brészvénytársaság\b|\be\.\s?v\.?(?=\W|$)|\bev\b|\begyéni vállalkozó\b|\bkisadózó\b"
    r"|\begyesület\b|\balapítvány\b|\bltd\b|\bgmbh\b|\bs\.r\.o\.|\bsrl\b|\bag\b"
    r"|\btársaság\b|\bkorlátolt felelősségű\b|\bbetéti\b|\bközkereseti\b|\bintézmény\b|\bönkormányzat\b)"
)
LEGAL_FORM_INTL_RE = re.compile(
    r"(?i)(?:\bkft\b|\bzrt\b|\bbt\b|\bnyrt\b|\bkkt\b|\brészvénytársaság\b|\be\.\s?v\.?(?=\W|$)|\begyesület\b|\balapítvány\b"
    r"|\bltd\.?(?=\W|$)|\blimited\b|\binc\.?(?=\W|$)|\bincorporated\b|\bllc\b|\bl\.l\.c\.|\bcorp\.?(?=\W|$)|\bcorporation\b|\bplc\b|\bpty\b"
    r"|\bgmbh\b|\bag\b|\bs\.r\.o\.|\bsrl\b|\bs\.r\.l\.|\bs\.p\.a\.|\bs\.a\.s\.|\bsarl\b|\bs\.à\s?r\.l\.|\bsp\.\s?z\s?o\.?\s?o\.?|\ba\.s\.|\ba\.ş\.|\bşti\.?(?=\W|$)"
    r"|\bb\.v\.|\bbv\b|\bn\.v\.|\boy\b|\bab\b|\bapS\b|\ba/s\b|\bd\.o\.o\.|\bpte\.?\s+ltd|\boü\b|\bsia\b|\buab\b"
    r"|\btársaság\b|\bkorlátolt felelősségű\b|\bbetéti\b|\bközkereseti\b|\bintézmény\b|\bönkormányzat\b)"
)
# 127: a label is a whole word (a customer-code label is not the buyer label followed by "code"); two more buyer labels
PARTY_LABEL_RE = re.compile(
    r"(?i)^(?:szállító|eladó|kibocsátó|kiállító|vevő|vásárló|ügyfél|megrendelő|szolgáltató|supplier|seller|buyer|customer|vendor)"
    r"(?!\w)\s*(?:neve|name)?\s*[:：]?\s*"
)
PARTY_LABEL_INTL_RE = re.compile(
    r"(?i)^(?:szállító|eladó|kibocsátó|kiállító|vevő|vásárló|ügyfél|megrendelő|szolgáltató|számlafizető|supplier|seller|buyer|customer|vendor|client"
    r"|from|bill(?:ed)?\s+to|sold\s+to|ship\s+to|invoice\s+to|remit\s+to|issued\s+by|sayın)"
    r"(?!\w)\s*(?:neve|name)?\s*[:：]?\s*"
)
LABEL_ONLY_RE = re.compile(r"(?i)^(?:számla|e-számla|szamla|sorszám|kiállító|vevő|eladó|szállító|megrendelő)\s*[:：]?$")
LABEL_ONLY_INTL_RE = re.compile(
    r"(?i)^(?:számla|e-számla|szamla|sorszám|kiállító|vevő|eladó|szállító|megrendelő|számlafizető|invoice|i\s*n\s*v\s*o\s*i\s*c\s*e|r\s*e\s*m\s*i\s*t\s*t\s*o"
    r"|date|due\s+date|total(?:\s+(?:amount|due))?|amount|bill\s+to|from|remit\s+to|description(?:\s*/\s*memo)?|subtotal|vat|tax|invoice\s*#|page\s*\d+.*|támogatás|rendelés\s+részletei)\s*[:：]?$"
)
NAME_TRAILING_ID_RE = re.compile(r"\s*,\s*\d{6,}\s*$")  # "Rádóczi Lajos István, 51455257"
ADDRESS_RE = re.compile(r"(?<!\d)\d{4}(?!\d)\s*,?\s*[A-ZÁÉÍÓÖŐÚÜŰ][a-záéíóöőúüűA-ZÁÉÍÓÖŐÚÜŰ]+")
ADDRESS_INTL_RE = re.compile(r"(?<!\d)\d{4,6}(?!\d)|\b[A-Z]{2}\s\d{5}\b|\b[A-Z]\d{1,2}\s?[A-Z0-9]{3,4}\b|\d+\s+[A-Z][a-z]+\s+(?:St|Str|Street|Ave|Avenue|Rd|Road|Blvd|Place|Park|Suite)\b")
ADDRESS_STOP_INTL_RE = re.compile(
    r"(?i)vat|tax|invoice|date|total|amount|bill\s+to|from|@|www\.|http|description|áfaazonosító|adószám|számla|határidő|időszak|rendelés"
    r"|^\d{4}\.\s|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}|\d{4}/\d{2}/\d{2}|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|[$€£]"
)  # date-, period-, identifier- and amount-like cells are not addresses
PAYMENT_METHOD_LINE_RE = re.compile(r"(?i)fizetési\s*mód|fizetés\s*módja|átutalás|utalás|készpénz|bankkártya|kártya")
COLUMN_X_TOLERANCE = 15.0  # pt - x0 difference of cells in the same column

# --- utility profile (OCR-text Hungarian utility bills: MVM electricity / gas, Díjbeszedő batch water / sewage / waste)
LEGAL_FORM_UTILITY_RE = re.compile(
    r"(?i)(?:\bkft\b|\bzrt\b|\bbt\b|\bnyrt\b|\bkkt\b|\brészvénytársaság\b|\bkorlátolt felelősségű\b|\btársaság\b|\bművek\b|\bholding\b"
    r"|\begyesület\b|\balapítvány\b|\bintézmény\b|\bönkormányzat\b|\bltd\b|\bgmbh\b)"
)
# OCR-tolerant labels: a character class in place of accented letters (OCR may also read "Elosztéi engedélyes",
# "Felhasznalo")
PARTY_LABEL_UTILITY_RE = re.compile(
    r"(?i)^(?:szolg[áa]ltat[óo] neve|szolg[áa]ltat[óo]|felhaszn[áa]l[óo] neve|felhaszn[áa]l[óo]|vev[őo]\s*\(fizet[őo]\)\s*neve|vev[őo]\s*\(fizet[őo]\)|vev[őo] neve|vev[őo]"
    r"|sz[áa]mlatulajdonos neve|sz[áa]mlatulajdonos|eloszt[óoóée]i enged[ée]lyes|f[öoóé]ldg[áa]zeloszt[óoé]|fizet[őo] neve|megb[íi]z[óo]\s*\(befizet[őo]\)\s*neve"
    r"|kibocs[áa]t[óo]|sz[áa]ll[íi]t[óo]|elad[óo]|ki[áa]ll[íi]t[óo]|d[íi]jbeszed[őo] jogosult|fogyaszt[óo] neve)"
    r"\s*[:：]?\s*"
)
ADDRESS_LABEL_UTILITY_RE = re.compile(
    r"(?i)^(?:(?:felhaszn[áa]l[óo]|vev[őo]\s*\(fizet[őo]\)|fogyaszt[óo]|felhaszn[áa]l[áa]si hely|szolg[áa]ltat[óo]|sz[ée]khely)?\s*c[íi]me?\s*[:：]?\s*"
    r"|(?:felhaszn[áa]l[áa]si hely|fogyaszt[áa]si hely)\s*[:：]?\s*)"
)
LABEL_ONLY_UTILITY_RE = re.compile(
    r"(?i)^(?:számla|e-számla|sorszám|kiállító|vevő|eladó|szállító|felhasználó|vevő\s*\(fizető\)|szolgáltató|számlatulajdonos|elosztói engedélyes"
    r"|oldalszám.*|számlarészletező|terhelési összesítő|feladóvevény|postai számlabefizetési megbízás|villamos energia|elszámoló számla|részszámla"
    r"|számla sorszáma|fizetési mód|fizetendő összeg|elszámolási időszak|fizetési határidő|összeg|forint|posta|tájékoztató adatok|áfa összesítő.*)\s*[:：]?$"
)
INVOICE_LABEL_UTILITY_RE = re.compile(
    r"(?i)számla\s*sorszám|sorszám|számlaszám|számla\s*száma|bizonylatszám|számla\s*azonosító|terhelési\s*összesítő\s*(?:száma|sorszáma)|bizonylat\s*sorszáma"
)
# OCR: a space may slip into the 8-digit block of the tax number ("2690357 0-2-44", "26903 570-2-44"); the form with
# the spaces removed becomes a candidate if it passes the check-digit test
TAXID_OCR_RE = re.compile(r"(?<!\d)\d(?:[  ]?\d){7}[- ]\d[- ]\d{2}(?!\d)")
TAXID_LABEL_HU_RE = re.compile(r"(?i)ad[óoóé]sz[áa]m")


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


HU = Profile(
    name="hu", intl=False, legal_form_re=LEGAL_FORM_RE, party_label_re=PARTY_LABEL_RE, label_only_re=LABEL_ONLY_RE,
    invoice_label_re=INVOICE_LABEL_RE, money_re=MONEY_RE, currency_tokens=CURRENCY_TOKENS,
)
INTL = Profile(
    name="intl", intl=True, legal_form_re=LEGAL_FORM_INTL_RE, party_label_re=PARTY_LABEL_INTL_RE, label_only_re=LABEL_ONLY_INTL_RE,
    invoice_label_re=INVOICE_LABEL_INTL_RE, money_re=MONEY_INTL_RE, currency_tokens=CURRENCY_TOKENS_INTL,
    extra_iban_res=(IBAN_INTL_RE,), extra_taxid_res=(TAXID_EU_INTL_RE,), short_dates=True,
    taxid_label_re=TAXID_LABEL_INTL_RE, name_cut_after_legal_form=True, reverse_charge_zero=True, intl_addresses=True,
)
UTILITY = Profile(
    name="utility", intl=False, legal_form_re=LEGAL_FORM_UTILITY_RE, party_label_re=PARTY_LABEL_UTILITY_RE, label_only_re=LABEL_ONLY_UTILITY_RE,
    invoice_label_re=INVOICE_LABEL_UTILITY_RE, money_re=MONEY_RE, currency_tokens=CURRENCY_TOKENS,
    ocr_dates=True, name_cut_after_legal_form=True, address_label_re=ADDRESS_LABEL_UTILITY_RE, invoice_lookahead=2,
    ocr_taxid=True, max_money_options=100,
)
PROFILES: dict[str, Profile] = {"hu": HU, "intl": INTL, "utility": UTILITY}


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


PARTIAL_HU_IBAN_RE = re.compile(r"^HU\d{2}(?:[  ]\d{4}){1,5}$")
IBAN_GROUP_RE = re.compile(r"^\d{4}$")


def find_ibans(lines: list[LineLayout], work: list[str], profile: Profile = HU) -> list[Candidate]:
    bucket = _Bucket("iban")
    seen_digits: dict[str, str] = {}

    def add(label_raw: str, i: int) -> None:
        digits = re.sub(r"\D", "", label_raw)
        label = seen_digits.get(digits[-16:], " ".join(label_raw.split()))
        seen_digits.setdefault(digits[-16:], label)
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
    """084: every date of every line by the shared date reader (`jav/dates.py`), on every profile, with the document's
    own day/month order; a date whose day and month can be read two ways is a flagged candidate (picking it gives a
    to-do). A range like "11/25/2022 - 12/25/2022" stays two dates: the reader never lets one date overlap another."""
    order = document_date_order(ln.text for ln in lines)
    bucket = _Bucket("date")
    for i in range(len(lines)):
        for h in find_dates_in(work[i], order=order, ocr=profile.ocr_dates):
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
    items = bucket.items()
    if len(items) > profile.max_money_options:
        # candidates of the summary lines (összesen / fizetendő / nettó / áfa / bruttó) come first, then document order
        priority = [c for c in items if TOTAL_LINE_RE.search(lines[c.line_no - 1].text)]
        rest = [c for c in items if c not in priority]
        items = (priority + rest)[: profile.max_money_options]
    return items


# Quantity lines (utility bill itemisation / meter table): a unit or a meter label in the line
QUANTITY_LINE_RE = re.compile(
    r"(?i)\bkwh\b|\bm3\b|m³|\bm\?|\bmj\b|mérőállás|mer[őo]all[áa]s|fogyaszt[áa]s|mennyis[ée]g|f[űu]t[őo][ée]rt[ée]k|korrekci|indul[óo]|z[áa]r[óo]|h[őo]mennyis[ée]g|leolvas"
    r"|szorz[óo]|\b(?:Leol|Becs|Dikt|EII|Ell)\b"  # the meter line is also recognised by its reading code (LM column) if OCR garbled the header
)
MAX_QUANTITY_OPTIONS = 80


def find_quantities(lines: list[LineLayout], profile: Profile = HU, convention: Convention | None = None) -> list[Candidate]:
    """Quantity candidates (`number` kind: consumption in kWh / m3 / MJ, meter readings, calorific value, correction
    factor): the numbers of the quantity lines, normalised like the money candidates (`money_label`), but only from
    lines with a unit / meter label - so the request stays small and JEV chooses with the unit as context. 081: read
    whole by the shared number reader, with the document's notation (`convention`)."""
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
    return bucket.items()[:MAX_QUANTITY_OPTIONS]


def find_currencies(lines: list[LineLayout], profile: str | Profile | None = None) -> list[str]:
    text = "\n".join(ln.text for ln in lines)
    return [code for code, rx in profile_of(profile).currency_tokens.items() if rx.search(text)]


_LEADING_ARTICLE_RE = re.compile(r"(?i)^(?:az?|the)\s+")
_PAREN_WRAP_RE = re.compile(r"^\((.+)\)\.?$")
# 127: a greeting before the addressee's name ("Dear <Name>,") is not part of the name
_GREETING_RE = re.compile(r"(?i)^(?:dear|hello|hi|kedves|tisztelt)\s+(?=\S)")
# 127: an address after a complete name in the same cell: a postcode ("1141", "1119 Budapest") or a street with a house
# number, optionally after a comma
_ADDRESS_TAIL_RE = re.compile(
    r"^[\s,;-]*(?:\d{4}(?!\d)|(?:[A-ZÁÉÍÓÖŐÚÜŰ][\w.\-]*\s+){1,4}(?:utca|u\.|út|útja|tér|tere|körút|krt\.|köz|sor|sétány|fasor"
    r"|rakpart|street|st\.|road|rd\.|avenue|ave\.)\s*\d)"
)


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


NAME_STOP_RE = re.compile(r"[:：]|\d{4}[ ,]|\d{8}|adószám|iban|bank|telefon|tel\.|e-mail|@|www\.")


# 127: a legal-form adjective that still wants its noun ("társaság") from the next line
_INCOMPLETE_LEGAL_FORM_RE = re.compile(r"(?i)^(?:korlátolt felelősségű|betéti|közkereseti)$")


def _ends_with_legal_form(text: str, legal_form_re: re.Pattern[str]) -> bool:
    """127: the name is complete when its last word is a legal form ("Minta Kft.", "... Ltd"); a legal-form adjective
    at the end is not complete."""
    last = None
    for last in legal_form_re.finditer(text):
        pass
    if last is None or text[last.end():].strip(" .,;"):
        return False
    return not _INCOMPLETE_LEGAL_FORM_RE.match(" ".join(last.group(0).split()))


# 129: the legal forms of every profile, for the name-tail rule that runs after the choice on both paths
_ANY_LEGAL_FORM_RE = re.compile("|".join(f"(?:{rx.pattern.removeprefix('(?i)')})"
                                         for rx in (LEGAL_FORM_RE, LEGAL_FORM_INTL_RE, LEGAL_FORM_UTILITY_RE)), re.IGNORECASE)
# a continuation that still belongs to a registered name: a partner, a branch, a winding-up state, a trading name
_NAME_GOES_ON_RE = re.compile(r"(?i)^(?:&|and\b|és\s+társa|fióktelep|branch\b|f\.\s?a\.|v\.\s?a\.|cs\.\s?a\.|kv\.\s?a\.|dba\b"
                              r"|d/b/a|t/a\b|trading as\b|spółka\b|co\.|kg\b)")
_NAME_TAIL_SEPARATOR_RE = re.compile(r"^\s*[,\-–—:|/]")


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
            if fallback >= MAX_NAME_FALLBACK or (profile.name == "hu" and len(bucket.items()) >= MAX_NAME_FALLBACK):
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


TEXT_VALUE_MAX = 120
_TEXT_STRIP = " :：;,.-–—|"


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


# --- entry point -----------------------------------------------------------------------


def find_all(
    lines: list[LineLayout], profile: str | Profile | None = None, text_labels: dict[str, tuple[str, ...]] | None = None
) -> dict[str, list[Candidate]]:
    """Every candidate kind according to the given profile (`hu` by default = the original Hungarian-invoice behaviour).
    `text_labels` (type pack): labelled text candidates per field under the key `text:<field>`."""
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
    for field, labels in (text_labels or {}).items():
        out[f"text:{field}"] = find_labelled_text(lines, field, labels)
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
