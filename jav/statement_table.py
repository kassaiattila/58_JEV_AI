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

137 (DECISIONS 137, "XML + PDF by code"): a **ledger** profile (`layout: ledger`) reads an export that lists every line
with its own account and statement number, such as the Erste Excel 2003 XML export (SpreadsheetML, read with
defusedxml): one statement per account and statement number, the period from the file name's month. Such an export has
no balance, and a card line names no merchant, so the profile's **companion** is the same month's PDF statement, found
by its name next to the export or in a `pdf` subfolder. Its text layer (the isolated PDF reader) is read with the
profile's patterns: the period, the account, the opening and closing balances and every line with its running balance,
the merchant and a foreign purchase's original amount and currency. The export's lines are matched to the PDF's by
booking date and amount, in order; the export stays the list of lines, the PDF adds the balances and the details, and a
line on one side only is a finding (`Account.companion_problems`). Without a PDF the balances cannot be checked
(`Account.balances` is `none`). A folder is read as a whole: every export in it, each with its own source and
companion, and the files no profile knows are listed (`Reading.skipped`).
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import html
import io
import json
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav import cfg
from jav.dates import read_date
from jav.numbers import read_number

CONFIG = "statement_tables"
SUFFIXES = (".xlsx", ".csv", ".xml")
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
    balances: str = "export"  # 137: where the balances come from: export | companion | none (cannot be checked)
    companion_problems: list[str] = field(default_factory=list)  # 137: lines on one side only, another account


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


_SS = "{urn:schemas-microsoft-com:office:spreadsheet}"


def _spreadsheetml_rows(data: bytes, limits: dict[str, Any]) -> list[list[str]]:
    """137: the first sheet of an Excel 2003 XML workbook (SpreadsheetML). defusedxml refuses a document type
    declaration, entities and external references; a cell's `ss:Index` skips the empty cells before it; a date-time
    keeps its date."""
    from defusedxml import ElementTree

    try:
        root = ElementTree.fromstring(data)
    except Exception as exc:  # defusedxml raises its own and ElementTree's errors (as in jav/fx.py)
        raise StatementTableError(f"the XML workbook cannot be read: {type(exc).__name__}") from exc
    sheet = root.find(_SS + "Worksheet") if root.tag == _SS + "Workbook" else None
    table = sheet.find(_SS + "Table") if sheet is not None else None
    if table is None:
        raise StatementTableError("not an Excel 2003 XML workbook with a table")
    rows, cells = [], 0
    for row in table.iter(_SS + "Row"):
        texts: list[str] = []
        for cell in row.findall(_SS + "Cell"):
            if (index := cell.get(_SS + "Index")) and index.isdigit():
                texts += [""] * max(0, int(index) - 1 - len(texts))
            data_el = cell.find(_SS + "Data")
            value = _text(data_el.text) if data_el is not None else ""
            if data_el is not None and data_el.get(_SS + "Type") == "DateTime":
                value = value[:10]
            texts.append(value)
        while texts and not texts[-1]:
            texts.pop()
        cells += len(texts)
        if len(rows) >= limits["max_rows"] or cells > limits["max_cells"]:
            raise StatementTableError("the workbook is over the row limit or the cell limit")
        rows.append(texts)
    return rows


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
    elif path.suffix.lower() == ".xml":
        rows = _spreadsheetml_rows(data, limits)
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


# --- 137: a ledger export (a line per row, with its account and statement number) and its PDF companion ----------------


def _ledger_amount(text: str, profile: dict[str, Any]) -> Decimal | None:
    """A machine number ("-7291.00") when the profile says so, otherwise the shared number reader."""
    if profile.get("amounts") == "machine":
        return Decimal(text).quantize(CENT) if re.fullmatch(r"-?\d+(?:\.\d+)?", text) else None
    return _money(text)


def _ledgers(rows: list[list[str]], profile: dict[str, Any]
             ) -> tuple[dict[str, int] | None, dict[tuple[str, str], list[list[str]]]]:
    """The header's columns and the rows after it, grouped by account and statement number, in order."""
    columns: dict[str, int] | None = None
    groups: dict[tuple[str, str], list[list[str]]] = {}
    for row in rows:
        if not any(row):
            continue
        if columns is None:
            columns = _header(row, profile)
            continue
        groups.setdefault((_cell(row, columns, "account"), _cell(row, columns, "statement")), []).append(row)
    return columns, groups


def _pdf_lines(path: Path) -> list[str]:
    """The PDF's text layer as lines (the isolated PDF reader, jav/pdf.py); the tests replace it."""
    from jav import pdf

    return pdf.read_pdf(path).lines


def _hu_amount(text: str) -> Decimal | None:
    read = read_number(text)
    return None if read.value is None or read.ambiguous else Decimal(read.value).quantize(CENT)


def _dot_amount(text: str) -> Decimal | None:
    """An amount with a decimal point and optional thousands commas ("1,234.56", "20.00")."""
    plain = text.replace(",", "")
    return Decimal(plain).quantize(CENT) if re.fullmatch(r"\d+(?:\.\d+)?", plain) else None


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


def parse_companion(lines: list[str], conf: dict[str, Any]) -> dict[str, Any]:
    """The PDF statement's period, account, currency, balances and lines (each with its details), from its text lines
    and the profile's patterns (`companion`). Pure: no file is read."""
    lines = _without_page_breaks(lines, conf.get("skip_blocks", []))
    text = "\n".join(lines)

    def first(key: str) -> re.Match[str] | None:
        return re.search(conf[key], text, re.MULTILINE) if conf.get(key) else None

    period, opening, closing = first("period"), first("opening"), first("closing")
    line_re, start_re, end_re = re.compile(conf["line"]), re.compile(conf["lines_start"]), re.compile(conf["lines_end"])
    details = {k: re.compile(v) for k, v in conf.get("details", {}).items()}
    started = False
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    for line in lines:
        if not started:
            started = bool(start_re.search(line))
            continue
        if end_re.search(line):
            break
        if m := line_re.match(line):
            booked, amount, balance = read_date(m["booked"]), _hu_amount(m["amount"]), _hu_amount(m["balance"])
            if booked.value is None or amount is None or balance is None:
                problems.append(f"PDF line {len(out) + 1}: unreadable")
            out.append({"booked": booked.value.isoformat() if booked.value else None, "kind": m["kind"].strip(),
                        "amount": amount, "balance": balance, "details": {}})
            continue
        if out:
            for key, rx in details.items():
                if key not in out[-1]["details"] and (d := rx.search(line)):
                    out[-1]["details"][key] = {k: v.strip() for k, v in d.groupdict().items() if v}
    start = read_date(period["start"]).value if period else None
    end = read_date(period["end"]).value if period else None
    account, currency = first("account"), first("currency")
    return {"period": (start.isoformat() if start else None, end.isoformat() if end else None),
            "account": account["value"] if account else None, "currency": currency["value"] if currency else None,
            "opening": _hu_amount(opening["value"]) if opening else None,
            "closing": _hu_amount(closing["value"]) if closing else None, "lines": out, "problems": problems}


def _companion_path(path: Path, conf: dict[str, Any] | None) -> Path | None:
    if not conf or not (m := re.match(conf["name_from"], path.name)):
        return None
    name = conf["name"].format(**m.groupdict())
    return next((p for folder in conf.get("folders", ["."]) if (p := path.parent / folder / name).is_file()), None)


def _month(file_name: str, pattern: str | None) -> tuple[str | None, str | None]:
    """The calendar month the file name names (`year`, `month`), as a period."""
    if not pattern or not (m := re.search(pattern, file_name)):
        return None, None
    year, month = int(m["year"]), int(m["month"])
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"


def _ledger_lines(rows: list[list[str]], columns: dict[str, int], profile: dict[str, Any]
                  ) -> tuple[list[dict[str, Any]], list[Decimal], list[str]]:
    placeholders = {_norm(x) for x in profile.get("placeholder_counterparty", [])}
    lines, amounts, problems = [], [], []
    for n, row in enumerate(rows, start=1):
        booked = read_date(_cell(row, columns, "date"))
        valued = read_date(_cell(row, columns, "value_date"))
        amount = _ledger_amount(_cell(row, columns, "amount"), profile)
        if booked.value is None or booked.ambiguous:
            problems.append(f"line {n}: unreadable date")
            continue
        if amount is None:
            problems.append(f"line {n}: unreadable amount")
            continue
        party = _cell(row, columns, "counterparty")
        amounts.append(amount)
        lines.append({"booking_date": booked.value.isoformat(),
                      "value_date": valued.value.isoformat() if valued.value and not valued.ambiguous else None,
                      "direction": "debit" if amount < 0 else "credit", "amount": _plain(abs(amount)),
                      "running_balance": None, "description": _cell(row, columns, "kind") or None,
                      "counterparty_name": None if _norm(party) in placeholders else party or None,
                      "counterparty_account": _cell(row, columns, "counterparty_account") or None,
                      "memo": _cell(row, columns, "memo") or None, "original_amount": None, "original_currency": None})
    return lines, amounts, problems


def _merge_companion(lines: list[dict[str, Any]], amounts: list[Decimal], pdf: dict[str, Any], currency: str
                     ) -> tuple[list[Decimal | None], list[str]]:
    """Each export line takes the first unused PDF line of its booking date and amount: its running balance, the
    merchant of a card line without a partner and a foreign purchase's original amount and currency."""
    used: set[int] = set()
    balances: list[Decimal | None] = []
    problems: list[str] = []
    for n, (line, amount) in enumerate(zip(lines, amounts), start=1):
        j = next((k for k, c in enumerate(pdf["lines"]) if k not in used and c["booked"] == line["booking_date"]
                  and c["amount"] == amount), None)
        if j is None:
            balances.append(None)
            problems.append(f"line {n}: not on the PDF statement")
            continue
        used.add(j)
        c = pdf["lines"][j]
        balances.append(c["balance"])
        line["running_balance"] = _plain(c["balance"])
        if not line["counterparty_name"] and (merchant := c["details"].get("merchant")):
            line["counterparty_name"] = merchant.get("value")
        original = c["details"].get("original") or {}
        value = _dot_amount(original.get("amount", ""))
        if original.get("currency") and original["currency"] != currency and value is not None:
            line["original_amount"], line["original_currency"] = _plain(value), original["currency"]
    problems += [f"PDF line {k + 1}: not in the export" for k in range(len(pdf["lines"])) if k not in used]
    return balances, problems


def _ledger_account(account_no: str, number: str, rows: list[list[str]], columns: dict[str, int],
                    profile: dict[str, Any], path: Path, file_name: str, source: dict[str, Any]) -> Account:
    lines, amounts, problems = _ledger_lines(rows, columns, profile)
    currency = profile["currency"]
    start, end = _month(file_name, profile.get("period_month_from_filename"))
    companion_path = _companion_path(path, profile.get("companion"))
    opening = closing = None
    balances: list[Decimal | None] = [None] * len(lines)
    companion_problems: list[str] = []
    if companion_path is not None:
        data = companion_path.read_bytes()
        pdf = parse_companion(_pdf_lines(companion_path), profile["companion"])
        source = {**source, "companion": {"file": companion_path.name, "sha256": hashlib.sha256(data).hexdigest()}}
        if pdf["account"] and re.sub(r"\D", "", pdf["account"]) != re.sub(r"\D", "", account_no):
            companion_problems.append("the PDF statement is of another account")
        else:
            if pdf["currency"] and pdf["currency"] != currency:
                companion_problems.append(f"the PDF statement's currency is {pdf['currency']}")
            balances, merged = _merge_companion(lines, amounts, pdf, currency)
            companion_problems += pdf["problems"] + merged
            opening, closing = pdf["opening"], pdf["closing"]
            start, end = pdf["period"][0] or start, pdf["period"][1] or end
    if start is None and lines:
        start, end = min(t["booking_date"] for t in lines), max(t["booking_date"] for t in lines)
    statement = {"statement_type": profile["statement_type"], "account_no": account_no, "account_iban": None,
                 "period_start": start, "period_end": end, "currency": currency,
                 "opening_balance": _plain(opening), "closing_balance": _plain(closing),
                 "total_debit": _plain(sum((-a for a in amounts if a < 0), Decimal(0))),
                 "total_credit": _plain(sum((a for a in amounts if a > 0), Decimal(0))), "transactions": lines}
    checked = opening is not None and closing is not None
    running = None
    if checked:
        ok, previous = 0, opening
        for amount, balance in zip(amounts, balances):
            ok += previous is not None and balance is not None and previous + amount == balance
            previous = balance
        running = {"ok": ok, "lines": len(lines)}
    checks = {"running_balance": running, "total_row": None,
              "closing_balance": opening + sum(amounts, Decimal(0)) == closing if checked else None}
    digits = re.sub(r"\D", "", account_no)
    return Account(key=f"{digits}:{currency}:{start}", title=f"…{digits[-4:]} {number}".strip(), currency=currency,
                   occurrence=1, statement=statement, checks=checks, problems=problems, source=source,
                   balances="companion" if checked else "none", companion_problems=companion_problems)


def _ledger_accounts(rows: list[list[str]], profile: dict[str, Any], path: Path, file_name: str,
                     source: dict[str, Any]) -> list[Account]:
    columns, groups = _ledgers(rows, profile)
    if columns is None:
        return []
    return [_ledger_account(account_no, number, group, columns, profile, path, file_name, source)
            for (account_no, number), group in groups.items() if account_no]


# --- reading a file or a folder ----------------------------------------------------------------------------------------


def _read_file(path: Path, *, name: str | None = None) -> Reading:
    if path.suffix.lower() not in SUFFIXES:
        raise StatementTableError(f"a statement table is a {' or '.join(SUFFIXES)} file")
    data = path.read_bytes()
    conf = _conf()
    rows, repairs = _rows(path, data, conf)
    file_name = name or path.name
    sha = hashlib.sha256(data).hexdigest()
    source = {"file": file_name, "sha256": sha, "repairs": repairs}
    for profile in conf["profiles"]:
        if profile.get("layout") == "ledger":
            accounts = _ledger_accounts(rows, profile, path, file_name, source)
        else:
            accounts = [replace(a, source=source) for a in _accounts(_blocks(rows, profile), file_name, profile)]
        if accounts:
            return Reading(profile=profile["name"], institution=profile["institution"], file_name=file_name,
                           sha256=sha, repairs=repairs, accounts=accounts)
    raise StatementTableError("no statement table of a known profile in the file")


def _read_folder(folder: Path) -> Reading:
    """137: every export directly in the folder; a file no profile reads is listed, and a statement read twice (the
    same statement in two files) keeps its first file."""
    limit = _conf()["limits"]["max_files"]
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES)
    if len(files) > limit:
        raise StatementTableError(f"the folder holds more than {limit} export files")
    readings, skipped = [], []
    for f in files:
        try:
            readings.append(_read_file(f))
        except StatementTableError as exc:  # listed for the person, not dropped
            skipped.append({"file": f.name, "reason": str(exc)})
    accounts: dict[str, Account] = {}
    for r in readings:
        for a in r.accounts:
            if a.key in accounts:
                skipped.append({"file": r.file_name, "reason": f"the statement {a.title} is already in another file"})
            else:
                accounts[a.key] = a
    if not accounts:
        raise StatementTableError("no statement export of a known profile in the folder")
    parts = sorted({f"{a.source['file']}:{a.source['sha256']}:{(a.source.get('companion') or {}).get('sha256', '')}"
                    for a in accounts.values() if a.source})
    return Reading(profile=",".join(dict.fromkeys(r.profile for r in readings)), institution=readings[0].institution,
                   file_name=folder.name, sha256=hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest(),
                   repairs=sorted({x for r in readings for x in r.repairs}), accounts=list(accounts.values()),
                   skipped=skipped)


def read(path: Path, *, name: str | None = None) -> Reading:
    """Reads a statement table with the first profile that finds a table in it; 137: or every export of a folder.
    `name`: the file name to take the period from, when the path is a copy (the source instance) of the original."""
    path = Path(path)
    return _read_folder(path) if path.is_dir() else _read_file(path, name=name)


def checks_ok(account: Account) -> bool:
    c = account.checks
    running = c["running_balance"]
    return (running is not None and running["ok"] == running["lines"] and c["total_row"] is not False
            and c["closing_balance"] is not False and not account.problems and not account.companion_problems)


def survey(reading: Reading) -> dict[str, Any]:
    """The accounts found, without their lines and balances: what a person chooses from (the account number only by
    its last four characters). 137: whether the balances could be checked, and the companion PDF's name."""
    out = []
    for a in reading.accounts:
        dates = [t["booking_date"] for t in a.statement["transactions"]]
        iban = a.statement["account_iban"]
        companion = (a.source or {}).get("companion")
        out.append({"key": a.key, "account": "…" + iban[-4:] if iban else None, "title": a.title, "occurrence": a.occurrence,
                    "currency": a.currency, "lines": len(dates), "first": min(dates) if dates else None,
                    "last": max(dates) if dates else None, "period_start": a.statement["period_start"],
                    "period_end": a.statement["period_end"], "checks_ok": checks_ok(a),
                    "problems": len(a.problems) + len(a.companion_problems),
                    "balance_checked": a.balances != "none", "companion": companion["file"] if companion else None})
    return {"profile": reading.profile, "institution": reading.institution, "file": reading.file_name,
            "repairs": reading.repairs, "accounts": out, "skipped": len(reading.skipped)}


# --- one file per chosen account ------------------------------------------------------------------------------------------

FORMAT = "jav.statement_table"
FORMAT_VERSION = 1
_UNSAFE = re.compile(r'[<>:"/\|?*\x00-\x1f]+')


def derived_dir() -> Path:
    """Where the accounts' statement files are written: next to the store in use (tests get their own folder)."""
    from jav import store

    return store.current_path().parent / "statement_tables"


def _file_name(reading: Reading, account: Account) -> str:
    s = account.statement
    name = f"{reading.institution} - {account.title} ({account.currency}) {s['period_start'] or ''}_{s['period_end'] or ''}"
    if account.occurrence > 1:
        name += f" {account.occurrence}"
    return _UNSAFE.sub("_", name).strip(" .") + ".json"


def derive(reading: Reading, keys: list[str], out_dir: Path | None = None) -> list[Path]:
    """Writes one statement file per chosen account (`keys`, as `Account.key`), the work package item of that
    account: the statement, the export's name and fingerprint, the account and the reader's findings. The content is
    canonical, so the same account of the same export always gives the same file and the same item. An unknown key is
    refused, so nothing is written for a wrong choice."""
    by_key = {a.key: a for a in reading.accounts}
    unknown = [k for k in keys if k not in by_key]
    if unknown or not keys:
        raise StatementTableError(f"choose at least one account of the file; unknown: {len(unknown)}")
    folder = (out_dir or derived_dir()) / reading.sha256[:16]
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for key in dict.fromkeys(keys):
        a = by_key[key]
        source = a.source or {"file": reading.file_name, "sha256": reading.sha256, "repairs": reading.repairs}
        content = {"format": FORMAT, "version": FORMAT_VERSION, "profile": reading.profile, "institution": reading.institution,
                   "source": {k: source[k] for k in ("file", "sha256", "repairs")},
                   "account": {"key": a.key, "title": a.title, "currency": a.currency, "occurrence": a.occurrence},
                   "checks": a.checks, "problems": a.problems, "statement": a.statement}
        if a.source is not None and a.balances != "export":  # 137: a ledger export; its companion PDF and findings
            content |= {"companion": source.get("companion"), "balances": a.balances, "companion_problems": a.companion_problems}
        path = folder / _file_name(reading, a)
        path.write_text(json.dumps(content, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8", newline="\n")
        paths.append(path)
    return paths


def load_derived(data: bytes) -> dict[str, Any]:
    """An account's statement file, checked for its format."""
    try:
        content = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StatementTableError("not a statement file") from exc
    if not isinstance(content, dict) or content.get("format") != FORMAT or content.get("version") != FORMAT_VERSION \
            or not isinstance(content.get("statement"), dict):
        raise StatementTableError("not a statement file of this version")
    return content

