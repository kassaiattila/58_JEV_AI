"""231 (plan stage C, C3g): what every statement reader shares, split out of `statement_table.py`.

Plain-language summary: the reading's records (an account's statement, `Account`, and a file's or a folder's reading,
`Reading`) and its error; the configuration (`configs/statement_tables.json`); the money readers (cents, a printed
amount in the bank's form); a table's header row; and the parts of a line the readers fill alike (the bounded text
lines of a PDF statement, its time and card details). The rules they follow are described in `statement_table.py`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.core import card_numbers, cfg
from jav.core.dates import read_date
from jav.core.numbers import read_number

CONFIG = "statement_tables"


SUFFIXES = (".xlsx", ".csv", ".xml")


TEXT_SUFFIXES = (".pdf", ".txt")  # 141: a statement printed as text


CENT = Decimal("0.01")


class StatementTableError(ValueError):
    """The file cannot be read as a statement table: over the limits, unreadable, or no profile knows it."""


@dataclass(frozen=True)
class Account:
    key: str  # the account number without spaces and the currency (one number may hold several currencies), or the
    #           printed title with its occurrence when no number is printed
    title: str  # the account's name without its currency
    currency: str
    occurrence: int  # the n-th account of the same printed title
    statement: dict[str, Any]
    checks: dict[str, Any]
    problems: list[str] = field(default_factory=list)
    source: dict[str, Any] | None = None  # 137: the export file (and its companion) this account was read from
    balances: str = "export"  # 137: where the balances come from: export (141: or the text statement itself) |
    #                           companion | none (cannot be checked) | 174 (review 160 M-12): lines (taken from the
    #                           lines themselves, with no total row: the first and last lines cannot be checked)
    companion_problems: list[str] = field(default_factory=list)  # 137: lines on one side only, another account
    stored_key: str | None = None  # 174 (review 160 M-7): the key written into the statement file (so into its id) when


@dataclass(frozen=True)
class Reading:
    profile: str
    institution: str
    file_name: str
    sha256: str
    repairs: list[str]
    accounts: list[Account]
    skipped: list[dict[str, str]] = field(default_factory=list)  # 137: the files of a folder no profile reads


def _conf() -> dict[str, Any]:
    return cfg.load(CONFIG)


def config_hash() -> str:
    return cfg.config_hash(CONFIG)


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _header(row: list[str], profile: dict[str, Any]) -> dict[str, int] | None:
    """The column of each role (its first occurrence) when the row holds every required role's alias."""
    cells = [_norm(c) for c in row]
    found: dict[str, int] = {}
    for role, aliases in profile["columns"].items():
        wanted = {_norm(a) for a in aliases}
        index = next((i for i, c in enumerate(cells) if c in wanted), None)
        if index is not None:
            found[role] = index
    return found if all(r in found for r in profile["required"]) else None


def _cents(value: Decimal) -> Decimal | None:
    """153 (review A6): an amount in cents, only when no non-zero digit stands beyond them ("10.000" is 10.00); "10.005"
    is None, so the line is unreadable and said so, instead of rounded without a word."""
    return value.quantize(CENT) if value == value.quantize(CENT) else None


def _money(text: str | None) -> Decimal | None:
    if not text:
        return None
    read = read_number(text)
    return None if read.value is None or read.ambiguous else _cents(Decimal(read.value))


def _cell(row: list[str], columns: dict[str, int], role: str) -> str:
    i = columns.get(role)
    return row[i] if i is not None and i < len(row) else ""


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


# 153 (review C1): what a statement's patterns read stays short. A crafted file with a 20,000-digit amount or a line of
# thousands of spaces kept the service busy for minutes (the patterns backtrack, and the reading after the isolated
# helper's parse runs in the service): a field or a line over LINE_MAX characters is cut or left out, and a run of three
# or more spaces becomes two (the text profiles separate their columns by two or more).
LINE_MAX = 2000


_SPACE_RUN = re.compile(r"[ \t]{3,}")


def _bounded(lines: list[str]) -> tuple[list[str], list[str]]:
    """The lines with their space runs shortened, then any line still over LINE_MAX characters left out, and the
    repairs that say how many were left out."""
    out, cut = [], 0
    for ln in lines:
        ln = _SPACE_RUN.sub("  ", ln)
        if len(ln) > LINE_MAX:
            cut += 1
            continue
        out.append(ln)
    return out, ([f"{cut} line(s) over {LINE_MAX} characters left out"] if cut else [])


def _within_size(path: Path, limits: dict[str, Any]) -> None:
    """153 (review C3): the size limit is checked before a file is read (a 1 GB file raised the service's memory to
    1.27 GB before it was refused)."""
    if path.stat().st_size > limits["max_bytes"]:
        raise StatementTableError("the file is over the size limit")


def _pdf_lines(path: Path) -> list[str]:
    """The PDF's text layer as lines (the isolated PDF reader, jav/documents/pdf.py); the tests replace it."""
    from jav.documents import pdf

    return pdf.read_pdf(path).lines


def _hu_amount(text: str) -> Decimal | None:
    read = read_number(text)
    return None if read.value is None or read.ambiguous else _cents(Decimal(read.value))


def _dot_amount(text: str) -> Decimal | None:
    """An amount with a decimal point and optional thousands commas ("1,234.56", "20.00")."""
    plain = text.replace(",", "")
    return _cents(Decimal(plain)) if re.fullmatch(r"\d+(?:\.\d+)?", plain) else None


def _without_page_breaks(lines: list[str], blocks: list[list[str]]) -> list[str]:
    """The lines without the repeated page footer and header: from a block's first pattern to its last, inclusive."""
    out: list[str] = []
    skipping: str | None = None
    for line in lines:
        if skipping is None:
            skipping = next((end for start, end in blocks if re.search(start, line)), None)
            if skipping is None:
                out.append(line)
        elif re.search(skipping, line):
            skipping = None
    return out


LINE_DETAILS = ("bank_reference", "order_id", "end_to_end_id", "card_number", "purchase_date", "transaction_time", "terminal",
                "authorisation_code", "exchange_rate", "fee")  # 144: the line's facts beyond the money (type pack 1.2.0)


def _with(line: dict[str, Any], **values: str | None) -> None:
    """144: the line's details that have a value (a line keeps no empty detail keys)."""
    line.update({k: v for k, v in values.items() if k in LINE_DETAILS and v not in (None, "")})


def _clock(text: str | None) -> str | None:
    """A time of day as HH:MM or HH:MM:SS ("10:00", "101500" → "10:15:00", "2026-06-04T10:15:30" → "10:15:30")."""
    if not text:
        return None
    m = re.search(r"(?:T|^)(\d{1,2}):?(\d{2})(?::?(\d{2}))?(?:\.\d+)?(?:[+-]\d{2}:?\d{2}|Z)?$", text.strip())
    if m is None or int(m[1]) > 23 or int(m[2]) > 59 or (m[3] and int(m[3]) > 59):
        return None
    return f"{int(m[1]):02d}:{m[2]}" + (f":{m[3]}" if m[3] else "")


def _card_details(found: dict[str, dict[str, str]]) -> dict[str, str | None]:
    """144: a line's card and charge details from the matches of a profile's `details` patterns (the camt.053 entry's
    additional information, the Erste PDF statement's card block): the masked card number, the purchase day and time,
    the terminal and the authorisation code, the exchange rate and the fee as the bank prints them."""
    card, terminal = found.get("card") or {}, found.get("terminal") or {}
    day = read_date(card["date"]).value if card.get("date") else None
    return {"card_number": card_numbers.masked(card.get("card")), "purchase_date": day.isoformat() if day else None,
            "transaction_time": _clock(card.get("time")), "terminal": terminal.get("terminal"),
            "authorisation_code": terminal.get("auth"),
            "exchange_rate": " ".join(found["rate"]["rate"].split()) if (found.get("rate") or {}).get("rate") else None,
            "fee": " ".join(found["fee"]["fee"].split()) if (found.get("fee") or {}).get("fee") else None}
