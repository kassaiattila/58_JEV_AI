"""231 (plan stage C, C3g): a ledger export and its PDF companion (137), split out of `statement_table.py`.

Plain-language summary: an export that lists every line with its own account and statement number (the Erste Excel
2003 XML export), one statement per account and statement number, with the same month's PDF statement as its
companion for the balances and the card details. The rules it follows are described in `statement_table.py`.
"""

from __future__ import annotations

import calendar
import hashlib
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.core.dates import read_date
from jav.domains.finance.statement_common import (
    Account,
    _bounded,
    _card_details,
    _cell,
    _cents,
    _conf,
    _dot_amount,
    _header,
    _hu_amount,
    _money,
    _norm,
    _pdf_lines,
    _plain,
    _with,
    _within_size,
    _without_page_breaks,
)


def _ledger_amount(text: str, profile: dict[str, Any]) -> Decimal | None:
    """A machine number ("-7291.00") when the profile says so, otherwise the shared number reader."""
    if profile.get("amounts") == "machine":
        return _cents(Decimal(text)) if re.fullmatch(r"-?\d+(?:\.\d+)?", text) else None
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
        _with(line, **_card_details(c["details"]))  # 144
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
        _within_size(companion_path, _conf()["limits"])
        data = companion_path.read_bytes()
        pdf = parse_companion(_bounded(_pdf_lines(companion_path))[0], profile["companion"])
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
