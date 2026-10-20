"""The finance domain's tables on the interface (185, plan G-full-move T1b; until then in `jav/datasets.py`).

Plain-language summary: three tables of the shared data view are the finance domain's: a reconciliation package's
inputs as its item list (169: the scope's statements, then the invoices its pairing may take, with where each result
comes from and where it stands in the pairing), and the utility cost of a run or of a package's current result, as a
monthly grid (054 K4) and as the source invoices of each cell. They moved here from `jav/datasets.py` as they were:
the same columns, rows and order. The finance domain module registers them (`jav/domains/finance.py`), and the data
view asks its registry.

Layer: application operation (a read view) → `jav.reconcile_package`, `jav.report_utility`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jav import datasets, work
from jav.datasets import Rows, col


def reconcile_inputs(scope: dict[str, str]) -> Rows:
    """169 (DECISIONS 169): a reconciliation package's inputs as its item list: the scope's statements, then the
    invoices its pairing may take (another party's only with `others`), each with the package and the run its result
    comes from, whether it blocks the approval, and where it stands in the pairing; with `left_out`, the documents left
    out of the package too, with who left them out, when and why. Read from the kept workspace."""
    from jav import reconcile_package

    ws = reconcile_package.kept_workspace(scope["workpackage_id"])
    refs = ws.get("open") or {}
    briefs = work.run_briefs(ref["run_id"] for ref in refs.values())
    blocking = {b["doc_id"] for b in ws["blockers"] if str(b["code"]).startswith("source_")}
    cols = [
        col("name", "Document", link="review"),
        col("kind", "Kind", "enum", labels="reconcile_input_kind"),
        col("subject", "Number or account"),
        col("partner", "Partner"),
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
    return cols, rows


def _utility_report(scope: dict[str, str]) -> tuple[Callable[[str | None], dict[str, Any]], dict[str, Any]]:
    from jav import report_utility

    link, records = datasets.linked_records(scope)
    return link, report_utility.build(records)


def utility_cost(scope: dict[str, str]) -> Rows:
    """The monthly utility-cost grid in long form: consumption point × utility × month per row (pivotable in Excel)."""
    link, rep = _utility_report(scope)
    to = link(None)
    cols = [
        col("address", "Fogyasztási hely"),
        col("utility", "Közmű", "enum"),
        col("month", "Hónap", "date"),
        col("status", "Állapot", "enum", labels="utility_status"),
        col("amount", "Összeg (bruttó, a hónapra jutó)", "money"),
        col("consumption", "Fogyasztás", "number"),
        col("unit", "Egység", "enum", hidden=True),
        col("settlement", "Elszámoló számla", "enum", labels="yes", hidden=True),
        col("summary_only", "Csak tájékoztató", "enum", labels="yes"),
        col("bills", "Forrásszámla", "number"),
        col("suppliers", "Szolgáltató", hidden=True),
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
        col("address", "Fogyasztási hely"),
        col("utility", "Közmű", "enum"),
        col("month", "Hónap", "date"),
        col("status", "Állapot", "enum", labels="utility_status"),
        col("amount", "Összeg (a hónapra jutó)", "money"),
        col("file", "Irat", link="review"),
        col("page", "Oldal", "number"),
        col("field", "Mező", "enum", labels="field"),
        col("corrected", "Javítva", "enum", labels="yes"),
        col("open_reasons", "Nyitott teendő", "number", alert=True),
        col("item_id", "Tétel-azonosító", "id", hidden=True),
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


# the tables, each with the table it follows in the catalogue (the order they always had); registered by
# `jav/domains/finance.py`
DATASETS = (
    (datasets.Dataset("reconcile_inputs", "A reconciliation's inputs", ("workpackage_id",), reconcile_inputs,
                      optional_scope=("others", "left_out")), "workpackage_items"),
    (datasets.Dataset("utility_cost", "Közmű-költség havonta", (), utility_cost, datasets.result_fingerprint,
                      one_of=datasets.RESULT_SCOPE), "line_items"),
    (datasets.Dataset("utility_sources", "Közmű-költség forrásai", (), utility_sources, datasets.result_fingerprint,
                      one_of=datasets.RESULT_SCOPE), "utility_cost"),
)


__all__ = ["DATASETS", "reconcile_inputs", "utility_cost", "utility_sources"]
