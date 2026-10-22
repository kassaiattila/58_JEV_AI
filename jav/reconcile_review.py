"""147 (backlog F-quick-review; DECISIONS 147): the quick review of a reconciliation package.

The owner's request of 2026-10-12: the lines whose pair or reason is known with high probability are shown in groups,
for a quick look and one click each - salary, needs no invoice, a transfer, a sure pair, and so on. Each line a person
still decides is in the first group that fits, in this order:

- `sure_pairs`: the unambiguous proposals (`reconcile_package.proposed_pairs`, as the cards' accept button);
- `earlier`: the reason a person gave the partner's other lines (the most frequent);
- `bank_category`: the reason the line's own category in the bank's export suggests (`reconcile.category_mark`);
- `salary_rule`: the salary reason the memo or the description suggests (`reconcile.salary_mark`);
- `ai_sure`: both engines (JEV and GPT) give the same kind of payment, it suggests a reason, and JEV's probability is
  at least the policy's threshold (`policy.json` `reconcile.ai_sure`, the owner's decision: 0.95);
- `ai_review`: the AI suggests a reason below the threshold, or only one engine answered: to look at;
- `expects_invoice`: the AI's kind says an invoice is expected and the line has no candidate (for information);
- `rest`: everything else, for the pairing page.

A line with a candidate invoice or an allocated amount is never in a reason group: a person pairs or rules it out. The
lines code left out (excluded) are counted by their reason, for information; 158: incoming money left out without an
outgoing invoice whose kind the AI read as one that expects an invoice (a customer's payment) is listed under
`expects_invoice` instead, as an outgoing invoice may be missing from the store. Accepting a group re-reads it and takes
only the lines still in it (a stale view is refused), all or none: a sure pair is allocated, a reason is marked with
the group as its `basis`. Agreement of the two models is not measured correctness; a person accepts each group.

Layer: UI/CLI → **this** (application operation) → `jav.reconcile_package` (the workspace, the pairs, the marks),
`jav.reconcile` (the salary rule) and `jav.policy` (the threshold). No AI call: it reads the answers already stored.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal
from typing import Any, Iterable

from jav import policy, reconcile, reconcile_package, values, work
from jav.user_messages import explained

GROUPS = ("sure_pairs", "earlier", "bank_category", "salary_rule", "ai_sure", "ai_review", "expects_invoice", "rest")
ACTIONS = {"sure_pairs": "pair", "expects_invoice": "none", "rest": "none"}  # every other group marks a reason
DECIDING = ("proposed", "amount_only", "partly_allocated", "open")  # a line a person still decides
ENGINES = ("jev", "gpt")
BRIEF = ("id", "statement_id", "booking_date", "amount", "currency", "direction", "counterparty_name", "memo", "description",
         "file", "partner")


class ReviewError(ValueError):
    """A quick review request that cannot be met: an unknown group, a group with nothing to accept, no line."""


def _money(value: Any) -> Decimal:
    """A stored amount, or zero when there is none (153, review A6: by the shared reader; "NaN" or an exponent counted
    before, "12,5" read as zero without a word)."""
    return values.stored_decimal(value) or Decimal(0)


def _answers(line: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The engines' usable answers about the line's kind of payment (an answer with an error or no kind is left out)."""
    out = {}
    for engine in ENGINES:
        a = (line.get("ai") or {}).get(engine)
        if a and not a.get("error") and a.get("kind"):
            out[engine] = a
    return out


def _place(line: dict[str, Any], sure: dict[str, list[str]], threshold: float) -> tuple[str, dict[str, Any]]:
    """The line's group and what the group suggests for it: the invoices of a sure pair or a reason."""
    if line["id"] in sure:
        return "sure_pairs", {"invoice_ids": sure[line["id"]]}
    # 174 (review 160 M-16): a candidate among another own party's invoices (133) keeps the line for a person too
    if line["candidates"] or line.get("other_candidates") or _money(line.get("allocated")) > 0:
        return "rest", {}
    if earlier := line.get("earlier_marks"):
        return "earlier", {"category": earlier[0]["category"]}  # the most frequent first (the workspace's order)
    if category := line.get("category_mark"):
        return "bank_category", {"category": category}
    if category := reconcile.salary_mark(line):
        return "salary_rule", {"category": category}
    answers = _answers(line)
    marks = {a.get("suggested_mark") for a in answers.values()}
    if len(answers) == len(ENGINES) and len({a["kind"] for a in answers.values()}) == 1 and None not in marks:
        sure_kind = (answers["jev"].get("kind_probability") or 0) >= threshold
        return ("ai_sure" if sure_kind else "ai_review"), {"category": marks.pop()}
    if len(answers) == 1 and None not in marks:
        return "ai_review", {"category": marks.pop()}
    if any(a.get("expects_invoice") for a in answers.values()):
        return "expects_invoice", {}
    return "rest", {}


def _brief(line: dict[str, Any], suggestion: dict[str, Any], invoices: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = {k: line.get(k) for k in BRIEF}
    if "category" in suggestion:
        out["category"] = suggestion["category"]
    if "invoice_ids" in suggestion:
        out["invoices"] = [{k: invoices.get(i, {}).get(k) for k in ("number", "supplier_name", "amount", "currency", "issue_date")}
                           | {"id": i, "partner_name": reconcile.partner_name(invoices.get(i, {}))}  # 148: the buyer if outgoing
                           for i in suggestion["invoice_ids"]]
    if answers := _answers(line):
        out["ai"] = {e: {"kind": a["kind"], "probability": a.get("kind_probability")} for e, a in answers.items()}
    if earlier := line.get("earlier_marks"):
        out["earlier_lines"] = earlier[0]["lines"]
    return out


def _totals(lines: Iterable[dict[str, Any]]) -> dict[str, str]:
    sums: dict[str, Decimal] = defaultdict(Decimal)
    for ln in lines:
        sums[str(ln.get("currency") or "")] += _money(ln.get("amount"))
    return {k: str(v) for k, v in sorted(sums.items())}


def review(wp_id: str) -> dict[str, Any]:
    """The package's lines to decide in their groups (each with its action, its lines, their count and totals per
    currency, and 158: how many of them a person decides - not the incoming money shown for information), the excluded
    lines by their reason, the decided ones counted by state, and the AI threshold used."""
    ws = reconcile_package.kept_workspace(wp_id)  # 153: read only
    sure: dict[str, list[str]] = defaultdict(list)
    for p in reconcile_package.proposed_pairs(wp_id):
        sure[p["line_id"]].append(p["invoice_doc_id"])
    threshold = float(policy.RECONCILE["ai_sure"]["min_jev_probability"])
    invoices = {i["id"]: i for i in ws["invoices"]}
    groups: dict[str, list[dict[str, Any]]] = {g: [] for g in GROUPS}
    shown_only: Counter[str] = Counter()  # 158: lines a group shows for information, with nothing for a person to decide
    excluded: dict[str, list[dict[str, Any]]] = defaultdict(list)
    decided: Counter[str] = Counter()
    for ln in ws["lines"]:
        if ln["state"] == "excluded" and ln.get("excluded_reason") == "not_outgoing_payment" and any(
                a.get("expects_invoice") for a in _answers(ln).values()):
            groups["expects_invoice"].append(_brief(ln, {}, invoices))  # 158: a customer's payment without its invoice
            shown_only["expects_invoice"] += 1
        elif ln["state"] == "excluded":
            excluded[ln.get("excluded_reason") or "other"].append(_brief(ln, {}, invoices))
        elif ln["state"] not in DECIDING or ln.get("locked"):
            decided[ln["state"]] += 1
        else:
            group, suggestion = _place(ln, sure, threshold)
            groups[group].append(_brief(ln, suggestion, invoices))
    return {"workpackage_id": wp_id, "threshold": threshold,
            "groups": [{"id": g, "action": ACTIONS.get(g, "mark"), "lines": ls, "count": len(ls),
                        "to_decide": len(ls) - shown_only[g], "totals": _totals(ls)} for g, ls in groups.items()],
            "excluded": {r: {"count": len(ls), "totals": _totals(ls), "lines": ls} for r, ls in sorted(excluded.items())},
            "decided": dict(sorted(decided.items()))}


def accept(wp_id: str, group: str, line_ids: Iterable[str], *, actor: str, expected_state: int | None = None) -> int:
    """A person accepts the group's suggestion for the given lines: all or none, and only lines still in the group
    (`work.RevisionConflict` otherwise: the view was stale). Returns how many lines were decided."""
    if group not in GROUPS:
        raise explained(ReviewError, "unknown group {{group}}", group=repr(group))
    if ACTIONS.get(group) == "none":
        raise explained(ReviewError, "the {{group}} group has nothing to accept", group=group)
    ids = list(dict.fromkeys(line_ids))
    if not ids:
        raise explained(ReviewError, "no line to accept")
    current = {ln["id"]: ln for g in review(wp_id)["groups"] if g["id"] == group for ln in g["lines"]}
    if gone := [lid for lid in ids if lid not in current]:
        raise explained(work.RevisionConflict, "{{gone}} line(s) are no longer in this group: reload the quick review",
                        gone=len(gone))
    if group == "sure_pairs":
        pairs = [{"invoice_doc_id": inv["id"], "line_id": lid} for lid in ids for inv in current[lid]["invoices"]]
        return len({row["line_id"] for row in reconcile_package.allocate(wp_id, pairs, note=None, actor=actor,
                                                                          expected_state=expected_state)})
    reconcile_package.mark_each(wp_id, {lid: current[lid]["category"] for lid in ids}, note=None, actor=actor, basis=group,
                                expected_state=expected_state)
    return len(ids)
