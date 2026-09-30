"""Közmű-költség idősor (054 K4): a futás közmű-számláiból fogyasztási hely + közmű szerinti havi rács.

Döntések (2026-09-28, `docs/DECISIONS.md`): a forrás a kiválasztott futás érvényes adata (gépi érték + javítás); a
számlázási időszak összege és fogyasztása napok arányában oszlik a hónapokra, kerekítés után is pontos összeggel; a
hónap állapota napra pontosan: `missing` (a sor első és utolsó számlája között egyik számla sem fedi), `partial` (van
fedetlen napja), `overlap` (van két számlával fedett napja), `ok`. A közös vízösszesítő (`summary_only`) csak tájékoztató:
a végösszegbe nem számít, mert a részszámlái külön iratként is bejönnek.

Két általános szabály (054, a valódi adaton talált esetek): (1) ugyanaz a típus + számlaszám csak egyszer számít (a
Díjbeszedő-kötegben és önálló iratként is bejövő számla), a többi `duplicates`; (2) az elszámoló számla — amelynek
időszaka a sor más számláit teljesen magába foglalja — különbözetet számláz: az összege az időszak utolsó hónapjához
kerül (`settlement`), és a lefedettséget (hiány / átfedés) nem befolyásolja.

A számítás kódban történik (CLAUDE.md §4), Decimal-lal; minden cella a forrásszámláit (tétel, fájl, oldal, arány)
hordozza, így minden szám visszakereshető. A beállítás: `configs/reports.json` `utility_cost`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from jav import cfg

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
    """Az összeg napok arányában a hónapokra, két tizedesre kerekítve; a kerekítési maradék az utolsó hónapé, így az
    összeg pontos marad."""
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
    """A cím összevethető alakja: kis/nagybetű, írásjel és szóköz nem számít („1111 BUDAPEST Minta utca 11.”)."""
    return " ".join(re.sub(r"[.,;:]", " ", s).split()).casefold()


_DISTRICT = re.compile(r"^(?:[ivxl]+|ker|kerület)$")


def _addr_key(s: str) -> str:
    """A fogyasztási hely kulcsa: mint a `_fold`, és a kerület római száma („XV.”, „XV. ker.”) sem számít, mert a
    budapesti irányítószám már tartalmazza."""
    return " ".join(t for t in _fold(s).split() if not _DISTRICT.match(t))


def _s(d: Decimal | None) -> str | None:
    return None if d is None else str(d.quantize(CENT, ROUND_HALF_UP))


def has_utility(records: list[dict[str, Any]]) -> bool:
    """Van-e a rekordok között közmű-számla (058: az Eredmény csak ekkor kínálja a közmű-költség nézetet)."""
    utilities = _conf()["utilities"]
    return any((r.get("doc_type") or "") in utilities for r in records)


def build(records: list[dict[str, Any]]) -> dict[str, Any]:
    """A rekordokból (`export.run_records`) a havi rács. Nem közmű irat kimarad; a közmű-számla, amelynek nincs
    időszaka vagy összege, az `unplaced` listába kerül okkal (nem becsülünk)."""
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
        bills.append({**base, "addr": key_addr, "utility": u["label"], "summary_only": bool(u.get("summary_only")),
                      "unit": u.get("unit"), "start": start, "end": end, "amount": _dec(f.get(amount_field)),
                      "amount_field": amount_field, "page": (r.get("pages") or {}).get(amount_field),
                      "consumption": _dec(f.get(cons_field)) if cons_field else None,
                      "supplier": f.get("supplier_name"), "invoice_number": f.get("invoice_number"), "corrected": amount_field in (r.get("corrected") or []),
                      "open_reasons": len(r.get("open_reasons") or [])})

    duplicates: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    unique: list[dict[str, Any]] = []
    for b in bills:
        number = _fold(str(b["invoice_number"])) if b["invoice_number"] else None
        first = seen.get((b["doc_type"], number)) if number else None
        if first is not None:
            duplicates.append({"item_id": b["item_id"], "file": b["file"], "doc_type": b["doc_type"],
                               "same_as": first["item_id"], "same_as_file": first["file"]})
            continue
        if number:
            seen[(b["doc_type"], number)] = b
        unique.append(b)
    series_bills: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for b in unique:
        series_bills[(b["addr"], b["utility"])].append(b)
    all_months: set[str] = set()
    series = []
    grand = Decimal(0)
    for (addr, utility), bs in sorted(series_bills.items()):
        bs.sort(key=lambda b: (b["start"], b["end"]))
        for b in bs:  # elszámoló: más számla időszakát teljesen magába foglalja
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
    return {"months": sorted(all_months), "series": series, "grand_total": _s(grand), "unplaced": unplaced, "duplicates": duplicates,
            "config_version": cfg.load("reports")["meta"]["version"]}


__all__ = ["build", "split_by_month"]
