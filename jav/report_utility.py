"""Utility cost time series (054 K4): a monthly grid by point of consumption + utility from the run's utility invoices.

Decisions (2026-09-28, `docs/DECISIONS.md`): the source is the effective data of the selected run (machine value +
correction); the amount and consumption of a billing period are split across the months in proportion to the days,
with an exact total even after rounding; a month's status is exact to the day: `missing` (between the series' first
and last invoice, no invoice covers it), `partial` (it has an uncovered day), `overlap` (it has a day covered by two
invoices), `ok`. The shared water summary (`summary_only`) is informative only: it does not count towards the grand
total, because its partial invoices also come in as separate documents.

Two general rules (054, from cases found in real data): (1) the same invoice counts only once (an invoice that arrives
both in the Díjbeszedő batch and as a separate document); the others are `duplicates`. 126: the same invoice is the
shared duplicate key (`jav/duplicates.py`: family, number, supplier), and a pair a person found different counts twice; (2) a
settlement invoice, whose period fully contains other invoices of the series, bills the difference: its amount goes
to the last month of its period (`settlement`), and it does not affect coverage (missing / overlap).

The computation happens in code (CLAUDE.md §4), with Decimal; every cell carries its source invoices (item, file,
page, share), so every number can be traced back. Settings: `utility_cost` in `configs/reports.json`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from jav import cfg, duplicates

CENT = Decimal("0.01")


def _conf() -> dict[str, Any]:
    return cfg.load("reports")["utility_cost"]


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def split_by_month(start: date, end: date, amount: Decimal) -> dict[str, Decimal]:
    """Splits the amount across the months in proportion to the days, rounded to two decimals; the rounding remainder
    goes to the last month, so the total stays exact."""
    per: dict[str, int] = defaultdict(int)
    for d in _days(start, end):
        per[_month(d)] += 1
    total_days = sum(per.values())
    out: dict[str, Decimal] = {}
    running = Decimal(0)
    months = list(per)
    for m in months[:-1]:
        share = (amount * per[m] / total_days).quantize(CENT, ROUND_HALF_UP)
        out[m] = share
        running += share
    out[months[-1]] = (amount - running).quantize(CENT, ROUND_HALF_UP)
    return out


def _dec(v: Any) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _date(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def _fold(s: str) -> str:
    """An address's comparable form: case, punctuation and spaces do not matter ("1111 BUDAPEST Minta utca 11.")."""
    return " ".join(re.sub(r"[.,;:]", " ", s).split()).casefold()


_DISTRICT = re.compile(r"^(?:[ivxl]+|ker|kerület)$")


def _addr_key(s: str) -> str:
    """Key of the point of consumption: like `_fold`, and the district's Roman numeral ("XV.", "XV. ker.") does not
    matter either, because the Budapest postcode already contains it."""
    return " ".join(t for t in _fold(s).split() if not _DISTRICT.match(t))


def _s(d: Decimal | None) -> str | None:
    return None if d is None else str(d.quantize(CENT, ROUND_HALF_UP))


def has_utility(records: list[dict[str, Any]]) -> bool:
    """Whether the records include a utility invoice (058: only then does Result offer the utility cost view)."""
    utilities = _conf()["utilities"]
    return any((r.get("doc_type") or "") in utilities for r in records)


def build(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The monthly grid from the records (`export.run_records`). Non-utility documents are skipped; a utility invoice
    without a period or an amount goes to the `unplaced` list with a reason (we do not estimate)."""
    conf = _conf()
    utilities: dict[str, dict[str, Any]] = conf["utilities"]
    start_f, end_f = conf["period_fields"]
    addresses: dict[str, str] = {}
    bills: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []
    for r in records:
        u = utilities.get(r.get("doc_type") or "")
        if u is None:
            continue
        f = r.get("fields") or {}
        start, end = _date(f.get(start_f)), _date(f.get(end_f))
        amount_field = next((a for a in conf["amount_fields"] if _dec(f.get(a)) is not None), None)
        raw_addr = next((str(f[a]) for a in conf["address_fields"] if f.get(a)), None)
        base = {"item_id": r["item_id"], "file": r.get("file"), "doc_type": r["doc_type"]}
        if start is None or end is None or end < start:
            unplaced.append({**base, "reason": "no_period"})
            continue
        if amount_field is None:
            unplaced.append({**base, "reason": "no_amount"})
            continue
        key_addr = _addr_key(raw_addr) if raw_addr else "(ismeretlen hely)"
        addresses.setdefault(key_addr, raw_addr or "(ismeretlen hely)")
        cons_field = u.get("consumption_field")
        mark = r.get("duplicate") or {}
        bills.append({**base, "addr": key_addr, "utility": u["label"], "summary_only": bool(u.get("summary_only")),
                      "unit": u.get("unit"), "start": start, "end": end, "amount": _dec(f.get(amount_field)),
                      "amount_field": amount_field, "page": (r.get("pages") or {}).get(amount_field),
                      "consumption": _dec(f.get(cons_field)) if cons_field else None,
                      "supplier": f.get("supplier_name"), "fields": f, "corrected": amount_field in (r.get("corrected") or []),
                      "open_reasons": len(r.get("open_reasons") or []),
                      "confirmed": mark.get("status") if mark.get("status") in ("copy", "variant") else None,
                      "different": set(mark.get("different") or ())})

    # 126: the same invoice by the shared duplicate key (family, number, supplier; `jav/duplicates.py`) counts once
    # until a person decides the two differ; the one a person confirmed as the repeat is the one left out
    duplicates_out: list[dict[str, Any]] = []
    unique: list[dict[str, Any]] = []
    for b in sorted(bills, key=lambda b: b["confirmed"] is not None):
        first = next((u for u in unique if u["item_id"] not in b["different"] and b["item_id"] not in u["different"]
                      and duplicates.same_invoice(u["doc_type"], u["fields"], b["doc_type"], b["fields"])), None)
        if first is not None:
            duplicates_out.append({"item_id": b["item_id"], "file": b["file"], "doc_type": b["doc_type"],
                                   "same_as": first["item_id"], "same_as_file": first["file"], "status": b["confirmed"] or "suspected"})
            continue
        unique.append(b)
    series_bills: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for b in unique:
        series_bills[(b["addr"], b["utility"])].append(b)
    all_months: set[str] = set()
    series = []
    grand = Decimal(0)
    for (addr, utility), bs in sorted(series_bills.items()):
        bs.sort(key=lambda b: (b["start"], b["end"]))
        for b in bs:  # settlement: fully contains another invoice's period
            b["settlement"] = any(o is not b and b["start"] <= o["start"] and o["end"] <= b["end"]
                                  and (o["start"], o["end"]) != (b["start"], b["end"]) for o in bs)
        regular = [b for b in bs if not b["settlement"]] or bs
        first, last = min(b["start"] for b in regular), max(b["end"] for b in regular)
        cover: dict[date, int] = defaultdict(int)
        for b in regular:
            for d in _days(b["start"], b["end"]):
                cover[d] += 1
        cells: dict[str, dict[str, Any]] = {}
        month_days: dict[str, list[date]] = defaultdict(list)
        for d in _days(first, last):
            month_days[_month(d)].append(d)
        for m, ds in month_days.items():
            counts = [cover[d] for d in ds]
            status = ("missing" if not any(counts) else "overlap" if max(counts) > 1 else "partial" if min(counts) == 0 else "ok")
            cells[m] = {"status": status, "amount": Decimal(0), "consumption": None, "sources": [], "settlement": False}
        for b in bs:
            if b["settlement"]:
                m = _month(b["end"])
                cells.setdefault(m, {"status": "ok", "amount": Decimal(0), "consumption": None, "sources": [], "settlement": False})
                cells[m]["settlement"] = True
                amounts, cons = {m: b["amount"]}, {}
            else:
                amounts = split_by_month(b["start"], b["end"], b["amount"])
                cons = split_by_month(b["start"], b["end"], b["consumption"]) if b["consumption"] is not None else {}
            for m, a in amounts.items():
                cell = cells[m]
                cell["amount"] += a
                if m in cons:
                    cell["consumption"] = (cell["consumption"] or Decimal(0)) + cons[m]
                cell["sources"].append({"item_id": b["item_id"], "file": b["file"], "amount": _s(a), "page": b["page"],
                                        "settlement": b["settlement"],
                                        "field": b["amount_field"], "corrected": b["corrected"], "open_reasons": b["open_reasons"]})
        total = sum((b["amount"] for b in bs), Decimal(0))
        if not bs[0]["summary_only"]:
            grand += total
        all_months.update(cells)
        series.append({
            "address": addresses[addr], "utility": utility, "summary_only": bs[0]["summary_only"],
            "suppliers": sorted({b["supplier"] for b in bs if b["supplier"]}), "consumption_unit": bs[0]["unit"],
            "total": _s(total), "bills": len(bs),
            "cells": {m: {"status": c["status"], "amount": _s(c["amount"]) if c["sources"] else None, "settlement": c["settlement"],
                          "consumption": _s(c["consumption"]), "sources": c["sources"]} for m, c in sorted(cells.items())},
        })
    series.sort(key=lambda s: (s["summary_only"], s["address"], s["utility"]))
    return {"months": sorted(all_months), "series": series, "grand_total": _s(grand), "unplaced": unplaced, "duplicates": duplicates_out,
            "config_version": cfg.load("reports")["meta"]["version"]}


__all__ = ["build", "split_by_month"]
