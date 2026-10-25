"""231 (plan stage C, C2b): the reconciliation's store adapter, split out of `reconcile.py`.

Plain-language summary: the tables of a person's decisions on pairs, allocations and marks (registered under the name
`reconcile`, as before), and the read-only adapter that builds the engine's snapshot from the store's effective values
(each document's counted result with its latest correction; the statements with their verified lines; the decisions,
allocations and marks; the MNB rates the invoices need), plus the command line's summary (`scan`). The engine
(`reconcile.propose`) stays pure.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from jav.app import package_result
from jav.core import store, type_roles, values
from jav.domains.finance import fx
from jav.domains.finance import reconcile_rules
from jav.domains.finance.reconcile_signals import money, statement_account, with_line_ids
from jav.domains.finance.reconcile_amounts import rate_need
from jav.domains.finance import reconcile


# --- the store adapter (read-only) ---------------------------------------------------------------------------------


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
    actor_id          TEXT,               -- 229 (SZ2c): the stable ids beside the names (`jav.core.identity`)
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
    actor_id          TEXT,
    note              TEXT,
    created_at        TEXT NOT NULL,
    revoked_at        TEXT,
    revoked_by        TEXT,
    revoked_by_id     TEXT,
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
    actor_id          TEXT,
    created_at        TEXT NOT NULL,
    revoked_at        TEXT,
    revoked_by        TEXT,
    revoked_by_id     TEXT,
    basis             TEXT                -- 147: the quick review's suggestion it accepted (NULL: a person's own choice)
);
CREATE INDEX IF NOT EXISTS ix_reconcile_line_marks_line ON reconcile_line_marks(line_id);
""")


def _migrate(conn) -> None:
    # 131: a rejection made in a reconciliation package (not on a run)
    store.add_columns(conn, "reconcile_decisions", {"workpackage_id": "TEXT"})
    # 147: the suggestion a mark accepted in the quick review came from
    store.add_columns(conn, "reconcile_line_marks", {"basis": "TEXT"})
    # 229 (SZ2c): the stable id beside every name of who acted; the earlier rows' from their names
    store.add_actor_ids(conn, "reconcile_decisions", ("actor",))
    store.add_actor_ids(conn, "reconcile_allocations", ("actor", "revoked_by"))
    store.add_actor_ids(conn, "reconcile_line_marks", ("actor", "revoked_by"))


store.register_migration("reconcile", _migrate)


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
               for name, codes in reconcile_rules._conf()["verified_when"].items())


_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")


def printable(value: Any) -> Any:
    """167 (review 153 E): a name without the control characters a PDF's text layer may carry (a broken glyph read as
    NUL), which the result table showed as they were; a run of them becomes one space. Other values stay as they are."""
    return " ".join(_CONTROL.sub(" ", value).split()) if isinstance(value, str) else value


def _counted(types: list[str]) -> list[dict[str, Any]]:
    """The counted result of every document of the given types, with the latest correction of its run item. 174 (plan
    170 L2, decisions 160 D3/D4 and 170 K17): the package's current result across every package the document is in
    (`package_result.counted_documents`); before, the store's latest result row, a later trial's too."""
    with store.connect() as c:
        return _documents(c, package_result.counted_documents(c), types)


def _documents(c, counted: dict[str, Any], types: list[str]) -> list[dict[str, Any]]:
    """The documents of `counted` (`package_result.CountedDocument` by document) of the given types, in the order of
    processing, with their effective values. A store without the work tables (a measurement store) has no run items
    and no corrections."""
    rows = package_result.result_rows(c, counted, "datapoints, validation", types=types)
    # 154 (DECISIONS 154): the documents that came as an attachment of an email routed as suspicious
    from jav.core.todo_kinds import SUSPICIOUS_ATTACHMENT

    suspicious = ({r["run_id"] for r in c.execute("SELECT DISTINCT run_id FROM review_reasons WHERE reason=?",
                                                  (SUSPICIOUS_ATTACHMENT,))}
                  if _has_table(c, "review_reasons") else set())
    corrected = package_result.latest_corrections(c)
    out = []
    for r in rows:
        x = counted[r["doc_id"]]
        values = package_result.effective_values(json.loads(r["datapoints"] or "{}"), corrected.get((x.work_run, x.item_id)))
        out.append({"doc_id": r["doc_id"], "doc_type": r["doc_type"], "values": values, "validation": r["validation"],
                    "seq": int(r["seq"]), "flow_run_id": r["run_id"], "work_run": x.work_run, "item_id": x.item_id,
                    "suspicious_source": r["run_id"] in suspicious})
    return out


def _amount(values: dict[str, Any]) -> str | None:
    """The amount to pay: the first of the configured fields with a positive canonical amount, else the last present."""
    present = [values.get(f) for f in reconcile_rules._conf()["invoice_fields"]["amount"] if values.get(f) not in (None, "")]
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
    return type_roles.has(doc_type, "incoming_invoice") or type_roles.has(doc_type, "statement")


def bank_rate_needs(invoices: list[dict[str, Any]], statements: list[dict[str, Any]]) -> set[tuple[str, date]]:
    """149: the (currency, day) rates a forint bank line may need: each foreign-currency invoice's fulfilment (else
    issue) day, and every booking day of the forint bank lines in each foreign currency present."""
    f, currencies = reconcile_rules._conf()["fx"], set(reconcile_rules._conf()["currencies"])
    banks = [s for s in statements if s.get("statement_type") in f["bank"]["statement_types"] and s.get("currency") == f["line_currency"]]
    foreign = [inv for inv in invoices if rate_need(inv) and inv.get("currency") in currencies]
    if not banks or not foreign:
        return set()
    needs = {(str(inv["currency"]), day) for inv in foreign
             if (day := values.stored_day(inv.get("fulfillment_date")) or values.stored_day(inv.get("issue_date")))}
    days = {day for s in banks for ln in s.get("lines") or [] if (day := values.stored_day(ln.get("booking_date")))}
    return needs | {(cur, day) for cur in {str(inv["currency"]) for inv in foreign} for day in days}


@store.one_connection
def snapshot(current: dict[str, Any] | None = None, *, fetch_rates: bool = False) -> dict[str, Any]:
    """The store's effective invoices and statements, the people's decisions and the exchange rates a card pair needs,
    as a snapshot for `propose`. `current` (doc_id, doc_type, values, validation): the document being processed, in
    place of its stored result. `fetch_rates`: fetch the missing MNB rates first (the processing and the command line);
    a view only reads the stored ones."""
    from jav.app import parties  # 147: an invoice's direction from the own parties' identities
    from jav.domains.finance import own_parties

    conf = reconcile_rules._conf()
    f = conf["invoice_fields"]
    marks = _duplicate_marks()
    res = parties.resolver()
    docs = _counted([*type_roles.types("incoming_invoice"), *type_roles.types("outgoing_invoice"), *type_roles.types("statement")])
    if current is not None:
        docs = [d for d in docs if d["doc_id"] != current["doc_id"]]
        docs.append({**current, "seq": max((d["seq"] for d in docs), default=0) + 1})
    invoices, statements = [], []
    for d in docs:
        v = d["values"]
        if type_roles.has(d["doc_type"], "statement"):
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
                             "direction": own_parties.direction(res, d["doc_type"], v)[0], **_origin(d)})
    # 139 (DECISIONS 139): one valid statement per account, currency and day; a replaced statement's decisions move to
    # the same lines of the one replacing it, and what has no same line is left over (`left_over`)
    from jav.domains.finance import statement_months

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
    from jav.core import card_numbers

    return {**line, **{k: card_numbers.mask_text(line[k]) for k in ("memo", "description", "counterparty_name") if line.get(k)}}


def statements() -> list[dict[str, Any]]:
    """139: every stored statement in the snapshot's shape, a replaced one too (`jav/domains/finance/statement_months.py` decides); 174:
    each by its counted result."""
    return [_statement(d) for d in _counted(list(type_roles.types("statement")))]


def run_statements(run_id: str) -> list[dict[str, Any]]:
    """174 (plan 170 L2): the statements of one run's finished items, by that run's own results and corrections, whatever
    counts now (the statement package's rule after an approval reads the approved run)."""
    with store.connect() as c:
        return [_statement(d) for d in _documents(c, package_result.run_documents(c, run_id), list(type_roles.types("statement")))]


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


def scan() -> dict[str, Any]:
    """Counts of the store's proposal for the command line (no values printed). 137: it opens no to-do; the pairs are
    decided in a reconciliation package."""
    snap = snapshot(fetch_rates=True)
    result = reconcile.propose(snap)

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
        "config_hash": result["config_hash"], "engine_version": reconcile.ENGINE_VERSION,
    }
