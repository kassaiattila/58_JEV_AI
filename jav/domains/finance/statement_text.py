"""231 (plan stage C, C3g): a statement printed as text (141), split out of `statement_table.py`.

Plain-language summary: a PDF's text layer or the bank's fixed-width text export (the CIB statement), known by its
profile's signature, read with the profile's patterns: the header, the lines with their value date rows and labelled
rows, and the statement's own checks. The rules it follows are described in `statement_table.py`.
"""

from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.core import card_numbers
from jav.core.dates import read_date
from jav.domains.finance.statement_common import (
    CENT,
    LINE_DETAILS,
    Account,
    Reading,
    StatementTableError,
    _bounded,
    _clock,
    _conf,
    _dot_amount,
    _hu_amount,
    _pdf_lines,
    _plain,
    _with,
    _within_size,
    _without_page_breaks,
)


def _signed(text: str | None) -> Decimal | None:
    """A Hungarian amount whose minus sign may stand apart ("- 2.000.000,00")."""
    return _hu_amount(re.sub(r"^-\s+", "-", text.strip())) if text else None


def _comma_amount(text: str) -> Decimal | None:
    """An amount with a decimal comma and no thousands separator ("1000,000"), when it is a whole number of cents."""
    if not re.fullmatch(r"\d+(?:,\d+)?", text):
        return None
    value = Decimal(text.replace(",", "."))
    return value.quantize(CENT) if value == value.quantize(CENT) else None


def _text_line(m: re.Match[str], *, expect_name: bool, reference: re.Pattern[str] | None = None) -> dict[str, Any]:
    """A line's first row; a card statement's row prints the purchase day (`value`) and no running balance. 144: the
    bank's reference after the kind's semicolon, when it has the profile's `reference` shape."""
    kind, groups = " ".join(m["kind"].split()), m.groupdict()
    value = read_date(groups["value"]).value if groups.get("value") else None
    after = kind.split(";", 1)[1].strip() if ";" in kind else ""
    ref = reference.fullmatch(after) if reference is not None and after else None
    return {"booked": read_date(m["booked"]).value, "kind": kind.split(";", 1)[0].strip() or kind,
            "amount": _hu_amount(m["amount"]), "balance": _hu_amount(groups["balance"]) if groups.get("balance") else None,
            "has_balance": "balance" in groups, "value_date": value, "counterparty_name": None, "counterparty_account": None,
            "memo": None, "note": None, "original_amount": None, "original_currency": None, "expect_name": expect_name,
            "details": {"bank_reference": ref["value"] if ref else None}}


def _card_row(current: dict[str, Any], m: re.Match[str]) -> None:
    """144: a card charge's detail row (`1234 5678 9012 3456 20260105 101500; …`): the masked card number, the purchase
    day and the time, on the line it belongs to."""
    groups = m.groupdict()
    day = read_date(re.sub(r"^(\d{4})(\d{2})(\d{2})$", r"\1-\2-\3", groups["date"])).value if groups.get("date") else None
    current["details"].update({"card_number": card_numbers.masked(groups["card"]),
                               "purchase_date": day.isoformat() if day else None, "transaction_time": _clock(groups.get("time"))})


_DOUBLED = re.compile(r"(?<!\S)(?=\S*\d)(?=\S*(?:\.\.|,,|--))(?:([0-9.,\-])\1)+(?!\S)")


def _undoubled(line: str) -> str:
    """141: a number the PDF's text layer prints with every character twice ("22002266..0022..0055.." for
    "2026.02.05.", the CIB statement's first row after a page break) is read once. Only a whole token of digits and
    separators whose every character is doubled, with a doubled separator, so no real number is touched."""
    return _DOUBLED.sub(lambda m: m.group(0)[::2], line)


def parse_text_statement(lines: list[str], profile: dict[str, Any]) -> dict[str, Any]:
    """The statement's header fields and lines from its text lines and the profile's patterns. Pure: no file is read.
    A text keeps single spaces only, as a fixed-width export pads inside a description where the PDF does not."""
    lines = [_undoubled(ln.strip()) for ln in lines]
    text = "\n".join(lines)
    header = {k: re.search(v, text, re.MULTILINE) for k, v in profile["header"].items()}
    start_re, end_re = re.compile(profile["lines_start"]), re.compile(profile["lines_end"])
    first = next((i for i, ln in enumerate(lines) if start_re.search(ln)), len(lines))
    last = next((i for i in range(first + 1, len(lines)) if end_re.search(lines[i])), len(lines))
    drop = [re.compile(x) for x in profile.get("drop_rows", [])]

    def optional(key: str) -> re.Pattern[str] | None:
        return re.compile(profile[key]) if profile.get(key) else None

    # 144: a card charge's detail row (the card, the day, the time) is kept even where its digits fit a dropped row
    card_row, card_section, reference = optional("card_row"), optional("card_section"), optional("reference")
    body = [ln for ln in _without_page_breaks(lines[first + 1:last], profile.get("skip_blocks", []))
            if ln.strip("-= ") and ((card_row is not None and card_row.match(ln)) or not any(rx.search(ln) for rx in drop))]
    line_re, value_re = re.compile(profile["line"]), optional("value_line")
    account_re, original_re, original_row = optional("counterparty_account"), optional("original"), optional("original_row")
    named_first = profile.get("name_from") == "first_unlabelled"  # a card purchase's merchant follows its line
    labels = {k: re.compile(v) for k, v in profile["labels"].items()}
    labelled, dated = re.compile(profile["labelled"]), re.compile(r"^\d{4}\.\d{2}\.\d{2}\.")
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    expect_value = False
    section_card: str | None = None  # 144: a credit card statement heads each card's purchases with its number
    for ln in body:
        if card_section is not None and (c := card_section.match(ln)):
            section_card = card_numbers.masked(c["card"])
            expect_value = False
            if out:
                out[-1]["expect_name"] = False
            continue
        if m := line_re.match(ln):
            out.append(_text_line(m, expect_name=named_first, reference=reference))
            if section_card:
                out[-1]["details"]["card_number"] = section_card
            if out[-1]["booked"] is None or out[-1]["amount"] is None or (out[-1]["has_balance"] and out[-1]["balance"] is None):
                problems.append(f"line {len(out)}: unreadable")
            expect_value = value_re is not None
            continue
        current = out[-1] if out else None
        if expect_value and current is not None and value_re is not None and (v := value_re.match(ln)):
            expect_value = False
            current["value_date"] = read_date(v["value_date"]).value
            rest = (v["text"] or "").strip()
            if account_re is not None and account_re.fullmatch(rest):
                current["counterparty_account"] = rest if "-" in rest else rest.replace(" ", "")
                current["expect_name"] = True
            elif rest:
                current["note"] = " ".join(rest.split())
                if original_re and (o := original_re.match(rest)) and (amount := _comma_amount(o["amount"])) is not None:
                    current["original_amount"], current["original_currency"] = amount, o["currency"]
                if card_row is not None and (c := card_row.match(current["note"])):
                    _card_row(current, c)
            continue
        expect_value = False
        if current is None:
            continue
        if dated.match(ln):
            problems.append(f"line {len(out)}: an unreadable row after it")
            continue
        if card_row is not None and (c := card_row.match(ln)):
            _card_row(current, c)
            continue
        if original_row is not None and (o := original_row.match(ln)):  # a card purchase's amount in its own currency
            if current["original_amount"] is None and (amount := _dot_amount(o["amount"])) is not None:
                current["original_amount"], current["original_currency"] = amount, o["currency"]
            continue
        found = False
        for key, rx in labels.items():
            if d := rx.match(ln):
                found = True
                value = " ".join(d["value"].split())
                if key in LINE_DETAILS:  # 144: an identifier the statement labels (the parties' end-to-end id, the order id)
                    current["details"][key] = current["details"].get(key) or value
                elif current[key] is None:
                    current[key] = value
        if not found and current["expect_name"] and not labelled.match(ln):
            current["counterparty_name"] = " ".join(ln.split())
        current["expect_name"] = False
    period = header.get("period")
    totals = header.get("totals")
    return {"number": header["number"]["value"] if header.get("number") else None,
            "period": (read_date(period["start"]).value, read_date(period["end"]).value) if period else (None, None),
            "currency": header["currency"]["value"] if header.get("currency") else None,
            "account": header["account"]["value"] if header.get("account") else None,
            "iban": header["iban"]["value"].replace(" ", "") if header.get("iban") else None,
            "opening": _signed(header["opening"]["value"]) if header.get("opening") else None,
            "closing": _signed(header["closing"]["value"]) if header.get("closing") else None,
            "totals": (_signed(totals["debit"]), _signed(totals["credit"])) if totals else None,
            "lines": out, "problems": problems}


def _text_account(parsed: dict[str, Any], profile: dict[str, Any], source: dict[str, Any]) -> Account:
    """One account's statement from a parsed text statement, with the checks of its own balances and totals."""
    lines = [t for t in parsed["lines"] if t["booked"] is not None and t["amount"] is not None]
    amounts = [t["amount"] for t in lines]
    currency = parsed["currency"] or ""
    for t in lines:  # an amount in the statement's own currency is no original amount
        if t["original_currency"] == currency:
            t["original_amount"] = t["original_currency"] = None
    transactions = [{"booking_date": t["booked"].isoformat(),
                     "value_date": t["value_date"].isoformat() if t["value_date"] else None,
                     "direction": "debit" if t["amount"] < 0 else "credit", "amount": _plain(abs(t["amount"])),
                     "running_balance": _plain(t["balance"]), "description": t["kind"] or None,
                     "counterparty_name": t["counterparty_name"], "counterparty_account": t["counterparty_account"],
                     "memo": t["memo"] or t["note"], "original_amount": _plain(t["original_amount"]),
                     "original_currency": t["original_currency"]} for t in lines]
    for line, t in zip(transactions, lines):
        _with(line, **t["details"])
    opening, closing = parsed["opening"], parsed["closing"]
    start, end = (d.isoformat() if d else None for d in parsed["period"])
    if start is None and transactions:
        start, end = min(t["booking_date"] for t in transactions), max(t["booking_date"] for t in transactions)
    debits = sum((-a for a in amounts if a < 0), Decimal(0))
    credits = sum((a for a in amounts if a > 0), Decimal(0))
    statement = {"statement_type": profile["statement_type"], "account_no": parsed["account"],
                 "account_iban": parsed["iban"], "period_start": start, "period_end": end, "currency": currency or None,
                 "opening_balance": _plain(opening), "closing_balance": _plain(closing), "total_debit": _plain(debits),
                 "total_credit": _plain(credits), "transactions": transactions}
    running = None
    if opening is not None and lines and all(t["has_balance"] for t in lines):  # a card statement prints none
        ok, previous = 0, opening
        for t in lines:
            ok += previous is not None and t["balance"] is not None and previous + t["amount"] == t["balance"]
            previous = t["balance"]
        running = {"ok": ok, "lines": len(lines)}
    totals = parsed["totals"]
    checks = {"running_balance": running,
              "total_row": None if totals is None or None in totals else (abs(totals[0]), totals[1]) == (debits, credits),
              "closing_balance": None if opening is None or closing is None else opening + sum(amounts, Decimal(0)) == closing}
    digits = re.sub(r"\D", "", parsed["account"] or (parsed["iban"] or "")[4:])
    number = parsed["number"]
    title = f"…{digits[-4:]} {int(number)}" if number else f"…{digits[-4:]}"
    return Account(key=f"{digits}:{currency}:{start}", title=title, currency=currency, occurrence=1, statement=statement,
                   checks=checks, problems=list(parsed["problems"]), source=source)


def _text_lines(path: Path, data: bytes, profiles: list[dict[str, Any]]) -> list[str]:
    """The lines of a PDF's text layer (the isolated PDF reader) or of a text export in one of the profiles' encodings."""
    if path.suffix.lower() == ".pdf":
        try:
            return _pdf_lines(path)
        except (ValueError, OSError) as exc:  # the PDF reader's refusals (size, pages, a parser error) are ValueErrors
            raise StatementTableError(f"the PDF cannot be read: {exc}") from exc
    for encoding in dict.fromkeys(e for p in profiles for e in p.get("encodings", ["utf-8"])):
        try:
            return data.decode(encoding).splitlines()
        except UnicodeDecodeError:
            continue
    raise StatementTableError("the text file is in none of the profiles' encodings")


def _read_text(path: Path, *, name: str | None = None) -> Reading:
    conf = _conf()
    _within_size(path, conf["limits"])
    data = path.read_bytes()
    profiles = [p for p in conf["profiles"] if p.get("layout") == "text" and path.suffix.lower() in p["suffixes"]]
    lines, repairs = _bounded([ln.strip() for ln in _text_lines(path, data, profiles)] if profiles else [])
    text = "\n".join(lines)
    file_name = name or path.name
    sha = hashlib.sha256(data).hexdigest()
    for profile in profiles:
        if all(re.search(s, text, re.MULTILINE) for s in profile["signature"]):
            account = _text_account(parse_text_statement(lines, profile), profile,
                                    {"file": file_name, "sha256": sha, "repairs": repairs})
            return Reading(profile=profile["name"], institution=profile["institution"], file_name=file_name,
                           sha256=sha, repairs=repairs, accounts=[account])
    raise StatementTableError("no statement of a known profile in the file")
