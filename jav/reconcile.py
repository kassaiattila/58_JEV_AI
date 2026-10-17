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

**A person's decision** (129, K2): a person confirms a pair (`paid_by`, "this line paid it") or rejects it with a reason
(`not_this`); the decision belongs to the pair (`reconcile_decisions`). In the core a rejected pair is never proposed
again, and a confirmed pair makes its invoice `confirmed` and takes the line and the invoice out of every other
proposal. 137 (DECISIONS 137): the decisions are made in the reconciliation package (`jav/reconcile_package.py`); the
processing no longer opens a to-do for a pair on the documents, and the review page's panel, the run's reconciliation
view and `scan(write=True)` are gone. The panel's decisions (129-136) stay: the core honours them and they stay part of
the reviewed result of their run (`decisions_for`, `corrections.review_version`).

**Card payments in another currency** (130, K3; DECISIONS 128 variant C, DECISIONS 130): a credit card statement books
in forints and does not print the original amount, so a forint line of a card statement (`fx.statement_types`) and an
invoice in another currency are compared through the official MNB rate of the invoice's issue date (`jav/fx.py`). Such
a pair needs a signal like any other and a line within `fx.window` around the issue date; it is proposed when the
line's amount is within `policy.json` `reconcile.fx_tolerance` of the converted amount (`fx_within`), listed but not
proposed outside it (`fx_outside`, status `amount_differs`) or without a known rate (`no_rate`, status
`rate_missing`). The card accounts also count in the coverage of a foreign-currency invoice, so "no payment found"
needs them covered too. The rates come in the snapshot (`fx_rates`), so the core stays pure; only the processing and
the command line fetch missing rates, a view reads the store.

**Bank lines in forints against an invoice in another currency** (149): a forint line of a bank account
(`fx.bank.statement_types`) may pay an invoice in another currency in two ways, measured on the store's 11 named
payments of 2022-2026: a Hungarian buyer pays the forint value at the MNB rate of the invoice's fulfilment day (5 of
5 to the forint), and a bank converts foreign money at its own rate on the booking day (6 of 6 within 0.6-1.1% below
the MNB rate). So the line is compared at the MNB rate of each day in `fx.bank.rate_days` in turn (`bank_rate_days`),
each with its own band (`policy.json` `reconcile.fx_bank_tolerance`); the first within its band makes the pair
`fx_within`, otherwise the nearest is `fx_outside`, listed only when the line names the invoice (a payment service
converting above the rate and a name alone gave 56 such listings on the store). The line is searched in the invoice's
payment window, as in one currency, and the forint bank accounts count in the coverage of an outgoing invoice in
another currency (incoming ones keep their card and same-currency accounts).

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

**Looser names, reference numbers, strength** (134, DECISIONS 134): a card line prints a merchant name glued to a
suffix ("EXAMPLETELECOMSZAML*12345") or with a misread letter, so the whole-word supplier name signal misses it.

- A **fuzzy supplier name** is a weak signal (`supplier_name_fuzzy`): a distinctive word of the supplier's name (cut
  after its legal form, without numbers) begins a word of the line's name, or the line's word begins it and holds most
  of it (a name cut short on a card terminal), or they differ by about a letter; the same whole word counts only when it leads the supplier's name (its brand: "SIMPLEP*EXAMPLEINSURE"
  and "Exampleinsure Hungaria Zrt."), otherwise the whole-word share rule decides. A word common to many suppliers or to
  many lines' names (a city) ties nothing (`common_words`). Like the payment method, it alone ties only an equal amount.
- A **reference number** is a signal (`reference`): the invoice's customer id, customer code, order or contract number
  (`invoice_fields.references`) in the line's memo or description, matched like the invoice number.
- Every candidate carries its **strength** (0-100) from its signals, its amounts and when the line was booked
  (`configs/reconcile.json` `strength`), and the days from the issue date: the pairing page orders the candidates by it
  and says why. It is no threshold; what is proposed is unchanged.

**A card purchase's original amount** (137, DECISIONS 137): a bank account's PDF statement (the Erste export completed
by code, `jav/statement_table.py`) prints a card purchase's original amount and currency next to its forint line
(`original_amount`, `original_currency`). Such a line meets an invoice of that currency (`meets`: `original`) in the card
window around the issue date and is compared on the original amount exactly (`equal` / `different`), without the MNB
rate; like a converted pair it is allocated only in whole. An account with such lines counts in the coverage of a
foreign-currency invoice's card window, as a card statement does.

**Accounts registered in advance** (138, DECISIONS 137): an own account or card can be registered with its party before
any statement of it is processed (`jav/parties.py`); a reconciliation package passes its scope's registrations in the
snapshot (`own_accounts`: key, kind, currencies, the days it was open). Such an account has to be covered like one
with statements, so an invoice it may have paid is never `no_payment_found` while its statements are missing; it is
asked only for the part of a window it was open, and a registered forint card counts in the card window.

**Allocations and marks** (131 E1, the reconciliation package, `jav/reconcile_package.py`): a confirmation is an
allocation of an amount (`reconcile_allocations`), several per line and per invoice, never over either amount; a
`paid_by` decision counts as both whole amounts. The proposal compares what is left, so the rest of a split payment can
be proposed (status `partly_paid` when nothing fits the rest); a converted card pair is compared only in whole. A line a
person marked as needing no invoice (`reconcile_line_marks`) takes part in nothing. A package's scope
(`scope_statements`) limits the lines and the coverage, never the amounts allocated so far.

**The sports club's gaps** (141, DECISIONS 141): the club's statements and invoices showed four, each closed by code.

- A **combined payment**: a line whose memo names two or more invoices (their number signal) whose amounts left add up to
  the line's amount left exactly proposes them together (`amount_relation: combined`, `combined`: the group's invoices
  in the order of issue, at most `combined.max_invoices`); the group counts as one proposal of its line, so accepting the
  unambiguous proposals allocates it whole. A line with a proposal of its own makes no group.
- A **credit note** (a negative invoice) that cancels exactly one eligible invoice of its supplier (the same supplier,
  currency and amount, issued on or before it) settles that invoice: status `credited` (`credited_by`), no candidate is
  listed for it, and the credit note is excluded as `credit_note` (`credits`). Not when two invoices could be meant (160:
  an invoice already paid counts among them), when anything was allocated to the invoice, or when a line naming the
  invoice's number is proposed for it (it was paid; a refund may follow).
- A line booked more than `proposal.unnamed_days_before_issue` days before an invoice's issue date is its candidate
  only with the invoice's number or a reference in the memo (an advance payment); without one it paid the previous
  month of a recurring bill.
- A line whose memo names an invoice (number or reference) proposes no other invoice, and such an invoice is proposed
  on no other line: the rest stay listed candidates for a person. An invoice whose candidates all stay unproposed this
  way gets its coverage status, not `amount_differs`.

**The finder** (143, DECISIONS 143): `compare` relates one line to one invoice for a person searching by hand, with
every pair kept (the proposal's rules decide nothing there).

**What the overview needs** (142, DECISIONS 142, the reconciliation result's first part): two facts a person reads, not
decisions.
- `repeats`: the invoices two or more outgoing lines each look like the full payment of: allocated or proposed in full
  for it, or of its exact amount, tied to it by a signal in its window and paying no other invoice (a possible double
  payment, or the invoice of a later month is missing). A line a person marked or rejected for it does not count.
- `checked_until` on an invoice's status: the last day up to which the statements of every account that could pay it
  cover it without a gap from its issue date (None: not from its issue date). An invoice past its due date by then,
  with nothing paid or proposed, is overdue with no payment found in the covered period.

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
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from jav import cfg, duplicates, fact_checks, fx, store
from jav.candidates import trim_after_legal_form
from jav.models import account_key  # 156: shared with the candidate finder; callers keep using reconcile.account_key

ENGINE_VERSION = "1.17.0"  # 154: the rule replaces a statement only when none of its lines is lost; 151: a forint bank line pays two or more invoices of another currency together; 1.15.0 (149): a forint bank line meets another currency; 1.14.0 (148): a credit line pays an outgoing invoice (its partner the buyer); 1.13.0: a known direction decides
STATUSES = ("confirmed", "credited", "proposed", "amount_only", "partly_paid", "amount_differs", "rate_missing",
            "no_payment_found", "partly_covered", "not_covered", "excluded")
RELATIONS = ("equal", "different", "fx_within", "fx_outside", "no_rate", "combined")  # how a candidate's amounts relate
NAMED_SIGNALS = frozenset({"invoice_number", "reference"})  # 141: the line's memo names the invoice
DECISIONS = ("paid_by", "not_this")
SIGNALS = ("invoice_number", "reference", "supplier_account", "supplier_name", "supplier_name_fuzzy", "payment_channel",
           "learned_name")
WEAK_SIGNALS = frozenset({"payment_channel", "supplier_name_fuzzy"})  # alone they tie only an equal amount
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
-- 131 (E1, DECISIONS 131): a person's allocation of a line's amount to an invoice in a reconciliation package; several
-- per line and per invoice (split and combined payments), within both sides' amounts. A revoked one keeps its row.
CREATE TABLE IF NOT EXISTS reconcile_allocations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_doc_id    TEXT NOT NULL,
    statement_doc_id  TEXT NOT NULL,
    line_id           TEXT NOT NULL,
    line_amount       TEXT NOT NULL,      -- canonical decimal, in the line's currency
    invoice_amount    TEXT NOT NULL,      -- canonical decimal, in the invoice's currency (equal in one currency)
    workpackage_id    TEXT NOT NULL,      -- the reconciliation package it was made in
    actor             TEXT NOT NULL,
    note              TEXT,
    created_at        TEXT NOT NULL,
    revoked_at        TEXT,
    revoked_by        TEXT,
    revoke_note       TEXT
);
CREATE INDEX IF NOT EXISTS ix_reconcile_allocations_line ON reconcile_allocations(line_id);
CREATE INDEX IF NOT EXISTS ix_reconcile_allocations_invoice ON reconcile_allocations(invoice_doc_id);
-- 131: a line that needs no invoice (a private expense, a fee, a transfer ...), by a person, with its reason
CREATE TABLE IF NOT EXISTS reconcile_line_marks (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_doc_id  TEXT NOT NULL,
    line_id           TEXT NOT NULL,
    category          TEXT NOT NULL,      -- configs/reconcile.json line_marks
    note              TEXT,
    workpackage_id    TEXT NOT NULL,
    actor             TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    revoked_at        TEXT,
    revoked_by        TEXT,
    basis             TEXT                -- 147: the quick review's suggestion it accepted (NULL: a person's own choice)
);
CREATE INDEX IF NOT EXISTS ix_reconcile_line_marks_line ON reconcile_line_marks(line_id);
""")


def _migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(reconcile_decisions)")}
    if cols and "workpackage_id" not in cols:  # 131: a rejection made in a reconciliation package (not on a run)
        conn.execute("ALTER TABLE reconcile_decisions ADD COLUMN workpackage_id TEXT")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(reconcile_line_marks)")}
    if cols and "basis" not in cols:  # 147: the suggestion a mark accepted in the quick review came from
        conn.execute("ALTER TABLE reconcile_line_marks ADD COLUMN basis TEXT")


store.register_migration("reconcile", _migrate)


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
    return _normalized(str(value or ""))


@lru_cache(maxsize=65536)
def _normalized(value: str) -> str:
    """149: memoised; one pairing normalises the same few thousand names and numbers some hundred thousand times."""
    text = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", "".join(c for c in text if not unicodedata.combining(c))))


def category_mark(line: dict[str, Any]) -> str | None:
    """140: the needs-no-invoice reason a line's own category suggests (`category_marks`: patterns on the normalised
    description, the first that matches), or None. A suggestion for a person, never a mark by itself."""
    text = normalize(line.get("description"))
    if not text:
        return None
    return next((r["mark"] for r in _conf().get("category_marks", []) if re.search(r["pattern"], text)), None)


def salary_mark(line: dict[str, Any]) -> str | None:
    """147: the salary reason when a line's normalised memo or description matches a `salary_marks` pattern, or None.
    A suggestion for a person, never a mark by itself."""
    text = " ".join(normalize(line.get(k)) for k in ("memo", "description")).strip()
    if text and any(re.search(p, text) for p in _conf().get("salary_marks", [])):
        return "salary"
    return None


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


def name_words(name: Any) -> list[str]:
    """134: a supplier's name as the signals compare it: cut after its legal form when an address or a remark follows
    (`candidates.trim_after_legal_form`), without numbers, legal forms and filler words."""
    return list(_name_words(str(name or "")))


@lru_cache(maxsize=16384)
def _name_words(name: str) -> tuple[str, ...]:
    """151: memoised, as `_normalized`; one pairing compares each supplier's name with every line in its window."""
    return tuple(w for w in normalize(trim_after_legal_form(name)).split()
                 if w not in _ignore_tokens() and not any(ch.isdigit() for ch in w))


def supplier_words(name: Any) -> list[str]:
    """134: the words of a supplier's name a fuzzy match may use: `name_words` of `fuzzy_name.min_chars` letters."""
    least = int(_conf()["signals"]["fuzzy_name"]["min_chars"])
    return [w for w in name_words(name) if len(w) >= least]


def line_words(payment: dict[str, Any]) -> list[str]:
    """134: the words of a line's name (the counterparty, else the description) without numbers and short pieces."""
    return list(_line_words(str(payment.get("counterparty_name") or payment.get("description") or "")))


@lru_cache(maxsize=16384)
def _line_words(name: str) -> tuple[str, ...]:
    """151: memoised, as `_name_words`."""
    return tuple(w for w in normalize(name).split() if len(w) >= 4 and not any(ch.isdigit() for ch in w))


def common_words(invoices: Iterable[dict[str, Any]], lines: Iterable[dict[str, Any]]) -> frozenset[str]:
    """134: the words too common to tie a name: in the names of `common_min` suppliers or more, or in the names of
    `common_min` lines or more that make at least `common_share` of the different line names (a city on every card
    line)."""
    f = _conf()["signals"]["fuzzy_name"]
    least = int(f["common_min"])
    by_supplier: Counter[str] = Counter()
    for words in {tuple(supplier_words(i.get("supplier_name"))) for i in invoices}:  # one supplier, however spelt
        by_supplier.update(set(words))
    keys = {" ".join(line_words(ln)) for ln in lines} - {""}
    by_line: Counter[str] = Counter(w for key in keys for w in set(key.split()))
    line_least = max(least, float(f["common_share"]) * len(keys))
    return frozenset({w for w, n in by_supplier.items() if n >= least} | {w for w, n in by_line.items() if n >= line_least})


@lru_cache(maxsize=65536)
def _fuzzy_word(word: str, other: str) -> bool:
    """The supplier's word begins the line's word (glued to a suffix), or the line's word begins the supplier's and
    holds `min_prefix_share` of it (a name cut short on a card terminal), or they differ by about a letter. 151:
    memoised (the configuration is read once per process, `_conf`)."""
    f = _conf()["signals"]["fuzzy_name"]
    least = int(f["min_chars"])
    if other.startswith(word) or (len(other) >= max(least, float(f["min_prefix_share"]) * len(word)) and word.startswith(other)):
        return True
    return (min(len(word), len(other)) >= least and abs(len(word) - len(other)) <= 2
            and SequenceMatcher(None, word, other).ratio() >= float(f["min_ratio"]))


def _number_in(value: Any, text: str) -> bool:
    """A document number in a line's text: as whole words, or without separators when long enough (128)."""
    s = _conf()["signals"]
    number, number_c = normalize(value), compact(value)
    return len(number_c) >= int(s["min_number_chars"]) and bool(
        re.search(r"(?<![a-z0-9])" + re.escape(number) + r"(?![a-z0-9])", normalize(text))
        or (len(number_c) >= int(s["min_compact_number_chars"]) and number_c in compact(text)))


_DECIMAL = re.compile(r"-?\d+(?:\.\d+)?")


def decimal_or_none(value: Any) -> Decimal | None:
    """153 (review A6): a stored amount ("1234.50", "-12.5", any number of decimals) as a finite Decimal; None for
    anything else ("NaN", "Infinity", "1E+3", "12,5", empty). The reconciliation views each had their own reader: some
    took "NaN" or an exponent, one read "12,5" as zero."""
    text = str(value) if value is not None else ""
    return Decimal(text) if _DECIMAL.fullmatch(text) else None


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


def outgoing(invoice: dict[str, Any]) -> bool:
    """148: whether the invoice is an own party's outgoing invoice: its direction when known (147), else its type."""
    return invoice["direction"] == "outgoing" if invoice.get("direction") else invoice.get("doc_type") in _conf()["outgoing_types"]


def pays(payment: dict[str, Any], invoice: dict[str, Any]) -> bool:
    """148: whether the line is on the invoice's side: an outgoing payment (debit) pays an incoming invoice, incoming
    money (credit) an outgoing one."""
    return (payment.get("direction") == "credit") == outgoing(invoice)


def partner_view(invoice: dict[str, Any]) -> dict[str, Any]:
    """148: the invoice as the signals compare it: the supplier fields carry its partner, the supplier of an incoming
    invoice and the buyer of an outgoing one; an outgoing invoice's bank account is the own party's, so it ties nothing."""
    if not outgoing(invoice):
        return invoice
    return {**invoice, "supplier_name": invoice.get("buyer_name"), "supplier_tax_id": invoice.get("buyer_tax_id"),
            "payment_account": None}


def partner_name(invoice: dict[str, Any]) -> Any:
    """148: the name the invoice is shown by: its partner's (`partner_view`), the buyer of an outgoing invoice."""
    return partner_view(invoice).get("supplier_name")


def _supplier_key(invoice: dict[str, Any]) -> str:
    return fact_checks.tax_party_key(invoice.get("supplier_tax_id")) or normalize(invoice.get("supplier_name"))


def _identity(invoice: dict[str, Any]) -> tuple[str, str, str] | None:
    number = duplicates.number_key(invoice.get("number"))
    supplier = _supplier_key(invoice)
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
    # 153 (decision of 2026-10-13, review A4): a payment is a transfer between own accounts only when it goes to a
    # registered own account (`registered_accounts`); before, any stored statement made its account "own", so one from a
    # trial run or an email attachment hid the payments to it. A payment to an account only a statement prints stays
    # in the pairing, marked (`unregistered_own`). A snapshot without registrations (a measurement case) takes the
    # statements' accounts, as before.
    printed = {statement_account(st) for st in statements.values()}
    registered = snapshot.get("registered_accounts")
    own_accounts = printed if registered is None else set(registered)
    unregistered_own: list[str] = []
    review = re.compile(conf["payment_review_pattern"])
    identities: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for key, inv in invoices.items():
        ident = _identity(inv)
        if ident and inv.get("duplicate") is None:  # a person's duplicate decision settles the pair
            identities[ident].append(key)
    clashing = {k for keys in identities.values() if len(keys) > 1 for k in keys}
    eligible_invoices, eligible_payments, excluded, credit_notes = {}, {}, [], {}
    views = {key: partner_view(inv) for key, inv in invoices.items()}  # 148: an outgoing invoice's partner is its buyer
    for key, inv in sorted(views.items()):
        reason = _amount_reason(inv.get("amount"))
        if inv.get("currency") not in currencies:
            reason = "unsupported_currency"
        if not _date(inv.get("issue_date")):
            reason = "missing_issue_date"
        if inv.get("duplicate") == "copy":
            reason = "duplicate_copy"
        elif key in clashing:
            reason = "duplicate_undecided"
        if reason:
            excluded.append({"kind": "invoice", "id": key, "reason": reason})
            if reason == "non_positive_amount" and money(str(inv["amount"])) < 0 and _supplier_key(inv):
                credit_notes[key] = inv  # 141: it may cancel an invoice of its supplier (`_credited`)
        else:
            eligible_invoices[key] = inv
    for key, pay in sorted(payments.items()):
        reason = _amount_reason(pay.get("amount"))
        if pay.get("currency") not in currencies:
            reason = "unsupported_currency"
        if not _date(pay.get("booking_date")):
            reason = "missing_booking_date"
        if pay.get("direction") not in ("debit", "credit"):
            reason = "not_outgoing_payment"
        elif account_key(pay.get("counterparty_account")) and account_key(pay.get("counterparty_account")) in own_accounts:
            reason = "own_account_transfer"
        elif account_key(pay.get("counterparty_account")) in printed:
            unregistered_own.append(key)  # 153: to an account a statement prints but no party holds: a person decides
        elif pay["direction"] == "debit" and review.search(normalize(f"{pay.get('description') or ''} {pay.get('memo') or ''}")):
            reason = "payment_kind_review"  # 148: a kind of outgoing payment; incoming money is paired or informational
        if reason:
            excluded.append({"kind": "line", "id": key, "reason": reason})
        else:
            eligible_payments[key] = pay
    return {"invoices": eligible_invoices, "payments": eligible_payments, "excluded": excluded,
            "statements": statements, "own_accounts": sorted(own_accounts), "lines": payments,
            "unregistered_own": sorted(unregistered_own),
            "common_words": common_words(views.values(), payments.values()), "credit_notes": credit_notes}


def _credited(prepared: dict[str, Any], paid_invoice: dict[str, Decimal]) -> dict[str, str]:
    """141: the invoices a credit note cancels: {invoice: credit note}. A credit note cancels an invoice of its supplier,
    currency and exact amount, issued on or before it, when that invoice is the only such eligible one no other credit
    note took, and it has nothing allocated. 160 (review M-2): an invoice already paid counts among the ones it could
    mean, so a credit note refunding a paid month does not cancel the unpaid month of the same amount; a person
    decides."""
    out: dict[str, str] = {}
    for cid, note in sorted(prepared["credit_notes"].items()):
        issued, amount = _date(note.get("issue_date")), -money(str(note["amount"]))
        matches = [iid for iid, inv in sorted(prepared["invoices"].items())
                   if iid not in out and _supplier_key(inv) == _supplier_key(note)
                   and inv.get("currency") == note.get("currency") and money(str(inv["amount"])) == amount
                   and issued is not None and _date(inv["issue_date"]) <= issued]
        if len(matches) == 1 and not paid_invoice.get(matches[0]):
            out[matches[0]] = cid
    return out


Settled = tuple[set[tuple[str, str]], list[dict[str, Any]], dict[str, Decimal], dict[str, Decimal], list[dict[str, Any]]]


def _settled(snapshot: dict[str, Any], prepared: dict[str, Any]) -> Settled:
    """The people's decisions in the snapshot: the rejected pairs, the confirmed allocations, and the amount allocated
    so far per line (in its currency) and per invoice (in its currency). A confirmation counts only when its invoice is
    eligible and its line still exists (a decision on a line a re-extraction removed changes nothing).

    131 (DECISIONS 131): a confirmation is an allocation of an amount (`snapshot["allocations"]`, from a reconciliation
    package: several per line and per invoice, for split and combined payments); a `paid_by` decision without an
    allocation of its pair counts as both whole amounts. Allocations apply in order while both sides have room; one that
    would exceed a side's amount is ignored (the recording refuses it, so only a re-extraction that changed an amount
    gets here). Of two whole-amount confirmations sharing a line or an invoice, the first therefore counts, as before.
    153 (review A3): such an ignored allocation is returned (`unfit`, the fifth element), so the package shows it to be
    revoked; before, it vanished from every view while it stayed recorded, and came back if the amount did.
    160 (review M-1): so is an allocation whose invoice left the pairing (`reason` `invoice_left_out`, with the
    invoice's exclusion reason as `invoice_reason`) or whose line is no longer on its statement (`line_gone`: a
    correction or a new reading gave it a new identity); the amount check's own reason is `amounts`. A `paid_by`
    decision without an allocation still changes nothing then (129)."""
    rejected: set[tuple[str, str]] = set()
    wanted: list[tuple[str, str, Any, Any, dict[str, Any] | None]] = []
    explicit = set()
    for a in snapshot.get("allocations") or []:
        explicit.add((str(a["invoice_id"]), str(a["line_id"])))
        wanted.append((str(a["invoice_id"]), str(a["line_id"]), a.get("line_amount"), a.get("invoice_amount"), a))
    for d in sorted(snapshot.get("decisions") or [], key=lambda d: (str(d["invoice_id"]), str(d["line_id"]))):
        pair = (str(d["invoice_id"]), str(d["line_id"]))
        if d["decision"] == "not_this":
            rejected.add(pair)
        elif d["decision"] == "paid_by" and pair not in explicit:
            wanted.append((pair[0], pair[1], None, None, None))
    confirmed: list[dict[str, Any]] = []
    unfit: list[dict[str, Any]] = []
    paid_line: dict[str, Decimal] = defaultdict(Decimal)
    paid_invoice: dict[str, Decimal] = defaultdict(Decimal)
    left_out = {e["id"]: e["reason"] for e in prepared["excluded"] if e["kind"] == "invoice"}
    for iid, lid, line_part, invoice_part, allocation in wanted:
        if lid not in prepared["lines"]:
            if allocation is not None:
                unfit.append({**allocation, "line_total": None, "invoice_total": None, "reason": "line_gone"})
            continue
        if iid not in prepared["invoices"]:
            if allocation is not None:
                unfit.append({**allocation, "line_total": None, "invoice_total": None, "reason": "invoice_left_out",
                              "invoice_reason": left_out.get(iid)})
            continue
        try:
            line_total = money(str(prepared["lines"][lid].get("amount")))
            invoice_total = money(str(prepared["invoices"][iid].get("amount")))
            la = money(str(line_part)) if line_part is not None else line_total
            ia = money(str(invoice_part)) if invoice_part is not None else invoice_total
        except ValueError:
            if allocation is not None:
                unfit.append({**allocation, "line_total": None, "invoice_total": None, "reason": "amounts"})
            continue
        if (la <= 0 or ia <= 0 or paid_line.get(lid, Decimal(0)) + la > line_total
                or paid_invoice.get(iid, Decimal(0)) + ia > invoice_total):
            if allocation is not None:
                unfit.append({**allocation, "line_total": str(line_total), "invoice_total": str(invoice_total),
                              "reason": "amounts"})
            continue
        paid_line[lid] += la
        paid_invoice[iid] += ia
        confirmed.append({"invoice_id": iid, "line_id": lid, "statement_id": prepared["lines"][lid]["statement_id"],
                          "line_amount": str(la), "invoice_amount": str(ia)})
    return rejected, confirmed, dict(paid_line), dict(paid_invoice), unfit


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


def named(invoice: dict[str, Any], payment: dict[str, Any]) -> list[str]:
    """The signals of a line's text naming the invoice (`NAMED_SIGNALS`): its number, a reference of it."""
    text = f"{payment.get('memo') or ''} {payment.get('description') or ''}"
    found = ["invoice_number"] if _number_in(invoice.get("number"), text) else []
    if any(_number_in(ref, text) for ref in invoice.get("references") or []):
        found.append("reference")
    return found


def signals(invoice: dict[str, Any], payment: dict[str, Any], learned: set[tuple[str, str]] | None = None,
            common: frozenset[str] | None = None) -> list[str]:
    """The facts that tie a line to an invoice; the amount is never one of them. `learned`: the (name key, supplier key)
    pairs of a person's confirmations; `common`: the words too common to tie a name (both from `signal_context`)."""
    s = _conf()["signals"]
    found = named(invoice, payment)
    account = account_key(invoice.get("payment_account"))
    if account and account == account_key(payment.get("counterparty_account")):
        found.append("supplier_account")
    supplier = set(name_words(invoice.get("supplier_name")))  # 134: without a printed address after the legal form
    counterparty = set(normalize(payment.get("counterparty_name") or payment.get("description")).split())
    if supplier and len(supplier & counterparty) / len(supplier) >= float(s["min_name_share"]):
        found.append("supplier_name")
    else:
        # a glued or misread word; a whole word only when it leads the supplier's name (its brand), else the share rule
        # above decides, so two suppliers sharing a trade word ("... Waterworks") are not tied by it
        common = common or frozenset()
        words = supplier_words(invoice.get("supplier_name"))
        mine = [w for w in words if w not in common]
        theirs = [w for w in line_words(payment) if w not in common]
        if any((w != o and _fuzzy_word(w, o)) or (w == o and w == words[0]) for w in mine for o in theirs):
            found.append("supplier_name_fuzzy")
    if _channel(invoice, payment):
        found.append("payment_channel")
    key = name_key(payment.get("counterparty_name"))
    if learned and key and any((key, sk) in learned for sk in supplier_keys(invoice)):
        found.append("learned_name")
    return found


def strength(invoice: dict[str, Any], payment: dict[str, Any], found: list[str], relation: str | None,
             in_window: bool = True) -> dict[str, Any]:
    """134: how strongly a candidate is tied, 0-100, from its signals, its amounts and when the line was booked
    (`strength` weights), with the days from the issue date and whether it was booked by the due date (`grace_days`
    after it). An order and a reason for a person, not a threshold. 143: a pair outside the invoice's payment window
    (`in_window` False, only the finder compares one) gets no timing weight."""
    w = _conf()["strength"]
    issue, booked = _date(invoice.get("issue_date")), _date(payment.get("booking_date"))
    due = _date(invoice.get("due_date")) or issue
    days = (booked - issue).days if issue and booked else None
    by_due = bool(issue and booked and due and issue <= booked <= max(due, issue) + timedelta(days=int(w["grace_days"])))
    score = sum(int(w["signals"].get(s, 0)) for s in found) + int(w["amount"].get(relation or "", 0))
    score += int(w["timing"]["by_due"] if by_due else w["timing"]["in_window"] if in_window else 0)
    return {"strength": min(score, int(w["max"])), "days_after_issue": days, "by_due": by_due}


def signal_context(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The snapshot-wide inputs of `signals` (134): the names a person's confirmations teach and the common words."""
    prepared = prepare(snapshot)
    return {"learned": _learned(prepared, _settled(snapshot, prepared)[1]), "common": prepared["common_words"]}


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


def fx_bank_capable(payment: dict[str, Any]) -> bool:
    """149: a forint line of a bank account statement (`fx.bank.statement_types`); `meets` leaves out a card purchase
    the statement prints with its original currency."""
    f = _conf()["fx"]
    return payment.get("currency") == f["line_currency"] and payment.get("statement_type") in f["bank"]["statement_types"]


def bank_rate_days(invoice: dict[str, Any], payment: dict[str, Any]) -> list[tuple[str, date]]:
    """149: the days whose MNB rate a forint bank line is compared at, in the order of `fx.bank.rate_days`: the
    invoice's fulfilment day (its issue day when none was read) and the line's booking day."""
    days = {"fulfillment": _date(invoice.get("fulfillment_date")) or _date(invoice.get("issue_date")),
            "booking": _date(payment.get("booking_date"))}
    return [(basis, day) for basis in _conf()["fx"]["bank"]["rate_days"] if (day := days.get(basis))]


def original(payment: dict[str, Any]) -> tuple[str, Decimal] | None:
    """137: a card purchase's original currency and amount, as the bank printed them next to the forint line."""
    currency, amount = payment.get("original_currency"), payment.get("original_amount")
    if not currency or amount in (None, ""):
        return None
    try:
        return str(currency), money(str(amount))
    except (ValueError, InvalidOperation):
        return None


def meets(invoice: dict[str, Any], payment: dict[str, Any]) -> str | None:
    """How a line can pay an invoice: `same` (one currency), `original` (137: a card purchase in the invoice's
    currency), `fx` (130: a forint card line against another currency, through the MNB rate), `fx_bank` (149: a forint
    bank line against another currency, through the MNB rate of the fulfilment or the booking day), or None."""
    if invoice.get("currency") == payment.get("currency"):
        return "same"
    if (orig := original(payment)) is not None and orig[0] == invoice.get("currency"):
        return "original"
    if fx_capable(payment) and rate_need(invoice):
        return "fx"
    if fx_bank_capable(payment) and original(payment) is None and rate_need(invoice):
        return "fx_bank"  # a card purchase printed with its original currency is that currency's, not converted
    return None


def pair_window(invoice: dict[str, Any], payment: dict[str, Any]) -> tuple[date, date] | None:
    """The days the line may be booked in to pay the invoice: its payment window in one currency, the card window
    around the issue date otherwise; None when their currencies cannot meet."""
    how = meets(invoice, payment)
    if how is None:
        return None
    return window(invoice) if how in ("same", "fx_bank") else fx_window(invoice)  # 149: a bank line in the payment window


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

    if meets(invoice, payment) == "fx_bank":
        return _convert_bank(invoice, payment, rates)
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


def _convert_bank(invoice: dict[str, Any], payment: dict[str, Any], rates: dict[str, Any] | None
                  ) -> tuple[str, dict[str, str] | None]:
    """149: a forint bank line against an invoice of another currency, at the MNB rate of each `bank_rate_days` day in
    turn, each with its band (`policy.reconcile_fx_bank_tolerance`): the first within makes `fx_within`, otherwise the
    nearest is `fx_outside`; `no_rate` without any rate. The conversion names the day's kind (`basis`)."""
    from jav import policy

    currency, amount, paid = str(invoice.get("currency")), money(str(invoice["amount"])), money(str(payment["amount"]))
    nearest: tuple[Decimal, dict[str, str]] | None = None
    for basis, day in bank_rate_days(invoice, payment):
        entry = (rates or {}).get(currency, {}).get(day.isoformat())
        if not entry:
            continue
        expected = amount * Decimal(str(entry["rate"]))
        deviation = paid / expected - 1
        conversion = {"rate": str(entry["rate"]), "rate_day": str(entry["rate_day"]), "source": str(entry.get("source") or "mnb"),
                      "basis": basis, "converted": str(expected.quantize(Decimal("0.01"))),
                      "deviation": str(deviation.quantize(Decimal("0.0001")))}
        below, above = policy.reconcile_fx_bank_tolerance(basis)
        if -below <= deviation <= above:
            return "fx_within", conversion
        if nearest is None or abs(deviation) < nearest[0]:
            nearest = (abs(deviation), conversion)
    return ("fx_outside", nearest[1]) if nearest else ("no_rate", None)


def convert_combined(invoices: list[dict[str, Any]], payment: dict[str, Any], rates: dict[str, Any] | None
                     ) -> tuple[str, dict[str, Any] | None]:
    """151: one forint bank line against two or more invoices of one other currency it pays together. Their sum is
    converted at the MNB rate of each `bank_rate_days` day in turn (each invoice at its own fulfilment day, all at the
    line's booking day), each with its band: the first within makes `fx_within`, otherwise the nearest is `fx_outside`;
    `no_rate` unless every invoice has a rate on some day. The conversion: the day's kind (`basis`), the converted sum,
    the line's deviation from it, and each invoice's own conversion (`parts`, in the order given)."""
    from jav import policy

    paid = money(str(payment["amount"]))
    nearest: tuple[Decimal, dict[str, Any]] | None = None
    for basis in _conf()["fx"]["bank"]["rate_days"]:
        parts = []
        for inv in invoices:
            day = dict(bank_rate_days(inv, payment)).get(basis)
            entry = (rates or {}).get(str(inv.get("currency")), {}).get(day.isoformat()) if day else None
            if not entry:
                break
            converted = money(str(inv["amount"])) * Decimal(str(entry["rate"]))
            parts.append({"rate": str(entry["rate"]), "rate_day": str(entry["rate_day"]), "source": str(entry.get("source") or "mnb"),
                          "basis": basis, "converted": str(converted.quantize(Decimal("0.01")))})
        if len(parts) < len(invoices):
            continue
        total = sum((money(p["converted"]) for p in parts), Decimal(0))
        deviation = paid / total - 1
        conversion = {"basis": basis, "converted": str(total.quantize(Decimal("0.01"))),
                      "deviation": str(deviation.quantize(Decimal("0.0001"))), "parts": parts}
        below, above = policy.reconcile_fx_bank_tolerance(basis)
        if -below <= deviation <= above:
            return "fx_within", conversion
        if nearest is None or abs(deviation) < nearest[0]:
            nearest = (abs(deviation), conversion)
    return ("fx_outside", nearest[1]) if nearest else ("no_rate", None)


def split_line(amount: Decimal, conversion: dict[str, Any]) -> list[Decimal]:
    """151: a line's amount shared among the invoices of a combined conversion in the ratio of their converted amounts,
    to two decimals; the rounding goes to the last, so the shares add up to the amount exactly."""
    weights = [money(p["converted"]) for p in conversion["parts"]]
    total = sum(weights, Decimal(0))
    shares = [(amount * w / total).quantize(Decimal("0.01")) for w in weights[:-1]]
    return [*shares, amount - sum(shares, Decimal(0))]


def amount_relation(invoice: dict[str, Any], payment: dict[str, Any], rates: dict[str, Any] | None = None
                    ) -> tuple[str | None, dict[str, str] | None]:
    """How a line's amount relates to an invoice's: `equal` / `different` in one currency or on a card purchase's
    original amount (137), the conversion for a card line of another currency (`convert`), None when the amounts cannot
    be compared."""
    try:
        how = meets(invoice, payment)
        if how == "same":
            return ("equal" if money(str(payment.get("amount"))) == money(str(invoice.get("amount"))) else "different"), None
        if how == "original":  # 137: the card purchase's original amount, exactly
            orig = original(payment)
            return ("equal" if orig is not None and orig[1] == money(str(invoice.get("amount"))) else "different"), None
        if how in ("fx", "fx_bank"):
            return convert(invoice, payment, rates)
    except (ValueError, InvalidOperation, ZeroDivisionError):
        return None, None
    return None, None


def compare(invoice: dict[str, Any], payment: dict[str, Any], learned: set[tuple[str, str]] | None = None,
            common: frozenset[str] | None = None, rates: dict[str, Any] | None = None) -> dict[str, Any]:
    """143: one line against one invoice, for a person looking for a line's invoice by hand (the pairing page's
    finder, DECISIONS 143). Unlike `propose` it drops no pair: the signals that tie them, whether the line went to
    another account than the one the invoice names (not for a line through a payment app, whose account is the app's),
    how their amounts relate and the invoice's amount less the line's (on a card purchase's original amount when it is
    in the invoice's currency), whether the line was booked in the invoice's payment window, and the strength. A
    reason for a person, never a proposal."""
    found = signals(invoice, payment, learned, common)
    relation, conversion = amount_relation(invoice, payment, rates)
    how = meets(invoice, payment)
    span = pair_window(invoice, payment) if _date(invoice.get("issue_date")) else None
    booked = _date(payment.get("booking_date"))
    in_window = bool(span and booked and span[0] <= booked <= span[1])
    mine, theirs = account_key(invoice.get("payment_account")), account_key(payment.get("counterparty_account"))
    difference = None
    try:
        if how == "same":
            difference = {"amount": f"{money(str(invoice['amount'])) - money(str(payment['amount'])):.2f}",
                          "currency": str(invoice.get("currency"))}
        elif how == "original" and (orig := original(payment)) is not None:
            difference = {"amount": f"{money(str(invoice['amount'])) - orig[1]:.2f}", "currency": orig[0]}
    except (KeyError, ValueError, InvalidOperation):
        difference = None
    return {"signals": found, "amount_relation": relation, "fx": conversion, "difference": difference,
            "account_differs": bool(mine and theirs and mine != theirs and not through_app(payment)),
            "in_window": in_window, **strength(invoice, payment, found, relation, in_window)}


def months(start: str, end: str) -> list[str]:
    """The months ("YYYY-MM") from the month of `start` to the month of `end`, both included."""
    y, m = int(start[:4]), int(start[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= end[:7]:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def merge_periods(intervals: Iterable[tuple[date, date]]) -> list[tuple[date, date]]:
    """The periods joined where they overlap or follow each other without a day between."""
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
    return {k: merge_periods(v) for k, v in periods.items()}


def covered_by(periods: list[tuple[date, date]], start: date, end: date) -> str:
    """full / partial / none: how much of [start, end] the merged periods cover."""
    if any(a <= start and end <= b for a, b in periods):
        return "full"
    return "partial" if any(a <= end and start <= b for a, b in periods) else "none"


def _named_first(candidates: list[dict[str, Any]]) -> None:
    """141: a line whose memo names a proposed invoice proposes no other, and a named invoice is proposed on no other
    line; those pairs stay listed candidates for a person."""
    named = [c for c in candidates if c["proposed"] and NAMED_SIGNALS & set(c["signals"])]
    lines, invoices = {c["line_id"] for c in named}, {c["invoice_id"] for c in named}
    for c in candidates:
        if c["proposed"] and not NAMED_SIGNALS & set(c["signals"]) and (c["line_id"] in lines or c["invoice_id"] in invoices):
            c["proposed"] = False


def _combine(candidates: list[dict[str, Any]], prepared: dict[str, Any], rest_invoice: dict[str, Decimal],
             rest_line: dict[str, Decimal], rates: dict[str, Any] | None = None) -> None:
    """141: a line without a proposal whose memo names two or more invoices of its currency whose amounts left add up
    to the line's amount left exactly proposes them together, in the order of issue. 151: so does a forint bank line
    naming two or more invoices of one other currency whose sum, converted as `convert_combined` does, is within its
    band (the pairs of two currencies are untouched on both sides, `propose`); each pair carries its own conversion at
    the day that decided (`fx`) and the group's (`combined_fx`)."""
    limit = int(_conf()["combined"]["max_invoices"])
    by_line: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in candidates:
        by_line[c["line_id"]].append(c)

    def by_issue(c: dict[str, Any]) -> tuple[str, str]:
        return str(prepared["invoices"][c["invoice_id"]].get("issue_date")), c["invoice_id"]

    for lid, mine in sorted(by_line.items()):
        if any(c["proposed"] for c in mine):
            continue
        pay = prepared["payments"][lid]
        group = [c for c in mine if "invoice_number" in c["signals"] and c["amount_relation"] == "different"
                 and c["currency"] == c["line_currency"]]
        fx = [c for c in mine if "invoice_number" in c["signals"] and c["amount_relation"] in ("fx_outside", "no_rate")
              and meets(prepared["invoices"][c["invoice_id"]], pay) == "fx_bank"]
        combined_fx = None
        if 2 <= len(group) <= limit and sum(rest_invoice[c["invoice_id"]] for c in group) == rest_line[lid]:
            group.sort(key=by_issue)
        elif 2 <= len(fx) <= limit and len({c["currency"] for c in fx}) == 1:
            group = sorted(fx, key=by_issue)
            relation, combined_fx = convert_combined([prepared["invoices"][c["invoice_id"]] for c in group], pay, rates)
            if relation != "fx_within" or combined_fx is None:
                continue
        else:
            continue
        ids = [c["invoice_id"] for c in group]
        for n, c in enumerate(group):
            c.update(proposed=True, amount_relation="combined", combined=ids,
                     **strength(prepared["invoices"][c["invoice_id"]], pay, c["signals"], "combined"))
            if combined_fx is not None:
                c.update(fx=combined_fx["parts"][n],
                         combined_fx={k: combined_fx[k] for k in ("basis", "converted", "deviation")})


def _repeats(prepared: dict[str, Any], candidates: list[dict[str, Any]], confirmed: list[dict[str, Any]],
             rejected: set[tuple[str, str]], marked: dict[str, str], scope: set[str],
             context: tuple[set[tuple[str, str]], frozenset[str]], allocated: set[str], credited: set[str]) -> list[dict[str, Any]]:
    """142 (DECISIONS 142): the invoices two or more outgoing lines each look like the full payment of - allocated in
    full, proposed for it while nothing is allocated to it, or of its exact amount in its currency, tied to it by a
    signal in its window and paying no other invoice (an unnamed line more than `proposal.unnamed_days_before_issue`
    days before the issue date paid another month, as for a candidate). A line a person marked, or rejected for the
    invoice, does not count. Each with the lines (`paid_by`: those allocated or proposed) and the signals of the others."""
    learned, common = context
    unnamed_days = int(_conf()["proposal"]["unnamed_days_before_issue"])
    proposals: dict[str, set[tuple[str, ...]]] = defaultdict(set)  # a line's proposals: one invoice, or a combined group
    for c in candidates:
        if c["proposed"]:
            proposals[c["line_id"]].add(tuple(c["combined"]) if c.get("combined") else (c["invoice_id"],))

    def elsewhere(pid: str, iid: str) -> bool:
        return any(iid not in unit for unit in proposals.get(pid, ()))

    allocated_to: dict[str, set[str]] = defaultdict(set)
    for a in confirmed:
        allocated_to[a["line_id"]].add(a["invoice_id"])
    by_amount: dict[tuple[str, Decimal], list[str]] = defaultdict(list)
    for pid, pay in prepared["payments"].items():
        if pay["statement_id"] in scope and pid not in marked:
            by_amount[(str(pay.get("currency")), money(str(pay["amount"])))].append(pid)
    out = []
    for iid, inv in sorted(prepared["invoices"].items()):
        if iid in credited:
            continue
        whole = money(str(inv["amount"]))
        paid_by = {a["line_id"] for a in confirmed if a["invoice_id"] == iid and money(a["invoice_amount"]) >= whole}
        if iid not in allocated:  # a line proposed for this invoice alone (or for its combined group)
            paid_by |= {pid for pid, units in proposals.items() if any(iid in u for u in units) and not elsewhere(pid, iid)}
        start, end = window(inv)
        tied = {}
        for pid in by_amount.get((str(inv.get("currency")), whole), []):
            pay = prepared["payments"][pid]
            booked = _date(pay["booking_date"])
            if (pid in paid_by or (iid, pid) in rejected or allocated_to[pid] - {iid} or elsewhere(pid, iid)
                    or not booked or not start <= booked <= end or not pays(pay, inv)):
                continue
            found = signals(inv, pay, learned, common)
            early = (booked - issued).days < -unnamed_days if (issued := _date(inv.get("issue_date"))) else False
            if found and (NAMED_SIGNALS & set(found) or not early):  # 141: an unnamed line well before the issue paid another month
                tied[pid] = found
        lines = sorted(paid_by | set(tied))
        if len(lines) >= 2:
            out.append({"invoice_id": iid, "line_ids": lines, "paid_by": sorted(paid_by), "signals": dict(sorted(tied.items()))})
    return out


def propose(snapshot: dict[str, Any]) -> dict[str, Any]:
    """The proposal for a snapshot: candidate pairs, exclusions, every invoice's status and the unpaired lines. The
    snapshot's `decisions` (a person's `paid_by` / `not_this` per invoice and line) and `allocations` settle their
    pairs first. 131: the amounts compared are what is left after the allocations, so the rest of a split payment can
    be proposed; a converted card pair needs both sides untouched; a line a person marked as needing no invoice
    (`marks`) takes part in nothing. `scope_statements` (a reconciliation package's scope): only the lines and the
    coverage of these statements count, while the amounts allocated so far come from every statement."""
    prepared = prepare(snapshot)
    scope = set(snapshot["scope_statements"]) if snapshot.get("scope_statements") is not None else set(prepared["statements"])
    rejected, confirmed, paid_line, paid_invoice, unfit = _settled(snapshot, prepared)
    learned, common = _learned(prepared, confirmed), prepared["common_words"]
    marked = {str(m["line_id"]): str(m["category"]) for m in snapshot.get("marks") or [] if str(m["line_id"]) in prepared["lines"]}
    # 160 (review M-1): a mark whose line is no longer on its statement is returned, as an allocation's is
    unfit_marks = [{**m, "reason": "line_gone"} for m in snapshot.get("marks") or [] if str(m["line_id"]) not in prepared["lines"]]
    rest_invoice = {iid: money(str(inv["amount"])) - paid_invoice.get(iid, Decimal(0)) for iid, inv in prepared["invoices"].items()}
    rest_line = {pid: money(str(pay["amount"])) - paid_line.get(pid, Decimal(0)) for pid, pay in prepared["payments"].items()}
    paid_invoices = {iid for iid, rest in rest_invoice.items() if rest <= 0}
    paid_lines = {pid for pid, rest in rest_line.items() if rest <= 0}
    rates = snapshot.get("fx_rates") or {}
    amount_only = bool(_conf()["amount_only"]["enabled"])
    unnamed_days = int(_conf()["proposal"]["unnamed_days_before_issue"])
    candidates = []
    # 149: the open invoices with what they have left, sorted once (the rests do not change in the loop); 151: with
    # their payment window and card window, so a line booked outside both is passed over before the costlier checks
    open_invoices = [(iid, inv_whole, {**inv_whole, "amount": str(rest_invoice[iid])}, window(inv_whole), fx_window(inv_whole))
                     for iid, inv_whole in sorted(prepared["invoices"].items()) if iid not in paid_invoices]
    for pid, pay_whole in sorted(prepared["payments"].items()):
        if pid in paid_lines or pid in marked or pay_whole["statement_id"] not in scope:
            continue
        pay = {**pay_whole, "amount": str(rest_line[pid])}
        booked = _date(pay["booking_date"])
        for iid, inv_whole, inv, pay_span, card_span in open_invoices:
            if not (pay_span[0] <= booked <= pay_span[1] or card_span[0] <= booked <= card_span[1]):
                continue  # 151: in neither window this line could be searched in
            if (iid, pid) in rejected or not pays(pay_whole, inv_whole):
                continue
            how = meets(inv, pay)
            if how is None:
                continue
            if how != "same" and (pid in paid_line or iid in paid_invoice):
                continue  # a pair of two currencies is compared only in whole (DECISIONS 131)
            start, end = pay_span if how in ("same", "fx_bank") else card_span  # 149: a bank line in the payment window
            if not start <= booked <= end:
                continue
            relation, conversion = amount_relation(inv, pay, rates)
            if how == "fx_bank" and relation != "fx_within" and not named(inv, pay):
                continue  # 149: a converted bank line outside its band is listed only when it names the invoice
            found = signals(inv, pay, learned, common)
            if found and set(found) <= WEAK_SIGNALS and relation not in ("equal", "fx_within"):
                continue  # a payment app pays many bills, a loose name is no proof: alone they tie no other amount (131, 134)
            if not found and not (amount_only and relation == "equal"):
                continue  # a converted amount alone ties nothing; an equal one is only listed for a person (131)
            tie = strength(inv, pay, found, relation)
            if not NAMED_SIGNALS & set(found) and tie["days_after_issue"] is not None and tie["days_after_issue"] < -unnamed_days:
                continue  # 141: well before the issue date, only a line naming the invoice is an advance payment
            candidate = {"line_id": pid, "invoice_id": iid, "statement_id": pay["statement_id"], "currency": inv["currency"],
                         "line_currency": pay["currency"], "amount_relation": relation,
                         "proposed": bool(found) and relation in ("equal", "fx_within"), "amount_only": not found,
                         "signals": found, "source_review_required": not pay["statement_verified"], **tie}
            if conversion is not None:
                candidate["fx"] = conversion
            if how == "original":  # 137: compared on the card purchase's original amount
                orig = original(pay)
                candidate["original"] = {"amount": f"{orig[1]:.2f}", "currency": orig[0]} if orig else None
            candidates.append(candidate)
    _named_first(candidates)
    named_paid = {c["invoice_id"] for c in candidates if c["proposed"] and NAMED_SIGNALS & set(c["signals"])}
    credited = {iid: cid for iid, cid in _credited(prepared, paid_invoice).items() if iid not in named_paid}
    candidates = [c for c in candidates if c["invoice_id"] not in credited]  # 141: a cancelled invoice needs no payment
    _combine(candidates, prepared, rest_invoice, rest_line, rates)
    proposed_lines = {c["line_id"] for c in candidates if c["proposed"]}
    proposed_invoices = {c["invoice_id"] for c in candidates if c["proposed"]}
    candidates = [c for c in candidates if not c["amount_only"]
                  or (c["line_id"] not in proposed_lines and c["invoice_id"] not in proposed_invoices)]
    per_line: dict[str, set[str]] = defaultdict(set)  # 141: a combined group is one proposal of its line
    per_invoice = defaultdict(int)
    open_line, open_invoice = defaultdict(int), defaultdict(int)  # the pairs waiting for a person: proposed or equal amount
    for c in candidates:
        if c["proposed"]:
            per_line[c["line_id"]].add("combined" if c.get("combined") else c["invoice_id"])
            per_invoice[c["invoice_id"]] += 1
        if c["proposed"] or c["amount_only"]:
            open_line[c["line_id"]] += 1
            open_invoice[c["invoice_id"]] += 1
    for c in candidates:
        c["multiple_candidates"] = ((c["proposed"] and (len(per_line[c["line_id"]]) > 1 or per_invoice[c["invoice_id"]] > 1))
                                    or (c["amount_only"] and (open_line[c["line_id"]] > 1 or open_invoice[c["invoice_id"]] > 1)))
    in_scope = {k: st for k, st in prepared["statements"].items() if k in scope}
    periods = coverage(in_scope)
    f = _conf()["fx"]
    purchases = {statement_account(st) for st in in_scope.values()  # 137: an account printing card purchases' originals
                 if any(original(ln) for ln in st.get("lines") or [])}
    card_accounts = {(statement_account(st), str(st.get("currency"))) for st in in_scope.values()
                     if (st.get("statement_type") in f["statement_types"] and st.get("currency") == f["line_currency"])
                     or statement_account(st) in purchases}
    bank_accounts = {(statement_account(st), str(st.get("currency"))) for st in in_scope.values()  # 149: they pay one too
                     if st.get("statement_type") in f["bank"]["statement_types"] and st.get("currency") == f["line_currency"]}
    registered = {str(a["key"]): a for a in snapshot.get("own_accounts") or []}
    for key, acct in sorted(registered.items()):  # 138: an account registered in advance has to be covered, statement or not
        for cur in acct.get("currencies") or []:
            periods.setdefault((key, str(cur)), [])
            if acct.get("kind") == "card" and cur == f["line_currency"]:
                card_accounts.add((key, str(cur)))

    def covered(key: tuple[str, str], start: date, end: date) -> str | None:
        """How far the account covers the window, within the days it was open (None: closed for the whole window)."""
        acct = registered.get(key[0]) or {}
        opened, closed = _date(acct.get("valid_from")), _date(acct.get("valid_to"))
        start, end = max(start, opened) if opened else start, min(end, closed) if closed else end
        return covered_by(periods[key], start, end) if start <= end else None

    def covered_until(key: tuple[str, str], start: date) -> date | None:
        """142: the last day the account covers without a gap from `start` (date.max: nothing to cover after it closed)."""
        acct = registered.get(key[0]) or {}
        opened, closed = _date(acct.get("valid_from")), _date(acct.get("valid_to"))
        if closed and closed < start:
            return date.max
        start = max(start, opened) if opened else start
        end = next((b for a, b in periods[key] if a <= start <= b), None)
        return date.max if end is not None and closed and end >= closed else end

    statuses = []
    for iid, inv in sorted(prepared["invoices"].items()):
        mine = [c for c in candidates if c["invoice_id"] == iid]
        signed = [c for c in mine if not c["amount_only"]]
        start, end = window(inv)
        keys = [key for key in sorted(periods) if key[1] == inv["currency"]]
        cover = [c for key in keys if (c := covered(key, start, end)) is not None]
        if rate_need(inv):  # a card account can pay it too, in the card window
            fx_start, fx_end = fx_window(inv)
            cover += [c for key in sorted(card_accounts) if (c := covered(key, fx_start, fx_end)) is not None]
            keys += sorted(card_accounts)
            if outgoing(inv):  # 149: an outgoing one is paid into a forint bank account, in its payment window
                cover += [c for key in sorted(bank_accounts - card_accounts) if (c := covered(key, start, end)) is not None]
                keys += sorted(bank_accounts - card_accounts)
        issued = _date(inv.get("issue_date"))
        untils = [covered_until(key, issued) for key in keys] if issued else []
        checked = None if not untils or None in untils else min(u for u in untils if u is not None)
        if iid in paid_invoices:
            status = "confirmed"
        elif iid in credited:
            status = "credited"  # 141: its credit note cancels it
        elif any(c["proposed"] for c in mine):
            status = "proposed"
        elif len(signed) < len(mine):
            status = "amount_only"
        elif iid in paid_invoice:
            status = "partly_paid"  # 131: part of it is allocated, nothing proposed for the rest
        elif any(c["amount_relation"] not in ("no_rate", "equal", "fx_within") for c in signed):
            status = "amount_differs"  # 141: an equal pair left unproposed (another invoice is named) is no difference
        elif any(c["amount_relation"] == "no_rate" for c in signed):
            status = "rate_missing"
        elif cover and all(c == "full" for c in cover):
            status = "no_payment_found"
        elif any(c != "none" for c in cover):
            status = "partly_covered"
        else:
            status = "not_covered"
        row = {"invoice_id": iid, "status": status, "window": [start.isoformat(), end.isoformat()],
               "checked_until": checked.isoformat() if checked not in (None, date.max) else None}
        statuses.append({**row, "credited_by": credited[iid]} if iid in credited else row)
    credits = {cid: iid for iid, cid in credited.items()}
    excluded = [{**e, "reason": "credit_note", "credits": credits[e["id"]]} if e["kind"] == "invoice" and e["id"] in credits else e
                for e in prepared["excluded"]]
    for e in excluded:
        if e["kind"] == "invoice":
            statuses.append({"invoice_id": e["id"], "status": "excluded", "reason": e["reason"]})
    # 148 (DECISIONS 148): incoming money with no outgoing invoice as a candidate stays informational, as before
    tied = {c["line_id"] for c in candidates} | set(paid_line) | set(marked)
    idle = sorted(pid for pid, pay in prepared["payments"].items() if pay.get("direction") == "credit" and pid not in tied)
    excluded += [{"kind": "line", "id": pid, "reason": "not_outgoing_payment"} for pid in idle]
    paired = {c["line_id"] for c in candidates if c["proposed"]} | paid_lines | set(marked) | set(idle)
    repeats = _repeats(prepared, candidates, confirmed, rejected, marked, scope, (learned, common), set(paid_invoice), set(credited))
    from jav import policy

    below, above = policy.reconcile_fx_tolerance()
    return {"engine_version": ENGINE_VERSION, "config_hash": config_hash(), "fx_tolerance": [str(below), str(above)],
            "candidates": candidates, "learned_names": len(learned),
            "confirmed": confirmed, "excluded": excluded, "unfit": unfit,  # 153: allocations that no longer fit
            "unfit_marks": unfit_marks,  # 160: marks whose line is gone
            "invoices": sorted(statuses, key=lambda s: s["invoice_id"]),
            "unpaired_line_ids": sorted(p for p, pay in prepared["payments"].items() if p not in paired and pay["statement_id"] in scope),
            "marked": sorted([lid, cat] for lid, cat in marked.items()), "repeats": repeats,
            "unregistered_own": prepared["unregistered_own"],  # 153: lines to an account no party holds
            "paid": {"invoices": {k: str(v) for k, v in sorted(paid_invoice.items())},  # 131: allocated so far
                     "lines": {k: str(v) for k, v in sorted(paid_line.items())}},
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


_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def printable(value: Any) -> Any:
    """167 (review 153 E): a name without the control characters a PDF's text layer may carry (a broken glyph read as
    NUL), which the result table showed as they were; a run of them becomes one space. Other values stay as they are."""
    return " ".join(_CONTROL.sub(" ", value).split()) if isinstance(value, str) else value


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
        # 154 (DECISIONS 154): the documents that came as an attachment of an email routed as suspicious
        from jav.work import SUSPICIOUS_ATTACHMENT

        suspicious = ({r["run_id"] for r in c.execute("SELECT DISTINCT run_id FROM review_reasons WHERE reason=?",
                                                      (SUSPICIOUS_ATTACHMENT,))}
                      if _has_table(c, "review_reasons") else set())
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
                    "seq": int(r["seq"]), "flow_run_id": r["flow_run_id"], "work_run": r["work_run"], "item_id": r["item_id"],
                    "suspicious_source": r["flow_run_id"] in suspicious})
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


def _first(values: dict[str, Any], fields: list[str]) -> Any:
    """The first of the fields with a value (133: the buyer is `buyer_name` on an invoice, `customer_name` on a bill)."""
    return next((values[f] for f in fields if values.get(f) not in (None, "")), None)


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


def bank_rate_needs(invoices: list[dict[str, Any]], statements: list[dict[str, Any]]) -> set[tuple[str, date]]:
    """149: the (currency, day) rates a forint bank line may need: each foreign-currency invoice's fulfilment (else
    issue) day, and every booking day of the forint bank lines in each foreign currency present."""
    f, currencies = _conf()["fx"], set(_conf()["currencies"])
    banks = [s for s in statements if s.get("statement_type") in f["bank"]["statement_types"] and s.get("currency") == f["line_currency"]]
    foreign = [inv for inv in invoices if rate_need(inv) and inv.get("currency") in currencies]
    if not banks or not foreign:
        return set()
    needs = {(str(inv["currency"]), day) for inv in foreign
             if (day := _date(inv.get("fulfillment_date")) or _date(inv.get("issue_date")))}
    days = {day for s in banks for ln in s.get("lines") or [] if (day := _date(ln.get("booking_date")))}
    return needs | {(cur, day) for cur in {str(inv["currency"]) for inv in foreign} for day in days}


def snapshot(current: dict[str, Any] | None = None, *, fetch_rates: bool = False) -> dict[str, Any]:
    """The store's effective invoices and statements, the people's decisions and the exchange rates a card pair needs,
    as a snapshot for `propose`. `current` (doc_id, doc_type, values, validation): the document being processed, in
    place of its stored result. `fetch_rates`: fetch the missing MNB rates first (the processing and the command line);
    a view only reads the stored ones."""
    from jav import parties  # 147: an invoice's direction from the own parties' identities

    conf = _conf()
    f = conf["invoice_fields"]
    marks = _duplicate_marks()
    res = parties.resolver()
    docs = _latest([*conf["invoice_types"], *conf["outgoing_types"], *conf["statement_types"]])
    if current is not None:
        docs = [d for d in docs if d["doc_id"] != current["doc_id"]]
        docs.append({**current, "seq": max((d["seq"] for d in docs), default=0) + 1})
    invoices, statements = [], []
    for d in docs:
        v = d["values"]
        if d["doc_type"] in conf["statement_types"]:
            statements.append(_statement(d))
        else:
            invoices.append({"id": d["doc_id"], "doc_type": d["doc_type"], "number": v.get(f["number"]),
                             "supplier_name": printable(v.get(f["supplier_name"])), "supplier_tax_id": v.get(f["supplier_tax_id"]),
                             "payment_account": _first(v, f["payment_account"]), "payment_method": v.get(f["payment_method"]),
                             "references": [str(v[r]) for r in f["references"] if v.get(r) not in (None, "")],
                             "amount": _amount(v),
                             "currency": v.get(f["currency"]), "issue_date": v.get(f["issue_date"]),
                             "due_date": v.get(f["due_date"]), "duplicate": marks.get(d["doc_id"]),
                             **{k: v.get(f[k]) for k in ("fulfillment_date", "net_total", "vat_total")},  # 142: shown only
                             "buyer_name": printable(_first(v, f["buyer_name"])), "buyer_tax_id": _first(v, f["buyer_tax_id"]),
                             "direction": parties.direction(res, d["doc_type"], v)[0], **_origin(d)})
    # 139 (DECISIONS 139): one valid statement per account, currency and day; a replaced statement's decisions move to
    # the same lines of the one replacing it, and what has no same line is left over (`left_over`)
    from jav import statement_months

    resolution = statement_months.resolve(statements, statement_months.choices())
    every = {s["id"]: s for s in statements}
    statements = resolution.live(statements)
    decisions, left_decisions = statement_months.carry(
        ({"invoice_id": r["invoice_doc_id"], "line_id": r["line_id"], "statement_id": r["statement_doc_id"],
          "decision": r["decision"], "pair_key": r["pair_key"]} for r in _decision_rows()), resolution)
    allocations, left_allocations = statement_months.carry(active_allocations(), resolution)
    marks, left_marks = statement_months.carry(active_marks(), resolution)
    f = conf["fx"]
    cards = any(s.get("statement_type") in f["statement_types"] and s.get("currency") == f["line_currency"] for s in statements)
    needs = {n for inv in invoices if (n := rate_need(inv)) and inv.get("currency") in conf["currencies"]} if cards else set()
    needs |= bank_rate_needs(invoices, statements)
    rates = fx.table(needs, fetch_missing=fetch_rates) if needs else {}
    return {"invoices": invoices, "statements": statements, "decisions": decisions, "fx_rates": rates,
            "allocations": allocations, "marks": marks,
            "registered_accounts": sorted(parties.registered_accounts()),  # 153: the own accounts a party holds
            "replaced": {old: {"by": r.new, "how": r.how, "account": statement_account(every[old]),
                               **{k: every[old].get(k) for k in ("currency", "period_start", "period_end", "doc_type", "work_run")},
                               "lines": every[old]["lines"]}
                         for old, r in sorted(resolution.replaced.items())},
            "conflicts": [list(p) for p in resolution.conflicts], "line_map": dict(resolution.line_map),
            "left_over": {"allocations": left_allocations, "marks": left_marks, "decisions": left_decisions}}


def _statement(d: dict[str, Any]) -> dict[str, Any]:
    """A stored statement in the snapshot's shape."""
    v = d["values"]
    lines = [t for t in v.get("transactions") or [] if isinstance(t, dict)]
    return {"id": d["doc_id"], "doc_type": d["doc_type"], "account": v.get("account_iban") or v.get("account_no"),
            "currency": v.get("currency"), "statement_type": v.get("statement_type"),
            "period_start": v.get("period_start"), "period_end": v.get("period_end"),
            "opening_balance": v.get("opening_balance"), "closing_balance": v.get("closing_balance"),
            "verified": verified(d["validation"]), "lines": [_masked(ln) for ln in with_line_ids(d["doc_id"], lines)],
            "suspicious_source": bool(d.get("suspicious_source")),  # 154: never replaces another statement by rule
            **_origin(d)}


def _masked(line: dict[str, Any]) -> dict[str, Any]:
    """144 (DECISIONS 144): a full card number in a line's texts is masked to its first six and last four digits for every
    view and request (a statement extracted by AI kept it). The id is taken first, so the decisions on the line stay."""
    from jav import card_numbers

    return {**line, **{k: card_numbers.mask_text(line[k]) for k in ("memo", "description", "counterparty_name") if line.get(k)}}


def statements() -> list[dict[str, Any]]:
    """139: every stored statement in the snapshot's shape, a replaced one too (`jav/statement_months.py` decides)."""
    return [_statement(d) for d in _latest(list(_conf()["statement_types"]))]


def active_allocations(c=None) -> list[dict[str, Any]]:
    """131: the allocations not revoked, in the order they were made, in the core's shape."""
    if c is None:
        with store.connect() as own:
            return active_allocations(own)
    if not _has_table(c, "reconcile_allocations"):
        return []
    return [{"id": r["id"], "invoice_id": r["invoice_doc_id"], "line_id": r["line_id"], "statement_id": r["statement_doc_id"],
             "line_amount": r["line_amount"], "invoice_amount": r["invoice_amount"], "workpackage_id": r["workpackage_id"]}
            for r in c.execute("SELECT * FROM reconcile_allocations WHERE revoked_at IS NULL ORDER BY id")]


def active_marks(c=None) -> list[dict[str, Any]]:
    """131: the lines a person marked as needing no invoice, not revoked (the latest per line counts)."""
    if c is None:
        with store.connect() as own:
            return active_marks(own)
    if not _has_table(c, "reconcile_line_marks"):
        return []
    latest: dict[str, dict[str, Any]] = {}
    for r in c.execute("SELECT * FROM reconcile_line_marks WHERE revoked_at IS NULL ORDER BY id"):
        latest[r["line_id"]] = {"id": r["id"], "line_id": r["line_id"], "statement_id": r["statement_doc_id"],
                                "category": r["category"], "note": r["note"], "workpackage_id": r["workpackage_id"]}
    return list(latest.values())


# --- the decisions on the pairs (129, K2; made in the reconciliation package since 137) ----------------------------------


def pair_key(invoice_id: str, line: str) -> str:
    return f"{invoice_id}|{line}"


def _waits(candidate: dict[str, Any]) -> bool:
    """Whether a candidate waits for a person: proposed, or listed for its equal amount alone (131)."""
    return candidate["proposed"] or candidate["amount_only"]


def decisions_for(doc_ids: Iterable[str], c=None) -> list[dict[str, Any]]:
    """The decisions on the pairs that have any of the documents as a side, in a fixed order."""
    ids = set(doc_ids)
    return [d for d in _decision_rows(c) if d["invoice_doc_id"] in ids or d["statement_doc_id"] in ids] if ids else []


def file_names(doc_ids: Iterable[str]) -> dict[str, str]:
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


# --- the pairs already in the store ------------------------------------------------------------------------------------


def scan() -> dict[str, Any]:
    """Counts of the store's proposal for the command line (no values printed). 137: it opens no to-do; the pairs are
    decided in a reconciliation package."""
    snap = snapshot(fetch_rates=True)
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
        "amount_only_pairs": sum(1 for c in result["candidates"] if c["amount_only"]),
        "amount_differs_pairs": sum(1 for c in result["candidates"] if not _waits(c)),
        "signals": count([{"s": s} for c in result["candidates"] for s in c["signals"]], "s"),
        "learned_names": result["learned_names"],
        "relations": count(result["candidates"], "amount_relation"),
        "rates": sum(len(days) for days in snap["fx_rates"].values()),
        "confirmed_pairs": len(result["confirmed"]), "decisions": count(_decision_rows(), "decision"),
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
        out.append({"id": case["id"], "note": case.get("note"),
                    "snapshot": {"invoices": invoices, "statements": statements, "decisions": case.get("decisions", []),
                                 "fx_rates": case.get("fx_rates", {}), "allocations": case.get("allocations", []),
                                 "marks": case.get("marks", []), "own_accounts": case.get("accounts", [])},
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
    if result["marked"] != sorted(exp.get("marked", [])):  # 131 E1: the lines marked as needing no invoice
        problems.append(f"marked {result['marked']} != {sorted(exp.get('marked', []))}")
    if "paid" in exp and result["paid"] != exp["paid"]:  # 131 E1: the amounts allocated so far
        problems.append(f"paid {result['paid']} != {exp['paid']}")
    got_repeats = sorted([r["invoice_id"], r["line_ids"]] for r in result["repeats"])
    if got_repeats != sorted(exp.get("repeats", [])):  # 142: every case names its possible double payments
        problems.append(f"repeats {got_repeats} != {sorted(exp.get('repeats', []))}")
    if "checked_until" in exp:  # 142: the day the named invoices are checked until
        got_until = {s["invoice_id"]: s.get("checked_until") for s in result["invoices"]}
        wanted_until = {k: got_until.get(k) for k in exp["checked_until"]}
        if wanted_until != exp["checked_until"]:
            problems.append(f"checked_until {wanted_until} != {exp['checked_until']}")
    return problems


def golden_score() -> dict[str, Any]:
    cases = golden_cases()
    failures = {c["id"]: p for c in cases if (p := check_case(c))}
    return {"passed": len(cases) - len(failures), "total": len(cases), "failures": failures}
