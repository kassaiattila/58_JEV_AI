"""142 (DECISIONS 142, the reconciliation result's first part): the overview of a reconciliation package's pairing.

The owner asked for a page where one transfer paying several invoices, or one invoice paid by several transfers, is
seen at once with every fact of both sides; where the lines without an invoice, the invoices without a payment, the
overdue invoices, the possible double payments and the late payments stand out. This module computes that view from
the package's workspace (`jav/reconcile_package.py`) and the engine's `repeats`, in code; it decides nothing.

- **Groups.** The statement lines and invoices joined by their pairs - allocated by a person or proposed by code - as
  far as the pairs reach: a transfer with the three invoices it pays, an invoice with the two lines that paid it in
  parts. A line of a possible double payment joins the invoice it may repeat (the nearest one when it may repeat
  several). A line or an own invoice with no pair is a group of its own. Kinds: `proposed` (a proposal waits for a
  person), `paired`, `line_only` (a line with no invoice), `invoice_only` (an invoice with no payment), `credited` (its
  credit note settles it), `marked` (needs no invoice), `excluded` (left out of the pairing).
- **Timing.** Every allocated or proposed pair has its days from the invoice's due date to the line's booking day:
  every day after the due date is a delay (DECISIONS 142: no grace and no severity threshold); none without a due date.
- **Overdue.** An own invoice with something left to pay, nothing proposed for it and its due date before the day its
  statements are checked until (the engine's `checked_until`) is overdue, with the days from its due date to that day:
  no payment was found in the covered period (the statements show nothing about cash or another account).
- **Lists.** Each group is in the lists a person checks (`LISTS`), counted per list.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

KINDS = ("proposed", "paired", "line_only", "invoice_only", "credited", "marked", "excluded")
LISTS = ("to_decide", "line_without_invoice", "invoice_without_payment", "overdue", "late", "double_payment", "clarify",
         "paired", "marked", "credited", "excluded")
OPEN_LINE_STATES = ("proposed", "amount_only", "partly_allocated", "open")
# the flags that ask a person to look at the documents
CLARIFY = ("several_candidates", "amount_differs", "statement_unverified", "double_payment", "rest_left")


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _money(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value not in (None, "") else None
    except InvalidOperation:
        return None


def days_from_due(line: dict[str, Any], invoice: dict[str, Any]) -> int | None:
    """The days from the invoice's due date to the line's booking day (positive: late), None without both."""
    due, booked = _day(invoice.get("due_date")), _day(line.get("booking_date"))
    return (booked - due).days if due and booked else None


class _Joined:
    """Union-find over ("line", id) and ("invoice", id)."""

    def __init__(self) -> None:
        self.parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(self, x: tuple[str, str]) -> tuple[str, str]:
        root = x
        while self.parent.get(root, root) != root:
            root = self.parent[root]
        while self.parent.get(x, x) != root:  # path compression
            self.parent[x], x = root, self.parent[x]
        return root

    def join(self, a: tuple[str, str], b: tuple[str, str]) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _pairs(lines: list[dict[str, Any]], invoices: dict[str, dict[str, Any]],
           repeats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The allocated and proposed pairs of the lines, and each double payment's other lines with the invoice they may
    repeat (the one whose due date, or issue date, is nearest to the line's booking day)."""
    pairs = []
    by_line = {ln["id"]: ln for ln in lines}
    for ln in lines:
        for a in ln.get("allocations") or []:
            if a["invoice_id"] in invoices:
                pairs.append({"line_id": ln["id"], "invoice_id": a["invoice_id"], "state": "allocated",
                              "line_amount": a.get("line_amount"), "invoice_amount": a.get("invoice_amount"),
                              "allocation_id": a.get("allocation_id"), "days_from_due": days_from_due(ln, invoices[a["invoice_id"]])})
        for c in ln.get("candidates") or []:
            if c.get("proposed") and c["invoice_id"] in invoices:
                pairs.append({"line_id": ln["id"], "invoice_id": c["invoice_id"], "state": "proposed",
                              "several": bool(c.get("multiple_candidates")), "relation": c.get("amount_relation"),
                              "days_from_due": days_from_due(ln, invoices[c["invoice_id"]])})
    nearest: dict[str, tuple[int, str]] = {}
    for r in repeats:
        inv = invoices.get(r["invoice_id"])
        if inv is None:
            continue
        anchor = _day(inv.get("due_date")) or _day(inv.get("issue_date"))
        for lid in r["line_ids"]:
            ln = by_line.get(lid)
            if ln is None or lid in r["paid_by"]:
                continue
            booked = _day(ln.get("booking_date"))
            distance = abs((booked - anchor).days) if booked and anchor else 10**6
            if lid not in nearest or (distance, r["invoice_id"]) < nearest[lid]:
                nearest[lid] = (distance, r["invoice_id"])
    pairs += [{"line_id": lid, "invoice_id": iid, "state": "repeat", "days_from_due": None}
              for lid, (_d, iid) in sorted(nearest.items())]
    return pairs


def _invoice_facts(inv: dict[str, Any], pairs: list[dict[str, Any]], lines: dict[str, dict[str, Any]],
                   repeat: dict[str, Any] | None) -> dict[str, Any]:
    """An invoice's payment timing: the day of its last allocated or proposed payment and its days from the due date,
    and the days it is overdue with no payment found by the day its statements are checked until."""
    paying = [p for p in pairs if p["invoice_id"] == inv["id"] and p["state"] in ("allocated", "proposed")]
    days = [d for p in paying if (d := _day(lines[p["line_id"]].get("booking_date")))]
    paid_on = max(days) if days else None
    due = _day(inv.get("due_date"))
    rest = _money(inv.get("rest"))
    checked = _day(inv.get("checked_until"))
    open_rest = (inv.get("own") is not False and inv.get("state") not in ("confirmed", "credited", "excluded")
                 and rest is not None and rest > 0 and not any(p["state"] == "proposed" for p in paying))
    overdue = (checked - due).days if open_rest and due and checked and due < checked else None
    return {"paid_on": paid_on.isoformat() if paid_on else None,
            "days_from_due": (paid_on - due).days if paid_on and due else None,
            "overdue_days": overdue, "checked_until": inv.get("checked_until"),
            "double_payment": {"line_ids": repeat["line_ids"], "paid_by": repeat["paid_by"]} if repeat else None}


def _kind(lines: list[dict[str, Any]], invoices: list[dict[str, Any]], states: set[str]) -> str:
    if "proposed" in states:
        return "proposed"
    if "allocated" in states:
        return "paired"
    if invoices:
        if all(i.get("state") == "credited" for i in invoices):
            return "credited"
        return "paired" if all(i.get("state") == "confirmed" for i in invoices) else "invoice_only"
    state = lines[0].get("state") if lines else None
    return "marked" if state == "marked" else "excluded" if state == "excluded" else "line_only"


def _flags(kind: str, lines: list[dict[str, Any]], invoices: list[dict[str, Any]], pairs: list[dict[str, Any]],
           facts: dict[str, dict[str, Any]]) -> list[str]:
    flags = []
    if any(p["state"] in ("allocated", "proposed") and (p["days_from_due"] or 0) > 0 for p in pairs):
        flags.append("late")
    if any(facts[i["id"]]["overdue_days"] is not None for i in invoices):
        flags.append("overdue")
    if any(facts[i["id"]]["double_payment"] for i in invoices):
        flags.append("double_payment")
    if any(p.get("several") for p in pairs):
        flags.append("several_candidates")
    if any(i.get("state") == "amount_differs" for i in invoices):
        flags.append("amount_differs")
    if any(not ln.get("statement_verified", True) for ln in lines if ln.get("state") != "excluded"):
        flags.append("statement_unverified")
    if ((kind == "paired" and any(ln.get("state") == "partly_allocated" for ln in lines))
            or any(i.get("state") == "partly_paid" for i in invoices)):
        flags.append("rest_left")
    if any(not i.get("due_date") for i in invoices):
        flags.append("no_due_date")
    if invoices and any(i.get("state") == "confirmed" for i in invoices) and not any(p["state"] == "allocated" for p in pairs):
        flags.append("paid_elsewhere")  # allocated to a line outside this package
    return flags


def _lists(kind: str, lines: list[dict[str, Any]], flags: list[str]) -> list[str]:
    out = []
    if any(ln.get("state") in OPEN_LINE_STATES for ln in lines):
        out.append("to_decide")
    out += {"line_only": ["line_without_invoice"], "invoice_only": ["invoice_without_payment"]}.get(kind, [])
    out += [f for f in ("overdue", "late", "double_payment") if f in flags]
    if any(f in CLARIFY for f in flags):
        out.append("clarify")
    if kind in ("paired", "marked", "credited", "excluded"):
        out.append(kind)
    return out


def build(lines: list[dict[str, Any]], invoices: list[dict[str, Any]], repeats: list[dict[str, Any]]) -> dict[str, Any]:
    """The groups of the package's lines and invoices with their pairs, kind, flags and lists; per invoice its payment
    timing; and the number of groups in each list."""
    line_by = {ln["id"]: ln for ln in lines}
    invoice_by = {i["id"]: i for i in invoices}
    pairs = _pairs(lines, invoice_by, repeats)
    joined = _Joined()
    for p in pairs:
        joined.join(("line", p["line_id"]), ("invoice", p["invoice_id"]))
    paired_invoices = {p["invoice_id"] for p in pairs}
    members: dict[tuple[str, str], dict[str, list[str]]] = {}
    for ln in lines:
        members.setdefault(joined.find(("line", ln["id"])), {"lines": [], "invoices": []})["lines"].append(ln["id"])
    for inv in invoices:  # another party's invoice is shown only in a pair
        if inv.get("own") is not False or inv["id"] in paired_invoices:
            members.setdefault(joined.find(("invoice", inv["id"])), {"lines": [], "invoices": []})["invoices"].append(inv["id"])
    repeat_of = {r["invoice_id"]: r for r in repeats if r["invoice_id"] in invoice_by}
    facts = {i["id"]: _invoice_facts(i, pairs, line_by, repeat_of.get(i["id"])) for i in invoices}
    pairs_of: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for p in pairs:
        pairs_of.setdefault(joined.find(("line", p["line_id"])), []).append(p)
    groups = []
    for root, m in members.items():
        g_lines = sorted((line_by[i] for i in m["lines"]), key=lambda ln: (str(ln.get("booking_date") or ""), ln["id"]))
        g_invoices = sorted((invoice_by[i] for i in m["invoices"]), key=lambda i: (str(i.get("issue_date") or ""), i["id"]))
        g_pairs = pairs_of.get(root, [])
        kind = _kind(g_lines, g_invoices, {p["state"] for p in g_pairs})
        flags = _flags(kind, g_lines, g_invoices, g_pairs, facts)
        days = [str(ln.get("booking_date") or "") for ln in g_lines] or [
            str(i.get("due_date") or i.get("issue_date") or "") for i in g_invoices]
        groups.append({"id": f"{root[0]}:{root[1]}", "kind": kind, "date": min(days) if days else "",
                       "lines": [ln["id"] for ln in g_lines], "invoices": [i["id"] for i in g_invoices],
                       "pairs": g_pairs, "flags": flags, "lists": _lists(kind, g_lines, flags)})
    groups.sort(key=lambda g: (g["date"], g["id"]))
    counts = {name: sum(1 for g in groups if name in g["lists"]) for name in LISTS}
    return {"groups": groups, "invoices": facts, "counts": {**counts, "all": len(groups)}}
