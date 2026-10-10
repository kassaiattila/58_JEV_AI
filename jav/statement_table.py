"""136 (backlog F-revolut-csv, E4): a bank's tabular statement export read by code, without AI.

The owner's decisions: a general tabular statement reader, not code for one bank (DECISIONS 132; the company card's
export comes later); processed as a work package with one statement per account, and only the accounts a person
chooses go into the store (DECISIONS 132, 136). The 2026 Revolut consolidated statement, an Excel workbook, holds the
summaries of every account first and then one transaction table per account; nothing in it needs a model.

A profile (`configs/statement_tables.json`) describes a kind of export as data:

- `columns`: the header aliases of each role (date, description, category, amount, balance); a row holding the aliases
  of every `required` role is a table header. A repeated header (an amount in the account's currency, then converted)
  takes its first column;
- `account_title`: a pattern for the row naming an account and its currency code in brackets; the summary block and
  the transaction table of an account follow such a row. Two accounts may share a title, so the n-th summary of a
  title belongs to its n-th table;
- `summary`: the labels of the account number and of the opening and closing balances, each followed by its value;
- `total_row`: the first cell of the row that totals a table and ends it;
- `period_from_filename`: the statement period, when only the file name states it; otherwise the first and the last
  booking date.

Reading takes the rows of cell texts of a workbook's first sheet (read only, values) or of a CSV file, within the
limits of the configuration. Three repairs an export may need, each recorded in `Reading.repairs`:

- `csv_in_first_columns`: a CSV export opened as a workbook keeps each record in its first one or two cells, so such
  rows are joined and split as CSV again;
- `mojibake`: UTF-8 text decoded as cp1250 is turned back, only when every text of the file survives the round trip
  (a byte cp1250 leaves undefined comes through as its own code point and goes back as that byte);
- `html_entities`: an entity left in a text (an ampersand written as `&amp;`) is unescaped.

The statement of an account has the fields of the bank statement type packs (`configs/types/statement_cib.json`):
statement type, account number, currency, period, opening and closing balance, debit and credit totals and the
transactions (booking date, direction, a positive amount, the running balance, the counterparty's name as printed in
the description column, and the category as the description). Without a summary, the opening balance is the first
line's balance less its amount and the closing balance the last line's. Code checks the running balance line by line,
the total row against the lines and the opening balance plus the lines against the closing balance (`Account.checks`);
a line whose date or amount cannot be read is left out and reported (`Account.problems`).
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav import cfg
from jav.dates import read_date
from jav.numbers import read_number

CONFIG = "statement_tables"
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


@dataclass(frozen=True)
class Reading:
    profile: str
    institution: str
    file_name: str
    sha256: str
    repairs: list[str]
    accounts: list[Account]


def _conf() -> dict[str, Any]:
    return cfg.load(CONFIG)


def config_hash() -> str:
    return cfg.config_hash(CONFIG)


# --- rows of cell texts ------------------------------------------------------------------------------------------------


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _workbook_rows(data: bytes, limits: dict[str, Any]) -> list[list[str]]:
    import openpyxl

    from jav.readers.contracts import ReadLimits
    from jav.readers.limits import DEFAULT_LIMITS, ReadFailure, inspect_package

    archive = limits["archive"]
    try:  # the shared ZIP inspection: no unsafe member, no expansion beyond the bounds, external parts inert
        inspect_package(data, ReadLimits(**{**DEFAULT_LIMITS.model_dump(), **archive, "input_bytes": limits["max_bytes"],
                                            "visited_cells": limits["max_cells"]}))
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (ReadFailure, OSError, KeyError, ValueError) as exc:
        raise StatementTableError(f"the workbook cannot be read: {exc}") from exc
    try:
        rows, cells = [], 0
        for row in wb.worksheets[0].iter_rows(values_only=True):
            texts = [_text(v) for v in row]
            while texts and not texts[-1]:
                texts.pop()
            cells += len(texts)
            if len(rows) >= limits["max_rows"] or cells > limits["max_cells"]:
                raise StatementTableError("the workbook is over the row limit or the cell limit")
            rows.append(texts)
        return rows
    finally:
        wb.close()


def _csv_rows(data: bytes) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1250")
        except UnicodeDecodeError as exc:
            raise StatementTableError("the CSV file is neither UTF-8 nor cp1250 text") from exc
    first = text.split("\n", 1)[0]
    delimiter = ";" if first.count(";") > first.count(",") else ","
    return [[_text(v) for v in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _joined_csv(rows: list[list[str]], conf: dict[str, Any]) -> list[list[str]] | None:
    """The records of a CSV export opened as a workbook: most rows fill at most `max_filled_cells` cells and hold a
    comma; each row's filled cells are joined with a comma and split as CSV again."""
    filled = [[c for c in r if c] for r in rows]
    content = [f for f in filled if f]
    narrow = [f for f in content if len(f) <= conf["max_filled_cells"]]
    if not content or len(narrow) < conf["min_share"] * len(content) or not any("," in f[0] for f in content):
        return None
    return [next(csv.reader(io.StringIO(",".join(f))), []) if f else [] for f in filled]


def _to_bytes(text: str, encoding: str) -> bytes:
    out = bytearray()
    for ch in text:
        try:
            out += ch.encode(encoding)
        except UnicodeEncodeError:
            if ord(ch) > 0xFF:
                raise
            out.append(ord(ch))  # a byte the encoding leaves undefined came through as its own code point
    return bytes(out)


def _unmangled(rows: list[list[str]], conf: dict[str, Any]) -> list[list[str]] | None:
    """UTF-8 read as `read_as`, turned back when a marker shows it and every text survives the round trip."""
    if not any(m in c for r in rows for c in r for m in conf["markers"]):
        return None
    try:
        return [[_to_bytes(c, conf["read_as"]).decode("utf-8") if not c.isascii() else c for c in r] for r in rows]
    except (UnicodeEncodeError, UnicodeDecodeError):
        return None


def _rows(path: Path, data: bytes, conf: dict[str, Any]) -> tuple[list[list[str]], list[str]]:
    limits, repairs = conf["limits"], []
    if len(data) > limits["max_bytes"]:
        raise StatementTableError("the file is over the size limit")
    if path.suffix.lower() == ".csv":
        rows = _csv_rows(data)
        if len(rows) > limits["max_rows"]:
            raise StatementTableError("the file is over the row limit")
    else:
        rows = _workbook_rows(data, limits)
    if (fixed := _unmangled(rows, conf["repairs"]["mojibake"])) is not None:
        rows, repairs = fixed, [*repairs, "mojibake"]
    if path.suffix.lower() != ".csv" and (joined := _joined_csv(rows, conf["repairs"]["csv_in_first_columns"])) is not None:
        rows, repairs = joined, [*repairs, "csv_in_first_columns"]
    if any("&" in c and html.unescape(c) != c for r in rows for c in r):
        rows, repairs = [[html.unescape(c) for c in r] for r in rows], [*repairs, "html_entities"]
    return rows, repairs


# --- sections ------------------------------------------------------------------------------------------------------------


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


def _value_after(row: list[str], aliases: list[str]) -> str | None:
    wanted = {_norm(a) for a in aliases}
    for i, c in enumerate(row):
        if _norm(c) in wanted:
            return next((v for v in row[i + 1:] if v), None)
    return None


@dataclass
class _Block:
    title: str  # as printed, with the currency
    name: str
    currency: str
    summary: dict[str, str] = field(default_factory=dict)
    columns: dict[str, int] | None = None
    lines: list[list[str]] = field(default_factory=list)
    total: list[str] | None = None


def _blocks(rows: list[list[str]], profile: dict[str, Any]) -> list[_Block]:
    title_re = re.compile(profile["account_title"])
    totals = {_norm(t) for t in profile["total_row"]}
    blocks: list[_Block] = []
    in_table = False
    for row in rows:
        filled = [c for c in row if c]
        if not filled:
            continue
        if len(filled) == 1:
            in_table = False
            if m := title_re.match(filled[0]):
                blocks.append(_Block(title=filled[0], name=m["name"].strip(), currency=m["currency"]))
            continue
        if not blocks:
            continue
        block = blocks[-1]
        if block.columns is None and (columns := _header(row, profile)) is not None:
            block.columns, in_table = columns, True
            continue
        if in_table:
            if _norm(row[0]) in totals:
                block.total, in_table = row, False
            else:
                block.lines.append(row)
            continue
        for key, aliases in profile["summary"].items():
            if key not in block.summary and (value := _value_after(row, aliases)) is not None:
                block.summary[key] = value
    return blocks


# --- the statement of an account ---------------------------------------------------------------------------------------


def _money(text: str | None) -> Decimal | None:
    if not text:
        return None
    read = read_number(text)
    return None if read.value is None or read.ambiguous else Decimal(read.value).quantize(CENT)


def _cell(row: list[str], columns: dict[str, int], role: str) -> str:
    i = columns.get(role)
    return row[i] if i is not None and i < len(row) else ""


def _plain(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _period(file_name: str, profile: dict[str, Any], dates: list[str]) -> tuple[str | None, str | None]:
    pattern = profile.get("period_from_filename")
    if pattern and (m := re.search(pattern, file_name)):
        return m["start"], m["end"]
    return (min(dates), max(dates)) if dates else (None, None)


def _account(block: _Block, summary: dict[str, str], occurrence: int, file_name: str, profile: dict[str, Any]) -> Account:
    columns = block.columns or {}
    lines, amounts, balances, problems = [], [], [], []
    for n, row in enumerate(block.lines, start=1):
        booked = read_date(_cell(row, columns, "date"))
        amount, balance = _money(_cell(row, columns, "amount")), _money(_cell(row, columns, "balance"))
        if booked.value is None or booked.ambiguous:
            problems.append(f"line {n}: unreadable date")
            continue
        if amount is None:
            problems.append(f"line {n}: unreadable amount")
            continue
        amounts.append(amount)
        balances.append(balance)
        lines.append({"booking_date": booked.value.isoformat(), "value_date": None,
                      "direction": "debit" if amount < 0 else "credit", "amount": _plain(abs(amount)),
                      "running_balance": _plain(balance), "description": _cell(row, columns, "category") or None,
                      "counterparty_name": _cell(row, columns, "description") or None, "counterparty_account": None, "memo": None})
    iban = (summary.get("account_iban") or "").replace(" ", "") or None
    opening, closing = _money(summary.get("opening_balance")), _money(summary.get("closing_balance"))
    if opening is None and balances and balances[0] is not None:
        opening = balances[0] - amounts[0]
    if closing is None and balances and balances[-1] is not None:
        closing = balances[-1]
    start, end = _period(file_name, profile, [t["booking_date"] for t in lines])
    statement = {"statement_type": profile["statement_type"], "account_no": None, "account_iban": iban,
                 "period_start": start, "period_end": end, "currency": block.currency,
                 "opening_balance": _plain(opening), "closing_balance": _plain(closing),
                 "total_debit": _plain(sum((-a for a in amounts if a < 0), Decimal(0))),
                 "total_credit": _plain(sum((a for a in amounts if a > 0), Decimal(0))), "transactions": lines}
    running, previous = 0, opening
    for amount, balance in zip(amounts, balances):
        running += previous is not None and balance is not None and previous + amount == balance
        previous = balance
    total = _money(_cell(block.total, columns, "amount")) if block.total else None
    checks = {"running_balance": {"ok": running, "lines": len(lines)},
              "total_row": None if block.total is None else total == sum(amounts, Decimal(0)),
              "closing_balance": None if opening is None or closing is None else opening + sum(amounts, Decimal(0)) == closing}
    key = f"{iban}:{block.currency}" if iban else f"{block.title}#{occurrence}"
    return Account(key=key, title=block.name, currency=block.currency, occurrence=occurrence, statement=statement,
                   checks=checks, problems=problems)


def _accounts(blocks: list[_Block], file_name: str, profile: dict[str, Any]) -> list[Account]:
    summaries: dict[str, list[dict[str, str]]] = {}
    for b in blocks:
        if b.columns is None:
            summaries.setdefault(b.title, []).append(b.summary)
    seen: dict[str, int] = {}
    out = []
    for b in blocks:
        if b.columns is None:
            continue
        n = seen[b.title] = seen.get(b.title, 0) + 1
        own = summaries.get(b.title, [])
        summary = b.summary or (own[n - 1] if n <= len(own) else {})
        out.append(_account(b, summary, n, file_name, profile))
    return out


def read(path: Path, *, name: str | None = None) -> Reading:
    """Reads a statement table with the first profile that finds a table in it. `name`: the file name to take the
    period from, when the path is a copy (the source instance) of the original."""
    path = Path(path)
    data = path.read_bytes()
    conf = _conf()
    rows, repairs = _rows(path, data, conf)
    file_name = name or path.name
    for profile in conf["profiles"]:
        accounts = _accounts(_blocks(rows, profile), file_name, profile)
        if accounts:
            return Reading(profile=profile["name"], institution=profile["institution"], file_name=file_name,
                           sha256=hashlib.sha256(data).hexdigest(), repairs=repairs, accounts=accounts)
    raise StatementTableError("no statement table of a known profile in the file")


def checks_ok(account: Account) -> bool:
    c = account.checks
    return (c["running_balance"]["ok"] == c["running_balance"]["lines"] and c["total_row"] is not False
            and c["closing_balance"] is not False and not account.problems)


def survey(reading: Reading) -> dict[str, Any]:
    """The accounts found, without their lines and balances: what a person chooses from (the account number only by
    its last four characters)."""
    out = []
    for a in reading.accounts:
        dates = [t["booking_date"] for t in a.statement["transactions"]]
        iban = a.statement["account_iban"]
        out.append({"key": a.key, "account": "…" + iban[-4:] if iban else None, "title": a.title, "occurrence": a.occurrence,
                    "currency": a.currency, "lines": len(dates), "first": min(dates) if dates else None,
                    "last": max(dates) if dates else None, "period_start": a.statement["period_start"],
                    "period_end": a.statement["period_end"], "checks_ok": checks_ok(a), "problems": len(a.problems)})
    return {"profile": reading.profile, "institution": reading.institution, "file": reading.file_name,
            "repairs": reading.repairs, "accounts": out}
