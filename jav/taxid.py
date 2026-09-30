"""Tax-number formats in one place (069, 066 Á05 / Á27, decision of 2026-09-29): the shared table of the candidate
finder, the checks and the normalisation (the G-path extraction, manual correction, scoring).

- `recognize`: recognised format → country, kind, uniform (canonical) spelling; unknown format → None. No label allowed.
- `clean`: strips the label and any superfluous prefix ("Adószám: …", "HU VAT HU…", "VAT ID: IE 8256796 U"); if the
  text does not contain exactly one recognised tax number, the original text is kept (the check raises a to-do for it).
- `hu_check`: checks the Hungarian tax number and the Hungarian EU VAT number (check digit, VAT code, county code).

The EU formats are the VIES formats (without country code, compacted); of the non-EU ones, the common formats seen in
the survey and in the legacy candidate profile (British, Norwegian, Swiss, US EIN). Check digits are computed only for
Hungarian numbers (as decided).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

HU_WEIGHTS = (9, 7, 3, 1, 9, 7, 3)

# country code → format of the body (compacted: without spaces, dots and hyphens)
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
    "EU": r"\d{9}",  # EU one-stop-shop (OSS) registration number
    "GB": r"\d{9}|\d{12}|GD\d{3}|HA\d{3}",
    "NO": r"\d{9}(?:MVA)?",
}
EU_MEMBERS = frozenset(FORMATS) - {"GB", "NO"}
_SUFFIX = {"NO": "MVA"}  # suffix dropped from the canonical form

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
    country: str  # "HU", "IE", "US" …
    kind: str  # hu | hu_eu | eu | intl
    canonical: str


def recognize(raw: str | None) -> TaxId | None:
    """Recognised tax-number format (without a label), or None."""
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
    """Cleans an extracted value: recognised format → canonical spelling; a single recognised tax number written with a
    label / prefix → the tax number; anything else → the original text (the check raises a to-do for it)."""
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
    if all(x.upper() == country for x in rest):  # "HU VAT HU12345678": the repeated country code is not a second ID
        return canonical
    return s


def hu_check(t: TaxId) -> tuple[bool, str, str | None]:
    """Hungarian tax number (8 digits, the 8th being the check digit + VAT code 1–5 + county code 02–20 / 22–44 / 51)
    or Hungarian EU VAT number (HU + 8 digits, with the same check digit). Returns: (ok, code, detail)."""
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
