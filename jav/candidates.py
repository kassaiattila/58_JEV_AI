"""Determinisztikus jelöltkeresők az S-karhoz: kód talál, Jev választ.

Elv: a keresők recall-ra hangoltak (inkább több jelölt), a Jev Choice-szal választ közülük, a kód a
kiválasztott szó szerinti értéket normalizálja. Amit a kereső nem talál meg, azt Jev nem választhatja -
ezért az offline `candidate_recall` (evals) az S-kar felső korlátja.

Sorrend + maszkolás: az érték-jellegű keresők (`iban -> tax_id -> date -> invoice_number -> money`) a talált
span-t `#`-ra cserélik a sor munkamásolatában, hogy a későbbi keresők ne találják meg újra (pl. az adószám
számjegyei ne legyenek pénzösszeg-jelöltek). A név/cím keresők cellákon dolgoznak és nem maszkolnak.

Jelölt-profilok (típus-csomag `candidate_profile`): a `hu` a magyar számla eddigi regex-készlete változatlanul; az
`intl` a nemzetközi bővítés (EU-s / török / lengyel / amerikai adóazonosítók, angol és kontinentális dátumalakok,
`$1,600.00` pénzjelölés, külföldi jogi formák, angol fél-címkék, fordított adózás = 0 áfa szintetikus jelölt).
A profil adat (`PROFILES`), a keresők mechanizmus. A `hu` profil a bevezetésekor bitre azonos volt a korábbival; azóta a
cím alatti számlaszám (065) és a számlaszám-jelölt maszkolása (066: csak önálló előfordulás) mindkét profilban közös.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field

from jav.models import (
    DATE_NUMERIC_RE,
    DATE_TEXT_RE,
    INTL_DATE_RES,
    Candidate,
    CandidateKind,
    LineLayout,
    money_label,
    normalize_date,
    normalize_tax_id,
    parse_money,
)
from jav.taxid import recognize as recognize_tax_id
from jav.validators import hu_tax_id

MAX_OPTIONS = 250  # 255-ös Choice-limit, mínusz a "none" és tartalék
MAX_NAME_FALLBACK = 60
CONTEXT_MAX_CHARS = 140

# --- reguláris kifejezések --------------------------------------------------------------

IBAN_RES = (
    re.compile(r"\bHU\d{2}(?:[  ]?\d{4}){6}\b"),
    re.compile(r"(?<!\d)\d{8}[- ]\d{8}[- ]\d{8}(?!\d)"),
    re.compile(r"(?<!\d)\d{8}[- ]\d{8}(?!\d)"),
    # 065: a tapadó alak önálló token (a kötőjeles azonosító része nem számlaszám: „6300001234567890-4” számlaszám)
    re.compile(r"(?<![\w-])\d{24}(?![\w-])"),
    re.compile(r"(?<![\w-])\d{16}(?![\w-])"),
)
# Külföldi IBAN (nem HU): országkód + 2 ellenőrző jegy + 11-30 alfanumerikus, szóközös csoportokkal is
IBAN_INTL_RE = re.compile(r"\b(?!HU)[A-Z]{2}\d{2}(?:[  ]?[A-Z0-9]{4}){2,7}(?:[  ]?[A-Z0-9]{1,4})?\b")
TAXID_FORMATTED_RE = re.compile(r"(?<!\d)\d{8}-\d-\d{2}(?!\d)")
TAXID_CONTIGUOUS_RE = re.compile(r"(?<![\d-])\d{11}(?![\d-])")
TAXID_EU_RE = re.compile(r"\bHU\d{8}\b")
# EU-s / brit / svájci adószám (nem HU): országkód + 8-12 alfanumerikus; az ír alak (IE + 7 jegy + 1-2 betű) is
# 065: az uniós OSS-nyilvántartási szám (EU + 9 jegy, pl. amerikai szolgáltatók uniós áfája) és a holland „…B01” végződés is
_EU_CC = "AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|GB|XI|NO|CH|TR|UA|RS|EU"  # valódi országkód-előtagok (az "ID 512345678" nem adószám)
# 069 (066 Á27): a norvég szóközös alak az MVA utótaggal; az ír alak különálló záró betűje („IE 8256796 U”) a jelölt része.
# A találat csak felismert alakként (jav/taxid.py) jelölt, kanonikus írásmóddal; a szóközös „NO …” MVA nélkül nem
# (az „INVOICE NO 123456789” sorszám, nem norvég adószám).
TAXID_EU_INTL_RE = re.compile(
    rf"\b(?:NO[ ]?\d{{3}}[ ]?\d{{3}}[ ]?\d{{3}}[ ]?MVA"
    rf"|(?:{_EU_CC})[- ]?\d{{7,12}}(?:[A-Z]{{1,2}}\d{{0,2}})?(?: [A-Z]{{1,2}}(?!\w))?"
    rf"|IE\d[A-Z0-9+*]\d{{5}}[A-Z]{{1,2}}|CHE[- ]?\d{{3}}\.?\d{{3}}\.?\d{{3}})\b")
# 069 (066 Á27): az EIN csak nagybetűvel címke (a német „ein” névelő nem)
TAXID_LABEL_INTL_RE = re.compile(r"(?i)\b(?:vat\s*(?:id|no|number|reg)|tax\s*(?:id|number|no)|(?-i:EIN)|vkn|tckn|nip|ust[-.]?\s?idnr|steuernummer|abn|gstin|vergi\s*no|áfaazonosító|adószám)\b")
TAXID_LABEL_TOKEN_RE = re.compile(r"(?<![\w-])(?:\d{2}-\d{7}|\d{9,11}|\d{3}[- ]\d{3}[- ]\d{3}[- ]\d{2,3})(?![\w-])")  # EIN 12-3456789, VKN 10 jegy, ABN 11 jegy

INVOICE_LABEL_RE = re.compile(
    r"(?i)számla\s*sorszám|sorszám|számlaszám|számla\s*száma|bizonylatszám|invoice\s*(?:no|number|#)|számla\s*azonosító"
)
INVOICE_LABEL_INTL_RE = re.compile(
    r"(?i)számla\s*sorszám|sorszám|számlaszám|számla\s*száma|bizonylatszám|invoice\s*(?:no|number|#|id)|számla\s*azonosító"
    r"|fatura\s*no|belge\s*no|bilet\s*no|rechnungs?-?(?:nr|nummer)|faktura(?:\s*(?:nr|vat|no))?|document\s*(?:no|number)|receipt\s*(?:no|number|#)|invoice\s*$"
    # 065: nyugtán a rendelés- / tranzakció-azonosító az irat száma; jóváíró számla; a Microsoft számlázási összesítője
    # 066 Á03: szóhatárral („Order now…” reklámsor, „recorder Number” nem címke)
    r"|\border\s*(?:no|number|id)\b|\border\s*#|\btransaction\s*id\b|\bcredit\s*note\b|számlázási\s*szám"
)
# 065: cím-sor („Elektronikus számla”, „Invoice”), alatta egyetlen azonosító (Billingo: a szám címke nélkül áll a cím alatt)
INVOICE_TITLE_RE = re.compile(r"(?i)^\s*(?:elektronikus\s+|e-)?(?:számla|invoice|tax\s+invoice|receipt|credit\s+note)\s*[:：]?\s*$")
INVOICE_TOKEN_RE = re.compile(r"(?<![\w/\-])[A-Za-z0-9][A-Za-z0-9\-/._]{1,}(?![\w/\-])")
# 066 Á03: összeg-alakú token (1 250,00 / 45.00 / 1,250.00): nem számlaszám-jelölt, a pénz-kereső dolga
AMOUNT_TOKEN_RE = re.compile(r"-?\d{1,3}(?:[,.  ]\d{3})*[.,]\d{2}|-?\d+[.,]\d{2}")

MONEY_RE = re.compile(
    r"(?<![\d.,])"
    r"(-?\d{1,3}(?:[  .]\d{3})+(?:,\d{1,2})?"  # 1 234 567 / 1.234.567 / 400 000,00
    r"|-?\d+,\d{1,2}"  # 20619,05
    r"|-?\d+\.\d{1,2}"  # 12.34 (ambiguous)
    r"|-?\d+)"  # 1000000 / 0
    r"(?![\d.,]\d)"
)
# intl: angol ezres vessző + tizedes pont ("1,600.00", "12,345", "$42.50") is egyben
MONEY_INTL_RE = re.compile(
    r"(?<![\d.,])"
    r"(-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"  # 1,600.00 / 12,345
    r"|-?\d{1,3}(?:[  .]\d{3})+(?:,\d{1,2})?"  # 1 234 567 / 1.234.567 / 400 000,00
    r"|-?\d+,\d{1,2}"  # 20619,05
    r"|-?\d+\.\d{1,2}"  # 12.34
    r"|-?\d+)"  # 1000000 / 0
    r"(?![\d.,]\d)"
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
    r"(?i)(?:\bkft\b|\bzrt\b|\bbt\b|\bnyrt\b|\bkkt\b|\be\.\s?v\.?(?=\W|$)|\bev\b|\begyéni vállalkozó\b|\bkisadózó\b"
    r"|\begyesület\b|\balapítvány\b|\bltd\b|\bgmbh\b|\bs\.r\.o\.|\bsrl\b|\bag\b"
    r"|\btársaság\b|\bkorlátolt felelősségű\b|\bbetéti\b|\bközkereseti\b|\bintézmény\b|\bönkormányzat\b)"
)
LEGAL_FORM_INTL_RE = re.compile(
    r"(?i)(?:\bkft\b|\bzrt\b|\bbt\b|\bnyrt\b|\bkkt\b|\be\.\s?v\.?(?=\W|$)|\begyesület\b|\balapítvány\b"
    r"|\bltd\.?(?=\W|$)|\blimited\b|\binc\.?(?=\W|$)|\bincorporated\b|\bllc\b|\bl\.l\.c\.|\bcorp\.?(?=\W|$)|\bcorporation\b|\bplc\b|\bpty\b"
    r"|\bgmbh\b|\bag\b|\bs\.r\.o\.|\bsrl\b|\bs\.r\.l\.|\bs\.p\.a\.|\bs\.a\.s\.|\bsarl\b|\bs\.à\s?r\.l\.|\bsp\.\s?z\s?o\.?\s?o\.?|\ba\.s\.|\ba\.ş\.|\bşti\.?(?=\W|$)"
    r"|\bb\.v\.|\bbv\b|\bn\.v\.|\boy\b|\bab\b|\bapS\b|\ba/s\b|\bd\.o\.o\.|\bpte\.?\s+ltd|\boü\b|\bsia\b|\buab\b"
    r"|\btársaság\b|\bkorlátolt felelősségű\b|\bbetéti\b|\bközkereseti\b|\bintézmény\b|\bönkormányzat\b)"
)
PARTY_LABEL_RE = re.compile(
    r"(?i)^(?:szállító|eladó|kibocsátó|kiállító|vevő|megrendelő|szolgáltató|supplier|seller|buyer|customer|vendor)"
    r"\s*(?:neve|name)?\s*[:：]?\s*"
)
PARTY_LABEL_INTL_RE = re.compile(
    r"(?i)^(?:szállító|eladó|kibocsátó|kiállító|vevő|megrendelő|szolgáltató|számlafizető|supplier|seller|buyer|customer|vendor|client"
    r"|from|bill(?:ed)?\s+to|sold\s+to|ship\s+to|invoice\s+to|remit\s+to|issued\s+by|sayın)"
    r"\s*(?:neve|name)?\s*[:：]?\s*"
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
)  # dátum-, időszak-, azonosító-, összeg-jellegű cellák nem címek
PAYMENT_METHOD_LINE_RE = re.compile(r"(?i)fizetési\s*mód|fizetés\s*módja|átutalás|utalás|készpénz|bankkártya|kártya")
COLUMN_X_TOLERANCE = 15.0  # pt - ugyanabban az oszlopban lévő cellák x0 eltérése

# --- közmű-profil (OCR-szövegű magyar közmű-számlák: MVM villany / gáz, Díjbeszedő-köteg víz / csatorna / hulladék) -----------
LEGAL_FORM_UTILITY_RE = re.compile(
    r"(?i)(?:\bkft\b|\bzrt\b|\bbt\b|\bnyrt\b|\bkkt\b|\brészvénytársaság\b|\bkorlátolt felelősségű\b|\btársaság\b|\bművek\b|\bholding\b"
    r"|\begyesület\b|\balapítvány\b|\bintézmény\b|\bönkormányzat\b|\bltd\b|\bgmbh\b)"
)
# OCR-tűrő címkék: az ékezetes betűk helyén betű-osztály (az OCR "Elosztéi engedélyes"-t, "Felhasznalo"-t is olvashat)
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
# OCR: a dátum-elválasztó néha vessző lesz ("2025.08.01-2025,08.31"); a vesszős alakot is elfogadjuk, a normalizálás előtt pontra cseréljük
DATE_OCR_RE = re.compile(r"(?<!\d)(\d{4})\s*[.\-/,]\s*(\d{1,2})\s*[.\-/,]\s*(\d{1,2})\.?(?!\d)")
# OCR: az adószám 8 jegyű blokkjába szóköz kerülhet ("2690357 0-2-44", "26903 570-2-44"); a szóköz nélküli alak ellenőrzőszám-teszttel jelölt
TAXID_OCR_RE = re.compile(r"(?<!\d)\d(?:[  ]?\d){7}[- ]\d[- ]\d{2}(?!\d)")
TAXID_LABEL_HU_RE = re.compile(r"(?i)ad[óoóé]sz[áa]m")


@dataclass(frozen=True)
class Profile:
    """Egy jelölt-profil regex-készlete (adat; a keresők a mechanizmus)."""

    name: str
    intl: bool  # parse_money / normalize_date nemzetközi alakjai
    legal_form_re: re.Pattern[str]
    party_label_re: re.Pattern[str]
    label_only_re: re.Pattern[str]
    invoice_label_re: re.Pattern[str]
    money_re: re.Pattern[str]
    currency_tokens: dict[str, re.Pattern[str]] = field(default_factory=dict)
    date_res: tuple[re.Pattern[str], ...] = (DATE_NUMERIC_RE, DATE_TEXT_RE)
    extra_iban_res: tuple[re.Pattern[str], ...] = ()
    extra_taxid_res: tuple[re.Pattern[str], ...] = ()
    taxid_label_re: re.Pattern[str] | None = None  # címkés sorban a címke utáni azonosító-tokenek is adószám-jelöltek
    name_cut_after_legal_form: bool = False  # "Microsoft Ireland Operations Ltd, One Microsoft Place, ..." -> a név a jogi formáig
    reverse_charge_zero: bool = False  # "reverse charge" nyomtatva és nincs 0 összeg -> szintetikus "0" pénz-jelölt (áfa)
    intl_addresses: bool = False
    ocr_dates: bool = False  # OCR-tűrés: a dátumban a vessző elválasztót pontnak vesszük
    address_label_re: re.Pattern[str] | None = None  # cím-címkék ("Felhasználó címe:") levágása a cím-jelöltről; alap: a fél-címkék
    invoice_lookahead: int = 1  # a számlaszám-címke utáni sorok, ahol az értéket keressük (OCR: a címke és az érték közé sor kerülhet)
    ocr_taxid: bool = False  # OCR-tűrés: szóközzel tört magyar adószám is jelölt, ha az ellenőrzőszáma stimmel
    max_money_options: int = MAX_OPTIONS  # a pénz-jelöltek felső korlátja (OCR-szövegű, sok számot tartalmazó közmű-számlán kisebb: a kérés token-korlátja)


HU = Profile(
    name="hu", intl=False, legal_form_re=LEGAL_FORM_RE, party_label_re=PARTY_LABEL_RE, label_only_re=LABEL_ONLY_RE,
    invoice_label_re=INVOICE_LABEL_RE, money_re=MONEY_RE, currency_tokens=CURRENCY_TOKENS,
)
INTL = Profile(
    name="intl", intl=True, legal_form_re=LEGAL_FORM_INTL_RE, party_label_re=PARTY_LABEL_INTL_RE, label_only_re=LABEL_ONLY_INTL_RE,
    invoice_label_re=INVOICE_LABEL_INTL_RE, money_re=MONEY_INTL_RE, currency_tokens=CURRENCY_TOKENS_INTL,
    # a perjeles US alak és a nap-először alak a HU év-először minta ELŐTT fut: különben a "2022 - 12/25" átnyúlik a tartomány-kötőjelen
    date_res=(DATE_TEXT_RE, *INTL_DATE_RES, DATE_NUMERIC_RE), extra_iban_res=(IBAN_INTL_RE,), extra_taxid_res=(TAXID_EU_INTL_RE,),
    taxid_label_re=TAXID_LABEL_INTL_RE, name_cut_after_legal_form=True, reverse_charge_zero=True, intl_addresses=True,
)
UTILITY = Profile(
    name="utility", intl=False, legal_form_re=LEGAL_FORM_UTILITY_RE, party_label_re=PARTY_LABEL_UTILITY_RE, label_only_re=LABEL_ONLY_UTILITY_RE,
    invoice_label_re=INVOICE_LABEL_UTILITY_RE, money_re=MONEY_RE, currency_tokens=CURRENCY_TOKENS,
    date_res=(DATE_OCR_RE, DATE_TEXT_RE), ocr_dates=True, name_cut_after_legal_form=True, address_label_re=ADDRESS_LABEL_UTILITY_RE, invoice_lookahead=2,
    ocr_taxid=True, max_money_options=100,
)
PROFILES: dict[str, Profile] = {"hu": HU, "intl": INTL, "utility": UTILITY}


def profile_of(profile: str | Profile | None) -> Profile:
    if isinstance(profile, Profile):
        return profile
    return PROFILES[profile or "hu"]


# --- segédek ---------------------------------------------------------------------------


def _context(lines: list[LineLayout], idx: int) -> str:
    prev = lines[idx - 1].text if idx > 0 else ""
    own = lines[idx].text
    return f"L{lines[idx].no:02d}: '{prev[:CONTEXT_MAX_CHARS]}' | '{own[:CONTEXT_MAX_CHARS]}'"


class _Bucket:
    """Jelöltek gyűjtése normalizált label szerinti dedup-pal, dokumentum-sorrendben."""

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


# --- keresők ---------------------------------------------------------------------------


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

    # sortörött HU IBAN (NAV Online Számlázó sablon): "HU82 1210 0028 4681 3574 0000" + alatta "0000"
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
                    continue  # túl rövid az IBAN-hoz (pl. egy EU-s adószám alakja)
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
            # 11 tapadó számjegy csak akkor adószám-jelölt, ha az ellenőrzőszám stimmel (telefonszámok kiszűrése)
            if hu_tax_id(m.group(0)).ok:
                bucket.add(normalize_tax_id(m.group(0)) or "", m.group(0), lines, i)
                work[i] = _mask(work[i], m.start(), m.end())
        for m in list(TAXID_EU_RE.finditer(work[i])):
            bucket.add(m.group(0), m.group(0), lines, i)
            work[i] = _mask(work[i], m.start(), m.end())
        if profile.ocr_taxid and TAXID_LABEL_HU_RE.search(ln.text):  # csak adószám-címkés sorban (a táblázat számoszlopai nem)
            for m in list(TAXID_OCR_RE.finditer(work[i])):
                compact = re.sub(r"[  ]", "", m.group(0))
                if hu_tax_id(compact).ok:  # csak érvényes ellenőrzőszámmal: a szóközös alak zajos
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
            # címkés sor (VAT ID / Tax ID / VKN / EIN ...): az azonosító-tokenek (helyi alakok) is jelöltek, de csak a címke
            # cellájában és az utána következő cellában (069, 066 Á27: a sor távoli cellájának telefonszáma nem)
            for start, end in _label_spans(ln, profile.taxid_label_re):
                for m in list(TAXID_LABEL_TOKEN_RE.finditer(work[i], start, end)):
                    bucket.add(m.group(0), m.group(0), lines, i)
                    work[i] = _mask(work[i], m.start(), m.end())
    return bucket.items()


def _recognized_prefix(raw: str) -> tuple[str, int] | None:
    """Az uniós / nemzetközi adószám-találat felismert része (kanonikus alak, hossz a találatban). A záró különálló
    betűcsoport lehet az ír adószám része („IE 8256796 U”) vagy a következő szó („DE123456789 AG”): előbb egészben,
    aztán nélküle próbáljuk. A szóközös „NO …” csak MVA utótaggal norvég adószám."""
    if re.match(r"NO[ -]", raw) and not raw.endswith("MVA"):
        return None
    for length in (len(raw), raw.rfind(" ")):
        if length > 0:
            t = recognize_tax_id(raw[:length])
            if t is not None:
                return t.canonical, length
    return None


def _label_spans(ln: LineLayout, label_re: re.Pattern[str]) -> list[tuple[int, int]]:
    """A címke-találatok tartománya a sor szövegében: a címke helyétől a címke cellájának, illetve a következő cellának a
    végéig. Cellák nélkül (vagy ha a cellák nem rakják ki a sort) a címkétől a sor végéig."""
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
    bucket = _Bucket("date")
    for i, ln in enumerate(lines):
        for rx in profile.date_res:
            for m in list(rx.finditer(work[i])):
                raw = m.group(0).replace(",", ".") if profile.ocr_dates else m.group(0)
                value = normalize_date(raw, intl=profile.intl)
                if value is None:
                    continue
                bucket.add(value.isoformat(), m.group(0), lines, i)
                work[i] = _mask(work[i], m.start(), m.end())
    return bucket.items()


def _invoice_tokens(text: str) -> list[str]:
    out = []
    for m in INVOICE_TOKEN_RE.finditer(text):
        tok = m.group(0).strip(":;,.")
        if "#" in tok or not any(ch.isdigit() for ch in tok) or len(tok) < 2:
            continue
        if re.fullmatch(r"\d{1,2}/\d{1,2}", tok):  # "1/1" oldalszám
            continue
        out.append(tok)
    return out


def _id_shaped(tok: str) -> bool:
    """066 Á03: a cím alatti egyetlen token csak azonosító-alakú lehet: betű vagy elválasztó (-, /) van benne, vagy
    legalább 5 számjegy; az évszám („2026”) és az összeg („45.00”) nem az."""
    if AMOUNT_TOKEN_RE.fullmatch(tok):
        return False
    return any(ch.isalpha() or ch in "-/" for ch in tok) or sum(ch.isdigit() for ch in tok) >= 5


def _mask_label_everywhere(work: list[str], label: str) -> None:
    """A számlaszám-jelölt kitakarása minden sorban, hogy a pénz-kereső ne lássa a számjegyeit; 066 Á03: csak önálló
    előfordulásként, egy nagyobb szám belsejében („15” a „1 150,00”-ban, a „15 000”-ben) nem."""
    rx = re.compile(rf"(?<![\w.,/\-])(?<!\d[  ]){re.escape(label)}(?![\w/\-])(?![.,]\d)(?![  ]\d{{3}}(?!\d))")
    for j, text in enumerate(work):
        for m in list(rx.finditer(text)):
            work[j] = _mask(work[j], m.start(), m.end())


def find_invoice_numbers(lines: list[LineLayout], work: list[str], profile: Profile = HU) -> list[Candidate]:
    bucket = _Bucket("invoice_number")
    label_idx = [i for i, ln in enumerate(lines) if profile.invoice_label_re.search(ln.text)]
    for i in label_idx:
        # címke-sor + szomszédok (a NAV-os sablonon a Sorszám: címke az érték ALATT van); OCR-nél a címke és az érték közé
        # egy köztes sor kerülhet (Díjbeszedő: "Terhelési összesítő száma" / tájékoztató sor / a szám) -> `invoice_lookahead`
        for j in (i, i - 1, *range(i + 1, i + 1 + profile.invoice_lookahead)):
            if 0 <= j < len(lines):
                for tok in _invoice_tokens(work[j]):
                    if j > i + 1 and len(tok) < 5:
                        continue  # a távolabbi sorból csak azonosító-hosszú token (a rövid számok pénz- / mennyiség-jelöltek, ne maszkoljuk őket)
                    if AMOUNT_TOKEN_RE.fullmatch(tok):
                        continue  # 066 Á03: összeg-alakú token nem számlaszám (a végösszeg a pénz-kereső jelöltje marad)
                    bucket.add(tok, tok, lines, j)
    for i, ln in enumerate(lines[:-1]):
        # 065: a cím alatti sor, ha az egész sor egyetlen azonosító (a több szavas sor név vagy cím, nem számlaszám)
        if INVOICE_TITLE_RE.match(ln.text):
            below = work[i + 1].strip()
            toks = _invoice_tokens(below)
            if len(toks) == 1 and toks[0] == below.strip(":;,.") and _id_shaped(toks[0]):
                bucket.add(toks[0], toks[0], lines, i + 1)
    for c in bucket.items():
        _mask_label_everywhere(work, c.label)
    return bucket.items()


def find_money(lines: list[LineLayout], work: list[str], profile: Profile = HU) -> list[Candidate]:
    bucket = _Bucket("money")
    for i, ln in enumerate(lines):
        for m in profile.money_re.finditer(work[i]):
            if PERCENT_AFTER_RE.match(work[i][m.end() :]):
                continue
            raw = m.group(1)
            if profile.intl:
                # a pénznem-jel / -kód a szám körül dönti el, hogy a pont tizedes ("$42.50", "42.50 USD")
                around = work[i][max(0, m.start() - 3) : m.start()] + raw + work[i][m.end() : m.end() + 5]
                parsed = parse_money(around if CURRENCY_HINT_RE.search(around) else raw, intl=True)
            else:
                parsed = parse_money(raw)
            if parsed.value is None:
                continue
            bucket.add(money_label(parsed.value), raw, lines, i, ambiguous=parsed.ambiguous)
    if profile.reverse_charge_zero and not bucket.has("0"):
        # kód-szabály: fordított adózás nyomtatva, de 0 összeg nincs -> az áfa 0 (a Jev csak felkínált értéket választhat)
        for i, ln in enumerate(lines):
            if REVERSE_CHARGE_RE.search(ln.text):
                bucket.add("0", "reverse charge", lines, i)
                break
    items = bucket.items()
    if len(items) > profile.max_money_options:
        # az összesítő-sorok (összesen / fizetendő / nettó / áfa / bruttó) jelöltjei elsőbbséget kapnak, utána dokumentum-sorrend
        priority = [c for c in items if TOTAL_LINE_RE.search(lines[c.line_no - 1].text)]
        rest = [c for c in items if c not in priority]
        items = (priority + rest)[: profile.max_money_options]
    return items


# Mennyiség-sorok (közmű-számla számlarészletező / mérő-tábla): mértékegység vagy mérő-címke a sorban
QUANTITY_LINE_RE = re.compile(
    r"(?i)\bkwh\b|\bm3\b|m³|\bm\?|\bmj\b|mérőállás|mer[őo]all[áa]s|fogyaszt[áa]s|mennyis[ée]g|f[űu]t[őo][ée]rt[ée]k|korrekci|indul[óo]|z[áa]r[óo]|h[őo]mennyis[ée]g|leolvas"
    r"|szorz[óo]|\b(?:Leol|Becs|Dikt|EII|Ell)\b"  # a mérő-sor a leolvasás-kóddal (LM oszlop) is felismerhető, ha a fejléc OCR-ben tönkrement
)
MAX_QUANTITY_OPTIONS = 80


def find_quantities(lines: list[LineLayout], profile: Profile = HU) -> list[Candidate]:
    """Mennyiség-jelöltek (`number` fajta: fogyasztás kWh / m3 / MJ, mérőállások, fűtőérték, korrekciós tényező): a mennyiség-
    sorok számai, a pénz-jelöltekkel azonos normalizálással (`money_label`), de csak a mértékegységes / mérő-címkés sorokból -
    így a kérés kicsi marad, és a Jev a mértékegység kontextusával választ."""
    bucket = _Bucket("money")
    hit = [bool(QUANTITY_LINE_RE.search(ln.text)) for ln in lines]
    for i, ln in enumerate(lines):
        # a mérő-tábla fejléce (Induló / Záró mérőállás, Fogyasztás) az érték-sor FÖLÖTT van: a szomszéd sor címkéje is számít
        if not (hit[i] or (i > 0 and hit[i - 1]) or (i + 1 < len(lines) and hit[i + 1])):
            continue
        for m in profile.money_re.finditer(ln.text):
            if PERCENT_AFTER_RE.match(ln.text[m.end() :]):
                continue
            parsed = parse_money(m.group(1))
            if parsed.value is None:
                continue
            bucket.add(money_label(parsed.value), m.group(1), lines, i, ambiguous=parsed.ambiguous)
    return bucket.items()[:MAX_QUANTITY_OPTIONS]


def find_currencies(lines: list[LineLayout], profile: str | Profile | None = None) -> list[str]:
    text = "\n".join(ln.text for ln in lines)
    return [code for code, rx in profile_of(profile).currency_tokens.items() if rx.search(text)]


_LEADING_ARTICLE_RE = re.compile(r"(?i)^(?:az?|the)\s+")
_PAREN_WRAP_RE = re.compile(r"^\((.+)\)\.?$")


def _clean_name(text: str, profile: Profile = HU) -> str:
    s = profile.party_label_re.sub("", text.strip())
    s = NAME_TRAILING_ID_RE.sub("", s)
    s = s.strip(" ,;:")
    if profile.name_cut_after_legal_form:
        # mondatba ágyazott / zárójeles cégnév ("az MVM Next ... Zrt.", "(MVM Next ... Zrt.)"): a névelő és a zárójel nem a név része
        s = _LEADING_ARTICLE_RE.sub("", s)
        s = _PAREN_WRAP_RE.sub(r"\1", s)
    return " ".join(s.split())


def _cut_after_legal_form(text: str, profile: Profile) -> str:
    """"Microsoft Ireland Operations Ltd, One Microsoft Place, ..." -> "Microsoft Ireland Operations Ltd" (a jogi forma utáni
    vesszős / kötőjeles / zárójeles folytatás cím vagy megjegyzés, nem név)."""
    matches = list(profile.legal_form_re.finditer(text))
    if not matches:
        return text
    for m in matches:  # "Díjbeszedő Holding Zrt. honlapján": a Holding után még jön a Zrt., a Zrt. után már mondat
        end = m.end() + (1 if text[m.end() : m.end() + 1] == "." else 0)  # a jogi forma pontja a névhez tartozik ("Zrt.")
        rest = text[end:].lstrip(". ")
        # vessző / kötőjel / zárójel / kisbetűs folytatás (mondatba ágyazott cégnév: "Zrt. honlapján bankkártyával") = nem a név része
        if rest.startswith((",", "-", "–", "—", "(")) or (rest[:1].isalpha() and rest[:1].islower()):
            return text[:end]
    if len(text) > 120:
        m = matches[0]
        return text[: m.end() + (1 if text[m.end() : m.end() + 1] == "." else 0)]
    return text


def _column_cells_below(lines: list[LineLayout], i: int, x0: float, depth: int, max_skip: int = 2) -> list[tuple[int, str]]:
    """Az i. sor alatti sorok azonos oszlopú cellái (max `depth`), a másik oszlop közbeszúrt sorait átugorva."""
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
    """A cella szövege + az alatta lévő (azonos oszlopú) cellákkal fokozatosan összefűzött változatok."""
    base = lines[i].cells[cell_idx]
    texts = [base.text]
    out: list[tuple[str, int]] = [(base.text, i)]
    for _, text in _column_cells_below(lines, i, base.x0, depth):
        texts.append(text)
        out.append((" ".join(texts), i))
    return out


NAME_STOP_RE = re.compile(r"[:：]|\d{4}[ ,]|\d{8}|adószám|iban|bank|telefon|tel\.|e-mail|@|www\.")


def _name_join(lines: list[LineLayout], i: int, cell_idx: int, depth: int) -> list[tuple[str, int]]:
    """Mint `_column_join`, de megáll, ha a következő cella már cím / címke / azonosító (nem névfolytatás)."""
    base = lines[i].cells[cell_idx]
    texts = [base.text]
    out: list[tuple[str, int]] = [(base.text, i)]
    for _, text in _column_cells_below(lines, i, base.x0, depth):
        if NAME_STOP_RE.search(text.casefold()):
            break
        texts.append(text)
        out.append((" ".join(texts), i))
    return out


def find_names(lines: list[LineLayout], profile: Profile = HU) -> list[Candidate]:
    bucket = _Bucket("name")
    for i, ln in enumerate(lines):
        for ci, cell in enumerate(ln.cells):
            for text, at in _name_join(lines, i, ci, depth=2):
                if profile.legal_form_re.search(text):
                    if profile.name_cut_after_legal_form:
                        text = _cut_after_legal_form(text, profile)
                    name = _clean_name(text, profile)
                    if 2 <= len(name) <= 120 and not profile.label_only_re.match(name):
                        bucket.add(name, text, lines, at)
    # Magánszemély (nincs jogi forma): a felső blokk rövid, betű-domináns cellái (legfeljebb MAX_NAME_FALLBACK darab -
    # a korlát a tartalék-nevekre vonatkozik, nem a jogi formás nevekkel együtt: egy hosszú tájékoztató szöveg cégnevei ne
    # szorítsák ki a magánszemély nevét)
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
                continue  # mondat, nem név
            if DATE_NUMERIC_RE.search(name) or MONEY_RE.fullmatch(name):
                continue
            if fallback >= MAX_NAME_FALLBACK or (profile.name == "hu" and len(bucket.items()) >= MAX_NAME_FALLBACK):
                break  # a `hu` profil viselkedése változatlan (a korábbi, összesített korlát)
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
    # intl: (1) a jogi forma utáni vesszős folytatás egy sorban ("..., Ltd, One Microsoft Place, ..., Dublin 18, D18 P521, Írország");
    # (2) postai / irányítószám-alakú cellák + az alattuk lévő 1-2 azonos oszlopú cella, címke-jellegű megállással
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
    """Címkés szöveg-mező jelöltjei (típus-csomag `text_labels`): a címke utáni szöveg ugyanabban a cellában, különben a
    sor következő cellája, különben az azonos oszlopú cella a sor alatt. Általános mechanizmus (tarifa, fizetési mód,
    szolgáltatás megnevezése, leolvasás módja...); a Jev választ a jelöltek közül, a `none` mindig opció."""
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
                    if len(text) >= 2 and not any(r.match(text) for r in regexes):  # az érték nem kezdődhet a címkével (a belsejében előfordulhat: "közszolgáltatás")
                        bucket.add(text, text, lines, at)
                break
    return bucket.items()


# --- belépési pont ---------------------------------------------------------------------


def find_all(
    lines: list[LineLayout], profile: str | Profile | None = None, text_labels: dict[str, tuple[str, ...]] | None = None
) -> dict[str, list[Candidate]]:
    """Minden jelölt-fajta a megadott profil szerint (`hu` alapból = a magyar számla eddigi viselkedése). `text_labels`
    (típus-csomag): mezőnként címkés szöveg-jelöltek `text:<mező>` kulcs alatt."""
    prof = profile_of(profile)
    work = [ln.text for ln in lines]
    out: dict[str, list[Candidate]] = {}
    out["iban"] = find_ibans(lines, work, prof)
    out["tax_id"] = find_tax_ids(lines, work, prof)
    out["date"] = find_dates(lines, work, prof)
    out["invoice_number"] = find_invoice_numbers(lines, work, prof)
    out["money"] = find_money(lines, work, prof)
    out["name"] = find_names(lines, prof)
    out["address"] = find_addresses(lines, prof)
    out["quantity"] = find_quantities(lines, prof)
    for field, labels in (text_labels or {}).items():
        out[f"text:{field}"] = find_labelled_text(lines, field, labels)
    return out


def candidate_lines(lines: list[LineLayout], cands: dict[str, list[Candidate]], kinds: list[str], margin: int = 1) -> set[int]:
    """Azon sorok 0-alapú indexei, ahol a megadott fajtájú jelöltek vannak (± margin)."""
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
            # a dedupolt kontextusokból is: "L12:" hivatkozások
            for m in re.finditer(r"L(\d+):", c.context):
                base2 = by_no.get(int(m.group(1)))
                if base2 is not None:
                    for j in range(base2 - margin, base2 + margin + 1):
                        if 0 <= j < len(lines):
                            idx.add(j)
    return idx
