"""Readers for the values the store keeps as text: a day, an amount, JSON lines (204, R1d).

Plain-language summary: dates are stored as ISO text ("2026-04-01", sometimes with a time after it) and amounts as
plain decimal text ("1234.50"). Eight modules had their own copy of the day reader, and three amount readers outside
the reconciliation still took "NaN", "Infinity" or an exponent, the error the 153 review closed there. One reader each
now; a module that needs a domain error wraps `iso_day` in its own.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import re
from typing import Any

_PLAIN_DECIMAL = re.compile(r"-?\d+(?:\.\d+)?")


def stored_day(value: Any) -> date | None:
    """The day of a stored ISO date or date-time ("2026-04-01", "2026-04-01T10:15"); None when empty or not a day."""
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def iso_day(value: Any) -> date:
    """The day of a stored ISO date or date-time; a missing or malformed one raises `ValueError`."""
    if not value:
        raise ValueError("an ISO date is required")
    return date.fromisoformat(str(value)[:10])


def stored_decimal(value: Any) -> Decimal | None:
    """153 (review A6): a stored amount as a finite Decimal. Text must be a plain decimal ("1234.50", "-12.5", any
    number of decimals); a number must be finite. None for anything else: "NaN", "Infinity", "1E+3", "12,5", empty, a
    truth value."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value)) if isinstance(value, float) else Decimal(value)
        return number if number.is_finite() else None
    text = str(value)
    return Decimal(text) if _PLAIN_DECIMAL.fullmatch(text) else None


def json_lines(path: Path | str) -> list[dict[str, Any]]:
    """The records of a JSON-lines file (UTF-8); blank lines are skipped."""
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


__all__ = ["iso_day", "json_lines", "stored_day", "stored_decimal"]
