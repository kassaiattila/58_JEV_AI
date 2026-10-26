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

138 (Q-table-reader-isolation, DECISIONS 138): the third-party parsing of an export (`parse_rows`) runs in the isolated
PDF reader's helper process, within its read time limit and memory limit, as the local service reads a file a person
picks; our own reading of the rows stays in the calling process.

141 (DECISIONS 141, the sports club's statements read by code first): a **text** profile (`layout: text`) reads a statement printed as text:
a PDF's text layer (the isolated PDF reader) or the bank's fixed-width text export (`.txt`, in one of the profile's
`encodings`), such as the CIB statement. A profile knows its statement by `signature` (every pattern found in the text);
`header` gives the statement number, period, currency, account, IBAN, opening and closing balances and the printed
totals; the lines stand between `lines_start` and `lines_end`, without the page breaks (`skip_blocks`). A line is its
first row (booking date, kind, signed amount, running balance), then its value date row, whose text is the
counterparty's account (the next unlabelled row is then the counterparty's name), a foreign transfer's original amount
(`original`) or the bank's own description of a fee; the labelled rows (`labels`) give the counterparty's name and
account and the memo. The statement checks itself: the running balance line by line, the printed totals and the closing
balance. A PDF no text profile knows is left alone when a folder is read: it may be another export's companion or a
statement to extract (`jav/domains/finance/statement_package.py`).

141 (DECISIONS 141, the Erste account's source): a **camt053** profile (`layout: camt053`) reads a bank's ISO 20022
camt.053 statement (an XML file in the `urn:iso:std:iso:20022:tech:xsd:camt.053.` namespace, parsed with defusedxml in
the isolated reader's helper): per statement its account (IBAN), currency, number, period, the booked opening and
closing balances and the printed totals, and per entry its booking and value dates, signed amount, running balance
(`POSTBALANCE`), counterparty (the creditor of a debit, the debtor of a credit) with its account, and memo. A bank,
known by its BIC (`banks`), adds the texts of its own transaction codes (`kinds`, as its Excel export prints them) and
the patterns of its card details in the entry's additional information (`details`: the merchant, a foreign purchase's
original amount and currency); another bank's statement keeps its codes. The statement checks itself like an export.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from jav.core import card_numbers
from jav.domains.finance.statement_common import (SUFFIXES, TEXT_SUFFIXES, Account, Reading, StatementTableError, _conf,
    _within_size)
from jav.domains.finance.statement_tabular import _accounts, _blocks, _rows
from jav.domains.finance.statement_ledger import _ledger_accounts
from jav.domains.finance.statement_text import _read_text
from jav.domains.finance.statement_camt import _is_camt, _read_camt

# 231 (C3g): the shared names the callers use, re-exported (a fixed list: new code imports from the defining module)
from jav.domains.finance.statement_common import (CONFIG as CONFIG, LINE_DETAILS as LINE_DETAILS,
    config_hash as config_hash)
from jav.domains.finance.statement_tabular import parse_rows as parse_rows
from jav.domains.finance.statement_ledger import parse_companion as parse_companion
from jav.domains.finance.statement_text import parse_text_statement as parse_text_statement
from jav.domains.finance.statement_camt import parse_camt as parse_camt


def _read_file(path: Path, *, name: str | None = None) -> Reading:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return _read_text(path, name=name)
    if path.suffix.lower() not in SUFFIXES:
        raise StatementTableError(f"a statement table is a {' or '.join(SUFFIXES + TEXT_SUFFIXES)} file")
    conf = _conf()
    _within_size(path, conf["limits"])
    data = path.read_bytes()
    file_name = name or path.name
    sha = hashlib.sha256(data).hexdigest()
    camt = next((p for p in conf["profiles"] if p.get("layout") == "camt053"), None)
    if camt is not None and path.suffix.lower() == ".xml" and _is_camt(data):  # 141: a bank's ISO 20022 statement
        if len(data) > conf["limits"]["max_bytes"]:
            raise StatementTableError("the file is over the size limit")
        return _read_camt(data, camt, conf["limits"], file_name, sha)
    rows, repairs = _rows(path, data, conf)
    source = {"file": file_name, "sha256": sha, "repairs": repairs}
    for profile in conf["profiles"]:
        if profile.get("layout") in ("text", "camt053"):  # 141: read from a PDF, a text export or a camt.053 file only
            continue
        if profile.get("layout") == "ledger":
            accounts = _ledger_accounts(rows, profile, path, file_name, source)
        else:
            accounts = [replace(a, source=source) for a in _accounts(_blocks(rows, profile), file_name, profile)]
        if accounts:
            return Reading(profile=profile["name"], institution=profile["institution"], file_name=file_name,
                           sha256=sha, repairs=repairs, accounts=accounts)
    raise StatementTableError("no statement table of a known profile in the file")


def inside(path: Path, folder: Path) -> bool:
    """153 (review C8): a file of the folder that stays in it once its links are followed (`work.folder_documents` does
    the same); a link to a file elsewhere is passed over, as the other folder readers do."""
    try:
        return path.resolve().is_relative_to(folder.resolve())
    except (OSError, ValueError):
        return False


def _read_folder(folder: Path) -> Reading:
    """137: every export directly in the folder; a file no profile reads is listed, and a statement read twice (the
    same statement in two files) keeps its first file. 141: and every statement printed as text; a PDF or a text file
    no profile reads is not listed (a PDF may be an export's companion or a statement to extract, a text file a note)."""
    limit = _conf()["limits"]["max_files"]
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUFFIXES + TEXT_SUFFIXES
                   and inside(p, folder))
    if len(files) > limit:
        raise StatementTableError(f"the folder holds more than {limit} statement files")
    readings, skipped = [], []
    for f in files:
        try:
            readings.append(_read_file(f))
        except StatementTableError as exc:  # listed for the person, not dropped
            if f.suffix.lower() not in TEXT_SUFFIXES:
                skipped.append({"file": f.name, "reason": str(exc)})
    accounts: dict[str, Account] = {}
    for r in readings:
        for a in r.accounts:
            first = accounts.get(a.key)
            if first is not None and first.statement.get("period_start") != a.statement.get("period_start"):
                # 174 (review 160 M-7): another month of the same account (a table export's key holds no period): its
                # key gets its period; its file keeps the key without it, so its id is the one it has read alone
                a = replace(a, key=f"{a.key}:{a.statement.get('period_start') or ''}", stored_key=a.key)
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
    return _masked(_read_folder(path) if path.is_dir() else _read_file(path, name=name))


def _masked(reading: Reading) -> Reading:
    """144 (DECISIONS 144): no full card number leaves a reader; the texts keep only its first six and last four digits."""
    for account in reading.accounts:
        for line in account.statement.get("transactions") or []:
            for key in ("memo", "description", "counterparty_name"):
                line[key] = card_numbers.mask_text(line.get(key))
    return reading


def checks_ok(account: Account) -> bool:
    """Every line's running balance checks out (141: or, on a statement printing none, such as a card statement, the
    closing balance does), and no check failed and nothing was unreadable."""
    c = account.checks
    running = c["running_balance"]
    balances = running["ok"] == running["lines"] if running is not None else c["closing_balance"] is True
    return (balances and c["total_row"] is not False and c["closing_balance"] is not False and not account.problems
            and not account.companion_problems)


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


# the stored statement file's format name, written into every file: not the module's path, so it stays as it was
# written when the module moves (208, plan G-process-core R2)
FORMAT = "jav.statement_table"


FORMAT_VERSION = 1


_UNSAFE = re.compile(r'[<>:"/\|?*\x00-\x1f]+')


def derived_dir() -> Path:
    """Where the accounts' statement files are written: next to the store in use (tests get their own folder)."""
    from jav.core import store

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
        path = folder / _file_name(reading, a)
        path.write_bytes(derived_bytes(reading, a))
        paths.append(path)
    return paths


def derived_bytes(reading: Reading, a: Account) -> bytes:
    """The content of an account's statement file (`derive`), canonical. 140: its fingerprint is the id of the item
    and of the document, so a survey knows it before anything is written (`derived_id`)."""
    source = a.source or {"file": reading.file_name, "sha256": reading.sha256, "repairs": reading.repairs}
    content = {"format": FORMAT, "version": FORMAT_VERSION, "profile": reading.profile, "institution": reading.institution,
               "source": {k: source[k] for k in ("file", "sha256", "repairs")},
               "account": {"key": a.stored_key or a.key, "title": a.title, "currency": a.currency, "occurrence": a.occurrence},
               "checks": a.checks, "problems": a.problems, "statement": a.statement}
    if a.source is not None and a.balances != "export":  # 137: a ledger export; its companion PDF and findings
        content |= {"companion": source.get("companion"), "balances": a.balances, "companion_problems": a.companion_problems}
    return (json.dumps(content, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


def derived_id(reading: Reading, a: Account) -> str:
    """The id an account's statement gets as an item and as a document: its statement file's fingerprint."""
    return hashlib.sha256(derived_bytes(reading, a)).hexdigest()


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
