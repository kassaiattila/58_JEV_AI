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
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Iterable

from jav import cfg, duplicates, fact_checks, store

ENGINE_VERSION = "1.0.0"
STATUSES = ("proposed", "amount_differs", "no_payment_found", "partly_covered", "not_covered", "excluded")
_MONEY = re.compile(r"-?\d+(?:\.\d{1,2})?")


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
                         "statement_verified": bool(st.get("verified"))})
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
            "statements": statements, "own_accounts": sorted(own_accounts)}


def window(invoice: dict[str, Any]) -> tuple[date, date]:
    """The days a payment of the invoice is searched in."""
    w = _conf()["window"]
    issue = _date(invoice["issue_date"])
    end = _date(invoice.get("due_date")) or issue
    return issue - timedelta(days=int(w["days_before_issue"])), max(end, issue) + timedelta(days=int(w["days_after_due"]))


def signals(invoice: dict[str, Any], payment: dict[str, Any]) -> list[str]:
    """The facts that tie a line to an invoice; the amount is never one of them."""
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
    return found


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
    """The proposal for a snapshot: candidate pairs, exclusions, every invoice's status and the unpaired lines."""
    prepared = prepare(snapshot)
    candidates = []
    for pid, pay in sorted(prepared["payments"].items()):
        booked = _date(pay["booking_date"])
        for iid, inv in sorted(prepared["invoices"].items()):
            if inv["currency"] != pay["currency"]:
                continue
            start, end = window(inv)
            if not start <= booked <= end:
                continue
            found = signals(inv, pay)
            if not found:
                continue  # an equal amount alone ties nothing
            equal = money(pay["amount"]) == money(inv.get("amount"))
            candidates.append({"line_id": pid, "invoice_id": iid, "statement_id": pay["statement_id"], "currency": inv["currency"],
                               "amount_relation": "equal" if equal else "different", "proposed": equal, "signals": found,
                               "source_review_required": not pay["statement_verified"]})
    per_line, per_invoice = defaultdict(int), defaultdict(int)
    for c in candidates:
        if c["proposed"]:
            per_line[c["line_id"]] += 1
            per_invoice[c["invoice_id"]] += 1
    for c in candidates:
        c["multiple_candidates"] = c["proposed"] and (per_line[c["line_id"]] > 1 or per_invoice[c["invoice_id"]] > 1)
    periods = coverage(prepared["statements"])
    statuses = []
    for iid, inv in sorted(prepared["invoices"].items()):
        mine = [c for c in candidates if c["invoice_id"] == iid]
        start, end = window(inv)
        accounts = [p for (_acct, cur), p in periods.items() if cur == inv["currency"]]
        cover = [_covered(p, start, end) for p in accounts]
        if any(c["proposed"] for c in mine):
            status = "proposed"
        elif mine:
            status = "amount_differs"
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
    paired = {c["line_id"] for c in candidates if c["proposed"]}
    return {"engine_version": ENGINE_VERSION, "config_hash": config_hash(), "candidates": candidates,
            "excluded": prepared["excluded"], "invoices": sorted(statuses, key=lambda s: s["invoice_id"]),
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
            f"SELECT d.doc_id, d.doc_type, d.datapoints, d.validation, {item}"
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
        out.append({"doc_id": r["doc_id"], "doc_type": r["doc_type"], "values": values, "validation": r["validation"]})
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


def snapshot() -> dict[str, Any]:
    """The store's effective invoices and statements as a snapshot for `propose`."""
    conf = _conf()
    f = conf["invoice_fields"]
    marks = _duplicate_marks()
    invoices = []
    for d in _latest([*conf["invoice_types"], *conf["outgoing_types"]]):
        v = d["values"]
        invoices.append({"id": d["doc_id"], "doc_type": d["doc_type"], "number": v.get(f["number"]),
                         "supplier_name": v.get(f["supplier_name"]), "supplier_tax_id": v.get(f["supplier_tax_id"]),
                         "payment_account": v.get(f["payment_account"]), "amount": _amount(v),
                         "currency": v.get(f["currency"]), "issue_date": v.get(f["issue_date"]),
                         "due_date": v.get(f["due_date"]), "duplicate": marks.get(d["doc_id"])})
    statements = []
    for d in _latest(conf["statement_types"]):
        v = d["values"]
        lines = [t for t in v.get("transactions") or [] if isinstance(t, dict)]
        statements.append({"id": d["doc_id"], "doc_type": d["doc_type"], "account": v.get("account_iban") or v.get("account_no"),
                           "currency": v.get("currency"), "statement_type": v.get("statement_type"),
                           "period_start": v.get("period_start"), "period_end": v.get("period_end"),
                           "verified": verified(d["validation"]), "lines": with_line_ids(d["doc_id"], lines)})
    return {"invoices": invoices, "statements": statements}


def scan() -> dict[str, Any]:
    """Counts of the store's proposal for the command line (read-only; nothing is written)."""
    snap = snapshot()
    result = propose(snap)

    def count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
        return dict(sorted(Counter(str(r.get(key)) for r in rows).items()))

    statements = snap["statements"]
    return {
        "statements": len(statements), "verified_statements": sum(1 for s in statements if s["verified"]),
        "lines": sum(len(s["lines"]) for s in statements), "invoices": len(snap["invoices"]),
        "excluded_invoices": count([e for e in result["excluded"] if e["kind"] == "invoice"], "reason"),
        "excluded_lines": count([e for e in result["excluded"] if e["kind"] == "line"], "reason"),
        "proposed_pairs": sum(1 for c in result["candidates"] if c["proposed"]),
        "multiple_candidates": sum(1 for c in result["candidates"] if c["multiple_candidates"]),
        "amount_differs_pairs": sum(1 for c in result["candidates"] if not c["proposed"]),
        "invoice_status": count(result["invoices"], "status"),
        "unpaired_lines": len(result["unpaired_line_ids"]),
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
        out.append({"id": case["id"], "note": case.get("note"), "snapshot": {"invoices": invoices, "statements": statements},
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
    return problems


def golden_score() -> dict[str, Any]:
    cases = golden_cases()
    failures = {c["id"]: p for c in cases if (p := check_case(c))}
    return {"passed": len(cases) - len(failures), "total": len(cases), "failures": failures}
