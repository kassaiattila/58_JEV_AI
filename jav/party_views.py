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

from collections import Counter, defaultdict
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

    def counted(i: dict[str, Any]) -> dict[str, Any]:
        n = name_n[i["key"]] if i["kind"] == "name" else tax_n[i["key"]] if i["kind"] == "tax" else acct.get(i["key"], {}).get("statements", 0)
        return {**i, "invoices": n}

    out = []
    for p in parties.parties():
        own = [{k: v for k, v in acct[i["key"]].items() if k != "holder_text"} for i in p["identities"]
               if i["kind"] == "account" and i["key"] in acct]
        first, last = _span(held.get(p["id"], []))
        out.append({"id": p["id"], "name": p["name"], "invoices": len(held.get(p["id"], [])), "first": first, "last": last,
                    "statements_first": _span([a["first"] or "" for a in own])[0], "statements_last": _span([a["last"] or "" for a in own])[1],
                    "accounts": own, "identities": [counted(i) for i in p["identities"]], "updated_at": p["updated_at"]})
    proposal = parties.suggest(invoices, accounts)
    return {"parties": out, "suggestions": proposal["suggestions"], "unassigned": proposal["unassigned"],
            "dismissed": [counted(i) for i in parties.dismissed()], "invoices": len(invoices), "unclaimed_invoices": unclaimed,
            "ambiguous_invoices": ambiguous, "buyer_is_supplier": proposal["buyer_is_supplier"], "no_buyer": proposal["no_buyer"],
            "config_hash": parties.config_hash()}


def accept(ids: list[str], *, names: dict[str, str] | None = None, actor: str) -> list[dict[str, Any]]:
    """Carries out the chosen suggestions, as the data proposes them now; one that has changed refuses them all."""
    invoices, accounts = observations()
    current = {s["id"]: s for s in parties.suggest(invoices, accounts)["suggestions"]}
    if missing := [i for i in ids if i not in current]:
        raise work.RevisionConflict(f"{len(missing)} suggestion(s) changed meanwhile; reload them")
    return [parties.apply(current[i], actor=actor, name=(names or {}).get(i)) for i in ids]
