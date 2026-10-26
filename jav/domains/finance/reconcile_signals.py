"""231 (plan stage C, C2b): what ties a statement line to an invoice, split out of `reconcile.py`.

Plain-language summary: the normalisation of names, numbers and amounts (ported from the legacy `payables.py`), the
stable line ids, an invoice's partner and direction, and the signals with their strength (the invoice number or a
reference in the memo, the supplier's account or name, a looser name, the payment app, a learnt name). The rules they
follow are described in `reconcile.py` (131, 134, 141); their parameters are `configs/reconcile.json`.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any, Iterable

from jav.documents import fact_checks
from jav.core import type_roles, values
from jav.ai.candidates import trim_after_legal_form
from jav.ai.models import account_key
from jav.domains.finance import reconcile_rules
from jav.domains.finance.reconcile_rules import _ignore_tokens


# --- normalisation and signals -------------------------------------------------------------------------------------


NAMED_SIGNALS = frozenset({"invoice_number", "reference"})  # 141: the line's memo names the invoice
SIGNALS = ("invoice_number", "reference", "supplier_account", "supplier_name", "supplier_name_fuzzy", "payment_channel",
           "learned_name")
WEAK_SIGNALS = frozenset({"payment_channel", "supplier_name_fuzzy"})  # alone they tie only an equal amount
_MONEY = re.compile(r"-?\d+(?:\.\d{1,2})?")


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
    return next((r["mark"] for r in reconcile_rules._conf().get("category_marks", []) if re.search(r["pattern"], text)), None)


def salary_mark(line: dict[str, Any]) -> str | None:
    """147: the salary reason when a line's normalised memo or description matches a `salary_marks` pattern, or None.
    A suggestion for a person, never a mark by itself."""
    text = " ".join(normalize(line.get(k)) for k in ("memo", "description")).strip()
    if text and any(re.search(p, text) for p in reconcile_rules._conf().get("salary_marks", [])):
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
    least = int(reconcile_rules._conf()["signals"]["fuzzy_name"]["min_chars"])
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
    f = reconcile_rules._conf()["signals"]["fuzzy_name"]
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
    f = reconcile_rules._conf()["signals"]["fuzzy_name"]
    least = int(f["min_chars"])
    if other.startswith(word) or (len(other) >= max(least, float(f["min_prefix_share"]) * len(word)) and word.startswith(other)):
        return True
    return (min(len(word), len(other)) >= least and abs(len(word) - len(other)) <= 2
            and SequenceMatcher(None, word, other).ratio() >= float(f["min_ratio"]))


def _number_in(value: Any, text: str) -> bool:
    """A document number in a line's text: as whole words, or without separators when long enough (128)."""
    s = reconcile_rules._conf()["signals"]
    number, number_c = normalize(value), compact(value)
    return len(number_c) >= int(s["min_number_chars"]) and bool(
        _whole_word(number).search(normalize(text))
        or (len(number_c) >= int(s["min_compact_number_chars"]) and number_c in compact(text)))


@lru_cache(maxsize=16384)
def _whole_word(number: str) -> re.Pattern[str]:
    """174 (review 160 M-10): a normalised number as a whole-word pattern, compiled once. `re` keeps 512 patterns, and
    a pairing of 1 500 invoices compiled thousands again and again (54 % of its 27 s)."""
    return re.compile(r"(?<![a-z0-9])" + re.escape(number) + r"(?![a-z0-9])")


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


def statement_account(statement: dict[str, Any]) -> str:
    """The own account a statement belongs to: its account key, else its printed account, else the statement itself."""
    key = account_key(statement.get("account"))
    return key or ("raw:" + compact(statement.get("account")) if compact(statement.get("account")) else "doc:" + str(statement["id"]))


def outgoing(invoice: dict[str, Any]) -> bool:
    """148: whether the invoice is an own party's outgoing invoice: its direction when known (147), else its type."""
    return invoice["direction"] == "outgoing" if invoice.get("direction") else type_roles.has(invoice.get("doc_type"), "outgoing_invoice")


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


def _line_text(payment: dict[str, Any]) -> str:
    return normalize(f"{payment.get('counterparty_name') or ''} {payment.get('description') or ''} {payment.get('memo') or ''}")


def through_app(payment: dict[str, Any]) -> bool:
    """Whether the line names the payment app of a configured channel (131): such a line pays many suppliers."""
    text = _line_text(payment)
    return any(re.search(ch["line_text"], text) for ch in reconcile_rules._conf()["payment_channels"])


def _channel(invoice: dict[str, Any], payment: dict[str, Any]) -> bool:
    """The invoice's payment method fits a channel and the line names that channel's payment app (131)."""
    method, text = normalize(invoice.get("payment_method")), _line_text(payment)
    return bool(method) and any(re.search(ch["invoice_method"], method) and re.search(ch["line_text"], text)
                                for ch in reconcile_rules._conf()["payment_channels"])


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
    s = reconcile_rules._conf()["signals"]
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
    w = reconcile_rules._conf()["strength"]
    issue, booked = values.stored_day(invoice.get("issue_date")), values.stored_day(payment.get("booking_date"))
    due = values.stored_day(invoice.get("due_date")) or issue
    days = (booked - issue).days if issue and booked else None
    by_due = bool(issue and booked and due and issue <= booked <= max(due, issue) + timedelta(days=int(w["grace_days"])))
    score = sum(int(w["signals"].get(s, 0)) for s in found) + int(w["amount"].get(relation or "", 0))
    score += int(w["timing"]["by_due"] if by_due else w["timing"]["in_window"] if in_window else 0)
    return {"strength": min(score, int(w["max"])), "days_after_issue": days, "by_due": by_due}
