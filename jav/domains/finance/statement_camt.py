"""231 (plan stage C, C3g): a bank's ISO 20022 camt.053 statement (141), split out of `statement_table.py`.

Plain-language summary: the XML statement (parsed in the isolated reader's helper process): per statement its account,
currency, number, period, balances and totals, and per entry its dates, amount, running balance, counterparty and memo,
with a known bank's texts of its transaction codes and card details. The rules it follows are described in
`statement_table.py`.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from jav.core.dates import read_date
from jav.documents import isolated_pdf
from jav.domains.finance.statement_common import (
    LINE_MAX,
    Account,
    Reading,
    StatementTableError,
    _card_details,
    _cents,
    _clock,
    _dot_amount,
    _plain,
    _with,
)

CAMT = "urn:iso:std:iso:20022:tech:xsd:camt.053."


_ROOT = re.compile(rb"<(?![?!])(?:[\w.\-]+:)?([\w.\-]+)([^>]*)>")


def _is_camt(data: bytes) -> bool:
    """Whether the file's root element is a camt.053 document. 144: the root decides, not any mention of the namespace
    in the head: the Erste Excel 2003 XML export declares a `camt` prefix on its `Workbook` root, and since 141 every
    such export went to the camt reader, which refused it."""
    root = _ROOT.search(re.sub(rb"<!--.*?-->", b"", data[:4096], flags=re.DOTALL))
    return root is not None and root.group(1) == b"Document" and CAMT.encode("ascii") in root.group(2)


def parse_camt(data: bytes, limits: dict[str, Any]) -> list[dict[str, Any]]:
    """The statements of a camt.053 file as plain texts (defusedxml refuses a document type declaration, entities and
    external references). It runs in the isolated reader's helper process, as the export parsing does (138)."""
    from defusedxml import ElementTree

    try:
        root = ElementTree.fromstring(data)
    except Exception as exc:  # defusedxml raises its own and ElementTree's errors (as in _spreadsheetml_rows)
        raise StatementTableError(f"the XML statement cannot be read: {type(exc).__name__}") from exc
    ns = root.tag[1:].split("}")[0] if root.tag.startswith("{") else ""
    if not ns.startswith(CAMT):
        raise StatementTableError("not an ISO 20022 camt.053 statement")

    def q(path: str) -> str:
        return "/".join(f"{{{ns}}}{part}" for part in path.split("/"))

    def text(el: Any, path: str) -> str | None:
        found = el.find(q(path))
        return found.text.strip() if found is not None and found.text and found.text.strip() else None

    out, count = [], 0
    for stmt in root.iter(q("Stmt")):
        balances = {}
        for bal in stmt.findall(q("Bal")):
            amount = text(bal, "Amt")
            if amount is not None:
                balances[text(bal, "Tp/CdOrPrtry/Cd")] = ("-" if text(bal, "CdtDbtInd") == "DBIT" else "") + amount
        entries = []
        for n in stmt.findall(q("Ntry")):
            count += 1
            if count > limits["max_rows"]:
                raise StatementTableError("the statement is over the row limit")
            debit = text(n, "CdtDbtInd") == "DBIT"
            role = "Cdtr" if debit else "Dbtr"
            post = next((text(a, "Amt") for a in n.iter(q("PrtryAmt")) if text(a, "Tp") == "POSTBALANCE"), None)
            party = f"NtryDtls/TxDtls/RltdPties/{role}"
            charges = [(text(c, "Amt"), c.find(q("Amt")).get("Ccy") if c.find(q("Amt")) is not None else None)
                       for c in n.findall(q("Chrgs"))]
            entries.append({"amount": text(n, "Amt"), "debit": debit, "booked": text(n, "BookgDt/Dt"), "value": text(n, "ValDt/Dt"),
                            "code": text(n, "BkTxCd/Prtry/Cd"), "name": text(n, f"{party}/Nm"),
                            "account": text(n, f"{party}Acct/Id/IBAN") or text(n, f"{party}Acct/Id/Othr/Id"),
                            "memo": " ".join(u.text.strip() for u in n.iter(q("Ustrd")) if u.text and u.text.strip()) or None,
                            "info": text(n, "NtryDtls/TxDtls/AddtlTxInf") or text(n, "AddtlNtryInf"), "balance": post,
                            # 144: the bank's reference, the parties' end-to-end id, when it was accepted, its charges
                            "reference": text(n, "NtryDtls/TxDtls/Refs/TxId") or text(n, "NtryDtls/TxDtls/Refs/AcctSvcrRef")
                            or text(n, "AcctSvcrRef"),
                            "end_to_end": text(n, "NtryDtls/TxDtls/Refs/EndToEndId"),
                            "accepted": text(n, "NtryDtls/TxDtls/RltdDts/AccptncDtTm"), "charges": charges})
        out.append({"id": text(stmt, "Id"), "iban": text(stmt, "Acct/Id/IBAN"), "other": text(stmt, "Acct/Id/Othr/Id"),
                    "currency": text(stmt, "Acct/Ccy"), "bic": text(stmt, "Acct/Svcr/FinInstnId/BIC"),
                    "bank": text(stmt, "Acct/Svcr/FinInstnId/Nm"), "from": (text(stmt, "FrToDt/FrDtTm") or "")[:10] or None,
                    "to": (text(stmt, "FrToDt/ToDtTm") or "")[:10] or None,
                    "opening": balances.get("OPBD") or balances.get("PRCD"), "closing": balances.get("CLBD"),
                    "credit_total": text(stmt, "TxsSummry/TtlCdtNtries/Sum"), "debit_total": text(stmt, "TxsSummry/TtlDbtNtries/Sum"),
                    "entries": entries})
    if not out:
        raise StatementTableError("no statement in the camt.053 file")
    return out


def _xml_amount(value: str | None) -> Decimal | None:
    """An XML decimal ("7291.00", ".00", "-12.5"). 153 (review C1): at most 40 characters, by a pattern that does not
    backtrack (a 20,000-digit amount took seconds)."""
    if not value or len(value) > 40 or not re.fullmatch(r"-?(?:\d+(?:\.\d+)?|\.\d+)", value):
        return None
    return _cents(Decimal(value))


def _camt_account(s: dict[str, Any], profile: dict[str, Any], source: dict[str, Any]) -> Account:
    bank = profile.get("banks", {}).get(s["bic"] or "", {})
    kinds, details = bank.get("kinds", {}), {k: re.compile(v) for k, v in bank.get("details", {}).items()}
    currency = s["currency"] or ""
    lines, amounts, balances, problems = [], [], [], []
    for n, e in enumerate(s["entries"], start=1):
        amount, booked = _xml_amount(e["amount"]), read_date(e["booked"]).value
        if amount is None or booked is None:
            problems.append(f"line {n}: unreadable")
            continue
        amount = -amount if e["debit"] else amount
        info = (e["info"] or "")[:LINE_MAX]  # 153 (review C1): the bank's patterns read a bounded text
        name = " ".join(e["name"].split()) if e["name"] else None  # single spaces, as the text statements keep them
        if not name and "merchant" in details and (m := details["merchant"].search(info)):
            name = " ".join(m["value"].split())
        original = details["original"].search(info) if "original" in details else None
        foreign = original is not None and original["currency"] != currency and _dot_amount(original["amount"]) is not None
        balance = _xml_amount(e["balance"])
        amounts.append(amount)
        balances.append(balance)
        value = read_date(e["value"]).value
        lines.append({"booking_date": booked.isoformat(), "value_date": value.isoformat() if value else None,
                      "direction": "debit" if amount < 0 else "credit", "amount": _plain(abs(amount)),
                      "running_balance": _plain(balance), "description": kinds.get(e["code"] or "", e["code"]),
                      "counterparty_name": name, "counterparty_account": e["account"],
                      "memo": " ".join(e["memo"].split()) if e["memo"] else None,
                      "original_amount": _plain(_dot_amount(original["amount"])) if foreign else None,
                      "original_currency": original["currency"] if foreign else None})
        # 144: the entry's references and its card and charge details (the bank's own text first, else its charges)
        found = {k: m.groupdict() for k, rx in details.items() if (m := rx.search(info))}
        card = _card_details(found)
        charged = [(a, c) for a, c in e.get("charges", []) if (v := _xml_amount(a)) is not None and v != 0]
        card["fee"] = card["fee"] or (" + ".join(f"{_plain(_xml_amount(a))} {c or currency}" for a, c in charged) or None)
        card["transaction_time"] = card["transaction_time"] or _clock(e.get("accepted"))
        end_to_end = e.get("end_to_end")
        _with(lines[-1], bank_reference=e.get("reference"), **card,
              end_to_end_id=None if not end_to_end or end_to_end.upper() == "NOTPROVIDED" else end_to_end)
    opening, closing = _xml_amount(s["opening"]), _xml_amount(s["closing"])
    start = read_date(s["from"]).value if s["from"] else None
    end = read_date(s["to"]).value if s["to"] else None
    if start is None and lines:
        start, end = (read_date(x).value for x in (min(t["booking_date"] for t in lines), max(t["booking_date"] for t in lines)))
    debits = sum((-a for a in amounts if a < 0), Decimal(0))
    credits = sum((a for a in amounts if a > 0), Decimal(0))
    iban = (s["iban"] or "").replace(" ", "") or None
    statement = {"statement_type": profile["statement_type"], "account_no": None if iban else s["other"], "account_iban": iban,
                 "period_start": start.isoformat() if start else None, "period_end": end.isoformat() if end else None,
                 "currency": currency or None, "opening_balance": _plain(opening), "closing_balance": _plain(closing),
                 "total_debit": _plain(debits), "total_credit": _plain(credits), "transactions": lines}
    running = None
    if opening is not None and lines and all(b is not None for b in balances):
        ok, previous = 0, opening
        for amount, balance in zip(amounts, balances):
            ok += previous + amount == balance
            previous = balance
        running = {"ok": ok, "lines": len(lines)}
    printed = (_xml_amount(s["debit_total"]), _xml_amount(s["credit_total"]))
    checks = {"running_balance": running,
              "total_row": None if None in printed else (abs(printed[0]), printed[1]) == (debits, credits),
              "closing_balance": None if opening is None or closing is None else opening + sum(amounts, Decimal(0)) == closing}
    digits = re.sub(r"\D", "", iban[4:]) if iban else re.sub(r"\D", "", s["other"] or "")
    return Account(key=f"{digits}:{currency}:{statement['period_start']}", title=f"…{digits[-4:]} {s['id'] or ''}".strip(),
                   currency=currency, occurrence=1, statement=statement, checks=checks, problems=problems, source=source)


def _read_camt(data: bytes, profile: dict[str, Any], limits: dict[str, Any], file_name: str, sha: str) -> Reading:
    try:
        statements = isolated_pdf.run(parse_camt, kind="read", data=data, limits=limits)
    except isolated_pdf.PdfReaderError as exc:
        name, _, message = str(exc).partition(": ")
        raise StatementTableError(message if name == StatementTableError.__name__ else str(exc)) from exc
    except isolated_pdf.PdfReaderLimit as exc:
        raise StatementTableError(f"the file could not be read within the reader's limits ({exc.reason}): {exc}") from exc
    source = {"file": file_name, "sha256": sha, "repairs": []}
    accounts = [_camt_account(s, profile, source) for s in statements]
    bank = profile.get("banks", {}).get(statements[0]["bic"] or "", {})
    return Reading(profile=profile["name"], institution=bank.get("institution") or statements[0]["bank"] or profile["institution"],
                   file_name=file_name, sha256=sha, repairs=[], accounts=accounts)
