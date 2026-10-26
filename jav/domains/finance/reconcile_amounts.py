"""231 (plan stage C, C2b): how a line's amount meets an invoice's, split out of `reconcile.py`.

Plain-language summary: the payment and card windows, whether a line and an invoice can meet (one currency, a card's
forint line, a bank's forint line, a card purchase's original amount) and how their amounts relate, through the MNB
rates the snapshot carries (`fx_rates`). The rules are described in `reconcile.py` (130, 137, 149, 151).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from jav.core import values
from jav.domains.finance import reconcile_rules
from jav.domains.finance.reconcile_rules import fx_bank_tolerance, fx_tolerance
from jav.domains.finance.reconcile_signals import money


# --- windows and amounts -------------------------------------------------------------------------------------------


def window(invoice: dict[str, Any]) -> tuple[date, date]:
    """The days a payment of the invoice is searched in."""
    w = reconcile_rules._conf()["window"]
    issue = values.stored_day(invoice["issue_date"])
    end = values.stored_day(invoice.get("due_date")) or issue
    return issue - timedelta(days=int(w["days_before_issue"])), max(end, issue) + timedelta(days=int(w["days_after_due"]))


def fx_capable(payment: dict[str, Any]) -> bool:
    """Whether a line can pay an invoice of another currency: a forint line of a card statement (130)."""
    f = reconcile_rules._conf()["fx"]
    return payment.get("currency") == f["line_currency"] and payment.get("statement_type") in f["statement_types"]


def fx_bank_capable(payment: dict[str, Any]) -> bool:
    """149: a forint line of a bank account statement (`fx.bank.statement_types`); `meets` leaves out a card purchase
    the statement prints with its original currency."""
    f = reconcile_rules._conf()["fx"]
    return payment.get("currency") == f["line_currency"] and payment.get("statement_type") in f["bank"]["statement_types"]


def bank_rate_days(invoice: dict[str, Any], payment: dict[str, Any]) -> list[tuple[str, date]]:
    """149: the days whose MNB rate a forint bank line is compared at, in the order of `fx.bank.rate_days`: the
    invoice's fulfilment day (its issue day when none was read) and the line's booking day."""
    days = {"fulfillment": values.stored_day(invoice.get("fulfillment_date")) or values.stored_day(invoice.get("issue_date")),
            "booking": values.stored_day(payment.get("booking_date"))}
    return [(basis, day) for basis in reconcile_rules._conf()["fx"]["bank"]["rate_days"] if (day := days.get(basis))]


def original(payment: dict[str, Any]) -> tuple[str, Decimal] | None:
    """137: a card purchase's original currency and amount, as the bank printed them next to the forint line."""
    currency, amount = payment.get("original_currency"), payment.get("original_amount")
    if not currency or amount in (None, ""):
        return None
    try:
        return str(currency), money(str(amount))
    except (ValueError, InvalidOperation):
        return None


def meets(invoice: dict[str, Any], payment: dict[str, Any]) -> str | None:
    """How a line can pay an invoice: `same` (one currency), `original` (137: a card purchase in the invoice's
    currency), `fx` (130: a forint card line against another currency, through the MNB rate), `fx_bank` (149: a forint
    bank line against another currency, through the MNB rate of the fulfilment or the booking day), or None."""
    if invoice.get("currency") == payment.get("currency"):
        return "same"
    if (orig := original(payment)) is not None and orig[0] == invoice.get("currency"):
        return "original"
    if fx_capable(payment) and rate_need(invoice):
        return "fx"
    if fx_bank_capable(payment) and original(payment) is None and rate_need(invoice):
        return "fx_bank"  # a card purchase printed with its original currency is that currency's, not converted
    return None


def pair_window(invoice: dict[str, Any], payment: dict[str, Any]) -> tuple[date, date] | None:
    """The days the line may be booked in to pay the invoice: its payment window in one currency, the card window
    around the issue date otherwise; None when their currencies cannot meet."""
    how = meets(invoice, payment)
    if how is None:
        return None
    return window(invoice) if how in ("same", "fx_bank") else fx_window(invoice)  # 149: a bank line in the payment window


def fx_window(invoice: dict[str, Any]) -> tuple[date, date]:
    """The days a card payment of the invoice is searched in: around its issue date (the day of the purchase)."""
    w = reconcile_rules._conf()["fx"]["window"]
    issue = values.stored_day(invoice["issue_date"])
    return issue - timedelta(days=int(w["days_before_issue"])), issue + timedelta(days=int(w["days_after_issue"]))


def rate_need(invoice: dict[str, Any]) -> tuple[str, date] | None:
    """The (currency, day) whose rate a card pair of the invoice needs: its currency on its issue date."""
    issue = values.stored_day(invoice.get("issue_date"))
    currency = invoice.get("currency")
    if not issue or not currency or currency == reconcile_rules._conf()["fx"]["line_currency"]:
        return None
    return str(currency), issue


def convert(invoice: dict[str, Any], payment: dict[str, Any], rates: dict[str, Any] | None) -> tuple[str, dict[str, str] | None]:
    """The relation of a card line to an invoice of another currency (`fx_within`, `fx_outside` or `no_rate`) and the
    conversion behind it: the rate and its day, the converted amount and the line's deviation from it."""
    if meets(invoice, payment) == "fx_bank":
        return _convert_bank(invoice, payment, rates)
    need = rate_need(invoice)
    entry = (rates or {}).get(need[0], {}).get(need[1].isoformat()) if need else None
    if not entry:
        return "no_rate", None
    per_unit = Decimal(str(entry["rate"]))
    expected = money(str(invoice["amount"])) * per_unit
    deviation = money(str(payment["amount"])) / expected - 1
    below, above = fx_tolerance()
    relation = "fx_within" if -below <= deviation <= above else "fx_outside"
    return relation, {"rate": str(entry["rate"]), "rate_day": str(entry["rate_day"]), "source": str(entry.get("source") or "mnb"),
                      "converted": str(expected.quantize(Decimal("0.01"))), "deviation": str(deviation.quantize(Decimal("0.0001")))}


def _convert_bank(invoice: dict[str, Any], payment: dict[str, Any], rates: dict[str, Any] | None
                  ) -> tuple[str, dict[str, str] | None]:
    """149: a forint bank line against an invoice of another currency, at the MNB rate of each `bank_rate_days` day in
    turn, each with its band (`fx_bank_tolerance`): the first within makes `fx_within`, otherwise the
    nearest is `fx_outside`; `no_rate` without any rate. The conversion names the day's kind (`basis`)."""
    currency, amount, paid = str(invoice.get("currency")), money(str(invoice["amount"])), money(str(payment["amount"]))
    nearest: tuple[Decimal, dict[str, str]] | None = None
    for basis, day in bank_rate_days(invoice, payment):
        entry = (rates or {}).get(currency, {}).get(day.isoformat())
        if not entry:
            continue
        expected = amount * Decimal(str(entry["rate"]))
        deviation = paid / expected - 1
        conversion = {"rate": str(entry["rate"]), "rate_day": str(entry["rate_day"]), "source": str(entry.get("source") or "mnb"),
                      "basis": basis, "converted": str(expected.quantize(Decimal("0.01"))),
                      "deviation": str(deviation.quantize(Decimal("0.0001")))}
        below, above = fx_bank_tolerance(basis)
        if -below <= deviation <= above:
            return "fx_within", conversion
        if nearest is None or abs(deviation) < nearest[0]:
            nearest = (abs(deviation), conversion)
    return ("fx_outside", nearest[1]) if nearest else ("no_rate", None)


def convert_combined(invoices: list[dict[str, Any]], payment: dict[str, Any], rates: dict[str, Any] | None
                     ) -> tuple[str, dict[str, Any] | None]:
    """151: one forint bank line against two or more invoices of one other currency it pays together. Their sum is
    converted at the MNB rate of each `bank_rate_days` day in turn (each invoice at its own fulfilment day, all at the
    line's booking day), each with its band: the first within makes `fx_within`, otherwise the nearest is `fx_outside`;
    `no_rate` unless every invoice has a rate on some day. The conversion: the day's kind (`basis`), the converted sum,
    the line's deviation from it, and each invoice's own conversion (`parts`, in the order given)."""
    paid = money(str(payment["amount"]))
    nearest: tuple[Decimal, dict[str, Any]] | None = None
    for basis in reconcile_rules._conf()["fx"]["bank"]["rate_days"]:
        parts = []
        for inv in invoices:
            day = dict(bank_rate_days(inv, payment)).get(basis)
            entry = (rates or {}).get(str(inv.get("currency")), {}).get(day.isoformat()) if day else None
            if not entry:
                break
            converted = money(str(inv["amount"])) * Decimal(str(entry["rate"]))
            parts.append({"rate": str(entry["rate"]), "rate_day": str(entry["rate_day"]), "source": str(entry.get("source") or "mnb"),
                          "basis": basis, "converted": str(converted.quantize(Decimal("0.01")))})
        if len(parts) < len(invoices):
            continue
        total = sum((money(p["converted"]) for p in parts), Decimal(0))
        deviation = paid / total - 1
        conversion = {"basis": basis, "converted": str(total.quantize(Decimal("0.01"))),
                      "deviation": str(deviation.quantize(Decimal("0.0001"))), "parts": parts}
        below, above = fx_bank_tolerance(basis)
        if -below <= deviation <= above:
            return "fx_within", conversion
        if nearest is None or abs(deviation) < nearest[0]:
            nearest = (abs(deviation), conversion)
    return ("fx_outside", nearest[1]) if nearest else ("no_rate", None)


def split_line(amount: Decimal, conversion: dict[str, Any]) -> list[Decimal]:
    """151: a line's amount shared among the invoices of a combined conversion in the ratio of their converted amounts,
    to two decimals; the rounding goes to the last, so the shares add up to the amount exactly."""
    weights = [money(p["converted"]) for p in conversion["parts"]]
    total = sum(weights, Decimal(0))
    shares = [(amount * w / total).quantize(Decimal("0.01")) for w in weights[:-1]]
    return [*shares, amount - sum(shares, Decimal(0))]


def amount_relation(invoice: dict[str, Any], payment: dict[str, Any], rates: dict[str, Any] | None = None
                    ) -> tuple[str | None, dict[str, str] | None]:
    """How a line's amount relates to an invoice's: `equal` / `different` in one currency or on a card purchase's
    original amount (137), the conversion for a card line of another currency (`convert`), None when the amounts cannot
    be compared."""
    try:
        how = meets(invoice, payment)
        if how == "same":
            return ("equal" if money(str(payment.get("amount"))) == money(str(invoice.get("amount"))) else "different"), None
        if how == "original":  # 137: the card purchase's original amount, exactly
            orig = original(payment)
            return ("equal" if orig is not None and orig[1] == money(str(invoice.get("amount"))) else "different"), None
        if how in ("fx", "fx_bank"):
            return convert(invoice, payment, rates)
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return None, None
    return None, None
