"""Adószám-alakok egy helyen (069, 066 Á05 / Á27, döntés 2026-09-29): a jelöltkereső, az ellenőrzés és a normalizálás
(a G-út kivonata, a kézi javítás, a pontozás) közös táblája.

- `recognize`: felismert alak → ország, fajta, egységes (kanonikus) írásmód; ismeretlen alak → None. Címkét nem tűr.
- `clean`: a címke és a felesleges előtag levágása („Adószám: …”, „HU VAT HU…”, „VAT ID: IE 8256796 U”); ha a szövegben
  nem pontosan egy felismert adószám áll, az eredeti szöveg marad (az ellenőrzés teendőt ad rá).
- `hu_check`: a magyar adószám és a magyar közösségi adószám ellenőrzése (ellenőrzőszám, áfakód, megyekód).

Az uniós alakok a VIES-formátumok (országkód nélkül, tömörítve); a nem uniósak közül a felmérésben és a régi jelölt-profilban
látott gyakoriak (brit, norvég, svájci, amerikai EIN). Ellenőrzőszámot csak a magyarnál számolunk (a döntés szerint).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HU_WEIGHTS = (9, 7, 3, 1, 9, 7, 3)

# országkód → a törzs alakja (tömörítve: szóköz, pont, kötőjel nélkül)
FORMATS: dict[str, str] = {
    "AT": r"U\d{8}",
    "BE": r"[01]\d{9}",
    "BG": r"\d{9,10}",
    "CY": r"\d{8}[A-Z]",
    "CZ": r"\d{8,10}",
    "DE": r"\d{9}",
    "DK": r"\d{8}",
    "EE": r"\d{9}",
    "EL": r"\d{9}",
    "ES": r"[A-Z0-9]\d{7}[A-Z0-9]",
    "FI": r"\d{8}",
    "FR": r"[A-HJ-NP-Z0-9]{2}\d{9}",
    "HR": r"\d{11}",
    "HU": r"\d{8}",
    "IE": r"\d{7}[A-W][A-I]?|\d[A-Z+*]\d{5}[A-W]",
    "IT": r"\d{11}",
    "LT": r"\d{9}|\d{12}",
    "LU": r"\d{8}",
    "LV": r"\d{11}",
    "MT": r"\d{8}",
    "NL": r"\d{9}B\d{2}",
    "PL": r"\d{10}",
    "PT": r"\d{9}",
    "RO": r"\d{2,10}",
    "SE": r"\d{10}01",
    "SI": r"\d{8}",
    "SK": r"\d{10}",
    "XI": r"\d{9}|\d{12}|GD\d{3}|HA\d{3}",
    "EU": r"\d{9}",  # uniós egyablakos (OSS) nyilvántartási szám
    "GB": r"\d{9}|\d{12}|GD\d{3}|HA\d{3}",
    "NO": r"\d{9}(?:MVA)?",
}
EU_MEMBERS = frozenset(FORMATS) - {"GB", "NO"}
_SUFFIX = {"NO": "MVA"}  # a kanonikus alakból elhagyott utótag

_HU_DOMESTIC_RE = re.compile(r"\d{8}[\s\-]?\d[\s\-]?\d{2}")
_EIN_RE = re.compile(r"\d{2}-\d{7}")
_CH_RE = re.compile(r"CHE(\d{9})(?:MWST|TVA|IVA)?")
_CC_RE = re.compile(r"([A-Z]{2})([0-9A-Z+*]{2,15})")
_SQUASH_RE = re.compile(r"[\s.\-]")

_LABEL_RE = re.compile(
    r"(?i)(?<!\w)(?:közösségi\s+adószám|kozossegi\s+adoszam|adószám|adoszam|adóazonosító(?:\s+jel)?|"
    r"tax\s*(?:id|number|no|reg(?:istration)?)(?:\s*(?:no|number))?|vat\s*(?:id|no|number|reg(?:istration)?)?(?:\s*(?:no|number))?|"
    r"ust[-.]?\s?id[-.]?\s?nr|uid|steuernummer|vkn|nip|abn|gstin|gst|ein|tva|btw|iva|moms)(?!\w)\s*[:.#]?"
)


@dataclass(frozen=True)
class TaxId:
    country: str  # „HU”, „IE”, „US” …
    kind: str  # hu | hu_eu | eu | intl
    canonical: str


def recognize(raw: str | None) -> TaxId | None:
    """Felismert adószám-alak (címke nélkül), vagy None."""
    if not raw:
        return None
    s = str(raw).strip()
    if re.fullmatch(r"[\d\s\-./]+", s):
        if _HU_DOMESTIC_RE.fullmatch(s):
            d = re.sub(r"\D", "", s)
            return TaxId("HU", "hu", f"{d[:8]}-{d[8]}-{d[9:]}")
        if _EIN_RE.fullmatch(s):
            return TaxId("US", "intl", s)
        return None
    compact = _SQUASH_RE.sub("", s).upper()
    m = _CH_RE.fullmatch(compact)
    if m:
        return TaxId("CH", "intl", "CHE" + m.group(1))
    m = _CC_RE.fullmatch(compact)
    if not m:
        return None
    cc, body = m.groups()
    fmt = FORMATS.get(cc)
    if fmt is None or not re.fullmatch(fmt, body):
        return None
    body = body.removesuffix(_SUFFIX.get(cc, "\0"))
    kind = "hu_eu" if cc == "HU" else "eu" if cc in EU_MEMBERS else "intl"
    return TaxId(cc, kind, cc + body)


def clean(raw: str | None) -> str | None:
    """A kinyert érték tisztítása: felismert alak → kanonikus írásmód; címkével / előtaggal együtt írt, egyetlen
    felismert adószám → az adószám; minden más → az eredeti szöveg (az ellenőrzés teendőt ad rá)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    t = recognize(s)
    if t is not None:
        return t.canonical
    tokens = [x.strip(",;:()") for x in _LABEL_RE.sub(" ", s).split()]
    tokens = [x for x in tokens if x]
    found: dict[str, tuple[int, int, str]] = {}
    for i in range(len(tokens)):
        for j in range(i + 1, min(i + 4, len(tokens)) + 1):
            t = recognize(" ".join(tokens[i:j]))
            if t is None:
                continue
            lo, hi, _ = found.get(t.canonical, (i, j, t.country))
            found[t.canonical] = (min(lo, i), max(hi, j), t.country)
    if len(found) != 1:
        return s
    canonical, (lo, hi, country) = next(iter(found.items()))
    rest = tokens[:lo] + tokens[hi:]
    if all(x.upper() == country for x in rest):  # „HU VAT HU12345678”: a megismételt országkód nem második azonosító
        return canonical
    return s


def hu_check(t: TaxId) -> tuple[bool, str, str | None]:
    """Magyar adószám (8 jegy + ellenőrzőszám + áfakód 1–5 + megyekód 02–20 / 22–44 / 51) vagy magyar közösségi adószám
    (HU + 8 jegy, ugyanazzal az ellenőrzőszámmal). Visszaad: (rendben, kód, részlet)."""
    d = re.sub(r"\D", "", t.canonical)
    s = sum(int(d[i]) * HU_WEIGHTS[i] for i in range(7))
    check = (10 - (s % 10)) % 10
    if check != int(d[7]):
        return False, "taxid.checkdigit", f"expected {check}, got {d[7]}"
    if t.kind == "hu_eu":
        return True, "taxid.ok", None
    vat_code = int(d[8])
    if not 1 <= vat_code <= 5:
        return False, "taxid.vatcode", f"A={vat_code}"
    county = int(d[9:11])
    if not ((2 <= county <= 20) or (22 <= county <= 44) or county == 51):
        return False, "taxid.county", f"KK={d[9:11]}"
    return True, "taxid.ok", None


__all__ = ["FORMATS", "TaxId", "clean", "hu_check", "recognize"]
