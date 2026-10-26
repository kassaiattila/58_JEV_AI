"""231 (plan stage C, C3g): a bank's tabular export read by code (136), split out of `statement_table.py`.

Plain-language summary: the rows of cell texts of a workbook, a SpreadsheetML file or a CSV export (138: parsed in the
isolated reader's helper process), with the three repairs an export may need; the blocks of an account (its title, its
summary and its transaction table); and the statement of each account, checked line by line. The rules it follows are
described in `statement_table.py`.
"""

from __future__ import annotations

import csv
import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.core.dates import read_date
from jav.documents import isolated_pdf
from jav.domains.finance.statement_common import (
    Account,
    StatementTableError,
    _cell,
    _header,
    _money,
    _norm,
    _plain,
    _with,
)


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _workbook_rows(data: bytes, limits: dict[str, Any]) -> list[list[str]]:
    import openpyxl

    from jav.documents.readers.contracts import ReadLimits
    from jav.documents.readers.limits import DEFAULT_LIMITS, ReadFailure, inspect_package

    archive = limits["archive"]
    try:  # the shared ZIP inspection: no unsafe member, no expansion beyond the bounds, external parts inert
        inspect_package(data, ReadLimits(**{**DEFAULT_LIMITS.model_dump(), **archive, "input_bytes": limits["max_bytes"],
                                            "visited_cells": limits["max_cells"]}))
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (ReadFailure, OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:  # 138: a broken archive too
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
    except Exception as exc:  # defusedxml raises its own and ElementTree's errors (as in jav/domains/finance/fx.py)
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


def _csv_rows(data: bytes, limits: dict[str, Any]) -> list[list[str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp1250")
        except UnicodeDecodeError as exc:
            raise StatementTableError("the CSV file is neither UTF-8 nor cp1250 text") from exc
    first = text.split("\n", 1)[0]
    delimiter = ";" if first.count(";") > first.count(",") else ","
    rows: list[list[str]] = []
    cells = 0
    for row in csv.reader(io.StringIO(text), delimiter=delimiter):  # 153 (review C3): the cell limit while reading
        cells += len(row)
        if len(rows) >= limits["max_rows"] or cells > limits["max_cells"]:
            raise StatementTableError("the file is over the row limit or the cell limit")
        rows.append([_text(v) for v in row])
    return rows


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


def parse_rows(suffix: str, data: bytes, limits: dict[str, Any]) -> list[list[str]]:
    """The rows of cell texts of an export's bytes: the third-party parsing (openpyxl, defusedxml, the CSV reader). 138
    (Q-table-reader-isolation): it runs in the isolated reader's helper process (`jav/documents/isolated_pdf.py`), within its time
    and memory limits, every setting a parameter."""
    if suffix == ".csv":
        return _csv_rows(data, limits)
    if suffix == ".xml":
        return _spreadsheetml_rows(data, limits)
    return _workbook_rows(data, limits)


def _parsed(suffix: str, data: bytes, limits: dict[str, Any]) -> list[list[str]]:
    """`parse_rows` in the isolated helper; its error keeps its message, a limit is a named refusal."""
    try:
        return isolated_pdf.run(parse_rows, kind="read", suffix=suffix, data=data, limits=limits)
    except isolated_pdf.PdfReaderError as exc:
        name, _, message = str(exc).partition(": ")
        raise StatementTableError(message if name == StatementTableError.__name__ else str(exc)) from exc
    except isolated_pdf.PdfReaderLimit as exc:
        raise StatementTableError(f"the file could not be read within the reader's limits ({exc.reason}): {exc}") from exc


def _rows(path: Path, data: bytes, conf: dict[str, Any]) -> tuple[list[list[str]], list[str]]:
    limits, repairs = conf["limits"], []
    if len(data) > limits["max_bytes"]:
        raise StatementTableError("the file is over the size limit")
    rows = _parsed(path.suffix.lower(), data, limits)
    if (fixed := _unmangled(rows, conf["repairs"]["mojibake"])) is not None:
        rows, repairs = fixed, [*repairs, "mojibake"]
    if path.suffix.lower() != ".csv" and (joined := _joined_csv(rows, conf["repairs"]["csv_in_first_columns"])) is not None:
        rows, repairs = joined, [*repairs, "csv_in_first_columns"]
    if any("&" in c and html.unescape(c) != c for r in rows for c in r):
        rows, repairs = [[html.unescape(c) for c in r] for r in rows], [*repairs, "html_entities"]
    return rows, repairs


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


TITLE_MAX = 200  # 174 (review 160 M-8): an account's printed title is short; a longer cell is never one


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
            # 174 (review 160 M-8): the title pattern takes quadratic time on a long cell of spaces (a 131 000-character
            # CSV cell held the service's process for about 40 s), so only a cell of a title's length is tried
            if len(filled[0]) <= TITLE_MAX and (m := title_re.match(filled[0])):
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
        if (fee := _money(_cell(row, columns, "fee"))) is not None and fee != 0:  # 144: a fee column (Revolut)
            _with(lines[-1], fee=f"{_plain(abs(fee))} {block.currency}")
    iban = (summary.get("account_iban") or "").replace(" ", "") or None
    opening, closing = _money(summary.get("opening_balance")), _money(summary.get("closing_balance"))
    printed = opening is not None and closing is not None
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
    # 174 (review 160 M-12): balances taken from the lines themselves agree with them by construction, so without a
    # total row nothing vouches for the first and last lines; the statement says so, and stays unverified
    from_lines = not printed and block.total is None
    return Account(key=key, title=block.name, currency=block.currency, occurrence=occurrence, statement=statement,
                   checks=checks, problems=problems, balances="lines" if from_lines else "export")


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
