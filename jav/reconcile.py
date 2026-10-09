"""128 (backlog F-reconciliation, K1): which bank statement line paid which incoming invoice, found by code.

An invoice in the store says what is owed; a bank statement line says what left an own account. This module proposes
the pairs by code, with no AI call, and says for every invoice how far the loaded statements can tell anything about it
(the owner's decisions of 2026-10-08, DECISIONS 128):

- A pair is **proposed** only when the currency and the amount are exactly equal and at least one signal ties the line
  to the invoice: its number in the line's memo or description, the supplier's account as the counterparty account (a
  Hungarian IBAN and the domestic account number are one account), or the supplier's name as the counterparty. An equal
  amount alone is never a pair. A signal with a different amount is listed (`amount_relation: different`) but not
  proposed; partial and combined payments come later.
- The line must fall in the invoice's payment window: from `days_before_issue` before the issue date (advance
  payments) to `days_after_due` after the due date (or the issue date without one).
- **Coverage, never "unpaid":** a statement counts as coverage only when its lines are verified by the balance checks
  (`verified_when`). An invoice without a proposed pair is `no_payment_found` only when, for every own account of its
  currency, verified statements cover its whole window; otherwise `partly_covered` or `not_covered`.
- **Own accounts** are the accounts the statements belong to; a line to another own account is a transfer, not a
  payment.
- Every exclusion has a reason code (`excluded`), so nothing drops out silently.

The core (`propose`) is pure: it takes a snapshot (invoices, statements with their lines) and returns the proposal;
`snapshot` builds one from the store's effective values (the latest result with its latest correction, as in
`duplicates.documents`), and `scan` summarises it for the command line. Parameters are data (`configs/reconcile.json`);
the synthetic golden cases are `configs/golden_reconcile.json`.

**A person's decision** (129, K2; the pattern of `jav/duplicates.py`): a proposed pair gets a
`reconcile:proposed:<invoice id prefix>:<line id>` to-do on the later processed document, in a worker run only
(`review_reasons`). A person confirms it (`paid_by`, "this line paid it") or rejects it with a reason (`not_this`); the
decision belongs to the pair (`reconcile_decisions`), closes its to-dos, is part of the reviewed result
(`corrections.review_version`) and is frozen with the approval of the run it was made in (`decide`). In the core a
rejected pair is never proposed again, and a confirmed pair makes its invoice `confirmed` and takes the line and the
invoice out of every other proposal: one line pays one invoice in this version. `scan(write=True)` opens the same to-do
on the pairs already in the store, on runs not yet approved; `item_pairs` and `run_rows` are the review page's panel and
the run's reconciliation view.

**Card payments in another currency** (130, K3; DECISIONS 128 variant C, DECISIONS 130): a credit card statement books
in forints and does not print the original amount, so a forint line of a card statement (`fx.statement_types`) and an
invoice in another currency are compared through the official MNB rate of the invoice's issue date (`jav/fx.py`). Such
a pair needs a signal like any other and a line within `fx.window` around the issue date; it is proposed when the
line's amount is within `policy.json` `reconcile.fx_tolerance` of the converted amount (`fx_within`), listed but not
proposed outside it (`fx_outside`, status `amount_differs`) or without a known rate (`no_rate`, status
`rate_missing`). The card accounts also count in the coverage of a foreign-currency invoice, so "no payment found"
needs them covered too. The rates come in the snapshot (`fx_rates`), so the core stays pure; only the processing and
the command line fetch missing rates, a view reads the store.

**Payment method, equal amounts, learnt names** (131, DECISIONS 131): the store's card lines show the payment service
(PostaCsekk, iCsekk) or a shortened merchant name (EXAMPLETEL*12345), not the supplier, so none of them carried a
signal. Three additions, all proposals for a person:

- The **payment method** is a signal (`payment_channel`): the invoice's payment method fits a configured channel
  (`payment_channels`, e.g. the postal cheque) and the line's name or description names that channel's payment app.
  Alone it ties no other amount: the app pays many bills.
- A line with **exactly the amount** of an invoice in one currency, in its window, but without any signal, is listed
  for a person (`amount_only`, its own `reconcile:amount_only:...` to-do, status `amount_only`), never proposed; not for
  a converted card amount (the band admits chance matches) and not beside a proposed pair of its line or invoice.
- A **learnt name** is a signal (`learned_name`): a person's confirmation ties the line's counterparty name, without its
  reference numbers (`name_key`), to the invoice's supplier (`supplier_keys`); a later line of that name and an invoice
  of that supplier are tied by it. A line through a payment app teaches nothing, as the app pays many suppliers.

Reuse: ported selectively from the legacy project's `orchestrator/framework/payables.py` 0.1.1 (10_AIFLOW_V4, HEAD
4256cba): `normalize`, `account_key`, the canonical money rule, the reason-coded exclusions, the three signals, "an equal
amount alone is no candidate" and the multiple-candidates flag; its 12 synthetic cases are rewritten in the golden file.
Not ported: the owner aliases (the own accounts come from the statements), the allocation arithmetic and the Postgres
review store. New: the exact-amount rule, the window's upper end, coverage by verified statements, stable line ids.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from jav import cfg, duplicates, fact_checks, fx, store

ENGINE_VERSION = "1.3.0"
STATUSES = ("confirmed", "proposed", "amount_only", "amount_differs", "rate_missing", "no_payment_found", "partly_covered",
            "not_covered", "excluded")
RELATIONS = ("equal", "different", "fx_within", "fx_outside", "no_rate")  # how a candidate's amounts relate
DECISIONS = ("paid_by", "not_this")
SIGNALS = ("invoice_number", "supplier_account", "supplier_name", "payment_channel", "learned_name")
KINDS = ("proposed", "amount_only")  # the to-do of a proposed pair and of a pair listed for its equal amount alone
REASON = "reconcile"
PRODUCER = "reconcile"  # the producer of the to-dos opened by `scan`; the flow's own ones are the M2 step's
PREFIX = 16  # the invoice's id prefix in the to-do (as in `duplicates`)
_MONEY = re.compile(r"-?\d+(?:\.\d{1,2})?")

store.register_schema("reconcile", """
CREATE TABLE IF NOT EXISTS reconcile_decisions (
    pair_key          TEXT PRIMARY KEY,   -- the invoice's document id + '|' + the line id: one decision per pair
    invoice_doc_id    TEXT NOT NULL,
    statement_doc_id  TEXT NOT NULL,
    line_id           TEXT NOT NULL,      -- the statement line's stable id (`line_id`)
    decision          TEXT NOT NULL,      -- paid_by | not_this
    signals           TEXT,               -- JSON: the signals of the pair when the person decided
    amount_relation   TEXT,               -- equal | different: the amounts when the person decided
    run_id            TEXT,               -- the run in which the person decided
    actor             TEXT NOT NULL,
    note              TEXT,
    decided_at        TEXT NOT NULL
);
""")


class DecisionError(ValueError):
    """A decision that cannot be recorded (unknown decision, a rejection without a reason, a pair the item is not part
    of, a second payment for one line or one invoice)."""


@lru_cache(maxsize=None)
def _conf() -> dict[str, Any]:
    return dict(cfg.load("reconcile"))


def config_hash() -> str:
    return cfg.config_hash("reconcile")


@lru_cache(maxsize=None)
def _ignore_tokens() -> frozenset[str]:
    """The legal forms and filler words a party name is compared without (shared with `fact_checks.same_party`)."""
    return frozenset(cfg.load("fact_checks")["parties"]["ignore_tokens"])


# --- normalisation (legacy payables.py) ----------------------------------------------------------------------------


def normalize(value: Any) -> str:
    """Lower-case ASCII words joined by single spaces: "INV-001/A" -> "inv 001 a"."""
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in text if not unicodedata.combining(c))))


def compact(value: Any) -> str:
    return normalize(value).replace(" ", "")


def name_key(value: Any) -> str | None:
    """A line's counterparty name without its reference numbers and single letters, so the monthly lines of one merchant
    share it: "EXAMPLETEL*12345 BUDAPEST" -> "exampletel budapest" (131); None when nothing is left."""
    words = [w for w in normalize(value).split() if len(w) > 1 and not any(ch.isdigit() for ch in w)]
    return " ".join(words) or None


def supplier_keys(invoice: dict[str, Any]) -> set[str]:
    """The keys a learnt name is tied to: the supplier's tax number and its name without legal forms and numbers, so an
    invoice that lacks one of them still finds the name (131)."""
    keys = set()
    if tax := fact_checks.tax_party_key(invoice.get("supplier_tax_id")):
        keys.add("tax:" + tax)
    words = [w for w in normalize(invoice.get("supplier_name")).split()
             if w not in _ignore_tokens() and not any(ch.isdigit() for ch in w)]
    if words:
        keys.add(" ".join(words))
    return keys


def account_key(value: Any) -> str:
    """One key for one account: a Hungarian IBAN and its 24-digit domestic number are the same, and a 16-digit domestic
    number is its 24-digit form; anything shorter than 16 characters is no account."""
    text = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if re.fullmatch(r"HU\d{26}", text):
        return text[4:]
    if re.fullmatch(r"\d{16}", text):
        return text + "00000000"
    return text if len(text) >= 16 else ""


def money(value: Any) -> Decimal:
    """Only a canonical decimal string ("1234.5", "-10"); a separator is never guessed and nothing is rounded."""
    if not isinstance(value, str) or not _MONEY.fullmatch(value):
        raise ValueError("canonical money string required")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid amount") from exc
    if not amount.is_finite():
        raise ValueError("finite amount required")
    return amount


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def line_id(statement_id: str, line: dict[str, Any], occurrence: int = 0) -> str:
    """A statement line's stable id: its statement, a digest of its content and its occurrence among identical lines.
    A re-extraction that inserts or drops another line does not shift it, unlike its position in the list."""
    content = [str(line.get(k) or "") for k in ("booking_date", "direction", "amount", "counterparty_name",
                                                   "counterparty_account", "memo", "description")]
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
    return f"{statement_id[:16]}:{digest}:{occurrence}"


def with_line_ids(statement_id: str, lines: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, int] = defaultdict(int)
    out = []
    for line in lines:
        base = line_id(statement_id, line)
        occurrence = seen[base]
        seen[base] += 1
        out.append({**line, "id": line_id(statement_id, line, occurrence)})
    return out


# --- the pure core -------------------------------------------------------------------------------------------------


def _ids(rows: Iterable[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("id") or "")
        if not key or key in out:
            raise ValueError(f"missing or duplicate {kind} id")
        out[key] = row
    return out


def statement_account(statement: dict[str, Any]) -> str:
    """The own account a statement belongs to: its account key, else its printed account, else the statement itself."""
    key = account_key(statement.get("account"))
    return key or ("raw:" + compact(statement.get("account")) if compact(statement.get("account")) else "doc:" + str(statement["id"]))


def _payments(statements: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Every line as a payment row carrying its statement's account, currency and verification."""
    rows = []
    for sid, st in sorted(statements.items()):
        for line in st.get("lines") or []:
            rows.append({**line, "statement_id": sid, "own_account": statement_account(st), "currency": st.get("currency"),
                         "statement_type": st.get("statement_type"), "statement_verified": bool(st.get("verified"))})
    return _ids(rows, "line")


def _identity(invoice: dict[str, Any]) -> tuple[str, str, str] | None:
    number = duplicates.number_key(invoice.get("number"))
    supplier = fact_checks.tax_party_key(invoice.get("supplier_tax_id")) or normalize(invoice.get("supplier_name"))
    if not number or not supplier or not invoice.get("currency"):
        return None
    return supplier, number, str(invoice["currency"])


def _amount_reason(value: Any) -> str | None:
    if value in (None, ""):
        return "missing_amount"
    try:
        return "non_positive_amount" if money(value) <= 0 else None
    except ValueError:
        return "invalid_amount"


def prepare(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Sorts the invoices and the lines into eligible and excluded (with a reason code) before any pairing."""
    conf = _conf()
    currencies = set(conf["currencies"])
    invoices = _ids(snapshot.get("invoices", []), "invoice")
    statements = _ids(snapshot.get("statements", []), "statement")
    payments = _payments(statements)
    own_accounts = {statement_account(st) for st in statements.values()}
    review = re.compile(conf["payment_review_pattern"])
    identities: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for key, inv in invoices.items():
        ident = _identity(inv)
        if ident and inv.get("duplicate") is None:  # a person's duplicate decision settles the pair
            identities[ident].append(key)
    clashing = {k for keys in identities.values() if len(keys) > 1 for k in keys}
    eligible_invoices, eligible_payments, excluded = {}, {}, []
    for key, inv in sorted(invoices.items()):
        reason = _amount_reason(inv.get("amount"))
        if inv.get("currency") not in currencies:
            reason = "unsupported_currency"
        if not _date(inv.get("issue_date")):
            reason = "missing_issue_date"
        if inv.get("doc_type") in conf["outgoing_types"]:
            reason = "outgoing_invoice"
        if inv.get("duplicate") == "copy":
            reason = "duplicate_copy"
        elif key in clashing:
            reason = "duplicate_undecided"
        if reason:
            excluded.append({"kind": "invoice", "id": key, "reason": reason})
        else:
            eligible_invoices[key] = inv
    for key, pay in sorted(payments.items()):
        reason = _amount_reason(pay.get("amount"))
        if pay.get("currency") not in currencies:
            reason = "unsupported_currency"
        if not _date(pay.get("booking_date")):
            reason = "missing_booking_date"
        if pay.get("direction") != "debit":
            reason = "not_outgoing_payment"
        elif account_key(pay.get("counterparty_account")) and account_key(pay.get("counterparty_account")) in own_accounts:
            reason = "own_account_transfer"
        elif review.search(normalize(f"{pay.get('description') or ''} {pay.get('memo') or ''}")):
            reason = "payment_kind_review"
        if reason:
            excluded.append({"kind": "line", "id": key, "reason": reason})
        else:
            eligible_payments[key] = pay
    return {"invoices": eligible_invoices, "payments": eligible_payments, "excluded": excluded,
            "statements": statements, "own_accounts": sorted(own_accounts), "lines": payments}


def _settled(snapshot: dict[str, Any], prepared: dict[str, Any]) -> tuple[set[tuple[str, str]], list[dict[str, Any]]]:
    """The people's decisions in the snapshot: the rejected pairs, and the confirmed pairs whose invoice is eligible and
    whose line still exists (a decision on a line a re-extraction removed changes nothing). One line pays one invoice:
    of two confirmations sharing a line or an invoice, the first in order counts."""
    rejected: set[tuple[str, str]] = set()
    confirmed: list[dict[str, Any]] = []
    used_lines: set[str] = set()
    used_invoices: set[str] = set()
    for d in sorted(snapshot.get("decisions") or [], key=lambda d: (str(d["invoice_id"]), str(d["line_id"]))):
        pair = (str(d["invoice_id"]), str(d["line_id"]))
        if d["decision"] == "not_this":
            rejected.add(pair)
        elif (d["decision"] == "paid_by" and pair[0] in prepared["invoices"] and pair[1] in prepared["lines"]
              and pair[0] not in used_invoices and pair[1] not in used_lines):
            used_invoices.add(pair[0])
            used_lines.add(pair[1])
            confirmed.append({"invoice_id": pair[0], "line_id": pair[1], "statement_id": prepared["lines"][pair[1]]["statement_id"]})
    return rejected, confirmed


def window(invoice: dict[str, Any]) -> tuple[date, date]:
    """The days a payment of the invoice is searched in."""
    w = _conf()["window"]
    issue = _date(invoice["issue_date"])
    end = _date(invoice.get("due_date")) or issue
    return issue - timedelta(days=int(w["days_before_issue"])), max(end, issue) + timedelta(days=int(w["days_after_due"]))


def _line_text(payment: dict[str, Any]) -> str:
    return normalize(f"{payment.get('counterparty_name') or ''} {payment.get('description') or ''} {payment.get('memo') or ''}")


def through_app(payment: dict[str, Any]) -> bool:
    """Whether the line names the payment app of a configured channel (131): such a line pays many suppliers."""
    text = _line_text(payment)
    return any(re.search(ch["line_text"], text) for ch in _conf()["payment_channels"])


def _channel(invoice: dict[str, Any], payment: dict[str, Any]) -> bool:
    """The invoice's payment method fits a channel and the line names that channel's payment app (131)."""
    method, text = normalize(invoice.get("payment_method")), _line_text(payment)
    return bool(method) and any(re.search(ch["invoice_method"], method) and re.search(ch["line_text"], text)
                                for ch in _conf()["payment_channels"])


def signals(invoice: dict[str, Any], payment: dict[str, Any], learned: set[tuple[str, str]] | None = None) -> list[str]:
    """The facts that tie a line to an invoice; the amount is never one of them. `learned`: the (name key, supplier key)
    pairs of a person's confirmations (`learned_names`)."""
    s = _conf()["signals"]
    found = []
    text = f"{payment.get('memo') or ''} {payment.get('description') or ''}"
    number, text_n = normalize(invoice.get("number")), normalize(text)
    number_c = compact(invoice.get("number"))
    if len(number_c) >= int(s["min_number_chars"]) and (
            re.search(r"(?<![a-z0-9])" + re.escape(number) + r"(?![a-z0-9])", text_n)
            or (len(number_c) >= int(s["min_compact_number_chars"]) and number_c in compact(text))):
        found.append("invoice_number")
    account = account_key(invoice.get("payment_account"))
    if account and account == account_key(payment.get("counterparty_account")):
        found.append("supplier_account")
    supplier = set(normalize(invoice.get("supplier_name")).split()) - _ignore_tokens()
    counterparty = set(normalize(payment.get("counterparty_name") or payment.get("description")).split())
    if supplier and len(supplier & counterparty) / len(supplier) >= float(s["min_name_share"]):
        found.append("supplier_name")
    if _channel(invoice, payment):
        found.append("payment_channel")
    key = name_key(payment.get("counterparty_name"))
    if learned and key and any((key, sk) in learned for sk in supplier_keys(invoice)):
        found.append("learned_name")
    return found


def _learned(prepared: dict[str, Any], confirmed: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """The (name key, supplier key) pairs confirmed at least `learning.min_confirmations` times; a line through a
    payment app or without a counterparty name teaches nothing (131)."""
    counts: Counter[tuple[str, str]] = Counter()
    for c in confirmed:
        line, invoice = prepared["lines"][c["line_id"]], prepared["invoices"][c["invoice_id"]]
        key = name_key(line.get("counterparty_name"))
        if key is None or through_app(line):
            continue
        counts.update((key, sk) for sk in supplier_keys(invoice))
    least = int(_conf()["learning"]["min_confirmations"])
    return {pair for pair, n in counts.items() if n >= least}


def learned_names(snapshot: dict[str, Any]) -> set[tuple[str, str]]:
    """The names a snapshot's confirmations teach (`_learned`), for the views that show a pair's signals."""
    prepared = prepare(snapshot)
    return _learned(prepared, _settled(snapshot, prepared)[1])


def fx_capable(payment: dict[str, Any]) -> bool:
    """Whether a line can pay an invoice of another currency: a forint line of a card statement (130)."""
    f = _conf()["fx"]
    return payment.get("currency") == f["line_currency"] and payment.get("statement_type") in f["statement_types"]


def fx_window(invoice: dict[str, Any]) -> tuple[date, date]:
    """The days a card payment of the invoice is searched in: around its issue date (the day of the purchase)."""
    w = _conf()["fx"]["window"]
    issue = _date(invoice["issue_date"])
    return issue - timedelta(days=int(w["days_before_issue"])), issue + timedelta(days=int(w["days_after_issue"]))


def rate_need(invoice: dict[str, Any]) -> tuple[str, date] | None:
    """The (currency, day) whose rate a card pair of the invoice needs: its currency on its issue date."""
    issue = _date(invoice.get("issue_date"))
    currency = invoice.get("currency")
    if not issue or not currency or currency == _conf()["fx"]["line_currency"]:
        return None
    return str(currency), issue


def convert(invoice: dict[str, Any], payment: dict[str, Any], rates: dict[str, Any] | None) -> tuple[str, dict[str, str] | None]:
    """The relation of a card line to an invoice of another currency (`fx_within`, `fx_outside` or `no_rate`) and the
    conversion behind it: the rate and its day, the converted amount and the line's deviation from it."""
    from jav import policy

    need = rate_need(invoice)
    entry = (rates or {}).get(need[0], {}).get(need[1].isoformat()) if need else None
    if not entry:
        return "no_rate", None
    per_unit = Decimal(str(entry["rate"]))
    expected = money(str(invoice["amount"])) * per_unit
    deviation = money(str(payment["amount"])) / expected - 1
    below, above = policy.reconcile_fx_tolerance()
    relation = "fx_within" if -below <= deviation <= above else "fx_outside"
    return relation, {"rate": str(entry["rate"]), "rate_day": str(entry["rate_day"]), "source": str(entry.get("source") or "mnb"),
                      "converted": str(expected.quantize(Decimal("0.01"))), "deviation": str(deviation.quantize(Decimal("0.0001")))}


def amount_relation(invoice: dict[str, Any], payment: dict[str, Any], rates: dict[str, Any] | None = None
                    ) -> tuple[str | None, dict[str, str] | None]:
    """How a line's amount relates to an invoice's: `equal` / `different` in one currency, the conversion for a card
    line of another currency (`convert`), None when the amounts cannot be compared."""
    try:
        if invoice.get("currency") == payment.get("currency"):
            return ("equal" if money(str(payment.get("amount"))) == money(str(invoice.get("amount"))) else "different"), None
        if fx_capable(payment) and rate_need(invoice):
            return convert(invoice, payment, rates)
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return None, None
    return None, None


def _merge(intervals: Iterable[tuple[date, date]]) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1] + timedelta(days=1):
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def coverage(statements: dict[str, dict[str, Any]]) -> dict[tuple[str, str], list[tuple[date, date]]]:
    """Per own account and currency, the merged periods of its verified statements; an account whose statements are
    all unverified is present with no period, so it still counts as an account to cover."""
    periods: dict[tuple[str, str], list[tuple[date, date]]] = defaultdict(list)
    for st in statements.values():
        key = (statement_account(st), str(st.get("currency")))
        periods.setdefault(key, [])
        start, end = _date(st.get("period_start")), _date(st.get("period_end"))
        if st.get("verified") and start and end and start <= end:
            periods[key].append((start, end))
    return {k: _merge(v) for k, v in periods.items()}


def _covered(periods: list[tuple[date, date]], start: date, end: date) -> str:
    """full / partial / none: how much of [start, end] the merged periods cover."""
    if any(a <= start and end <= b for a, b in periods):
        return "full"
    return "partial" if any(a <= end and start <= b for a, b in periods) else "none"


def propose(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The proposal for a snapshot: candidate pairs, exclusions, every invoice's status and the unpaired lines. The
    snapshot's `decisions` (a person's `paid_by` / `not_this` per invoice and line) settle their pairs first."""
    prepared = prepare(snapshot)
    rejected, confirmed = _settled(snapshot, prepared)
    learned = _learned(prepared, confirmed)
    paid_invoices = {c["invoice_id"] for c in confirmed}
    paid_lines = {c["line_id"] for c in confirmed}
    rates = snapshot.get("fx_rates") or {}
    amount_only = bool(_conf()["amount_only"]["enabled"])
    candidates = []
    for pid, pay in sorted(prepared["payments"].items()):
        if pid in paid_lines:
            continue
        booked = _date(pay["booking_date"])
        for iid, inv in sorted(prepared["invoices"].items()):
            if iid in paid_invoices or (iid, pid) in rejected:
                continue
            same = inv["currency"] == pay["currency"]
            if not same and not (fx_capable(pay) and rate_need(inv)):
                continue
            start, end = window(inv) if same else fx_window(inv)
            if not start <= booked <= end:
                continue
            found = signals(inv, pay, learned)
            relation, conversion = amount_relation(inv, pay, rates)
            if found == ["payment_channel"] and relation not in ("equal", "fx_within"):
                continue  # a payment app pays many bills: its channel alone says nothing about another amount (131)
            if not found and not (amount_only and relation == "equal"):
                continue  # a converted amount alone ties nothing; an equal one is only listed for a person (131)
            candidate = {"line_id": pid, "invoice_id": iid, "statement_id": pay["statement_id"], "currency": inv["currency"],
                         "line_currency": pay["currency"], "amount_relation": relation,
                         "proposed": bool(found) and relation in ("equal", "fx_within"), "amount_only": not found,
                         "signals": found, "source_review_required": not pay["statement_verified"]}
            if conversion is not None:
                candidate["fx"] = conversion
            candidates.append(candidate)
    proposed_lines = {c["line_id"] for c in candidates if c["proposed"]}
    proposed_invoices = {c["invoice_id"] for c in candidates if c["proposed"]}
    candidates = [c for c in candidates if not c["amount_only"]
                  or (c["line_id"] not in proposed_lines and c["invoice_id"] not in proposed_invoices)]
    per_line, per_invoice = defaultdict(int), defaultdict(int)
    open_line, open_invoice = defaultdict(int), defaultdict(int)  # the pairs waiting for a person: proposed or equal amount
    for c in candidates:
        if c["proposed"]:
            per_line[c["line_id"]] += 1
            per_invoice[c["invoice_id"]] += 1
        if c["proposed"] or c["amount_only"]:
            open_line[c["line_id"]] += 1
            open_invoice[c["invoice_id"]] += 1
    for c in candidates:
        c["multiple_candidates"] = ((c["proposed"] and (per_line[c["line_id"]] > 1 or per_invoice[c["invoice_id"]] > 1))
                                    or (c["amount_only"] and (open_line[c["line_id"]] > 1 or open_invoice[c["invoice_id"]] > 1)))
    periods = coverage(prepared["statements"])
    f = _conf()["fx"]
    card_accounts = {(statement_account(st), str(st.get("currency"))) for st in prepared["statements"].values()
                     if st.get("statement_type") in f["statement_types"] and st.get("currency") == f["line_currency"]}
    statuses = []
    for iid, inv in sorted(prepared["invoices"].items()):
        mine = [c for c in candidates if c["invoice_id"] == iid]
        signed = [c for c in mine if not c["amount_only"]]
        start, end = window(inv)
        cover = [_covered(p, start, end) for (_acct, cur), p in periods.items() if cur == inv["currency"]]
        if rate_need(inv):  # a card account can pay it too, in the card window
            fx_start, fx_end = fx_window(inv)
            cover += [_covered(periods[key], fx_start, fx_end) for key in sorted(card_accounts)]
        if iid in paid_invoices:
            status = "confirmed"
        elif any(c["proposed"] for c in mine):
            status = "proposed"
        elif len(signed) < len(mine):
            status = "amount_only"
        elif any(c["amount_relation"] != "no_rate" for c in signed):
            status = "amount_differs"
        elif signed:
            status = "rate_missing"
        elif cover and all(c == "full" for c in cover):
            status = "no_payment_found"
        elif any(c != "none" for c in cover):
            status = "partly_covered"
        else:
            status = "not_covered"
        statuses.append({"invoice_id": iid, "status": status, "window": [start.isoformat(), end.isoformat()]})
    for e in prepared["excluded"]:
        if e["kind"] == "invoice":
            statuses.append({"invoice_id": e["id"], "status": "excluded", "reason": e["reason"]})
    paired = {c["line_id"] for c in candidates if c["proposed"]} | paid_lines
    from jav import policy

    below, above = policy.reconcile_fx_tolerance()
    return {"engine_version": ENGINE_VERSION, "config_hash": config_hash(), "fx_tolerance": [str(below), str(above)],
            "candidates": candidates, "learned_names": len(learned),
            "confirmed": confirmed, "excluded": prepared["excluded"],
            "invoices": sorted(statuses, key=lambda s: s["invoice_id"]),
            "unpaired_line_ids": sorted(set(prepared["payments"]) - paired),
            "coverage": [{"account": a, "currency": c, "periods": [[s.isoformat(), e.isoformat()] for s, e in p]}
                         for (a, c), p in sorted(periods.items())]}


# --- the store adapter (read-only) ---------------------------------------------------------------------------------


def _has_table(c, name: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def verified(validation: Any) -> bool:
    """Whether a statement's lines are complete by its balance checks (`verified_when`)."""
    if isinstance(validation, str):
        try:
            validation = json.loads(validation)
        except ValueError:
            return False
    results = {r.get("name"): r for r in validation or [] if isinstance(r, dict)}
    return all(name in results and results[name].get("ok") is True and results[name].get("code") in codes
               for name, codes in _conf()["verified_when"].items())


def _latest(types: list[str]) -> list[dict[str, Any]]:
    """The latest result of every document of the given types, with the latest correction of its run item. A store
    without the work tables (a measurement store) has no run items and no corrections."""
    with store.connect() as c:
        work = _has_table(c, "run_items")
        item = ("ri.run_id AS work_run, ri.item_id" if work else "NULL AS work_run, NULL AS item_id")
        join = (" LEFT JOIN run_items ri ON ri.flow_run_id = d.run_id AND ri.item_id = d.doc_id" if work else "")
        rows = c.execute(
            f"SELECT d.rowid AS seq, d.run_id AS flow_run_id, d.doc_id, d.doc_type, d.datapoints, d.validation, {item}"
            " FROM datapoints d JOIN (SELECT doc_id, MAX(rowid) AS m FROM datapoints GROUP BY doc_id) l ON l.m = d.rowid"
            f"{join} WHERE d.doc_type IN ({','.join('?' * len(types))}) ORDER BY d.rowid", types).fetchall()
        corrected: dict[tuple[str, str], dict[str, Any]] = {}
        if work and _has_table(c, "run_item_corrections"):
            for r in c.execute("SELECT c.run_id, c.item_id, c.fields FROM run_item_corrections c JOIN"
                               " (SELECT run_id, item_id, MAX(revision) AS m FROM run_item_corrections GROUP BY run_id, item_id) l"
                               " ON l.run_id = c.run_id AND l.item_id = c.item_id AND l.m = c.revision"):
                corrected[(r["run_id"], r["item_id"])] = json.loads(r["fields"])
    out = []
    for r in rows:
        values = json.loads(r["datapoints"] or "{}")
        values.update(corrected.get((r["work_run"], r["item_id"])) or {})
        out.append({"doc_id": r["doc_id"], "doc_type": r["doc_type"], "values": values, "validation": r["validation"],
                    "seq": int(r["seq"]), "flow_run_id": r["flow_run_id"], "work_run": r["work_run"], "item_id": r["item_id"]})
    return out


def _amount(values: dict[str, Any]) -> str | None:
    """The amount to pay: the first of the configured fields with a positive canonical amount, else the last present."""
    present = [values.get(f) for f in _conf()["invoice_fields"]["amount"] if values.get(f) not in (None, "")]
    for value in present:
        try:
            if money(str(value)) > 0:
                return str(value)
        except ValueError:
            continue
    return str(present[-1]) if present else None


def _duplicate_marks() -> dict[str, str]:
    """The duplicate decisions as invoice marks: the repeat of a confirmed copy is `copy`; both documents of a pair a
    person called different (or a modified version) are `distinct`."""
    marks: dict[str, str] = {}
    with store.connect() as c:
        if not _has_table(c, "duplicate_decisions"):
            return marks
        for r in c.execute("SELECT doc_id, other_doc_id, decision FROM duplicate_decisions"):
            if r["decision"] == "copy":
                marks[r["doc_id"]] = "copy"
            else:
                marks.setdefault(r["doc_id"], "distinct")
                marks.setdefault(r["other_doc_id"], "distinct")
    return marks


def _origin(d: dict[str, Any]) -> dict[str, Any]:
    """Where a document's values come from: the order of processing and its flow and work run (not used by `propose`)."""
    return {"seq": d.get("seq", 0), "flow_run_id": d.get("flow_run_id"), "work_run": d.get("work_run"), "item_id": d.get("item_id")}


def _decision_rows(c=None) -> list[dict[str, Any]]:
    if c is None:
        with store.connect() as own:
            return _decision_rows(own)
    if not _has_table(c, "reconcile_decisions"):
        return []
    return [dict(r) for r in c.execute("SELECT * FROM reconcile_decisions ORDER BY pair_key")]


def handles(doc_type: str | None) -> bool:
    """Whether a document of this type takes part in the reconciliation as an incoming invoice or a statement."""
    conf = _conf()
    return doc_type in conf["invoice_types"] or doc_type in conf["statement_types"]


def snapshot(current: dict[str, Any] | None = None, *, fetch_rates: bool = False) -> dict[str, Any]:
    """The store's effective invoices and statements, the people's decisions and the exchange rates a card pair needs,
    as a snapshot for `propose`. `current` (doc_id, doc_type, values, validation): the document being processed, in
    place of its stored result. `fetch_rates`: fetch the missing MNB rates first (the processing and the command line);
    a view only reads the stored ones."""
    conf = _conf()
    f = conf["invoice_fields"]
    marks = _duplicate_marks()
    docs = _latest([*conf["invoice_types"], *conf["outgoing_types"], *conf["statement_types"]])
    if current is not None:
        docs = [d for d in docs if d["doc_id"] != current["doc_id"]]
        docs.append({**current, "seq": max((d["seq"] for d in docs), default=0) + 1})
    invoices, statements = [], []
    for d in docs:
        v = d["values"]
        if d["doc_type"] in conf["statement_types"]:
            lines = [t for t in v.get("transactions") or [] if isinstance(t, dict)]
            statements.append({"id": d["doc_id"], "doc_type": d["doc_type"], "account": v.get("account_iban") or v.get("account_no"),
                               "currency": v.get("currency"), "statement_type": v.get("statement_type"),
                               "period_start": v.get("period_start"), "period_end": v.get("period_end"),
                               "verified": verified(d["validation"]), "lines": with_line_ids(d["doc_id"], lines), **_origin(d)})
        else:
            invoices.append({"id": d["doc_id"], "doc_type": d["doc_type"], "number": v.get(f["number"]),
                             "supplier_name": v.get(f["supplier_name"]), "supplier_tax_id": v.get(f["supplier_tax_id"]),
                             "payment_account": v.get(f["payment_account"]), "payment_method": v.get(f["payment_method"]),
                             "amount": _amount(v),
                             "currency": v.get(f["currency"]), "issue_date": v.get(f["issue_date"]),
                             "due_date": v.get(f["due_date"]), "duplicate": marks.get(d["doc_id"]), **_origin(d)})
    decisions = [{"invoice_id": r["invoice_doc_id"], "line_id": r["line_id"], "decision": r["decision"]} for r in _decision_rows()]
    f = conf["fx"]
    cards = any(s.get("statement_type") in f["statement_types"] and s.get("currency") == f["line_currency"] for s in statements)
    needs = {n for inv in invoices if (n := rate_need(inv)) and inv.get("currency") in conf["currencies"]} if cards else set()
    rates = fx.table(needs, fetch_missing=fetch_rates) if needs else {}
    return {"invoices": invoices, "statements": statements, "decisions": decisions, "fx_rates": rates}


# --- the to-do and the person's decision (129, K2) -------------------------------------------------------------------


def reason(invoice_id: str, line: str, kind: str = "proposed") -> str:
    """The to-do of a pair: its kind (`KINDS`: proposed, or listed for its equal amount alone), the invoice by its id
    prefix and the line by its stable id."""
    if kind not in KINDS:
        raise ValueError(f"unknown reconciliation to-do kind: {kind}")
    return f"{REASON}:{kind}:{invoice_id[:PREFIX]}:{line}"


def _kind(candidate: dict[str, Any]) -> str:
    return "amount_only" if candidate["amount_only"] else "proposed"


def _waits(candidate: dict[str, Any]) -> bool:
    """Whether a candidate waits for a person: proposed, or listed for its equal amount alone (131)."""
    return candidate["proposed"] or candidate["amount_only"]


def parse_reason(code: str) -> tuple[str, str] | None:
    """(the invoice's id prefix, the line id) of a reconciliation to-do of either kind; None for any other to-do."""
    parts = code.split(":")
    if len(parts) == 6 and parts[0] == REASON and parts[1] in KINDS and parts[2]:
        return parts[2], ":".join(parts[3:])
    return None


def pair_key(invoice_id: str, line: str) -> str:
    return f"{invoice_id}|{line}"


def review_reasons(doc_id: str | None, doc_type: str | None, values: dict[str, Any], validation: Any) -> list[str]:
    """The reconciliation to-dos of the document being processed: every proposed pair it is a side of, and every pair
    listed for its equal amount alone (131), against the store, in a worker run only (as `duplicates.review_reasons`). A
    decided pair adds nothing."""
    if not duplicates.enabled() or not doc_id or not handles(doc_type):
        return []
    snap = snapshot({"doc_id": doc_id, "doc_type": doc_type, "values": values, "validation": validation}, fetch_rates=True)
    if not snap["statements"] or not snap["invoices"]:
        return []
    return [reason(c["invoice_id"], c["line_id"], _kind(c)) for c in propose(snap)["candidates"]
            if _waits(c) and doc_id in (c["invoice_id"], c["statement_id"])]


def decisions_for(doc_ids: Iterable[str], c=None) -> list[dict[str, Any]]:
    """The decisions on the pairs that have any of the documents as a side, in a fixed order."""
    ids = set(doc_ids)
    return [d for d in _decision_rows(c) if d["invoice_doc_id"] in ids or d["statement_doc_id"] in ids] if ids else []


def _find_line(snap: dict[str, Any], line: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    for st in snap["statements"]:
        for ln in st["lines"]:
            if ln["id"] == line:
                return st, ln
    return None


def _open_to_dos(c) -> list[dict[str, Any]]:
    return [dict(r) for r in c.execute(
        "SELECT r.id, r.reason, q.subject_id FROM review_reasons r JOIN review_queue q ON q.id = r.review_id"
        " WHERE q.subject_kind='document' AND r.status='open' AND r.reason LIKE ? ORDER BY r.id", (f"{REASON}:%",))
        if parse_reason(r["reason"]) is not None]


def decide(run_id: str, item_id: str, invoice_doc_id: str, line: str, *, decision: str, actor: str,
           note: str | None = None) -> dict[str, Any]:
    """A person's decision on a pair, made on a run's item (the invoice or the statement): `paid_by` ("this line paid
    it") or `not_this` (with a reason). One decision per pair; it may be changed until the run it was made in is
    approved. The pair's open to-dos close; a confirmation also closes the to-dos of the other pairs of its line and its
    invoice, as one line pays one invoice. Frozen on an approved run (`work.RevisionConflict`), checked again in the
    writing transaction, as `duplicates.decide`."""
    from jav import work

    if decision not in DECISIONS:
        raise DecisionError(f"unknown reconciliation decision: {decision}")
    note = (note or "").strip() or None
    if decision == "not_this" and note is None:
        raise DecisionError("a rejected pair needs a reason")
    run = work.get_run(run_id)
    if run["approval"]:
        raise work.RevisionConflict(f"run {run_id} is approved; reconciliation decisions are frozen")
    if not any(i["item_id"] == item_id and i.get("kind") != "email" for i in run["input"]["items"]):
        raise KeyError(item_id)
    snap = snapshot()
    invoice = next((i for i in snap["invoices"] if i["id"] == invoice_doc_id), None)
    if invoice is None:
        raise KeyError(invoice_doc_id)
    found = _find_line(snap, line)
    if found is None:
        raise KeyError(line)
    statement, row = found
    if item_id not in (invoice_doc_id, statement["id"]):
        raise DecisionError("the item is neither the invoice nor the statement of the pair")
    if invoice["doc_type"] in _conf()["outgoing_types"]:
        raise DecisionError("an outgoing invoice is not paid from an own account")
    key = pair_key(invoice_doc_id, line)
    pay = {**row, "currency": statement.get("currency"), "statement_type": statement.get("statement_type")}
    with store.connect() as c:
        store.begin_immediate(c)
        approved = c.execute("SELECT approval FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if approved is not None and approved["approval"]:
            raise work.RevisionConflict(f"run {run_id} is approved; reconciliation decisions are frozen")
        before = c.execute("SELECT run_id FROM reconcile_decisions WHERE pair_key=?", (key,)).fetchone()
        if before is not None and before["run_id"] != run_id:
            owner = c.execute("SELECT approval FROM runs WHERE run_id=?", (before["run_id"],)).fetchone()
            if owner is not None and owner["approval"]:
                raise work.RevisionConflict("the pair was decided in an approved run; the decision is frozen")
        if decision == "paid_by" and c.execute(
                "SELECT 1 FROM reconcile_decisions WHERE decision='paid_by' AND pair_key<>? AND (line_id=? OR invoice_doc_id=?)",
                (key, line, invoice_doc_id)).fetchone():
            raise DecisionError("the line or the invoice is already paired; reject that pair first")
        c.execute("INSERT INTO reconcile_decisions(pair_key, invoice_doc_id, statement_doc_id, line_id, decision, signals,"
                  " amount_relation, run_id, actor, note, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
                  " ON CONFLICT(pair_key) DO UPDATE SET decision=excluded.decision, signals=excluded.signals,"
                  " amount_relation=excluded.amount_relation, run_id=excluded.run_id, actor=excluded.actor,"
                  " note=excluded.note, decided_at=excluded.decided_at",
                  (key, invoice_doc_id, statement["id"], line, decision, json.dumps(signals(invoice, pay, learned_names(snap))),
                   amount_relation(invoice, pay, snap.get("fx_rates"))[0],
                   run_id, actor, note, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        to_dos = _open_to_dos(c)
    for r in to_dos:
        parsed = parse_reason(r["reason"])
        if parsed is None:
            continue
        same_line, same_invoice = parsed[1] == line, invoice_doc_id.startswith(parsed[0])
        if same_line and same_invoice:
            work.resolve_reason(r["id"], actor=actor, resolution={"reconcile": decision, "pair": key}, note=note)
        elif decision == "paid_by" and (same_line or same_invoice):
            work.resolve_reason(r["id"], actor=actor, resolution={"reconcile": "superseded", "pair": key}, note=note)
    return next(d for d in _decision_rows() if d["pair_key"] == key)


# --- views (129, K2) ---------------------------------------------------------------------------------------------------


def _file_names(doc_ids: Iterable[str]) -> dict[str, str]:
    ids = sorted(set(doc_ids))
    if not ids:
        return {}
    out: dict[str, str] = {}
    with store.connect() as c:
        for start in range(0, len(ids), 500):  # stays under the SQLite parameter limit
            chunk = ids[start:start + 500]
            for r in c.execute(f"SELECT doc_id, source_path FROM documents WHERE doc_id IN ({','.join('?' * len(chunk))})", chunk):
                out[r["doc_id"]] = Path(r["source_path"] or "").name
    return out


def _packages(runs: Iterable[str | None]) -> dict[str, str]:
    ids = sorted({r for r in runs if r})
    if not ids:
        return {}
    with store.connect() as c:
        if not _has_table(c, "runs"):
            return {}
        return {r["run_id"]: r["workpackage_id"] for r in c.execute(
            f"SELECT run_id, workpackage_id FROM runs WHERE run_id IN ({','.join('?' * len(ids))})", ids)}


def _invoice_view(inv: dict[str, Any] | None, files: dict[str, str]) -> dict[str, Any] | None:
    if inv is None:
        return None
    return {"number": inv.get("number"), "supplier": inv.get("supplier_name"), "amount": inv.get("amount"),
            "currency": inv.get("currency"), "issue_date": inv.get("issue_date"), "due_date": inv.get("due_date"),
            "file": files.get(inv["id"])}


def _line_view(found: tuple[dict[str, Any], dict[str, Any]] | None, files: dict[str, str]) -> dict[str, Any] | None:
    if found is None:
        return None
    st, ln = found
    return {"booking_date": ln.get("booking_date"), "direction": ln.get("direction"), "amount": ln.get("amount"),
            "currency": st.get("currency"), "counterparty_name": ln.get("counterparty_name"),
            "counterparty_account": ln.get("counterparty_account"), "memo": ln.get("memo"),
            "description": ln.get("description"), "file": files.get(st["id"]), "verified": bool(st.get("verified"))}


def item_pairs(item_id: str, reasons: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pairs to show on a document's review page: one per open reconciliation to-do (this run's or an earlier one)
    and per decision on the document, with the invoice and the statement line side by side."""
    wanted: dict[tuple[str, str], int | None] = {}
    for r in reasons:
        parsed = parse_reason(r["reason"])
        if parsed is not None:
            wanted.setdefault(parsed, r["id"])
    decided = {(d["invoice_doc_id"], d["line_id"]): d for d in decisions_for([item_id])}
    if not wanted and not decided:
        return []
    snap = snapshot()
    learned = learned_names(snap)
    invoices = {i["id"]: i for i in snap["invoices"]}
    pairs: dict[tuple[str, str], int | None] = {}
    for (prefix, line), reason_id in wanted.items():
        full = [i for i in invoices if i.startswith(prefix)]
        if len(full) == 1:
            pairs.setdefault((full[0], line), reason_id)
    for key in decided:
        pairs.setdefault(key, None)
    lines = {key[1]: _find_line(snap, key[1]) for key in pairs}
    statement_ids = {found[0]["id"] for found in lines.values() if found}
    statement_ids |= {d["statement_doc_id"] for d in decided.values()}
    files = _file_names([*invoices.keys() & {k[0] for k in pairs}, *statement_ids])
    statements = {s["id"]: s for s in snap["statements"]}
    packages = _packages([*(i.get("work_run") for i in invoices.values()), *(s.get("work_run") for s in statements.values())])
    out = []
    for (iid, line), reason_id in pairs.items():
        inv, found, d = invoices.get(iid), lines[line], decided.get((iid, line))
        sid = found[0]["id"] if found else (d["statement_doc_id"] if d else None)
        pay = ({**found[1], "currency": found[0].get("currency"), "statement_type": found[0].get("statement_type")}
               if found else None)
        relation, conversion = amount_relation(inv, pay, snap.get("fx_rates")) if inv and pay else (None, None)
        side = "invoice" if item_id == iid else "statement"
        other = statements.get(sid) if side == "invoice" else inv
        other_id = sid if side == "invoice" else iid
        tied = signals(inv, pay, learned) if inv and pay else (json.loads(d["signals"] or "[]") if d else [])
        relation = relation if inv and pay else (d["amount_relation"] if d else None)
        out.append({
            "invoice_doc_id": iid, "statement_doc_id": sid, "line_id": line, "side": side,
            "invoice": _invoice_view(inv, files), "line": _line_view(found, files),
            "signals": tied, "amount_relation": relation, "fx": conversion,
            "amount_only": relation == "equal" and not tied,
            "source_review_required": bool(found) and not found[0].get("verified"), "reason_id": reason_id,
            "decision": d["decision"] if d else None, "decided_by": d["actor"] if d else None,
            "decided_at": d["decided_at"] if d else None, "note": d["note"] if d else None,
            "other_doc_id": other_id, "other_file": files.get(other_id or ""),
            "other_run_id": other.get("work_run") if other else None, "other_item_id": other.get("item_id") if other else None,
            "other_workpackage_id": packages.get(other.get("work_run") or "") if other else None,
        })
    return sorted(out, key=lambda p: (p["decision"] is not None, p["line"]["booking_date"] if p["line"] else "", p["line_id"]))


def _run_doc_ids(run_id: str) -> list[str]:
    from jav import work

    return [i["item_id"] for i in work.get_run(run_id)["input"]["items"] if i.get("kind") != "email"]


def run_rows(run_id: str) -> list[dict[str, Any]]:
    """The run's reconciliation view: a row per invoice of the run (its status and the line that paid it or may have)
    and a row per line of the run's statements (the invoice it paid or may have), from the whole store."""
    mine = set(_run_doc_ids(run_id))
    snap = snapshot()
    if not mine & {d["id"] for d in [*snap["invoices"], *snap["statements"]]}:
        return []
    result = propose(snap)
    learned = learned_names(snap)
    invoices = {i["id"]: i for i in snap["invoices"]}
    lines = {ln["id"]: (st, ln) for st in snap["statements"] for ln in st["lines"]}
    proposed = [c for c in result["candidates"] if c["proposed"]]
    equal_only = [c for c in result["candidates"] if c["amount_only"]]
    confirmed = result["confirmed"]
    rejected = {(d["invoice_id"], d["line_id"]) for d in snap["decisions"] if d["decision"] == "not_this"}
    files = _file_names([*invoices, *(s["id"] for s in snap["statements"])])
    excluded = {(e["kind"], e["id"]): e["reason"] for e in result["excluded"]}

    def line_text(line: str) -> str | None:
        st, ln = lines.get(line, (None, None))
        return files.get(st["id"]) if st else None

    def signal_flags(inv: dict[str, Any] | None, found: tuple[dict[str, Any], dict[str, Any]] | None) -> dict[str, bool | None]:
        """The pair's signals as yes/no columns (empty without a pair)."""
        got = (signals(inv, {**found[1], "currency": found[0].get("currency")}, learned)
               if inv is not None and found is not None else None)
        return {f"signal_{s}": (s in got if got is not None else None) for s in SIGNALS}

    rows = []
    for s in result["invoices"]:
        iid = s["invoice_id"]
        if iid not in mine:
            continue
        inv = invoices[iid]
        paid = [c for c in confirmed if c["invoice_id"] == iid]
        offers = (paid or [c for c in proposed if c["invoice_id"] == iid] or [c for c in equal_only if c["invoice_id"] == iid]
                  or [c for c in result["candidates"] if c["invoice_id"] == iid])
        first = offers[0] if offers else None
        st_ln = lines.get(first["line_id"]) if first else None
        rows.append({"_key": f"invoice|{iid}", "item_id": iid, "kind": "invoice", "file": files.get(iid), "status": s["status"],
                     "date": inv.get("issue_date"), "amount": inv.get("amount"), "currency": inv.get("currency"),
                     "partner": inv.get("supplier_name"), "number": inv.get("number"), "memo": None,
                     "paired_file": line_text(first["line_id"]) if first else None,
                     "paired_date": st_ln[1].get("booking_date") if st_ln else None,
                     "candidates": len(offers),
                     **signal_flags(inv, st_ln),
                     "decision": "paid_by" if paid else ("not_this" if any(p[0] == iid for p in rejected) else None),
                     "reason": s.get("reason")})
    for st in snap["statements"]:
        if st["id"] not in mine:
            continue
        for ln in st["lines"]:
            lid = ln["id"]
            paid = [c for c in confirmed if c["line_id"] == lid]
            offers = (paid or [c for c in proposed if c["line_id"] == lid] or [c for c in equal_only if c["line_id"] == lid]
                      or [c for c in result["candidates"] if c["line_id"] == lid])
            status = ("confirmed" if paid else "proposed" if offers and offers[0] in proposed else
                      "amount_only" if offers and offers[0] in equal_only else
                      "amount_differs" if offers else "excluded" if ("line", lid) in excluded else "unpaired")
            first = offers[0] if offers else None
            inv = invoices.get(first["invoice_id"]) if first else None
            rows.append({"_key": f"line|{lid}", "item_id": st["id"], "kind": "line", "file": files.get(st["id"]), "status": status,
                         "date": ln.get("booking_date"), "amount": ln.get("amount"), "currency": st.get("currency"),
                         "partner": ln.get("counterparty_name"), "number": inv.get("number") if inv else None,
                         "memo": ln.get("memo") or ln.get("description"),
                         "paired_file": files.get(first["invoice_id"]) if first else None,
                         "paired_date": inv.get("issue_date") if inv else None, "candidates": len(offers),
                         **signal_flags(inv, (st, ln)),
                         "decision": "paid_by" if paid else ("not_this" if any(p[1] == lid for p in rejected) else None),
                         "reason": excluded.get(("line", lid))})
    return rows


def worth_showing(rows: Iterable[dict[str, Any]]) -> bool:
    """Whether a run's reconciliation view (`run_rows`) says anything: the run has a statement line, or one of its
    invoices has a pair, a decision or (partial) coverage by verified statements."""
    return any(r["kind"] == "line" or r["status"] in ("confirmed", "proposed", "amount_only", "amount_differs",
                                                      "no_payment_found", "partly_covered")
               for r in rows)


def fingerprint() -> str:
    """What the reconciliation of a run depends on besides the run itself: the store's invoices and statements, their
    corrections, the decisions and the stored exchange rates (`datasets` caches the view by it)."""
    conf = _conf()
    types = [*conf["invoice_types"], *conf["outgoing_types"], *conf["statement_types"]]
    with store.connect() as c:
        docs = c.execute(f"SELECT COUNT(*), MAX(rowid) FROM datapoints WHERE doc_type IN ({','.join('?' * len(types))})", types).fetchone()
        corr = (c.execute("SELECT COUNT(*), MAX(created_at) FROM run_item_corrections").fetchone()
                if _has_table(c, "run_item_corrections") else (0, None))
        dec = [[d["pair_key"], d["decision"], d["decided_at"]] for d in _decision_rows(c)]
    return "|".join(str(x) for x in (*docs, *corr, hashlib.sha256(json.dumps(dec).encode("utf-8")).hexdigest()[:16],
                                      fx.fingerprint()))


# --- the pairs already in the store ------------------------------------------------------------------------------------


def scan(*, write: bool = False) -> dict[str, Any]:
    """Counts of the store's proposal for the command line (no values printed), and with `write` the same to-do the
    processing would open, on the later processed document of each proposed pair and of each pair listed for its equal
    amount alone (131), under the flow run that produced it. 131: when the later document's result is not from a work
    run (an evaluation on the command line) or its run is approved, the to-do goes to the other document of the pair if
    that one is in a run not yet approved; a pair with neither is skipped."""
    from jav import work

    snap = snapshot(fetch_rates=True)
    result = propose(snap)

    def count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
        return dict(sorted(Counter(str(r.get(key)) for r in rows).items()))

    docs = {d["id"]: d for d in [*snap["invoices"], *snap["statements"]]}
    with store.connect() as c:
        approved = ({r["run_id"] for r in c.execute("SELECT run_id FROM runs WHERE approval IS NOT NULL")}
                    if _has_table(c, "runs") else set())
        already = {(r["subject_id"], r["reason"]) for r in _open_to_dos(c)}
    pending: dict[str, tuple[dict[str, Any], list[str]]] = {}
    skipped: dict[str, int] = defaultdict(int)
    for cand in (c for c in result["candidates"] if _waits(c)):
        sides = sorted((docs[cand["invoice_id"]], docs[cand["statement_id"]]), key=lambda d: d["seq"], reverse=True)
        in_work = [d for d in sides if d.get("work_run") is not None]
        target = next((d for d in in_work if d["work_run"] not in approved), None)  # 131: the later one in a work run
        code = reason(cand["invoice_id"], cand["line_id"], _kind(cand))
        if target is None:
            skipped["approved_run" if in_work else "no_work_run"] += 1
        elif (target["id"], code) in already:
            skipped["already_open"] += 1  # an earlier --write (or the processing) opened it
        else:
            pending.setdefault(target["id"], (target, []))[1].append(code)
    written = 0
    if write:
        for doc, codes in pending.values():
            store.review_enqueue(subject_kind="document", subject_id=doc["id"], run_id=doc["flow_run_id"] or "",
                                 reasons=codes, producer=PRODUCER)
            written += len(codes)
        for run_id in sorted({doc["work_run"] for doc, _ in pending.values()}):
            work.refresh_run_status(run_id)
    statements = snap["statements"]
    return {
        "statements": len(statements), "verified_statements": sum(1 for s in statements if s["verified"]),
        "lines": sum(len(s["lines"]) for s in statements), "invoices": len(snap["invoices"]),
        "excluded_invoices": count([e for e in result["excluded"] if e["kind"] == "invoice"], "reason"),
        "excluded_lines": count([e for e in result["excluded"] if e["kind"] == "line"], "reason"),
        "proposed_pairs": sum(1 for c in result["candidates"] if c["proposed"]),
        "multiple_candidates": sum(1 for c in result["candidates"] if c["multiple_candidates"]),
        "amount_only_pairs": sum(1 for c in result["candidates"] if c["amount_only"]),
        "amount_differs_pairs": sum(1 for c in result["candidates"] if not _waits(c)),
        "signals": count([{"s": s} for c in result["candidates"] for s in c["signals"]], "s"),
        "learned_names": result["learned_names"],
        "relations": count(result["candidates"], "amount_relation"),
        "rates": sum(len(days) for days in snap["fx_rates"].values()),
        "confirmed_pairs": len(result["confirmed"]), "decisions": count(_decision_rows(), "decision"),
        "invoice_status": count(result["invoices"], "status"),
        "unpaired_lines": len(result["unpaired_line_ids"]),
        "to_open": sum(len(codes) for _, codes in pending.values()), "written": written, "skipped": dict(sorted(skipped.items())),
        "config_hash": result["config_hash"], "engine_version": ENGINE_VERSION,
    }


# --- the synthetic golden cases (configs/golden_reconcile.json) ----------------------------------------------------


def golden_cases() -> list[dict[str, Any]]:
    """The golden cases with their defaults filled in: each has `snapshot` and `expected`."""
    g = cfg.load("golden_reconcile")
    d = g["defaults"]
    out = []
    for case in g["cases"]:
        invoices = [{**d["invoice"], **inv} for inv in case["invoices"]]
        statements = [{**d["statement"], **st, "lines": [{**d["line"], **ln} for ln in st.get("lines", [])]}
                      for st in case["statements"]]
        out.append({"id": case["id"], "note": case.get("note"),
                    "snapshot": {"invoices": invoices, "statements": statements, "decisions": case.get("decisions", []),
                                 "fx_rates": case.get("fx_rates", {})},
                    "expected": case["expected"], "source_review": case.get("source_review", [])})
    return out


def check_case(case: dict[str, Any]) -> list[str]:
    """The differences between a golden case's expectation and the proposal (empty: the case passes)."""
    result = propose(case["snapshot"])
    exp = case["expected"]
    problems = []
    got_pairs = sorted([c["line_id"], c["invoice_id"], c["proposed"], c["multiple_candidates"]] for c in result["candidates"])
    if got_pairs != sorted(exp["pairs"]):
        problems.append(f"pairs {got_pairs} != {sorted(exp['pairs'])}")
    got_excluded = sorted([e["kind"], e["id"], e["reason"]] for e in result["excluded"])
    if got_excluded != sorted(exp["excluded"]):
        problems.append(f"excluded {got_excluded} != {sorted(exp['excluded'])}")
    got_status = {s["invoice_id"]: s["status"] for s in result["invoices"]}
    if got_status != exp["status"]:
        problems.append(f"status {got_status} != {exp['status']}")
    review = sorted(c["line_id"] for c in result["candidates"] if c["source_review_required"])
    if review != sorted(case["source_review"]):
        problems.append(f"source review {review} != {sorted(case['source_review'])}")
    if "relations" in exp:  # 130: the amount relation of the listed pairs (a card pair's conversion)
        got_rel = {f'{c["line_id"]}|{c["invoice_id"]}': c["amount_relation"] for c in result["candidates"]}
        wanted = {k: got_rel.get(k) for k in exp["relations"]}
        if wanted != exp["relations"]:
            problems.append(f"relations {wanted} != {exp['relations']}")
    got_confirmed = sorted([c["line_id"], c["invoice_id"]] for c in result["confirmed"])
    if got_confirmed != sorted(exp.get("confirmed", [])):
        problems.append(f"confirmed {got_confirmed} != {sorted(exp.get('confirmed', []))}")
    got_equal = sorted([c["line_id"], c["invoice_id"]] for c in result["candidates"] if c["amount_only"])
    if got_equal != sorted(exp.get("amount_only", [])):  # 131: every case names its equal-amount pairs
        problems.append(f"amount_only {got_equal} != {sorted(exp.get('amount_only', []))}")
    if "signals" in exp:  # 131: the signals of the named pairs
        got_sig = {f'{c["line_id"]}|{c["invoice_id"]}': c["signals"] for c in result["candidates"]}
        wanted_sig = {k: got_sig.get(k) for k in exp["signals"]}
        if wanted_sig != exp["signals"]:
            problems.append(f"signals {wanted_sig} != {exp['signals']}")
    return problems


def golden_score() -> dict[str, Any]:
    cases = golden_cases()
    failures = {c["id"]: p for c in cases if (p := check_case(c))}
    return {"passed": len(cases) - len(failures), "total": len(cases), "failures": failures}
