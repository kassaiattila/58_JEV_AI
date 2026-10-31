"""The finance domain's tables on the interface (185, plan G-full-move T1b; until then in `jav/app/datasets.py`).

Plain-language summary: three tables of the shared data view are the finance domain's: a reconciliation package's
inputs as its item list (169: the scope's statements, then the invoices its pairing may take, with where each result
comes from and where it stands in the pairing), and the utility cost of a run or of a package's current result, as a
monthly grid (054 K4) and as the source invoices of each cell. They moved here from `jav/app/datasets.py` as they were:
the same columns, rows and order. The finance domain module registers them (`jav/domains/finance/__init__.py`), and the data
view asks its registry.

Layer: application operation (a read view) → `jav.domains.finance.reconcile_package`, `jav.domains.finance.report_utility`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jav.app import datasets, work
from jav.app.datasets import Rows, col


def reconcile_inputs(scope: dict[str, str]) -> Rows:
    """169 (DECISIONS 169): a reconciliation package's inputs as its item list: the scope's statements, then the
    invoices its pairing may take (another party's only with `others`), each with the package and the run its result
    comes from, whether it blocks the approval, and where it stands in the pairing; with `left_out`, the documents left
    out of the package too, with who left them out, when and why. Read from the kept workspace. 231 (C2d): `kind`
    (`statement` or `invoice`) keeps only that kind (a pairing case's Statements and Invoices tabs)."""
    from jav.domains.finance import reconcile_package

    ws = reconcile_package.kept_workspace(scope["workpackage_id"])
    refs = ws.get("open") or {}
    briefs = work.run_briefs(ref["run_id"] for ref in refs.values())
    blocking = {b["doc_id"] for b in ws["blockers"] if str(b["code"]).startswith("source_")}
    cols = [
        col("name", "Document", link="review"),
        col("kind", "Kind", "enum", labels="reconcile_input_kind"),
        col("subject", "Number or account"),
        col("partner", "Counterparty"),
        col("date", "Date or period"),
        col("amount", "Amount", "money"),
        col("currency", "Currency", hidden=True),
        col("party", "Party", hidden=scope.get("others") != "1"),
        col("package", "Package", link="workpackage"),
        col("source", "Counted run", "enum", labels="reconcile_input_source", link="run", badge=True),
        col("pairing", "In the pairing", "enum", labels="reconcile_invoice_state"),
        col("open_lines", "Open lines", "number", alert=True, hidden=True),  # a statement's only; Pairing shows its lines
        col("blocks", "Blocks the approval", "enum", labels="yes", hidden=True),  # the Preparation's blockers card lists them
        col("lines", "Lines in the period", "number", hidden=True),
        col("verified", "Balances check out", "enum", labels="yes", hidden=True),
        col("doc_id", "Document ID", "id", hidden=True),
    ]

    def common(doc_id: str, file: str | None, source: str | None) -> dict[str, Any]:
        ref = refs.get(doc_id) or {}
        brief = briefs.get(ref.get("run_id") or "") or {}
        shown_source = (("live" if brief.get("mode") == "apply" else "trial") if source == "not_approved" else source)
        return {"_key": doc_id, "_wp": ref.get("workpackage_id"), "_run": ref.get("run_id"), "_left_out": False,
                "item_id": ref.get("item_id"), "doc_id": doc_id, "name": file or doc_id[:12],
                "package": brief.get("workpackage_name"), "source": shown_source, "blocks": "igen" if doc_id in blocking else None}

    def period(row: dict[str, Any]) -> str | None:
        """A statement's period, its end without the year when it is the start's (the column stays narrow)."""
        first, last = str(row.get("period_start") or "")[:10], str(row.get("period_end") or "")[:10]
        if first[:5] and first[:5] == last[:5]:
            last = last[5:]
        return f"{first} – {last}" if first or last else None

    rows = []
    for st in sorted(ws.get("statements") or [], key=lambda s: (str(s.get("account") or ""), str(s.get("period_start") or ""))):
        rows.append({**common(st["id"], st["file"], st["source"]), "kind": "statement", "subject": st.get("account"),
                     "partner": None, "date": period(st), "amount": None, "currency": st.get("currency"),
                     "party": (ws["scope"].get("party") or {}).get("name"), "pairing": None, "open_lines": st["open_lines"],
                     "lines": st["lines"], "verified": "igen" if st["verified"] else None})
    for inv in ws["invoices"]:
        if not inv["own"] and scope.get("others") != "1":
            continue
        rows.append({**common(inv["id"], inv.get("file"), inv.get("source")), "kind": "outgoing" if inv.get("outgoing") else "incoming",
                     "subject": inv.get("number"), "partner": inv.get("partner_name"), "date": inv.get("issue_date"),
                     "amount": inv.get("amount"), "currency": inv.get("currency"), "party": (inv.get("party") or {}).get("name"),
                     "pairing": inv.get("state"), "open_lines": None, "lines": None, "verified": None})
    if scope.get("left_out") == "1":
        cols += [col("left_out_by", "Left out by"), col("left_out_at", "Left out at", "datetime", hidden=True),
                 col("left_out_reason", "Reason for leaving it out")]
        rows = [{**r, "left_out_by": None, "left_out_at": None, "left_out_reason": None} for r in rows]
        for g in ws.get("left_out") or []:
            invoice = g["kind"] == "invoice"
            rows.append({**common(g["id"], g.get("file"), g.get("source")), "_left_out": True, "blocks": None,
                         "kind": ("outgoing" if g.get("outgoing") else "incoming") if invoice else "statement",
                         "subject": g.get("number") if invoice else g.get("account"), "partner": g.get("partner_name"),
                         "date": g.get("issue_date") if invoice else period(g), "amount": g.get("amount"),
                         "currency": g.get("currency"), "party": (g.get("party") or {}).get("name"), "pairing": None,
                         "open_lines": None, "lines": None, "verified": None, "left_out_by": g["actor"],
                         "left_out_at": g["left_out_at"], "left_out_reason": g["reason"]})
    if scope.get("kind") in ("statement", "invoice"):
        rows = [r for r in rows if (r["kind"] == "statement") == (scope["kind"] == "statement")]
    return cols, rows


def _utility_report(scope: dict[str, str]) -> tuple[Callable[[str | None], dict[str, Any]], dict[str, Any]]:
    from jav.domains.finance import report_utility

    link, records = datasets.linked_records(scope)
    return link, report_utility.build(records)


def utility_cost(scope: dict[str, str]) -> Rows:
    """The monthly utility-cost grid in long form: consumption point × utility × month per row (pivotable in Excel)."""
    link, rep = _utility_report(scope)
    to = link(None)
    cols = [
        col("address", "Point of consumption"),
        col("utility", "Utility", "enum"),
        col("month", "Month", "date"),
        col("status", "Status", "enum", labels="utility_status"),
        col("amount", "Amount (gross, for the month)", "money"),
        col("consumption", "Consumption", "number"),
        col("unit", "Unit (column)", "enum", hidden=True),
        col("settlement", "Settlement invoice", "enum", labels="yes", hidden=True),
        col("summary_only", "Information only", "enum", labels="yes"),
        col("bills", "Source invoices", "number"),
        col("suppliers", "Supplier (column)", hidden=True),
    ]
    rows = []
    for s_ in rep["series"]:
        for m, c in s_["cells"].items():
            rows.append({"_key": f"{s_['address']}|{s_['utility']}|{m}", "_run": to["_run"], "_wp": to["_wp"],
                         "address": s_["address"], "utility": s_["utility"], "month": m, "status": c["status"], "amount": c["amount"],
                         "consumption": c["consumption"], "unit": s_["consumption_unit"], "settlement": "igen" if c["settlement"] else None,
                         "summary_only": "igen" if s_["summary_only"] else None, "bills": len(c["sources"]),
                         "suppliers": ", ".join(s_["suppliers"])})
    return cols, rows


def utility_sources(scope: dict[str, str]) -> Rows:
    """Source invoices of each utility-cost cell (the report's "Közmű-források" sheet): cell → document, page, sum."""
    link, rep = _utility_report(scope)
    cols = [
        col("address", "Point of consumption"),
        col("utility", "Utility", "enum"),
        col("month", "Month", "date"),
        col("status", "Status", "enum", labels="utility_status"),
        col("amount", "Amount (for the month)", "money"),
        col("file", "Document (column)", link="review"),
        col("page", "Page", "number"),
        col("field", "Field", "enum", labels="field"),
        col("corrected", "Corrected (column)", "enum", labels="yes"),
        col("open_reasons", "Open to-dos (column)", "number", alert=True),
        col("item_id", "Item ID", "id", hidden=True),
    ]
    rows = []
    for s_ in rep["series"]:
        for m, c in s_["cells"].items():
            for i, x in enumerate(c["sources"]):
                rows.append({"_key": f"{s_['address']}|{s_['utility']}|{m}|{i}", **datasets.run_wp(link(x["item_id"])),
                             "address": s_["address"], "utility": s_["utility"], "month": m,
                             "status": "settlement" if x.get("settlement") else c["status"], "amount": x["amount"], "file": x["file"],
                             "page": x["page"], "field": x["field"], "corrected": "igen" if x["corrected"] else None,
                             "open_reasons": x["open_reasons"], "item_id": x["item_id"]})
    for u in rep["unplaced"]:
        rows.append({"_key": f"unplaced|{u['item_id']}", **datasets.run_wp(link(u["item_id"])), "status": u["reason"],
                     "file": u["file"], "item_id": u["item_id"]})
    for d in rep.get("duplicates", []):
        rows.append({"_key": f"duplicate|{d['item_id']}", **datasets.run_wp(link(d["item_id"])), "status": "duplicate",
                     "file": d["file"], "item_id": d["item_id"]})
    return cols, rows


def own_parties(_scope: dict[str, str]) -> Rows:
    """263 (plan E, E1; the owner's decisions of 2026-10-30: one list everywhere): the own parties as a Settings list -
    each with its tax numbers, how many invoices name it and their span, its accounts and their statements' span; a row
    opens the party's page in Settings (`link="settings"`, section `parties`)."""
    from jav.domains.finance import party_views

    cols = [
        col("name", "Name", link="settings", section="parties"),
        col("tax", "Tax number", "id"),
        col("invoices", "Invoices", "number"),
        col("first", "First invoice", "date"),
        col("last", "Last invoice", "date"),
        col("accounts", "Accounts", "number"),
        col("statements_last", "Last statement", "date"),
        col("updated_at", "Changed", "datetime", hidden=True),
    ]
    rows = [{"_key": p["id"], "name": p["name"],
             "tax": ", ".join(i["label"] for i in p["identities"] if i["kind"] == "tax") or None,
             "invoices": p["invoices"], "first": p["first"], "last": p["last"], "accounts": len(p["accounts"]),
             "statements_last": p["statements_last"], "updated_at": p["updated_at"]} for p in party_views.overview()["parties"]]
    return cols, rows


def _statement(scope: dict[str, str]) -> tuple[dict[str, Any], dict[str, str]]:
    """263 (F3): a reconciliation's statement as it stands now, or its approved `version`, and the buyer of each own
    party's outgoing invoice (shown by its buyer, as the pairing shows it; the statement keeps its supplier)."""
    from jav.domains.finance import reconcile_package, reconcile_statement

    wp_id = scope["workpackage_id"]
    ws = reconcile_package.kept_workspace(wp_id)
    buyers = {i["id"]: i["partner_name"] for i in ws["invoices"] if i.get("outgoing") and i.get("partner_name")}
    version = scope.get("version")
    statement = (reconcile_statement.approved_version(wp_id, int(version))["statement"] if version and version.isdigit()
                 else reconcile_statement.build(ws, work.get(wp_id)["name"]))
    return statement, buyers


def statement_invoices(scope: dict[str, str]) -> Rows:
    """263 (plan E, F3; the owner's decision of 2026-10-30: every list the one list): the invoices of a reconciliation's
    statement with their results, payments and lateness - searchable, sortable and grouped by their result."""
    statement, buyers = _statement(scope)
    cols = [
        col("number", "Invoice number"),
        col("counterparty", "Counterparty", group=True),
        col("due_date", "Due date", "date"),
        col("amount", "Amount", "money"),
        col("currency", "Currency", hidden=True),
        col("result", "Result", "enum", labels="reconcile_invoice_result", group=True),
        col("rest", "Left", "money"),
        col("paid_on", "Paid on", "date"),
        col("days_late", "Days late", "number"),
        col("overdue_days", "Days overdue", "number", hidden=True),
        col("other_party", "Another party's", hidden=True),
        col("file", "File", hidden=True),
    ]
    rows = [{"_key": i["id"], "number": i.get("number"), "counterparty": buyers.get(i["id"]) or i.get("supplier_name"),
             "buyer": i["id"] in buyers, "due_date": i.get("due_date"), "amount": i.get("amount"), "currency": i.get("currency"),
             "result": i["result"], "rest": None if i["result"] == "paid" else i.get("rest"), "paid_on": i.get("paid_on"),
             "days_late": i.get("days_from_due") if (i.get("days_from_due") or 0) > 0 else None,
             "overdue_days": i.get("overdue_days"), "other_party": i.get("other_party"), "file": i.get("file")}
            for i in statement["invoices"]]
    return cols, rows


def statement_lines(scope: dict[str, str]) -> Rows:
    """263 (F3): the lines of a reconciliation's statement with their results and what they paid or why they need no
    invoice - searchable, sortable and grouped by their result (a person filters to the open ones)."""
    statement, _buyers = _statement(scope)
    cols = [
        col("booking_date", "Booking date", "date"),
        col("counterparty", "Counterparty", group=True),
        col("memo", "Remittance info", clamp=2),
        col("amount", "Amount", "money"),
        col("currency", "Currency", hidden=True),
        col("direction", "Direction", "enum", labels="reconcile_direction", group=True),
        col("result", "Result", "enum", labels="reconcile_line_result", group=True),
        col("pays", "Reason or invoice", clamp=2),
        col("account", "Account", group=True, hidden=True),
    ]
    rows = [{"_key": ln["id"], "booking_date": ln.get("booking_date"), "counterparty": ln.get("counterparty_name"),
             "memo": ln.get("memo") or ln.get("description"), "amount": ln.get("amount"), "currency": ln.get("currency"),
             "direction": ln.get("direction"), "result": ln["result"], "reason": ln.get("reason"), "note": ln.get("note"),
             "pays": ", ".join(str(x.get("number") or x.get("supplier_name") or "") for x in ln["pays"]) or None,
             "account": ln.get("account")}
            for ln in statement["lines"]]
    return cols, rows


def package_statements(scope: dict[str, str]) -> Rows:
    """264 (plan E, F6; the owner's decision of 2026-10-31: the small lists the one list too): a bank statements batch's
    statements - the file (leading to its review), the account, the period, how it was read and its state - grouped by
    their state; one booking the same days as another is where a person chooses the valid one."""
    from jav.domains.finance import statement_package

    wp_id = scope["workpackage_id"]
    cols = [
        col("file", "File", link="item"),
        col("account", "Account", "id"),
        col("period", "Period"),
        col("period_start", "From", "date", hidden=True),
        col("rank", "Checks", "enum", labels="statement_rank", group=True),
        col("state", "State", "enum", labels="statement_state", badge=True, group=True,
            marks={"valid": "done", "replaced": "muted", "conflict": "review", "pending": "waiting"}),
    ]
    rows = [{"_key": s["item_id"], "_wp": wp_id, "item_id": s["item_id"], "file": s.get("file"),
             "account": " ".join(x for x in (s.get("account"), s.get("currency")) if x) or None,
             "period": f"{s['period_start']} – {s.get('period_end') or '?'}" if s.get("period_start") else None,
             "period_start": s.get("period_start"), "rank": s.get("rank"), "state": s.get("state")}
            for s in statement_package.package_view(wp_id)["statements"]]
    return cols, rows


_STATEMENT_STATE = {"valid": "valid", "replaced": "replaced by a better statement",
                    "conflict": "books the same days as another statement", "pending": "no statement from it yet"}
_STATEMENT_RANK = {"code_checked": "read by code, balances check out", "extracted_checked": "extracted by AI, balances check out",
                   "unchecked": "balances not checked"}
_INVOICE_RESULT = {"paid": "Paid", "partly_paid": "Partly paid", "credited": "Settled by a credit note",
                   "undecided": "Proposal to decide", "no_payment_found": "No payment in the covered period",
                   "not_covered": "Statements do not cover it"}
_LINE_RESULT = {"paired": "Paired", "partly_paired": "Partly paired", "needs_no_invoice": "Needs no invoice",
                "left_out": "Left out", "open": "Open"}
_DIRECTION = {"credit": "Incoming", "debit": "Outgoing"}
LABEL_SETS = tuple(datasets.LabelSet(name, __name__, labels.copy) for name, labels in (
    ("reconcile_invoice_result", _INVOICE_RESULT), ("reconcile_line_result", _LINE_RESULT), ("reconcile_direction", _DIRECTION),
    ("statement_state", _STATEMENT_STATE), ("statement_rank", _STATEMENT_RANK)))


# the tables, each with the table it follows in the catalogue (the order they always had); registered by
# `jav/domains/finance/__init__.py`
DATASETS = (
    (datasets.Dataset("reconcile_inputs", "A reconciliation's inputs", ("workpackage_id",), reconcile_inputs,
                      optional_scope=("others", "left_out", "kind")), "workpackage_items"),
    (datasets.Dataset("utility_cost", "Utility cost by month", (), utility_cost, datasets.result_fingerprint,
                      one_of=datasets.RESULT_SCOPE), "line_items"),
    (datasets.Dataset("utility_sources", "Sources of the utility costs", (), utility_sources, datasets.result_fingerprint,
                      one_of=datasets.RESULT_SCOPE), "utility_cost"),
    (datasets.Dataset("settings_own_parties", "Own parties", (), own_parties), "started_cases"),  # 263 (E1)
    (datasets.Dataset("reconcile_statement_invoices", "A reconciliation statement's invoices", ("workpackage_id",),
                      statement_invoices, optional_scope=("version",)), "reconcile_inputs"),  # 263 (F3)
    (datasets.Dataset("reconcile_statement_lines", "A reconciliation statement's lines", ("workpackage_id",),
                      statement_lines, optional_scope=("version",)), "reconcile_statement_invoices"),  # 263 (F3)
    (datasets.Dataset("statement_package_statements", "A statement batch's statements", ("workpackage_id",),
                      package_statements), "reconcile_statement_lines"),  # 264 (F6)
)


__all__ = ["DATASETS", "LABEL_SETS", "own_parties", "package_statements", "reconcile_inputs", "statement_invoices",
           "statement_lines", "utility_cost", "utility_sources"]
