"""Deterministic business checks on the normalised `InvoiceHU`.

Semantic port of the validators in 10_AIFLOW_V4 `sidecar/app/validate/service.py` (lines 137-285).
The legacy code was byte-for-byte on par with the n8n JS validator (float tricks, V8 Date.parse); that is not
a requirement here - we work with Decimal and `date`. The codes (`totals.ok`, `taxid.checkdigit`, ...) are kept.

Which checks run: the type pack's `validators` list (the legacy `rules.json` `named` list + the format rules of
`fields`, as data): `{"check": <name>, "field": <field>, "optional": true, "regex": ...}`. An `optional`
check is skipped if the field is empty. The Hungarian invoice's list gives the earlier `run_all` behaviour unchanged.
A role-pair check names two fields: `{"check": "distinct_parties", "fields": [<first>, <second>]}` (120).
121: `party_orientation` (same shape) compares the pair with the earlier documents of the same type; it needs the
document's identifier and type (`run_checks(..., doc_id=, doc_type=)`) and runs only in a worker run.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from jav import fact_checks, party_history, taxid
from jav.models import CheckResult, InvoiceHU

HU_TAXID_WEIGHTS = taxid.HU_WEIGHTS
# space, TAB, NBSP, hyphen - routine in printed/PDF bank details
_IBAN_STRIP = re.compile("[ \t -]")
_IBAN_SHAPE = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]+$")
_DIGITS_FULL = re.compile(r"^[0-9]+$")


def vat_consistency(inv: InvoiceHU) -> CheckResult:
    """|net + VAT - gross| <= tolerance. HUF: whole forints, tolerance 1; otherwise 2 decimals, tolerance 0.02."""
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
    """`optional=True` (in the pack's `validators` list): a missing due date is no error - e-tickets / card invoices
    often have none."""
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
    """069 (066 Á05, decision of 2026-09-29): a recognised form, otherwise a to-do. Hungarian tax number and Hungarian
    EU VAT number: check digit (weighted), for the domestic one also VAT code 1-5 and county code 02-20 / 22-44 / 51; EU
    and a few common non-EU forms: format (`jav/taxid.py`). A value written with its label is cleaned first; whatever is
    still not recognisable (a phone number, two identifiers in one field) is `taxid.unrecognized`. Before this, every
    value that was not 11 digits passed as "foreign"."""
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
    """The legacy name (type packs, candidate finder): since 069 the same as `tax_id`."""
    return tax_id(value, name=name)


_GIRO_WEIGHTS = (9, 7, 3, 1)


def hu_account_check_digits_ok(digits: str) -> bool:
    """075 (repeated security audit, F01): the two check digits of a Hungarian domestic account number (16 or 24
    digits; the giro rule of the central bank). The first 8 digits and the rest each end in a check digit: with the
    weights 9-7-3-1 repeating, the weighted sum of each part is divisible by 10. The data guard uses the same rule."""
    if len(digits) not in (16, 24) or not digits.isdigit():
        return False
    return all(sum(int(d) * _GIRO_WEIGHTS[i % 4] for i, d in enumerate(part)) % 10 == 0 for part in (digits[:8], digits[8:]))


def iban_check(value: str | None, name: str = "iban_check") -> CheckResult:
    """ISO 13616 mod-97; a HU IBAN is exactly 28 characters and its inner account number must pass the domestic check
    digits too; 16/24 digits = a domestic account number, valid only with both check digits right (075)."""
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
        if remainder != 1:
            return CheckResult(name=name, ok=False, code="iban.checksum")
        if s.startswith("HU") and not hu_account_check_digits_ok(s[4:]):
            return CheckResult(name=name, ok=False, code="iban.hu_account_checksum")
        return CheckResult(name=name, ok=True, code="iban.ok")
    if _DIGITS_FULL.match(s) and len(s) in (16, 24):
        if not hu_account_check_digits_ok(s):
            return CheckResult(name=name, ok=False, code="account.hu_checksum")
        return CheckResult(name=name, ok=True, code="account.hu_domestic")
    return CheckResult(name=name, ok=False, code="account.format", detail=s[:40])


def format_check(value: object, regex: str, name: str = "format") -> CheckResult:
    """The legacy rules.json `fields.<field>.regex` rule: whether the value (as a string) matches (e.g. currency
    `^[A-Z]{3}$`)."""
    if value is None:
        return CheckResult(name=name, ok=False, code="format.missing")
    s = str(value)
    if re.fullmatch(regex, s):
        return CheckResult(name=name, ok=True, code="format.ok")
    return CheckResult(name=name, ok=False, code="format.mismatch", detail=f"{s[:40]!r} !~ {regex}")


def _tolerance(inv: InvoiceHU, n: int) -> Decimal:
    """Sum tolerance: for HUF, 2 Ft or half a forint per item (per-line rounding), otherwise 0.02 / 0.005 per item."""
    if (inv.currency or "HUF").upper() == "HUF":
        return max(Decimal("2"), Decimal("0.5") * n)
    return max(Decimal("0.02"), Decimal("0.005") * n)


def _rows(lines: list[int]) -> str:
    return ", ".join(f"line {i}" for i in lines)


def line_items_total(inv: InvoiceHU) -> CheckResult:
    """053 T3.2: the sum of the items = the header's total (net and gross separately). It is enough if one side is
    complete and matches (on the long water lists the per-line net is often missing, the gross is complete). No items is
    no error (the code + JEV path does not read items). The wrong / incomplete line is numbered from 1 in `detail`
    (`line N`), which is how the UI marks it."""
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
    """VAT rate from text: "27%", "27", "5,0" -> 0.27 / 0.05; "0,27" -> 0.27. Not a number (AHK, TAM, mentes): None."""
    m = _RATE.match(rate or "")
    if not m:
        return None
    v = Decimal(m.group(1).replace(",", "."))
    return v / 100 if v > 1 else v


def line_items_arithmetic(inv: InvoiceHU) -> CheckResult:
    """053 T3.2: per line, quantity × unit price ≈ net, and net × (1 + VAT rate) ≈ gross; tolerance max(1 unit, 1 %).
    Only among filled-in values; where the unit price means something else (MOHU), the pack does not request this
    check."""
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
    """047: the legacy statement rules (`jav/legacy_validation.py`, a faithful port of the legacy rules.json) on the
    whole record: running balance, closing balance, debit/credit totals, transactions within the period."""
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
PAIR_CHECKS = frozenset({"distinct_parties", "party_orientation"})  # 120/121: checks naming two fields in `fields`


def run_checks(inv: InvoiceHU, validators: tuple[dict[str, Any], ...] | list[dict[str, Any]], *, doc_id: str | None = None,
               doc_type: str | None = None) -> list[CheckResult]:
    """According to the type pack's `validators` list: record-level checks always; field-level ones on the field's
    value, skipped with `optional: true` if the field is empty (the `optional` semantics of the legacy `named` list).
    053: `"review": false` = signal only (`advisory`): the result is visible, but the to-do rule skips it. 121: the
    document's identifier and type, for the checks that compare it with earlier documents."""
    results: list[CheckResult] = []
    for spec in validators:
        r = _run_one(inv, spec, doc_id=doc_id, doc_type=doc_type)
        if r is None:
            continue
        if spec.get("review", True) is False:
            r.advisory = True
        results.append(r)
    return results


def distinct_parties(inv: InvoiceHU, first: str, second: str) -> CheckResult | None:
    """120: two role fields must not name one party (`jav.fact_checks.same_party`). The to-do stands at the second
    field; the detail names only the fields, never their values. Skipped when either field is empty."""
    a, b = inv.get_field(first), inv.get_field(second)
    if a in (None, "") or b in (None, ""):
        return None
    name = f"distinct_parties:{second}"
    if fact_checks.same_party(a, b):
        return CheckResult(name=name, ok=False, code="parties.same_entity", detail=f"{first} ~ {second}")
    return CheckResult(name=name, ok=True, code="parties.ok")


def party_orientation(inv: InvoiceHU, first: str, second: str, *, doc_id: str | None, doc_type: str | None) -> CheckResult | None:
    """121: the pair against the earlier documents of the same type (`jav/party_history.py`). The to-do stands at the
    second field; the detail holds counts only. Skipped outside a worker run, for a missing value, or when no earlier
    document names the same two parties."""
    counts = party_history.orientation(doc_id, doc_type, (first, second), (inv.get_field(first), inv.get_field(second)))
    if counts is None or counts == (0, 0):
        return None
    other, alike = counts
    name = f"party_orientation:{second}"
    if fact_checks.orientation_issue(other, alike):
        return CheckResult(name=name, ok=False, code="parties.orientation_reversed", detail=f"{other} the other way, {alike} alike")
    return CheckResult(name=name, ok=True, code="parties.orientation_ok")


def _run_one(inv: InvoiceHU, spec: dict[str, Any], *, doc_id: str | None = None, doc_type: str | None = None) -> CheckResult | None:
    check = spec["check"]
    if check == "date_order":
        return date_order(inv, optional=bool(spec.get("optional", False)))
    if check in _RECORD_CHECKS:
        return _RECORD_CHECKS[check](inv)
    if check in PAIR_CHECKS:
        first, second = spec["fields"]
        if check == "party_orientation":
            return party_orientation(inv, first, second, doc_id=doc_id, doc_type=doc_type)
        return distinct_parties(inv, first, second)
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


def run_all(inv: InvoiceHU, validators: tuple[dict[str, Any], ...] | None = None, *, doc_id: str | None = None,
            doc_type: str | None = None) -> list[CheckResult]:
    """Default: the list of the Hungarian invoice's type pack (= the legacy rules.json `named`: vat_consistency,
    date_order always; tax number / IBAN only if there is a value). For another type, pass the pack's `validators`
    list."""
    if validators is None:
        from jav.typepack import get

        validators = get("invoice_hu").validators
    return run_checks(inv, validators, doc_id=doc_id, doc_type=doc_type)
