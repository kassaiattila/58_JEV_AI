"""133 (backlog F-own-parties; DECISIONS 133): the own parties as the settings page and the reconciliation package see
them.

The observations come from the store's effective documents (`reconcile.snapshot`): the buyer side of every incoming
invoice, and for every own account its statements' span and the holder text at the top of a first page (`configs/
parties.json` `holder_zone`). The overview gives every party its invoices, their span and its accounts, beside what the
data proposes; accepting a suggestion recomputes the proposal first, so a stale page cannot apply an old one.

Layer: UI/CLI → **this** (application operation) → `jav.parties` (the parties and their identities) and
`jav.reconcile` (the store's documents). No AI call.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from jav import cfg, parties, reconcile, source_layer, store, work


def _holder_text(statement: dict[str, Any]) -> str:
    """The words at the top of the statement's first page, where the bank prints the account holder."""
    zone = cfg.load("parties")["holder_zone"]
    with store.connect() as c:
        row = c.execute("SELECT source_layer_id FROM datapoints WHERE run_id=? AND doc_id=? ORDER BY rowid DESC LIMIT 1",
                        (statement.get("flow_run_id"), statement["id"])).fetchone()
    layer = source_layer.load(row["source_layer_id"]) if row and row["source_layer_id"] else None
    if layer is None:
        return ""
    words = [w for w in layer.words if w.page == int(zone["page"]) and w.y1 <= float(zone["max_y"])]
    return " ".join(w.text for w in sorted(words, key=lambda w: w.id))


def _span(values: list[str]) -> tuple[str | None, str | None]:
    days = sorted(v[:10] for v in values if v)
    return (days[0], days[-1]) if days else (None, None)


def observations(snap: dict[str, Any] | None = None, *, holder_text: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The buyer side of every incoming invoice, and every own account with its statements (`parties.suggest`'s input)."""
    snap = snap if snap is not None else reconcile.snapshot()
    outgoing = set(cfg.load("reconcile")["outgoing_types"])
    invoices = [{"doc_id": i["id"], "name": i.get("buyer_name"), "tax_id": i.get("buyer_tax_id"),
                 "supplier_name": i.get("supplier_name"), "supplier_tax_id": i.get("supplier_tax_id"),
                 "issue_date": i.get("issue_date")} for i in snap["invoices"] if i.get("doc_type") not in outgoing]
    by_account: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for st in snap["statements"]:
        by_account[reconcile.statement_account(st)].append(st)
    accounts = []
    for key, sts in sorted(by_account.items()):
        sts.sort(key=lambda s: str(s.get("period_start") or ""))
        first, _ = _span([str(s.get("period_start") or "") for s in sts])
        _, last = _span([str(s.get("period_end") or "") for s in sts])
        texts = (t for s in sts if (t := _holder_text(s))) if holder_text else iter(())
        accounts.append({"key": key, "label": next((s["account"] for s in sts if s.get("account")), key), "statements": len(sts),
                         "first": first, "last": last, "holder_text": next(texts, ""),
                         "statement_types": sorted({str(s.get("statement_type")) for s in sts if s.get("statement_type")}),
                         "currencies": sorted({str(s.get("currency")) for s in sts if s.get("currency")})})
    return invoices, accounts


def overview() -> dict[str, Any]:
    """The settings page: every party with its invoices (count and span), identities (with counts) and accounts;
    the suggestions and the unassigned identities; the dismissed ones; how many invoices no party claims."""
    invoices, accounts = observations()
    r = parties.resolver()
    held: dict[str, list[str]] = defaultdict(list)
    name_n, tax_n = Counter(), Counter()
    unclaimed = ambiguous = 0
    for inv in invoices:
        pid, how = r.invoice(inv["name"], inv["tax_id"])
        if nk := parties.name_key(inv["name"]):
            name_n[nk] += 1
        if tk := parties.tax_key(inv["tax_id"]):
            tax_n[tk] += 1
        if pid:
            held[pid].append(str(inv.get("issue_date") or ""))
        else:
            unclaimed += 1
            ambiguous += how == "ambiguous"
    acct = {a["key"]: a for a in accounts}
    registered = parties.accounts()

    def counted(i: dict[str, Any]) -> dict[str, Any]:
        n = name_n[i["key"]] if i["kind"] == "name" else tax_n[i["key"]] if i["kind"] == "tax" else acct.get(i["key"], {}).get("statements", 0)
        return {**i, "invoices": n}

    def account(i: dict[str, Any]) -> dict[str, Any]:
        """138: an account with what its statements show, or registered without a statement yet, and its details."""
        seen = acct.get(i["key"]) or {"key": i["key"], "label": i["label"], "statements": 0, "first": None, "last": None,
                                      "statement_types": [], "currencies": []}
        details = registered.get(i["key"])
        currencies = sorted({*seen["currencies"], *(details["currencies"] if details else [])})
        return {**{k: v for k, v in seen.items() if k != "holder_text"}, "currencies": currencies, "registered": details}

    out = []
    for p in parties.parties():
        own = [account(i) for i in p["identities"] if i["kind"] == "account" and (i["key"] in acct or i["key"] in registered)]
        first, last = _span(held.get(p["id"], []))
        out.append({"id": p["id"], "name": p["name"], "invoices": len(held.get(p["id"], [])), "first": first, "last": last,
                    "statements_first": _span([a["first"] or "" for a in own])[0], "statements_last": _span([a["last"] or "" for a in own])[1],
                    "accounts": own, "identities": [counted(i) for i in p["identities"]], "updated_at": p["updated_at"]})
    proposal = parties.suggest(invoices, accounts)
    return {"parties": out, "suggestions": proposal["suggestions"], "unassigned": proposal["unassigned"],
            "dismissed": [counted(i) for i in parties.dismissed()], "invoices": len(invoices), "unclaimed_invoices": unclaimed,
            "ambiguous_invoices": ambiguous, "buyer_is_supplier": proposal["buyer_is_supplier"], "no_buyer": proposal["no_buyer"],
            "config_hash": parties.config_hash()}


def account_key(number: str) -> str:
    """138: the key of an account number as a person types it: the statement's key (a Hungarian IBAN and its domestic
    number are one account)."""
    key = reconcile.account_key(number)
    if not key:
        raise parties.PartyError("an account number has 16 characters at least: an IBAN or a domestic account number")
    return key


def register_account(party_id: str, number: str, *, kind: str, currencies: list[str], bank: str | None = None,
                     valid_from: str | None = None, valid_to: str | None = None, actor: str) -> dict[str, Any]:
    """138: an own account or card registered with its party by its number, before or after its statements."""
    parties.register_account(party_id, account_key(number), " ".join(number.split()), kind=kind, currencies=currencies,
                             bank=bank, valid_from=valid_from, valid_to=valid_to, actor=actor)
    return overview()


def accept(ids: list[str], *, names: dict[str, str] | None = None, actor: str) -> list[dict[str, Any]]:
    """Carries out the chosen suggestions, as the data proposes them now; one that has changed refuses them all."""
    invoices, accounts = observations()
    current = {s["id"]: s for s in parties.suggest(invoices, accounts)["suggestions"]}
    if missing := [i for i in ids if i not in current]:
        raise work.RevisionConflict(f"{len(missing)} suggestion(s) changed meanwhile; reload them")
    return [parties.apply(current[i], actor=actor, name=(names or {}).get(i)) for i in ids]


# --- the monthly data status (138) ---------------------------------------------------------------------------------------

_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
MAX_MONTHS = 120
STATES = ("ok", "unapproved", "unverified", "partial", "missing", "none")


def _bounds(month: str) -> tuple[date, date]:
    y, m = int(month[:4]), int(month[5:7])
    following = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
    return date(y, m, 1), following - timedelta(days=1)


def _day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _balance(value: Any) -> Decimal | None:
    try:
        return reconcile.money(str(value)) if value not in (None, "") else None
    except ValueError:
        return None


def period(start: str | None, end: str | None, today: date) -> tuple[str, str]:
    """The months asked for ("YYYY-MM"); by default this year up to the last closed month (last year in January)."""
    end = end or (date(today.year, today.month, 1) - timedelta(days=1)).strftime("%Y-%m")
    start = start or f"{end[:4]}-01"
    if not _MONTH.fullmatch(start) or not _MONTH.fullmatch(end):
        raise parties.PartyError("a month is written YYYY-MM")
    if start > end:
        raise parties.PartyError("the period ends before it starts")
    if len(reconcile.months(start, end)) > MAX_MONTHS:
        raise parties.PartyError(f"at most {MAX_MONTHS} months at once")
    return start, end


def _column(statements: list[dict[str, Any]], opened: date | None, closed: date | None, months: list[str], today: date,
            approved: set[str]) -> list[dict[str, Any]]:
    """One account and currency month by month: the state of its statements in the month (`STATES`), and the flags of
    two statements booking the same days (`overlap`) or an opening balance that does not continue the previous
    statement's closing one (`break`). Up to yesterday: the running month is asked only as far as it has gone."""
    dated = sorted(((s, a, b) for s in statements
                    if (a := _day(s.get("period_start"))) and (b := _day(s.get("period_end"))) and a <= b),
                   key=lambda t: (t[1], t[2], t[0]["id"]))
    overlaps: set[str] = set()
    breaks: set[str] = set()
    for (first, start1, end1), (second, start2, end2) in zip(dated, dated[1:]):
        touching = start2 == end1 and start1 < start2  # a card cycle starts on the previous one's closing day
        if start2 <= end1 and not touching:
            overlaps.update(reconcile.months(start2.isoformat(), min(end1, end2).isoformat()))
        elif touching or start2 == end1 + timedelta(days=1):
            closing, opening = _balance(first.get("closing_balance")), _balance(second.get("opening_balance"))
            if closing is not None and opening is not None and closing != opening:
                breaks.add(start2.strftime("%Y-%m"))
    yesterday = today - timedelta(days=1)
    cells = []
    for month in months:
        first_day, last_day = _bounds(month)
        lo = max(first_day, opened) if opened else first_day
        hi = min(last_day, closed, yesterday) if closed else min(last_day, yesterday)
        meets = [(s, a, b) for s, a, b in dated if a <= last_day and b >= first_day]
        if not meets:
            state = "missing" if lo <= hi and last_day < today else "none"
        elif lo <= hi and reconcile.covered_by(reconcile.merge_periods((a, b) for _s, a, b in meets), lo, hi) != "full":
            state = "partial"
        elif not all(s.get("verified") for s, _a, _b in meets):
            state = "unverified"
        elif not all(s.get("work_run") in approved for s, _a, _b in meets):
            state = "unapproved"
        else:
            state = "ok"
        cells.append({"month": month, "state": state, "statements": len(meets),
                      "flags": [flag for flag, hit in (("overlap", overlaps), ("break", breaks)) if month in hit]})
    return cells


def months(party_id: str, start: str | None = None, end: str | None = None, *, today: date | None = None) -> dict[str, Any]:
    """138 (DECISIONS 137): a party's data month by month, before it is reconciled: per own account and currency
    whether statements cover the month, check out by their balances, come from an approved run and continue the
    previous one; and how many of the party's incoming invoices the month has, by the state of their run. A month is
    expected from the day the account was opened (registered, else its first statement) to the day it was closed, up
    to the last closed month."""
    today = today or date.today()
    start, end = period(start, end, today)
    party = parties.get(party_id)
    wanted = reconcile.months(start, end)
    snap = reconcile.snapshot()
    registered = parties.accounts()
    conf = cfg.load("reconcile")
    by_column: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for st in snap["statements"]:
        by_column[(reconcile.statement_account(st), str(st.get("currency") or ""))].append(st)
    r = parties.resolver()
    invoices = [i for i in snap["invoices"] if i.get("doc_type") not in conf["outgoing_types"] and i.get("duplicate") != "copy"
                and r.invoice(i.get("buyer_name"), i.get("buyer_tax_id"))[0] == party_id]
    approved = work.approved_runs([*(s.get("work_run") for sts in by_column.values() for s in sts),
                                   *(i.get("work_run") for i in invoices)])
    columns = []
    for ident in (i for i in party["identities"] if i["kind"] == "account"):
        details = registered.get(ident["key"])
        seen = {cur for key, cur in by_column if key == ident["key"]}
        for currency in sorted(seen | set((details or {}).get("currencies") or [])):
            sts = by_column.get((ident["key"], currency), [])
            first = min((d for s in sts if (d := _day(s.get("period_start")))), default=None)
            opened = _day((details or {}).get("valid_from")) or first
            closed = _day((details or {}).get("valid_to"))
            card = any(s.get("statement_type") in conf["fx"]["statement_types"] for s in sts)
            columns.append({"key": ident["key"], "currency": currency, "label": ident["label"],
                            "kind": (details or {}).get("kind") or ("card" if card else "account"),
                            "bank": (details or {}).get("bank"), "registered": details is not None,
                            "opened": opened.isoformat() if opened else None, "closed": closed.isoformat() if closed else None,
                            "statements": len(sts), "months": _column(sts, opened, closed, wanted, today, approved)})
    per_month: dict[str, Counter] = {m: Counter() for m in wanted}
    for inv in invoices:
        month = str(inv.get("issue_date") or "")[:7]
        if month in per_month:
            run = inv.get("work_run")
            per_month[month]["total"] += 1
            per_month[month]["no_run" if run is None else "approved" if run in approved else "not_approved"] += 1
    states = Counter(cell["state"] for col in columns for cell in col["months"])
    flags = Counter(flag for col in columns for cell in col["months"] for flag in cell["flags"])
    return {"party": {"id": party["id"], "name": party["name"]}, "start": start, "end": end, "months": wanted,
            "today": today.isoformat(), "columns": columns,
            "invoices": [{"month": m, **{k: c[k] for k in ("total", "approved", "not_approved", "no_run")}}
                         for m, c in per_month.items()],
            "summary": {**{s: states[s] for s in STATES if s != "none"}, "overlap": flags["overlap"], "break": flags["break"]}}
