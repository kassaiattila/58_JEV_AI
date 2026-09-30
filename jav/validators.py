"""Determinisztikus üzleti ellenőrzések a normalizált `InvoiceHU`-n.

Szemantikai port a 10_AIFLOW_V4 `sidecar/app/validate/service.py` (137-285. sor) validátoraiból.
A régi kód a n8n-es JS validátorral volt byte-paritásban (float-trükkök, V8 Date.parse); ez itt nem
követelmény - Decimal-lal és `date`-tel dolgozunk. Kódok (`totals.ok`, `taxid.checkdigit`, ...) megtartva.

Melyik ellenőrzés fut: a típus-csomag `validators` listája (a régi `rules.json` `named` listája + a `fields`
formátum-szabályai adatként): `{"check": <név>, "field": <mező>, "optional": true, "regex": ...}`. Az `optional`
ellenőrzés kimarad, ha a mező üres. A magyar számla listája a korábbi `run_all` viselkedését adja változatlanul.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from jav import taxid
from jav.models import CheckResult, InvoiceHU

HU_TAXID_WEIGHTS = taxid.HU_WEIGHTS
# szóköz, TAB, NBSP, kötőjel - nyomtatott/PDF bankadatokban rutinszerű
_IBAN_STRIP = re.compile("[ \t -]")
_IBAN_SHAPE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$")
_DIGITS_FULL = re.compile(r"^[0-9]+$")


def vat_consistency(inv: InvoiceHU) -> CheckResult:
    """|nettó + áfa - bruttó| <= tűrés. HUF: egész forint, tűrés 1; egyébként 2 tizedes, tűrés 0.02."""
    if inv.net_total is None or inv.vat_total is None or inv.gross_total is None:
        return CheckResult(
            name="vat_consistency",
            ok=False,
            code="totals.unparseable",
            detail=f"net={inv.net_total} vat={inv.vat_total} gross={inv.gross_total}",
        )
    is_huf = (inv.currency or "").upper() == "HUF"
    tol = Decimal("1") if is_huf else Decimal("0.02")
    diff = inv.net_total + inv.vat_total - inv.gross_total
    if abs(diff) <= tol:
        return CheckResult(name="vat_consistency", ok=True, code="totals.ok")
    return CheckResult(
        name="vat_consistency",
        ok=False,
        code="totals.mismatch",
        detail=f"net+vat-gross={diff} ({inv.currency or '?'})",
    )


def date_order(inv: InvoiceHU, optional: bool = False) -> CheckResult:
    """`optional=True` (a csomag `validators` listájában): hiányzó határidő nem hiba - e-jegyen / kártyás számlán gyakran nincs."""
    if optional and inv.issue_date is not None and inv.due_date is None:
        return CheckResult(name="date_order", ok=True, code="dates.no_due")
    if inv.issue_date is None or inv.due_date is None:
        return CheckResult(
            name="date_order",
            ok=False,
            code="dates.unparseable",
            detail=f"issue={inv.issue_date} ful={inv.fulfillment_date} due={inv.due_date}",
        )
    if inv.due_date < inv.issue_date:
        return CheckResult(name="date_order", ok=False, code="dates.due_before_issue")
    return CheckResult(name="date_order", ok=True, code="dates.ok")


def tax_id(value: str | None, name: str = "tax_id") -> CheckResult:
    """069 (066 Á05, döntés 2026-09-29): felismert alak, különben teendő. Magyar adószám és magyar közösségi adószám:
    ellenőrzőszám (súlyozott), a belföldinél áfakód 1-5 és megyekód 02-20 / 22-44 / 51; uniós és néhány gyakori nem uniós
    alak: formátum (`jav/taxid.py`). A címkével írt értéket előbb tisztítja; ami így sem ismerhető fel (telefonszám,
    két azonosító egy mezőben), az `taxid.unrecognized`. Eddig minden nem 11 jegyű érték „külföldiként” átment."""
    if not value:
        return CheckResult(name=name, ok=False, code="taxid.missing")
    t = taxid.recognize(taxid.clean(str(value)))
    if t is None:
        return CheckResult(name=name, ok=False, code="taxid.unrecognized", detail=str(value).strip()[:40])
    if t.country == "HU":
        ok, code, detail = taxid.hu_check(t)
        return CheckResult(name=name, ok=ok, code=code, detail=detail)
    return CheckResult(name=name, ok=True, code="taxid.foreign", detail=t.country)


def hu_tax_id(value: str | None, name: str = "hu_tax_id") -> CheckResult:
    """A régi név (típuscsomagok, jelöltkereső): 069 óta ugyanaz, mint a `tax_id`."""
    return tax_id(value, name=name)


def iban_check(value: str | None, name: str = "iban_check") -> CheckResult:
    """ISO 13616 mod-97; HU IBAN pontosan 28 karakter; 16/24 számjegy = hazai számlaszám (ok)."""
    if not value:
        return CheckResult(name=name, ok=False, code="account.missing")
    s = _IBAN_STRIP.sub("", str(value)).upper()
    if _IBAN_SHAPE.match(s):
        if s.startswith("HU") and len(s) != 28:
            return CheckResult(name=name, ok=False, code="iban.hu_length", detail=f"{len(s)} chars")
        rearranged = s[4:] + s[:4]
        expanded = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
        remainder = 0
        for i in range(0, len(expanded), 7):
            remainder = int(str(remainder) + expanded[i : i + 7]) % 97
        if remainder == 1:
            return CheckResult(name=name, ok=True, code="iban.ok")
        return CheckResult(name=name, ok=False, code="iban.checksum")
    if _DIGITS_FULL.match(s) and len(s) in (16, 24):
        return CheckResult(name=name, ok=True, code="account.hu_domestic")
    return CheckResult(name=name, ok=False, code="account.format", detail=s[:40])


def format_check(value: object, regex: str, name: str = "format") -> CheckResult:
    """A régi rules.json `fields.<mező>.regex` szabálya: az érték (stringként) illeszkedik-e (pl. pénznem `^[A-Z]{3}$`)."""
    if value is None:
        return CheckResult(name=name, ok=False, code="format.missing")
    s = str(value)
    if re.fullmatch(regex, s):
        return CheckResult(name=name, ok=True, code="format.ok")
    return CheckResult(name=name, ok=False, code="format.mismatch", detail=f"{s[:40]!r} !~ {regex}")


def _tolerance(inv: InvoiceHU, n: int) -> Decimal:
    """Összeg-tűrés: HUF-nál 2 Ft vagy tételenként fél forint (soronkénti kerekítés), egyébként 0,02 / tételenként 0,005."""
    if (inv.currency or "HUF").upper() == "HUF":
        return max(Decimal("2"), Decimal("0.5") * n)
    return max(Decimal("0.02"), Decimal("0.005") * n)


def _rows(lines: list[int]) -> str:
    return ", ".join(f"line {i}" for i in lines)


def line_items_total(inv: InvoiceHU) -> CheckResult:
    """053 T3.2: a tételek összege = a fej végösszege (nettó és bruttó külön). Elég, ha az egyik oldal teljes és egyezik
    (a hosszú víz-listákon a soronkénti nettó gyakran hiányzik, a bruttó teljes). Tétel nélkül nem hiba (a kód + JEV út
    nem olvas tételt). A hibás / hiányos sor 1-től számozva a `detail`-ben (`line N`), a felület így jelöli."""
    items = inv.line_items
    if not items:
        return CheckResult(name="line_items_total", ok=True, code="lines.none")
    tol = _tolerance(inv, len(items))
    matched, mismatches, missing = [], [], []
    for side, attr, total in (("net", "net_amount", inv.net_total), ("gross", "gross_amount", inv.gross_total)):
        values = [getattr(li, attr) for li in items]
        if total is None or all(v is None for v in values):
            continue
        absent = [i + 1 for i, v in enumerate(values) if v is None]
        if absent:
            missing.append(f"{side} missing on {_rows(absent)}")
            continue
        diff = sum(values, Decimal("0")) - total
        (matched if abs(diff) <= tol else mismatches).append(f"{side}: sum-total={diff}")
    if mismatches:
        return CheckResult(name="line_items_total", ok=False, code="lines.total_mismatch", detail="; ".join(mismatches + missing))
    if matched:
        return CheckResult(name="line_items_total", ok=True, code="lines.total_ok", detail="; ".join(matched + missing) or None)
    if missing:
        return CheckResult(name="line_items_total", ok=False, code="lines.incomplete", detail="; ".join(missing))
    return CheckResult(name="line_items_total", ok=True, code="lines.no_total")


_RATE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*%?\s*$")


def _vat_fraction(rate: str | None) -> Decimal | None:
    """ÁFA-kulcs szövegből: „27%”, „27”, „5,0” -> 0,27 / 0,05; „0,27” -> 0,27. Nem szám (AHK, TAM, mentes): None."""
    m = _RATE.match(rate or "")
    if not m:
        return None
    v = Decimal(m.group(1).replace(",", "."))
    return v / 100 if v > 1 else v


def line_items_arithmetic(inv: InvoiceHU) -> CheckResult:
    """053 T3.2: soronként mennyiség × egységár ≈ nettó, és nettó × (1 + ÁFA-kulcs) ≈ bruttó; tűrés max(1 egység, 1 %).
    Csak a kitöltött értékek közt; ahol az egységár más jelentésű (MOHU), a csomag nem kéri ezt az ellenőrzést."""
    bad: list[str] = []
    checked = 0
    for i, li in enumerate(inv.line_items, start=1):
        pairs = []
        if li.quantity is not None and li.unit_price is not None and li.net_amount is not None:
            pairs.append(("qty*price", li.quantity * li.unit_price, li.net_amount))
        rate = _vat_fraction(li.vat_rate)
        if li.net_amount is not None and rate is not None and li.gross_amount is not None:
            pairs.append(("net*(1+vat)", li.net_amount * (1 + rate), li.gross_amount))
        for label, computed, stated in pairs:
            checked += 1
            if abs(computed - stated) > max(Decimal("1"), abs(stated) / 100):
                bad.append(f"line {i}: {label}={computed.quantize(Decimal('0.01'))} vs {stated}")
    if bad:
        return CheckResult(name="line_items_arithmetic", ok=False, code="lines.arithmetic_mismatch", detail="; ".join(bad))
    if checked == 0:
        return CheckResult(name="line_items_arithmetic", ok=True, code="lines.not_checkable")
    return CheckResult(name="line_items_arithmetic", ok=True, code="lines.arithmetic_ok")


def _statement_check(name: str):
    """047: a régi kivonat-szabályok (`jav/legacy_validation.py`, a régi rules.json hű portja) a teljes rekordon: futó
    egyenleg, záró egyenleg, terhelés/jóváírás összegek, tranzakciók az időszakon belül."""
    def check(inv: InvoiceHU) -> CheckResult:
        from jav import legacy_validation
        from jav.models import _plain

        dp = {**{k: _plain(v) for k, v in inv.extra.items()},
              **{f: _plain(getattr(inv, f)) for f in type(inv).model_fields if f not in ("extra", "line_items")}}
        r = getattr(legacy_validation, name)(dp)
        return CheckResult(name=name, ok=bool(r["ok"]), code=r["code"], detail=r.get("detail"))
    return check


_RECORD_CHECKS = {"vat_consistency": vat_consistency, "date_order": date_order,
                  "line_items_total": line_items_total, "line_items_arithmetic": line_items_arithmetic,
                  **{n: _statement_check(n) for n in ("running_balance_check", "closing_balance_check", "totals_consistency", "period_dates")}}
_FIELD_CHECKS = {"hu_tax_id": hu_tax_id, "tax_id": tax_id, "iban_check": iban_check}


def run_checks(inv: InvoiceHU, validators: tuple[dict[str, Any], ...] | list[dict[str, Any]]) -> list[CheckResult]:
    """A típus-csomag `validators` listája szerint: rekord-szintű ellenőrzések mindig; mező-szintűek a mező értékén,
    `optional: true` mellett kimaradnak, ha a mező üres (a régi `named` lista `optional` szemantikája).
    053: `"review": false` = csak jelzés (`advisory`): az eredmény látszik, de a teendő-szabály kihagyja."""
    results: list[CheckResult] = []
    for spec in validators:
        r = _run_one(inv, spec)
        if r is None:
            continue
        if spec.get("review", True) is False:
            r.advisory = True
        results.append(r)
    return results


def _run_one(inv: InvoiceHU, spec: dict[str, Any]) -> CheckResult | None:
    check = spec["check"]
    if check == "date_order":
        return date_order(inv, optional=bool(spec.get("optional", False)))
    if check in _RECORD_CHECKS:
        return _RECORD_CHECKS[check](inv)
    field = spec["field"]
    value = inv.get_field(field)
    if value is None and spec.get("optional", False):
        return None
    name = f"{check}:{field}"
    if check == "format":
        return format_check(value, spec["regex"], name=name)
    if check in _FIELD_CHECKS:
        return _FIELD_CHECKS[check](None if value is None else str(value), name=name)
    raise ValueError(f"ismeretlen validátor a típus-csomagban: {check}")


def run_all(inv: InvoiceHU, validators: tuple[dict[str, Any], ...] | None = None) -> list[CheckResult]:
    """Alap: a magyar számla típus-csomagjának listája (= a régi rules.json `named`: vat_consistency, date_order mindig;
    adószám / IBAN csak ha van érték). Más típusnál a csomag `validators` listáját add át."""
    if validators is None:
        from jav.typepack import get

        validators = get("invoice_hu").validators
    return run_checks(inv, validators)
