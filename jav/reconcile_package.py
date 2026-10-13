"""131 (backlog F-reconciliation E1; DECISIONS 131): the reconciliation package.

A work package of its own kind (`source_kind = 'reconcile'`). Its input is not files but a scope: own accounts or
cards (the account keys of the statements in the store, `reconcile.statement_account`) and a period. It works on the
documents other packages processed, from their effective values (the latest result with its latest correction), and
nothing in it calls an AI model or the worker. A person pairs statement lines with invoices in two lists, with an
amount per pair (split and combined payments), rejects a pair with a reason, or marks a line as needing no invoice;
every decision can be revoked.

Rules (the owner's decisions of 2026-10-09):
- The decisions belong to the pair, not to the package: a line pays the same invoice whichever package shows it. The
  allocations of a line and of an invoice never exceed its amount; a converted card pair is allocated only in whole.
- An allocation that does not use up both sides' rest (a split), or a converted pair outside the card band or without a
  rate, needs a reason.
- A source document whose run is not approved, or that came from an evaluation on the command line, is shown as a
  blocker; the package's approval (E3) needs every one of them approved. Open lines do not block the approval.
- Two writers are kept apart optimistically: a decision checks, in its writing transaction, that no other decision was
  recorded since it read the state (`work.RevisionConflict`, the interface reloads).
- 133 (DECISIONS 133): a package is one own party's (`jav.parties`). Its invoices and the unassigned ones are its own;
  another party's invoice is listed with its party for a person to pair on purpose, never proposed to the line's state
  or accepted in bulk (`other_candidates`). A package without a party (made before 133) takes every invoice as its own.
- 135 (plan 134 P2): a line's partner is its counterparty name without its reference numbers (`reconcile.name_key`),
  so the page can group a partner's lines and mark them in one step (`unmark` undoes them in one step). The reasons a
  person gave earlier for that partner's lines, in any package, come with each line (`earlier_marks`) as a suggestion,
  never applied by itself; a line through a payment app teaches nothing, as the app pays many suppliers (131).

- 143 (DECISIONS 143): the finder of the two lists (`matches`) compares the selected line with every invoice of the
  page in code - name, invoice number, account, amount, timing - and orders them by how they fit; it decides nothing.
- 145 (DECISIONS 132, 145; the result, `jav/reconcile_statement.py`): the approved versions of a package's statement
  (`reconcile_versions`) lock their lines: no decision on them is made or revoked in any package, and the package's
  scope does not change, until a person reopens the version (`Locked`). A source from an evaluation on the command line
  stops blocking once a person accepts its result as a source (`reconcile_source_acceptances`). A statement whose
  balances do not check out is a warning, not a blocker (DECISIONS 132).

Layer: UI/CLI → **this** (application operation) → `jav.reconcile` (the core and its store adapter) and `jav.work`
(the package record and its log).
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from collections import Counter, OrderedDict, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable

from jav import cfg, corrections, grounding, parties, reconcile, reconcile_overview, store, typepack, work
from jav.statement_table import LINE_DETAILS  # 144: a code reader's facts beyond the money

KIND = "reconcile"
REVOKE_KINDS = ("allocation", "mark", "decision")

store.register_schema("reconcile_package", """
CREATE TABLE IF NOT EXISTS reconcile_scopes (
    workpackage_id TEXT PRIMARY KEY,
    accounts       TEXT NOT NULL,      -- JSON: the own account keys (reconcile.statement_account)
    period_start   TEXT NOT NULL,      -- ISO date
    period_end     TEXT NOT NULL,      -- ISO date, inclusive
    revision       INTEGER NOT NULL DEFAULT 1,
    actor          TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    party_id       TEXT                -- 133: the own party (jav.parties); NULL: every invoice is the package's
);
-- 145: an approved, unchangeable version of a package's statement (jav/reconcile_statement.py); while it is not
-- reopened, its lines are locked
CREATE TABLE IF NOT EXISTS reconcile_versions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workpackage_id TEXT NOT NULL,
    version        INTEGER NOT NULL,
    content        TEXT NOT NULL,      -- JSON: the statement as approved
    fingerprint    TEXT NOT NULL,      -- sha256 of the content
    line_ids       TEXT NOT NULL,      -- JSON: the statement's lines, locked while the version is not reopened
    approved_by    TEXT NOT NULL,
    approved_at    TEXT NOT NULL,
    reopened_by    TEXT,
    reopened_at    TEXT,
    reopen_note    TEXT,
    UNIQUE (workpackage_id, version)
);
-- 145 (DECISIONS 132): a person accepted a document's result from an evaluation on the command line as a source; a
-- later result of the document needs a new acceptance
CREATE TABLE IF NOT EXISTS reconcile_source_acceptances (
    doc_id         TEXT NOT NULL,
    flow_run_id    TEXT NOT NULL,
    workpackage_id TEXT NOT NULL,
    actor          TEXT NOT NULL,
    accepted_at    TEXT NOT NULL,
    PRIMARY KEY (doc_id, flow_run_id)
);
""")


def _migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(reconcile_scopes)")}
    if cols and "party_id" not in cols:  # 133: a package is one own party's
        conn.execute("ALTER TABLE reconcile_scopes ADD COLUMN party_id TEXT")


store.register_migration("reconcile_package", _migrate)
parties.register_reference(
    "reconcile_package",
    count=lambda c, pid: c.execute("SELECT COUNT(*) FROM reconcile_scopes WHERE party_id=?", (pid,)).fetchone()[0],
    repoint=lambda c, old, new: c.execute("UPDATE reconcile_scopes SET party_id=? WHERE party_id=?", (new, old)))


class PackageError(ValueError):
    """A request the reconciliation package refuses (not such a package, a line outside its scope, an amount over a
    side's rest, a missing reason ...); the interface shows the message (422)."""


class Locked(PackageError):
    """145: a decision on a line of an approved statement, or a change of an approved package's scope; the version has
    to be reopened first (422, code `reconcile_locked`)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _conf() -> dict[str, Any]:
    return dict(cfg.load("reconcile"))


def _iso(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def _day(value: Any, what: str) -> date:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise PackageError(f"{what}: an ISO date is required") from exc


# --- the scope ---------------------------------------------------------------------------------------------------------


def accounts() -> list[dict[str, Any]]:
    """The own accounts and cards to choose a package's scope from: those the store has statements of and, 138, those
    registered with a party without a statement yet: the account key, the printed account, the statement kinds and
    currencies, how many statements and the span they cover, the party and the registered details."""
    groups: dict[str, dict[str, Any]] = {}
    for st in reconcile.snapshot()["statements"]:
        key = reconcile.statement_account(st)
        g = groups.setdefault(key, {"key": key, "account": st.get("account"), "statement_types": set(), "currencies": set(),
                                    "statements": 0, "first": None, "last": None})
        g["statement_types"].add(str(st.get("statement_type") or ""))
        g["currencies"].add(str(st.get("currency") or ""))
        g["statements"] += 1
        for k, pick in (("period_start", min), ("period_end", max)):
            if st.get(k):
                edge = "first" if k == "period_start" else "last"
                g[edge] = pick(filter(None, (g[edge], str(st[k])[:10])))
    r, names, registered = parties.resolver(), _party_names(), _registered()
    for key, details in registered.items():
        if key not in groups:
            groups[key] = {"key": key, "account": details["label"], "statement_types": set(), "currencies": set(),
                           "statements": 0, "first": None, "last": None}
    return [{**g, "statement_types": sorted(t for t in g["statement_types"] if t),
             "currencies": sorted({*(c for c in g["currencies"] if c), *registered.get(k, {}).get("currencies", [])}),
             "party": _party_ref(r.account(k), names), "registered": registered.get(k)}
            for k, g in sorted(groups.items())]


def _registered() -> dict[str, dict[str, Any]]:
    """138: the accounts registered with a party, with their details and the label the party knows them by."""
    labels = {i["key"]: i["label"] for p in parties.parties() for i in p["identities"] if i["kind"] == "account"}
    return {k: {**d, "label": labels[k]} for k, d in parties.accounts().items() if k in labels}


def _party_names() -> dict[str, str]:
    return {p["id"]: p["name"] for p in parties.parties()}


def _party_ref(party_id: str | None, names: dict[str, str]) -> dict[str, str] | None:
    return {"id": party_id, "name": names.get(party_id, party_id)} if party_id else None


def _checked_party(party_id: str | None) -> str | None:
    if party_id is None:
        return None
    try:
        return parties.get(party_id)["id"]
    except KeyError:
        raise PackageError(f"no own party {party_id}") from None


def _checked_scope(keys: Iterable[str], period_start: Any, period_end: Any) -> tuple[list[str], str, str]:
    start, end = _day(period_start, "period_start"), _day(period_end, "period_end")
    if start > end:
        raise PackageError("the period ends before it starts")
    chosen = sorted(set(keys))
    if not chosen:
        raise PackageError("choose at least one account or card")
    known = {a["key"] for a in accounts()}
    if unknown := [k for k in chosen if k not in known]:
        raise PackageError(f"neither a statement nor a registered account: {', '.join(unknown)}")
    return chosen, start.isoformat(), end.isoformat()


def create(*, name: str, accounts: list[str], period_start: str, period_end: str, actor: str,
           party_id: str | None = None) -> dict[str, Any]:
    """A new reconciliation package with its scope and own party; the creator owns it (decision 065)."""
    keys, start, end = _checked_scope(accounts, period_start, period_end)
    party = _checked_party(party_id)
    wp = work.create_workpackage(name=name, source_kind=KIND, source_ref=f"{start}..{end}", owner=actor)
    with store.connect() as c:
        store.begin_immediate(c)
        c.execute("INSERT INTO reconcile_scopes(workpackage_id, accounts, period_start, period_end, revision, actor, updated_at,"
                  " party_id) VALUES (?,?,?,?,1,?,?,?)", (wp["id"], json.dumps(keys), start, end, actor, _now(), party))
        work.record_event(c, wp["id"], "reconcile_scope", actor, {"accounts": len(keys), "period": [start, end], "party": party})
    return scope(wp["id"])


def _package(wp_id: str) -> dict[str, Any]:
    wp = work.get(wp_id)
    if wp["source_kind"] != KIND:
        raise PackageError("not a reconciliation package")
    return wp


def scope(wp_id: str) -> dict[str, Any]:
    _package(wp_id)
    with store.connect() as c:
        row = c.execute("SELECT * FROM reconcile_scopes WHERE workpackage_id=?", (wp_id,)).fetchone()
    if row is None:
        raise KeyError(wp_id)
    return {"workpackage_id": wp_id, "accounts": json.loads(row["accounts"]), "period_start": row["period_start"],
            "period_end": row["period_end"], "revision": row["revision"], "updated_at": row["updated_at"],
            "party_id": row["party_id"], "party": _party_ref(row["party_id"], _party_names())}


def set_scope(wp_id: str, *, accounts: list[str], period_start: str, period_end: str, expected_revision: int,
              actor: str, party_id: str | None = None) -> dict[str, Any]:
    """A changed scope and party; the decisions stay (they belong to the pairs). 145: not while approved."""
    keys, start, end = _checked_scope(accounts, period_start, period_end)
    party = _checked_party(party_id)
    scope(wp_id)
    if active := active_versions().get(wp_id):
        raise Locked(f"the package's statement is approved (version {active['version']}); reopen it to change the scope")
    with store.connect() as c:
        store.begin_immediate(c)
        row = c.execute("SELECT revision FROM reconcile_scopes WHERE workpackage_id=?", (wp_id,)).fetchone()
        if row["revision"] != expected_revision:
            raise work.RevisionConflict(f"the scope is at revision {row['revision']}, not {expected_revision}")
        c.execute("UPDATE reconcile_scopes SET accounts=?, period_start=?, period_end=?, revision=revision+1, actor=?,"
                  " updated_at=?, party_id=? WHERE workpackage_id=?", (json.dumps(keys), start, end, actor, _now(), party, wp_id))
        c.execute("UPDATE workpackages SET source_ref=?, updated_at=? WHERE id=?", (f"{start}..{end}", _now(), wp_id))
        work.record_event(c, wp_id, "reconcile_scope", actor, {"accounts": len(keys), "period": [start, end], "party": party})
    return scope(wp_id)


def _in_scope(st: dict[str, Any], sc: dict[str, Any]) -> bool:
    """A statement of a scope account whose period meets the scope's period (without a period: any line in it)."""
    if reconcile.statement_account(st) not in sc["accounts"]:
        return False
    first, last = str(st.get("period_start") or "")[:10], str(st.get("period_end") or "")[:10]
    if first and last:
        return first <= sc["period_end"] and last >= sc["period_start"]
    return any(sc["period_start"] <= str(ln.get("booking_date") or "")[:10] <= sc["period_end"] for ln in st["lines"])


def scoped_snapshot(wp_id: str, *, fetch_rates: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    """The store's snapshot with the package's scope: every statement stays for the amounts allocated so far, the
    proposal and the coverage take the scope's statements only; 138: the scope's registered accounts have to be
    covered too, with or without a statement (`own_accounts`)."""
    sc = scope(wp_id)
    snap = reconcile.snapshot(fetch_rates=fetch_rates)
    own = [{"key": k, **{f: d[f] for f in ("kind", "currencies", "valid_from", "valid_to")}}
           for k, d in sorted(parties.accounts().items()) if k in sc["accounts"]]
    return {**snap, "scope_statements": [st["id"] for st in snap["statements"] if _in_scope(st, sc)], "own_accounts": own}, sc


# --- the workspace -----------------------------------------------------------------------------------------------------


class _Parties:
    """133: the own party of an invoice (`{id, name, how}` or None) and whether it is the package's own: of the
    package's party or of none; a package without a party takes every invoice as its own."""

    def __init__(self, sc: dict[str, Any], invoices: dict[str, dict[str, Any]]):
        self.party, self.invoices = sc.get("party_id"), invoices
        self.resolver, self.names = parties.resolver(), _party_names()
        self.cache: dict[str, dict[str, Any] | None] = {}

    def of(self, invoice_id: str) -> dict[str, Any] | None:
        if invoice_id not in self.cache:
            inv = self.invoices.get(invoice_id) or {}
            side = "supplier" if reconcile.outgoing(inv) else "buyer"  # 148: an outgoing invoice is its issuer's
            pid, how = self.resolver.invoice(inv.get(f"{side}_name"), inv.get(f"{side}_tax_id"))
            self.cache[invoice_id] = {"id": pid, "name": self.names.get(pid, pid), "how": how} if pid else None
        return self.cache[invoice_id]

    def own(self, invoice_id: str) -> bool:
        ref = self.of(invoice_id) if self.party else None
        return ref is None or ref["id"] == self.party


def _credit_note(credit_id: str | None, invoices: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """141: the credit note that cancels an invoice: its id and number, for the pairing page."""
    if not credit_id:
        return None
    return {"id": credit_id, "number": (invoices.get(credit_id) or {}).get("number")}


def _money(value: Any) -> Decimal | None:
    try:
        return reconcile.money(str(value))
    except ValueError:
        return None


def _open_refs(docs: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """132: where a document's image opens: the package, run and item of its work run, and its page count. A document
    from an evaluation on the command line has none (it belongs to no package)."""
    docs = [d for d in docs if d.get("work_run") and d.get("item_id")]
    runs = sorted({d["work_run"] for d in docs})
    ids = sorted({d["id"] for d in docs})
    if not docs:
        return {}
    with store.connect() as c:
        packages = {r["run_id"]: r["workpackage_id"] for r in c.execute(
            f"SELECT run_id, workpackage_id FROM runs WHERE run_id IN ({','.join('?' * len(runs))})", runs)}
        pages: dict[str, int | None] = {}
        for start in range(0, len(ids), 500):  # stays under the SQLite parameter limit
            chunk = ids[start:start + 500]
            pages.update({r["doc_id"]: r["page_count"] for r in c.execute(
                f"SELECT doc_id, page_count FROM documents WHERE doc_id IN ({','.join('?' * len(chunk))})", chunk)})
    return {d["id"]: {"workpackage_id": packages[d["work_run"]], "run_id": d["work_run"], "item_id": d["item_id"],
                      "pages": pages.get(d["id"])} for d in docs if d["work_run"] in packages}


def _partner_marks(snap: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
    """135: the active needs-no-invoice marks per partner (`reconcile.name_key`) and reason: the lines marked with it.
    A line through a payment app, or without a name, teaches nothing."""
    lines = {ln["id"]: ln for st in snap["statements"] for ln in st["lines"]}
    out: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for m in snap["marks"]:
        ln = lines.get(m["line_id"])
        key = reconcile.name_key(ln.get("counterparty_name")) if ln else None
        if key and not reconcile.through_app(ln):
            out[key][m["category"]].add(m["line_id"])
    return out


def _earlier_marks(history: dict[str, dict[str, set[str]]], line: dict[str, Any], key: str | None) -> list[dict[str, Any]]:
    """The reasons given for the partner's other lines, the most frequent first (135); none through a payment app."""
    if not key or key not in history or reconcile.through_app(line):
        return []
    counts = {cat: len(ids - {line["id"]}) for cat, ids in history[key].items()}
    return [{"category": cat, "lines": n} for cat, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])) if n]


# 140 (Q-filter-slowness): what a workspace reads, as `store.table_marks` specs. A workspace is kept until one of these
# changes (about 1 s to build; the package list builds one per reconciliation package). Each entry adds what changes
# in place to the row count and the largest rowid: an approval, a revocation, a decision, a party's identities.
WORKSPACE_INPUTS: dict[str, str | None] = {
    "datapoints": None,
    "run_item_corrections": None,
    "run_items": "SUM(status='done'), MAX(updated_at)",
    "documents": "SUM(page_count)",
    "runs": "(SELECT group_concat(run_id || ':' || COALESCE(approval, ''), '|') FROM runs)",
    "duplicate_decisions": "(SELECT group_concat(pair_key || ':' || decision || ':' || decided_at, '|') FROM duplicate_decisions)",
    "statement_choices": None,
    "reconcile_decisions": "(SELECT group_concat(pair_key || ':' || decision || ':' || decided_at, '|') FROM reconcile_decisions)",
    "reconcile_allocations": "COUNT(revoked_at)",
    "reconcile_line_marks": "COUNT(revoked_at)",
    "reconcile_scopes": "(SELECT group_concat(workpackage_id || ':' || revision, '|') FROM reconcile_scopes)",
    # an answer is replaced in place (one row per line and engine), possibly within the same second: its content counts
    "reconcile_ai_proposals": "(SELECT group_concat(line_id || ':' || engine || ':' || COALESCE(pays, '') || ':'"
                              " || COALESCE(kind, '') || ':' || COALESCE(error, '') || ':' || COALESCE(options, '') || ':'"
                              " || COALESCE(asked_line_id, '') || ':' || COALESCE(config_hash, '') || ':' || created_at, '|')"
                              " FROM reconcile_ai_proposals)",  # 147: the version of the question shows (stale answers)
    "fx_rates": "MAX(fetched_at)",
    "reconcile_versions": "COUNT(reopened_at)",  # 145: an approval, a reopening
    "reconcile_source_acceptances": None,
    "own_parties":"(SELECT group_concat(id || ':' || name, '|') FROM own_parties)",
    "own_party_identities": "(SELECT group_concat(kind || ':' || key || ':' || COALESCE(party_id, '-'), '|') FROM own_party_identities)",
    "own_accounts": "(SELECT group_concat(key || ':' || kind || ':' || currencies || ':' || COALESCE(valid_from, '')"
                    " || ':' || COALESCE(valid_to, ''), '|') FROM own_accounts)",
}
_kept: OrderedDict[tuple[str, str], tuple[str, dict[str, Any]]] = OrderedDict()
_kept_lock = threading.Lock()
KEPT_WORKSPACES = 16
KEEP_SECONDS = 120  # a safety bound: a change the marks miss shows within this time at the latest


def inputs_mark(c=None) -> str:
    """140: a mark of everything a workspace reads (the tables above, the configurations and the day), and a time slot
    of `KEEP_SECONDS`, so nothing is kept longer than that."""
    # the modules whose tables the workspace reads register them on import (a later import would change the mark)
    from jav import duplicates, fx, reconcile_ai, statement_months  # noqa: F401

    if c is None:
        with store.connect() as own:
            return inputs_mark(own)
    parts = [store.table_marks(c, WORKSPACE_INPUTS), reconcile.config_hash(), parties.config_hash(), cfg.config_hash("fx"),
             reconcile.ENGINE_VERSION, date.today().isoformat(), int(time.time() // KEEP_SECONDS)]
    return hashlib.sha256(json.dumps(parts, default=str).encode("utf-8")).hexdigest()


def clear_cache() -> None:
    with _kept_lock:
        _kept.clear()
        _signal_inputs_kept.clear()


def workspace(wp_id: str) -> dict[str, Any]:
    """Everything the pairing page shows (`_workspace`), kept until its inputs change (140); the caller gets its own
    copy, so changing it changes nothing kept."""
    mark = inputs_mark()
    key = (str(store.active_path()), wp_id)
    with _kept_lock:
        hit = _kept.get(key)
        if hit and hit[0] == mark:
            _kept.move_to_end(key)
            return copy.deepcopy(hit[1])
    built = _workspace(wp_id)
    with _kept_lock:
        _kept[key] = (mark, built)
        _kept.move_to_end(key)
        while len(_kept) > KEPT_WORKSPACES:
            _kept.popitem(last=False)
    return copy.deepcopy(built)


def _workspace(wp_id: str) -> dict[str, Any]:
    """Everything the pairing page shows: the scope's lines (in the period) and the invoices they may pay, each with
    its state, the amount allocated and left, its allocations and candidates, its partner and the reasons given earlier
    for that partner's lines; the coverage per account and month; the blockers of the approval; and counts."""
    snap, sc = scoped_snapshot(wp_id)
    history = _partner_marks(snap)
    result = reconcile.propose(snap)
    scope_ids = set(snap["scope_statements"])
    statements = [st for st in snap["statements"] if st["id"] in scope_ids]
    invoices = {i["id"]: i for i in snap["invoices"]}
    status = {s["invoice_id"]: s for s in result["invoices"]}
    paid_line = {k: Decimal(v) for k, v in result["paid"]["lines"].items()}
    paid_invoice = {k: Decimal(v) for k, v in result["paid"]["invoices"].items()}
    marks = {m["line_id"]: m for m in snap["marks"]}
    excluded = {(e["kind"], e["id"]): e["reason"] for e in result["excluded"]}
    by_line, by_invoice = defaultdict(list), defaultdict(list)
    for c in result["candidates"]:
        by_line[c["line_id"]].append(c)
        by_invoice[c["invoice_id"]].append(c)
    alloc_ids = {(a["invoice_id"], a["line_id"]): a for a in snap["allocations"]}
    shares_line, shares_invoice = defaultdict(list), defaultdict(list)
    for a in result["confirmed"]:
        row = alloc_ids.get((a["invoice_id"], a["line_id"]))
        share = {"invoice_id": a["invoice_id"], "line_id": a["line_id"], "line_amount": a["line_amount"],
                 "invoice_amount": a["invoice_amount"], "allocation_id": row["id"] if row else None,
                 "workpackage_id": row["workpackage_id"] if row else None}
        shares_line[a["line_id"]].append(share)
        shares_invoice[a["invoice_id"]].append(share)
    rejected = {(d["invoice_id"], d["line_id"]) for d in snap["decisions"] if d["decision"] == "not_this"}
    who = _Parties(sc, invoices)
    locked = locks(snap)  # 145: the lines of approved statements

    def candidate_view(c: dict[str, Any]) -> dict[str, Any]:
        return {k: c.get(k) for k in ("invoice_id", "line_id", "proposed", "amount_only", "signals", "amount_relation",
                                      "multiple_candidates", "source_review_required", "fx", "original", "strength",
                                      "days_after_issue", "by_due", "combined", "combined_fx")}

    lines = []
    for st in statements:
        for ln in st["lines"]:
            booked = str(ln.get("booking_date") or "")[:10]
            if not sc["period_start"] <= booked <= sc["period_end"]:
                continue
            lid, amount = ln["id"], _money(ln.get("amount"))
            paid = paid_line.get(lid, Decimal(0))
            mine = [c for c in by_line.get(lid, []) if who.own(c["invoice_id"])]
            theirs = [c for c in by_line.get(lid, []) if not who.own(c["invoice_id"])]
            if lid in marks:
                state = "marked"
            elif amount is not None and paid >= amount > 0:
                state = "allocated"
            elif any(c["proposed"] for c in mine):
                state = "proposed"
            elif any(c["amount_only"] for c in mine):
                state = "amount_only"
            elif paid > 0:
                state = "partly_allocated"
            elif ("line", lid) in excluded:
                state = "excluded"
            else:
                state = "open"
            partner = reconcile.name_key(ln.get("counterparty_name"))
            lines.append({"id": lid, "statement_id": st["id"], "account": reconcile.statement_account(st),
                          "statement_type": st.get("statement_type"), "currency": st.get("currency"),
                          "booking_date": ln.get("booking_date"), "direction": ln.get("direction"), "amount": ln.get("amount"),
                          "counterparty_name": ln.get("counterparty_name"), "counterparty_account": ln.get("counterparty_account"),
                          "description": ln.get("description"), "memo": ln.get("memo"),
                          "original_amount": ln.get("original_amount"), "original_currency": ln.get("original_currency"),
                          "value_date": ln.get("value_date"), "running_balance": ln.get("running_balance"),  # 142: the card
                          **{k: ln[k] for k in LINE_DETAILS if ln.get(k)},  # 144: the facts beyond the money
                          "state": state, "excluded_reason": excluded.get(("line", lid)),
                          "allocated": str(paid), "rest": str(amount - paid) if amount is not None else None,
                          "mark": marks.get(lid), "allocations": shares_line.get(lid, []),
                          "candidates": [candidate_view(c) for c in mine],
                          "other_candidates": [{"invoice_id": c["invoice_id"], "party": (who.of(c["invoice_id"]) or {}).get("name")}
                                               for c in theirs],
                          "rejected": sorted(i for i, l_ in rejected if l_ == lid),
                          "statement_verified": bool(st.get("verified")),
                          "partner": partner, "earlier_marks": _earlier_marks(history, ln, partner),
                          "category_mark": reconcile.category_mark(ln),  # 140: the line's own category suggests a reason
                          "locked": locked.get(lid)})
    line_ids = {ln["id"] for ln in lines}
    from jav import reconcile_ai  # 134: the AI's stored answers per line (that module reads this workspace)

    # 139: a line of a statement that replaced another keeps the answers given on the same line of the replaced one
    earlier = {new: old for old, new in snap.get("line_map", {}).items() if new in line_ids}
    ai = reconcile_ai.proposals(line_ids | set(earlier.values()))
    for ln in lines:
        ln["ai"] = ai.get(ln["id"]) or ai.get(earlier.get(ln["id"], ""), {})
    currencies = {str(st.get("currency")) for st in statements}
    cards = any(reconcile.fx_capable({"currency": st.get("currency"), "statement_type": st.get("statement_type")})
                or any(reconcile.original(ln) for ln in st["lines"]) for st in statements)  # 137: card purchases' originals
    start, end = date.fromisoformat(sc["period_start"]), date.fromisoformat(sc["period_end"])
    wanted = {c["invoice_id"] for lid in line_ids for c in by_line.get(lid, [])}
    wanted |= {s["invoice_id"] for lid in line_ids for s in shares_line.get(lid, [])}
    for iid, inv in invoices.items():
        if status.get(iid, {}).get("status") == "excluded" or _iso(inv.get("issue_date")) is None:
            continue
        same = str(inv.get("currency")) in currencies
        if not same and not (cards and reconcile.rate_need(inv)):
            continue
        w_start, w_end = reconcile.window(inv) if same else reconcile.fx_window(inv)
        if w_start <= end and w_end >= start:
            wanted.add(iid)
    files = reconcile.file_names([*wanted, *(st["id"] for st in statements)])
    docs = [*(invoices[i] for i in wanted if i in invoices), *statements]
    approved = work.approved_runs(d.get("work_run") for d in docs)
    accepted = accepted_sources()
    invoice_rows = []
    for iid in sorted(wanted, key=lambda i: (str(invoices[i].get("issue_date") or ""), i)):
        inv = invoices[iid]
        amount = _money(inv.get("amount"))
        paid = paid_invoice.get(iid, Decimal(0))
        invoice_rows.append({"id": iid, "doc_type": inv.get("doc_type"), "number": inv.get("number"),
                             "supplier_name": inv.get("supplier_name"), "amount": inv.get("amount"),
                             "outgoing": reconcile.outgoing(inv), "partner_name": reconcile.partner_name(inv),  # 148
                             "currency": inv.get("currency"), "issue_date": inv.get("issue_date"), "due_date": inv.get("due_date"),
                             "payment_method": inv.get("payment_method"), "file": files.get(iid),
                             "state": status.get(iid, {}).get("status"), "allocated": str(paid),
                             "rest": str(amount - paid) if amount is not None else None,
                             "allocations": shares_invoice.get(iid, []), "candidates": [candidate_view(c) for c in by_invoice.get(iid, [])
                                                                                      if c["line_id"] in line_ids],
                             "source": _source_state(inv, approved, accepted), "party": who.of(iid), "own": who.own(iid),
                             "credited_by": _credit_note(status.get(iid, {}).get("credited_by"), invoices),
                             # 142: every fact the card shows, and the day its statements are checked until
                             **{k: inv.get(k) for k in ("supplier_tax_id", "payment_account", "references", "buyer_name",
                                                        "fulfillment_date", "net_total", "vat_total", "duplicate")},
                             "checked_until": status.get(iid, {}).get("checked_until")})
    for ln in lines:
        ln["file"] = files.get(ln["statement_id"])
    coverage = []
    for key in sc["accounts"]:
        own = [st for st in statements if reconcile.statement_account(st) == key]
        for month in reconcile.months(sc["period_start"], sc["period_end"]):
            meets = [st for st in own if str(st.get("period_start") or "")[:7] <= month <= str(st.get("period_end") or "")[:7]]
            coverage.append({"account": key, "month": month, "statements": len(meets),
                             "verified": sum(1 for st in meets if st.get("verified"))})
    blockers, warnings = [], []
    for st in statements:
        state = _source_state(st, approved, accepted)
        if state not in SOURCE_OK:
            blockers.append({"code": f"source_{state}", "doc_id": st["id"], "file": files.get(st["id"]), "kind": "statement"})
        if not st.get("verified"):  # DECISIONS 132: a warning in the statement, not a blocker
            warnings.append({"code": "statement_unverified", "doc_id": st["id"], "file": files.get(st["id"]), "kind": "statement"})
    for row in invoice_rows:
        # DECISIONS 145: an invoice of no own party (every package's own, 133) or of another party blocks only once a
        # line of this package paid it; the package party's own invoice also with a candidate or a payment elsewhere
        paid_here = any(a["line_id"] in line_ids for a in row["allocations"])
        mine = row["own"] and row["party"] is not None
        if row["source"] not in SOURCE_OK and (paid_here or (mine and (row["allocations"] or row["candidates"]))):
            blockers.append({"code": f"source_{row['source']}", "doc_id": row["id"], "file": row["file"], "kind": "invoice"})
    left_over = left_over_rows(snap, scope_ids, wp_id)
    for row in left_over:
        blockers.append({"code": "decision_not_carried", "doc_id": row["statement_id"], "file": row["file"], "kind": "statement"})
    unfit = unfit_rows(result, snap, scope_ids, wp_id)
    for row in unfit:
        blockers.append({"code": "allocation_no_longer_fits", "doc_id": row["invoice_id"], "file": row["invoice_file"],
                         "kind": "invoice"})
    return {"workpackage_id": wp_id, "scope": sc, "lines": lines, "invoices": invoice_rows, "coverage": coverage,
            "left_over": left_over, "unfit": unfit, "overview": reconcile_overview.build(lines, invoice_rows, result["repeats"]),
            "blockers": blockers, "warnings": warnings, "approval": approval(wp_id),
            "line_marks": list(_conf()["line_marks"]), "open": _open_refs(docs),
            "counts": {"lines": dict(sorted(Counter(ln["state"] for ln in lines).items())),
                       "invoices": dict(sorted(Counter(str(r["state"]) for r in invoice_rows if r["own"]).items())),
                       "other_invoices": sum(1 for r in invoice_rows if not r["own"]),
                       "open_lines": sum(1 for ln in lines if ln["state"] in OPEN_LINE_STATES)},
            "learned_names": result["learned_names"], "fx_tolerance": result["fx_tolerance"],
            "engine_version": reconcile.ENGINE_VERSION, "config_hash": reconcile.config_hash(),
            "decision_state": _decision_state()}


OPEN_LINE_STATES = ("proposed", "amount_only", "partly_allocated", "open")  # a person still has to decide these


# --- 143: the finder ---------------------------------------------------------------------------------------------------

FITS = ("proposed", "candidate", "named", "tied", "same_amount")  # how an invoice fits a line (`_fit`)
_signal_inputs_kept: dict[str, tuple[str, dict[str, Any]]] = {}


def _signal_inputs() -> dict[str, Any]:
    """The store-wide inputs of `reconcile.compare` (the learnt names, the common words, the exchange rates), kept
    until the workspace's inputs change."""
    mark, key = inputs_mark(), str(store.active_path())
    with _kept_lock:
        hit = _signal_inputs_kept.get(key)
        if hit and hit[0] == mark:
            return hit[1]
    snap = reconcile.snapshot()
    built = {**reconcile.signal_context(snap), "rates": snap.get("fx_rates") or {}}
    with _kept_lock:
        _signal_inputs_kept[key] = (mark, built)
    return built


def _compared(row: dict[str, Any]) -> Any:
    """The amount a side is compared on: what is left of it, or the whole when nothing is (a paid invoice may be paid
    again)."""
    left = _money(row.get("rest"))
    return str(left) if left is not None and left > 0 else row.get("amount")


def _fit(facts: dict[str, Any], candidate: dict[str, Any] | None) -> str | None:
    """How an invoice fits the line (`FITS`): proposed or listed by the engine for the line; its number or reference in
    the line's text (wherever booked: an advance or a late payment); in its payment window, tied by a signal that is
    not weak, or of the same amount; None otherwise."""
    if candidate is not None:
        return "proposed" if candidate.get("proposed") else "candidate"
    found = set(facts["signals"])
    if found & reconcile.NAMED_SIGNALS:
        return "named"
    if facts["in_window"] and found - reconcile.WEAK_SIGNALS:
        return "tied"
    if facts["in_window"] and facts["amount_relation"] in ("equal", "fx_within"):
        return "same_amount"
    return None


def matches(wp_id: str, line_id: str) -> dict[str, Any]:
    """143 (DECISIONS 143): every invoice of the package's page compared with one of its lines (`reconcile.compare`,
    on what is left of both sides), with how it fits (`_fit`) and the days from its due date to the line's booking
    day: the engine's proposals first, then the other fitting ones by strength, then the rest by the nearest amount.
    Raises KeyError for a line the page does not show."""
    ws = workspace(wp_id)
    line = next((ln for ln in ws["lines"] if ln["id"] == line_id), None)
    if line is None:
        raise KeyError(line_id)
    inputs = _signal_inputs()
    payment = {**line, "amount": _compared(line)}
    candidates = {c["invoice_id"]: c for c in line["candidates"]}
    found = []
    for row in ws["invoices"]:
        facts = reconcile.compare({**row, "amount": _compared(row)}, payment, inputs["learned"], inputs["common"], inputs["rates"])
        found.append({"invoice_id": row["id"], "fit": _fit(facts, candidates.get(row["id"])), **facts,
                      "days_from_due": reconcile_overview.days_from_due(line, row)})

    def order(m: dict[str, Any]) -> tuple[Any, ...]:
        rank = 0 if m["fit"] == "proposed" else 1 if m["fit"] else 2
        gap = abs(Decimal(m["difference"]["amount"])) if m["difference"] else None
        return (rank, -int(m["strength"] or 0) if m["fit"] else 0, gap is None, gap or Decimal(0), m["invoice_id"])

    return {"line_id": line_id, "matches": sorted(found, key=order)}


def left_over_rows(snap: dict[str, Any], scope_ids: set[str], wp_id: str) -> list[dict[str, Any]]:
    """139 (DECISIONS 139): the decisions made on a replaced statement's line that has no same line on the statement
    replacing it, for the package that made them or whose scope holds the replacing statement; each with its line and
    the two statements, to be revoked (and made again on the valid statement)."""
    replaced = snap.get("replaced") or {}
    out = []
    for kind, rows in sorted((snap.get("left_over") or {}).items()):
        for row in rows:
            old = replaced.get(str(row.get("statement_id")))
            if old is None or (row.get("workpackage_id") != wp_id and old["by"] not in scope_ids):
                continue
            line = next((ln for ln in old["lines"] if ln["id"] == row["line_id"]), {})
            out.append({"kind": kind[:-1], "ref": str(row["pair_key"] if kind == "decisions" else row["id"]),
                        "line_id": row["line_id"], "statement_id": row["statement_id"], "replaced_by": old["by"],
                        "invoice_id": row.get("invoice_id"), "category": row.get("category"), "decision": row.get("decision"),
                        "workpackage_id": row.get("workpackage_id"), "currency": old.get("currency"),
                        **{k: line.get(k) for k in ("booking_date", "amount", "direction", "counterparty_name")}})
    files = reconcile.file_names([*(r["statement_id"] for r in out), *(r["replaced_by"] for r in out),
                                  *(r["invoice_id"] for r in out if r["invoice_id"])])
    for r in out:
        r["file"], r["replaced_by_file"] = files.get(r["statement_id"]), files.get(r["replaced_by"])
        r["invoice_file"] = files.get(r["invoice_id"]) if r["invoice_id"] else None
    return out


def unfit_rows(result: dict[str, Any], snap: dict[str, Any], scope_ids: set[str], wp_id: str) -> list[dict[str, Any]]:
    """153 (review A3): the allocations that no longer fit their line or invoice (an amount corrected or read again
    since, `reconcile._settled`), for the package that made them or whose scope holds the line; each with its amounts and
    the sides' amounts now, to be revoked (and made again). They block the approval."""
    lines = {ln["id"]: {**ln, "statement_id": st["id"], "currency": st.get("currency")}
             for st in snap["statements"] for ln in st["lines"]}
    out = []
    for a in result.get("unfit") or []:
        line = lines.get(str(a["line_id"]), {})
        if a.get("workpackage_id") != wp_id and line.get("statement_id") not in scope_ids:
            continue
        out.append({"kind": "allocation", "ref": str(a["id"]), "line_id": a["line_id"], "invoice_id": a["invoice_id"],
                    "statement_id": line.get("statement_id") or a.get("statement_id"), "workpackage_id": a.get("workpackage_id"),
                    "line_amount": a.get("line_amount"), "invoice_amount": a.get("invoice_amount"),
                    "line_total": a.get("line_total"), "invoice_total": a.get("invoice_total"), "currency": line.get("currency"),
                    **{k: line.get(k) for k in ("booking_date", "direction", "counterparty_name")}})
    files = reconcile.file_names([r["invoice_id"] for r in out])
    for r in out:
        r["invoice_file"] = files.get(r["invoice_id"])
    return out


SOURCE_OK = ("approved", "accepted")  # 145: a source that does not block the approval


def _source_state(doc: dict[str, Any], approved: set[str], accepted: set[tuple[str, str]] | frozenset = frozenset()) -> str:
    """approved: its run is approved; not_approved: a run not yet approved; no_run: an evaluation on the command line;
    145: accepted, such an evaluation's result a person accepted as a source."""
    run = doc.get("work_run")
    if run is None:
        return "accepted" if (doc["id"], str(doc.get("flow_run_id"))) in accepted else "no_run"
    return "approved" if run in approved else "not_approved"


# --- 145: approved versions and accepted sources ---------------------------------------------------------------------


def _version_meta(r: Any) -> dict[str, Any]:
    return {k: r[k] for k in ("version", "fingerprint", "approved_by", "approved_at", "reopened_by", "reopened_at", "reopen_note")}


def active_versions(c=None) -> dict[str, dict[str, Any]]:
    """The approved versions not reopened, per package, with the lines they lock."""
    if c is None:
        with store.connect() as own:
            return active_versions(own)
    return {r["workpackage_id"]: {**_version_meta(r), "line_ids": json.loads(r["line_ids"])}
            for r in c.execute("SELECT * FROM reconcile_versions WHERE reopened_at IS NULL ORDER BY id")}


def approval(wp_id: str, c=None) -> dict[str, Any]:
    """A package's approval: its active version (None while it has none) and every version, the latest first."""
    if c is None:
        with store.connect() as own:
            return approval(wp_id, own)
    versions = [_version_meta(r) for r in c.execute(
        "SELECT * FROM reconcile_versions WHERE workpackage_id=? ORDER BY version DESC", (wp_id,))]
    return {"active": next((v for v in versions if v["reopened_at"] is None), None), "versions": versions}


def locks(snap: dict[str, Any] | None = None, c=None) -> dict[str, dict[str, Any]]:
    """The locked lines: a line's id -> the package and version locking it; 139: the same line of a statement that
    replaced a locked one is locked too (the decisions moved to it)."""
    out: dict[str, dict[str, Any]] = {}
    for wp_id, v in active_versions(c).items():
        for lid in v["line_ids"]:
            out.setdefault(lid, {"workpackage_id": wp_id, "version": v["version"]})
    for old, new in ((snap or {}).get("line_map") or {}).items():
        if old in out:
            out.setdefault(new, out[old])
    return out


def accepted_sources(c=None) -> set[tuple[str, str]]:
    """The command-line results a person accepted as a source: (document, its flow run)."""
    if c is None:
        with store.connect() as own:
            return accepted_sources(own)
    return {(r["doc_id"], r["flow_run_id"]) for r in c.execute("SELECT doc_id, flow_run_id FROM reconcile_source_acceptances")}


def _decision_state(c=None) -> list[Any]:
    """What a decision depends on having read: the allocations, marks and decisions recorded so far, and (145) the
    approvals (for the optimistic check of a write)."""
    if c is None:
        with store.connect() as own:
            return _decision_state(own)
    state: list[Any] = []
    for table in ("reconcile_allocations", "reconcile_line_marks"):
        state.append(list(c.execute(f"SELECT COUNT(*), MAX(id), COUNT(revoked_at) FROM {table}").fetchone()))
    state.append(list(c.execute("SELECT COUNT(*), MAX(decided_at) FROM reconcile_decisions").fetchone()))
    state.append(list(c.execute("SELECT COUNT(*), MAX(id), COUNT(reopened_at) FROM reconcile_versions").fetchone()))
    # 153 (review A3): a scope changed meanwhile (a line checked against the old one might now be outside it)
    state.append(list(c.execute("SELECT COUNT(*), SUM(revision) FROM reconcile_scopes").fetchone()))
    return state


def _write(read_state: list[Any], fn) -> Any:
    """A decision's write: in one transaction, after checking nobody recorded one since the state was read."""
    with store.connect() as c:
        store.begin_immediate(c)
        if _decision_state(c) != read_state:
            raise work.RevisionConflict("another decision was recorded meanwhile; reload the package")
        return fn(c)


# --- decisions -----------------------------------------------------------------------------------------------------------


def _refuse_approved(wp_id: str) -> None:
    """145: an approved package takes no decision until its version is reopened."""
    if active := active_versions().get(wp_id):
        raise Locked(f"the package's statement is approved (version {active['version']}); reopen it first")


def _context(wp_id: str) -> dict[str, Any]:
    """What a decision reads; 145: an approved package takes no decision until its version is reopened."""
    _package(wp_id)
    state = _decision_state()
    _refuse_approved(wp_id)
    snap, sc = scoped_snapshot(wp_id)
    result = reconcile.propose(snap)
    prepared = reconcile.prepare(snap)
    return {"state": state, "snap": snap, "scope": sc, "result": result, "prepared": prepared,
            "scope_ids": set(snap["scope_statements"]), "invoices": {i["id"]: i for i in snap["invoices"]},
            "paid_line": {k: Decimal(v) for k, v in result["paid"]["lines"].items()},
            "paid_invoice": {k: Decimal(v) for k, v in result["paid"]["invoices"].items()},
            "marks": {m["line_id"]: m for m in snap["marks"]}, "locked": locks(snap)}


def _unlocked(ctx: dict[str, Any], line_ids: Iterable[str]) -> None:
    """145: refuses a decision on a line of an approved statement (of any package)."""
    for lid in line_ids:
        if lock := ctx["locked"].get(lid):
            raise Locked(f"the line is in version {lock['version']} of an approved statement ({lock['workpackage_id']});"
                         " reopen it first")


def _scope_line(ctx: dict[str, Any], line_id: str) -> dict[str, Any]:
    line = ctx["prepared"]["lines"].get(line_id)
    if line is None:
        raise KeyError(line_id)
    if line["statement_id"] not in ctx["scope_ids"]:
        raise PackageError("the line is not in the package's scope")
    return line


def _converted_groups(ctx: dict[str, Any], pairs: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], Decimal], bool]:
    """151: the lines a step pairs with two or more invoices of another currency (a forint bank line paying them
    together). Each such group is allocated in whole on both sides: the invoices' whole amounts, the line's whole amount
    split in the ratio of their converted amounts (`reconcile.convert_combined`, `reconcile.split_line`). Returns each
    pair's line share and whether a group is outside its band (a reason is needed); `PackageError` for a group that
    cannot be converted: one of its sides already allocated, an amount given, invoices of several currencies, a line
    that cannot meet them, or no rate for every invoice."""
    by_line: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in pairs:
        inv, line = ctx["invoices"].get(str(p["invoice_doc_id"])), ctx["prepared"]["lines"].get(str(p["line_id"]))
        if inv is not None and line is not None and inv.get("currency") != line.get("currency"):
            by_line[str(p["line_id"])].append(p)
    shares: dict[tuple[str, str], Decimal] = {}
    needs_reason = False
    for lid, group in by_line.items():
        if len(group) < 2:
            continue
        line = ctx["prepared"]["lines"][lid]
        invoices = [ctx["invoices"][str(p["invoice_doc_id"])] for p in group]
        if (ctx["paid_line"].get(lid) or any(ctx["paid_invoice"].get(i["id"]) for i in invoices)
                or any(p.get("line_amount") or p.get("invoice_amount") for p in group)):
            raise PackageError("a pair of two currencies is allocated only in whole")
        if len({i.get("currency") for i in invoices}) > 1 or any(reconcile.meets(i, line) != "fx_bank" for i in invoices):
            raise PackageError("a line pays several invoices of another currency only from a bank account, in one currency")
        relation, conversion = reconcile.convert_combined(invoices, line, ctx["snap"].get("fx_rates"))
        if conversion is None:
            raise PackageError("a combined payment of another currency needs an exchange rate for every invoice")
        needs_reason |= relation != "fx_within"
        for p, share in zip(group, reconcile.split_line(_money(line.get("amount")), conversion)):
            shares[(str(p["invoice_doc_id"]), lid)] = share
    return shares, needs_reason


def allocate(wp_id: str, pairs: list[dict[str, Any]], *, note: str | None, actor: str) -> list[dict[str, Any]]:
    """Allocations of lines to invoices in one step (all or none). A pair without an amount takes what both sides have
    left in one currency, or both whole amounts for a converted card pair. A step that leaves a rest on a line or an
    invoice it touches in one currency (a split), or a converted pair outside the card band or without a rate, needs
    `note`; 132: instalments or a combined payment that settle every side they touch do not. 151: a line paying several
    invoices of another currency together is split in the ratio of their converted amounts (`_converted_groups`)."""
    note = (note or "").strip() or None
    if not pairs:
        raise PackageError("no pair to allocate")
    ctx = _context(wp_id)
    rows, needs_reason = [], False
    used_line: dict[str, Decimal] = defaultdict(Decimal)
    used_invoice: dict[str, Decimal] = defaultdict(Decimal)
    rest_after: dict[tuple[str, str], Decimal] = {}  # the rest each one-currency side touched is left with
    shares, group_reason = _converted_groups(ctx, pairs)  # 151: a line paying several invoices of another currency
    needs_reason |= group_reason
    for p in pairs:
        iid, lid = str(p["invoice_doc_id"]), str(p["line_id"])
        inv = ctx["invoices"].get(iid)
        if inv is None:
            raise KeyError(iid)
        line = _scope_line(ctx, lid)
        if not reconcile.pays(line, inv):  # 151: the engine's side rule (148), not a ban on the outgoing type
            raise PackageError("the line is not on the invoice's side: incoming money pays an outgoing invoice, a payment an incoming one")
        _unlocked(ctx, [lid])
        if lid in ctx["marks"]:
            raise PackageError("the line is marked as needing no invoice; revoke the mark first")
        line_total, invoice_total = _money(line.get("amount")), _money(inv.get("amount"))
        if not line_total or line_total <= 0 or not invoice_total or invoice_total <= 0:
            raise PackageError("the line or the invoice has no positive amount")
        line_rest = line_total - ctx["paid_line"].get(lid, Decimal(0)) - used_line[lid]
        invoice_rest = invoice_total - ctx["paid_invoice"].get(iid, Decimal(0)) - used_invoice[iid]
        if inv.get("currency") == line.get("currency"):
            given = {_money(p[k]) for k in ("line_amount", "invoice_amount") if p.get(k) not in (None, "")}
            if None in given or len(given) > 1:
                raise PackageError("in one currency the line's and the invoice's share are one canonical amount")
            share = given.pop() if given else min(line_rest, invoice_rest)
            la = ia = share
            rest_after[("line", lid)] = line_rest - la
            rest_after[("invoice", iid)] = invoice_rest - ia
        elif (iid, lid) in shares:
            la, ia = shares[(iid, lid)], invoice_total
        else:
            if (ctx["paid_line"].get(lid) or ctx["paid_invoice"].get(iid) or used_line[lid] or used_invoice[iid]
                    or p.get("line_amount") or p.get("invoice_amount")):
                raise PackageError("a pair of two currencies is allocated only in whole")
            if reconcile.meets(inv, line) is None:  # 137: a card purchase in the invoice's currency meets it too
                raise PackageError("this line cannot pay an invoice of another currency")
            relation, _conv = reconcile.amount_relation(inv, line, ctx["snap"].get("fx_rates"))
            la, ia = line_total, invoice_total
            needs_reason |= relation not in ("fx_within", "equal")
        if la <= 0 or la > line_rest or ia > invoice_rest:
            raise PackageError("the amount is over what the line or the invoice has left")
        used_line[lid] += la
        used_invoice[iid] += ia
        rows.append((iid, line["statement_id"], lid, str(la), str(ia)))
    needs_reason |= any(rest > 0 for rest in rest_after.values())
    if needs_reason and note is None:
        raise PackageError("a split, or a pair outside the card band or without a rate, needs a reason")

    def write(c) -> list[dict[str, Any]]:
        now, ids = _now(), []
        for iid, sid, lid, la, ia in rows:
            cur = c.execute("INSERT INTO reconcile_allocations(invoice_doc_id, statement_doc_id, line_id, line_amount,"
                            " invoice_amount, workpackage_id, actor, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                            (iid, sid, lid, la, ia, wp_id, actor, note, now))
            ids.append(cur.lastrowid)
        work.record_event(c, wp_id, "reconcile_allocate", actor, {"allocations": ids})
        return [dict(r) for r in c.execute(f"SELECT * FROM reconcile_allocations WHERE id IN ({','.join('?' * len(ids))})", ids)]
    return _write(ctx["state"], write)


def proposed_pairs(wp_id: str) -> list[dict[str, str]]:
    """The unambiguous proposals of the scope: proposed, the only candidate of its line and its invoice, on a statement
    whose balances check out, the line booked in the period, the invoice the package's own (133: another party's pair
    waits for a person), the line in no approved statement (145). 147: the quick review's sure pairs are these. 149: read
    from the kept workspace, whose lines are the period's and whose candidates are the package's own invoices; a fresh
    pairing here made the quick review pair the whole scope twice on every request."""
    _package(wp_id)
    _refuse_approved(wp_id)
    return [{"invoice_doc_id": c["invoice_id"], "line_id": ln["id"]} for ln in workspace(wp_id)["lines"] if not ln.get("locked")
            for c in ln["candidates"] if c["proposed"] and not c["multiple_candidates"] and not c["source_review_required"]]


def accept_proposed(wp_id: str, *, actor: str) -> int:
    """Every unambiguous proposal of the scope at once (`proposed_pairs`). Returns how many were allocated."""
    pairs = proposed_pairs(wp_id)
    if not pairs:
        return 0
    return len(allocate(wp_id, pairs, note=None, actor=actor))


def reject(wp_id: str, invoice_doc_id: str, line_id: str, *, note: str, actor: str) -> dict[str, Any]:
    """'Not this one' with a reason: the pair is never proposed or listed again (a decision on the pair, as on the
    review page)."""
    note = (note or "").strip()
    if not note:
        raise PackageError("a rejected pair needs a reason")
    ctx = _context(wp_id)
    inv = ctx["invoices"].get(invoice_doc_id)
    if inv is None:
        raise KeyError(invoice_doc_id)
    line = _scope_line(ctx, line_id)
    _unlocked(ctx, [line_id])
    if any(a["invoice_id"] == invoice_doc_id and a["line_id"] == line_id for a in ctx["result"]["confirmed"]):
        raise PackageError("the pair is allocated; revoke the allocation first")
    key = reconcile.pair_key(invoice_doc_id, line_id)

    def write(c) -> dict[str, Any]:
        before = c.execute("SELECT run_id FROM reconcile_decisions WHERE pair_key=?", (key,)).fetchone()
        if before is not None and before["run_id"] and work.approved_runs([before["run_id"]]):
            raise work.RevisionConflict("the pair was decided in an approved run; the decision is frozen")
        c.execute("INSERT INTO reconcile_decisions(pair_key, invoice_doc_id, statement_doc_id, line_id, decision, signals,"
                  " amount_relation, run_id, actor, note, decided_at, workpackage_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                  " ON CONFLICT(pair_key) DO UPDATE SET decision=excluded.decision, signals=excluded.signals,"
                  " amount_relation=excluded.amount_relation, run_id=NULL, actor=excluded.actor, note=excluded.note,"
                  " decided_at=excluded.decided_at, workpackage_id=excluded.workpackage_id",
                  (key, invoice_doc_id, line["statement_id"], line_id, "not_this",
                   json.dumps(reconcile.signals(inv, line, **reconcile.signal_context(ctx["snap"]))),
                   reconcile.amount_relation(inv, line, ctx["snap"].get("fx_rates"))[0], None, actor, note, _now(), wp_id))
        work.record_event(c, wp_id, "reconcile_reject", actor, {"pair": key})
        return dict(c.execute("SELECT * FROM reconcile_decisions WHERE pair_key=?", (key,)).fetchone())
    return _write(ctx["state"], write)


def mark(wp_id: str, line_ids: Iterable[str], *, category: str, note: str | None, actor: str) -> list[dict[str, Any]]:
    """'Needs no invoice' with its reason (`configs/reconcile.json` `line_marks`) for one or more lines in one step,
    all or none (132: most lines of a real statement need no invoice); a line with an allocation cannot be marked. A
    new mark replaces the line's earlier one."""
    ids = list(dict.fromkeys(line_ids))
    if not ids:
        raise PackageError("no line to mark")
    return mark_each(wp_id, {lid: category for lid in ids}, note=note, actor=actor)


def mark_each(wp_id: str, marks: dict[str, str], *, note: str | None, actor: str, basis: str | None = None) -> list[dict[str, Any]]:
    """147: several lines marked in one step, each with its own reason (the quick review accepts a group whose lines'
    suggestions differ), all or none; `basis` records the suggestion they came from (None: a person's own choice)."""
    note = (note or "").strip() or None
    if not marks:
        raise PackageError("no line to mark")
    conf = _conf()
    for category in set(marks.values()):
        if category not in conf["line_marks"]:
            raise PackageError(f"unknown reason: {category}")
        if category in conf["line_mark_note_required"] and note is None:
            raise PackageError("this reason needs a note")
    ids = list(marks)
    ctx = _context(wp_id)
    lines = [_scope_line(ctx, lid) for lid in ids]
    _unlocked(ctx, ids)
    if any(ctx["paid_line"].get(lid) for lid in ids):
        raise PackageError("a line has an allocation; revoke it first")

    def write(c) -> list[dict[str, Any]]:
        now, made = _now(), []
        for lid, line in zip(ids, lines):
            c.execute("UPDATE reconcile_line_marks SET revoked_at=?, revoked_by=? WHERE line_id=? AND revoked_at IS NULL",
                      (now, actor, lid))
            cur = c.execute("INSERT INTO reconcile_line_marks(statement_doc_id, line_id, category, note, workpackage_id, actor,"
                            " created_at, basis) VALUES (?,?,?,?,?,?,?,?)",
                            (line["statement_id"], lid, marks[lid], note, wp_id, actor, now, basis))
            made.append(cur.lastrowid)
        categories = sorted(set(marks.values()))
        work.record_event(c, wp_id, "reconcile_mark", actor, {"marks": made, "category": categories[0] if len(categories) == 1
                                                               else categories} | ({"basis": basis} if basis else {}))
        return [dict(r) for r in c.execute(f"SELECT * FROM reconcile_line_marks WHERE id IN ({','.join('?' * len(made))})", made)]
    return _write(ctx["state"], write)


def unmark(wp_id: str, line_ids: Iterable[str], *, actor: str) -> int:
    """135: revokes the needs-no-invoice marks of lines of the scope in one step (a partner's lines marked at once are
    undone at once); lines without a mark are skipped, but at least one must have one. Returns how many were revoked."""
    ids = list(dict.fromkeys(line_ids))
    if not ids:
        raise PackageError("no line to unmark")
    ctx = _context(wp_id)
    for lid in ids:
        _scope_line(ctx, lid)
    _unlocked(ctx, ids)
    marked = [ctx["marks"][lid]["id"] for lid in ids if lid in ctx["marks"]]
    if not marked:
        raise PackageError("none of the lines is marked")

    def write(c) -> int:
        now = _now()
        for mark_id in marked:
            c.execute("UPDATE reconcile_line_marks SET revoked_at=?, revoked_by=? WHERE id=? AND revoked_at IS NULL",
                      (now, actor, mark_id))
        work.record_event(c, wp_id, "reconcile_revoke", actor, {"kind": "marks", "refs": marked})
        return len(marked)
    return _write(ctx["state"], write)


def revoke(wp_id: str, *, kind: str, ref: str, actor: str, note: str | None = None) -> None:
    """Revokes a decision on a line of the scope: an allocation or a mark (by id; the row stays, marked revoked), or a
    decision on a pair (`paid_by` / `not_this` by its pair key; a decision made on an approved run is frozen)."""
    if kind not in REVOKE_KINDS:
        raise PackageError(f"unknown kind: {kind}")
    ctx = _context(wp_id)
    note = (note or "").strip() or None
    table = {"allocation": "reconcile_allocations", "mark": "reconcile_line_marks"}.get(kind)
    with store.connect() as c:
        row = (c.execute(f"SELECT * FROM {table} WHERE id=? AND revoked_at IS NULL", (int(ref),)).fetchone() if table
               else c.execute("SELECT * FROM reconcile_decisions WHERE pair_key=?", (ref,)).fetchone())
    if row is None:
        raise KeyError(ref)
    # 139: a decision made on a replaced statement's line stands on the same line of the valid one, or is left over
    left = {(r["kind"], r["ref"]) for r in left_over_rows(ctx["snap"], ctx["scope_ids"], wp_id)}
    left |= {(r["kind"], r["ref"]) for r in unfit_rows(ctx["result"], ctx["snap"], ctx["scope_ids"], wp_id)}  # 153
    if (kind, str(ref)) not in left:
        _scope_line(ctx, ctx["snap"].get("line_map", {}).get(row["line_id"], row["line_id"]))
    _unlocked(ctx, [row["line_id"], ctx["snap"].get("line_map", {}).get(row["line_id"], row["line_id"])])
    if kind == "decision" and row["run_id"] and work.approved_runs([row["run_id"]]):
        raise work.RevisionConflict("the pair was decided in an approved run; the decision is frozen")

    def write(c) -> None:
        if table == "reconcile_allocations":
            c.execute("UPDATE reconcile_allocations SET revoked_at=?, revoked_by=?, revoke_note=? WHERE id=?",
                      (_now(), actor, note, row["id"]))
        elif table:
            c.execute("UPDATE reconcile_line_marks SET revoked_at=?, revoked_by=? WHERE id=?", (_now(), actor, row["id"]))
        else:
            c.execute("DELETE FROM reconcile_decisions WHERE pair_key=?", (ref,))
        work.record_event(c, wp_id, "reconcile_revoke", actor, {"kind": kind, "ref": str(ref), "row": dict(row), "note": note})
    _write(ctx["state"], write)


# --- where a line stands on its statement page --------------------------------------------------------------------------


def place(layer: Any, doc_type: str, lines: list[dict[str, Any]], line_id: str) -> tuple[int | None, list[float] | None]:
    """The page and the box (0-1 fractions of the page: x0, y0, x1, y1) of one statement line in the statement's word
    layer. 138 (Q-line-locator reuse): the statement's lines are located together, in document order, by the review
    page's row locator (`grounding.locate_rows`: the line's amounts, with either sign, and dates on one text line), so
    identical lines land on consecutive text lines; only a sure place counts, (None, None) otherwise. On the store's 233
    lines it placed every one; on 3 it chose the booking line with its running balance, where the pairing page's own
    search of 132 had chosen a detail line printing the same amount."""
    return _placed(layer, doc_type, lines)[[ln["id"] for ln in lines].index(line_id)]


# 144: the places of a statement's lines, kept for the next line of the same statement (the row locator took about half
# a second for a ten-line statement); the key is the layer's content id and the lines' content
_places: OrderedDict[tuple[str, str, str, str], list[tuple[int | None, list[float] | None]]] = OrderedDict()
_places_lock = threading.Lock()
_PLACES_MAX = 64


def _placed(layer: Any, doc_type: str, lines: list[dict[str, Any]]) -> list[tuple[int | None, list[float] | None]]:
    plain = [{k: v for k, v in ln.items() if k != "id"} for ln in lines]
    key = (str(store.active_path()), layer.layer_id, doc_type,
           hashlib.sha256(json.dumps(plain, sort_keys=True, default=str).encode("utf-8")).hexdigest())
    with _places_lock:
        if key in _places:
            _places.move_to_end(key)
            return _places[key]
    kinds = dict(typepack.get(doc_type).list_fields.get("transactions", {}))
    rows = grounding.locate_rows(layer, plain, kinds)
    out = [(r.get("page"), r.get("bbox")) if r["status"] == "located" else (None, None) for r in rows]
    with _places_lock:
        _places[key] = out
        while len(_places) > _PLACES_MAX:
            _places.popitem(last=False)
    return out


LINE_FACTS = ("booking_date", "value_date", "direction", "amount", "original_amount", "original_currency", "counterparty_name",
              "counterparty_account", "memo", "description", "running_balance", *LINE_DETAILS)


def _statement_view(statement: dict[str, Any], institution: str | None) -> dict[str, Any]:
    """144: the statement as read, for the documents' statement pane: its heading facts and every line in its order."""
    return {"file": reconcile.file_names([statement["id"]]).get(statement["id"]), "institution": institution,
            "account": reconcile.statement_account(statement),
            **{k: statement.get(k) for k in ("currency", "period_start", "period_end", "opening_balance", "closing_balance")},
            "verified": bool(statement.get("verified")),
            "lines": [{"id": ln["id"], **{k: ln.get(k) for k in LINE_FACTS}} for ln in statement["lines"]]}


def _scope_statement(wp_id: str, line_id: str) -> dict[str, Any]:
    """The statement of a line in the scope (KeyError: no such line; `PackageError`: out of the scope). 144: without the
    proposals (`_context`), which a document view does not need (it took most of the time)."""
    _package(wp_id)
    snap, _sc = scoped_snapshot(wp_id)
    statement = next((st for st in snap["statements"] if any(ln["id"] == line_id for ln in st["lines"])), None)
    if statement is None:
        raise KeyError(line_id)
    if statement["id"] not in set(snap["scope_statements"]):
        raise PackageError("the line is not in the package's scope")
    return statement


def locate(wp_id: str, line_id: str) -> dict[str, Any]:
    """Where a line of the scope stands: its statement as read (`statement`), the page image to show (`image`: `item`,
    the statement's own document; `original`, the bank's PDF behind a statement read by code; None), and the line's
    page and box on it (None when there is no word layer or the line's amount is not printed on it). 144: a statement
    read by code has no page of its own (its item is the reader's statement file); `original` says whether the bank's
    PDF was found (`jav/statement_original.py`)."""
    from jav import statement_original

    statement = _scope_statement(wp_id, line_id)
    coded = statement["doc_type"] == statement_original.DOC_TYPE
    source = statement_original.source_of(statement["item_id"]) if coded and statement.get("item_id") else None
    out: dict[str, Any] = {"line_id": line_id, "statement_id": statement["id"],
                           "open": _open_refs([statement]).get(statement["id"]), "image": None, "pages": None,
                           "page": None, "box": None, "original": None,
                           "statement": _statement_view(statement, (source or {}).get("institution"))}
    if coded:
        original = statement_original.find(statement["item_id"]) if statement.get("item_id") else None
        if original is None:
            return out
        out["original"] = {"file": original.file, "state": original.state}
        if original.state != statement_original.FOUND:
            return out
        layer = statement_original.layer(original)
        out["image"], out["pages"] = "original", (len(layer.pages) if layer else statement_original.page_count(original))
    else:
        if out["open"] is None:
            return out
        out["image"], out["pages"] = "item", out["open"].get("pages")
        layer = corrections.layer_for(corrections.datapoints_row(statement["work_run"], statement["item_id"]))
    if layer is not None:
        out["page"], out["box"] = place(layer, statement["doc_type"], statement["lines"], line_id)
    return out


def original_page(wp_id: str, line_id: str, page: int, *, dpi: int) -> bytes:
    """144: a page of the bank's PDF behind the statement of a line in the scope, read by code (KeyError: none found)."""
    from jav import statement_original

    statement = _scope_statement(wp_id, line_id)
    if statement["doc_type"] != statement_original.DOC_TYPE or not statement.get("item_id"):
        raise KeyError(line_id)
    original = statement_original.find(statement["item_id"])
    if original.state != statement_original.FOUND:
        raise KeyError(original.file or line_id)
    return statement_original.page(original, page, dpi=dpi)


def refresh(wp_id: str) -> dict[str, Any]:
    """Recomputes with the missing MNB rates fetched (a processing step: only dates and currency codes leave)."""
    snap, _sc = scoped_snapshot(wp_id, fetch_rates=True)
    return {"rates": sum(len(days) for days in snap["fx_rates"].values())}


# --- the package in the lists ------------------------------------------------------------------------------------------


def package_view(wp_id: str) -> dict[str, Any]:
    """The package header's data (`work_views.workpackage_view` for this kind): the scope, the counts, the blockers as
    the readiness, and the next step."""
    ws = workspace(wp_id)
    blockers = [{"code": b["code"], "message": b["file"] or b["doc_id"][:12]} for b in ws["blockers"]]
    warnings = [{"code": w["code"], "message": w["file"] or w["doc_id"][:12]} for w in ws["warnings"]]
    return {"scope": ws["scope"], "counts": ws["counts"], "coverage": ws["coverage"], "approval": ws["approval"],
            "readiness": {"workpackage_id": wp_id, "ready": bool(ws["lines"]), "blockers": blockers, "warnings": warnings,
                          "counts": {"items": 0, "lines": len(ws["lines"]), "invoices": len(ws["invoices"])}},
            "next": next_step(ws)}


def next_step(ws: dict[str, Any]) -> dict[str, Any]:
    """The package's next step for its kind (the shape of `work_views.next_step`; the UI translates the code)."""
    def step(code: str, label: str, stage: str, **params: Any) -> dict[str, Any]:
        return {"code": code, "label": label, "stage": stage, "params": params}

    if active := (ws.get("approval") or {}).get("active"):  # 145
        return step("reconcile_approved", f"Approved: version {active['version']}", "result", version=active["version"])
    if not ws["lines"]:
        return step("reconcile_empty", "No statement line in the scope", "process")
    if ws["counts"]["open_lines"]:
        return step("reconcile_pair", f"Pairing: {ws['counts']['open_lines']} open lines", "review", n=ws["counts"]["open_lines"])
    return step("reconcile_result", "Reconciliation result", "result")


def _delete_guard(c, wp_id: str) -> None:
    """A reconciliation package with decisions made in it, or (145) an approved version, can only be hidden (they refer
    to it)."""
    for table in ("reconcile_allocations", "reconcile_line_marks", "reconcile_decisions", "reconcile_versions"):
        if c.execute(f"SELECT 1 FROM {table} WHERE workpackage_id=? LIMIT 1", (wp_id,)).fetchone() is not None:
            raise work.NotReady("a reconciliation package with decisions can only be archived",
                                [{"code": "has_decisions", "message": "The package has decisions: it can only be hidden."}])
    c.execute("DELETE FROM reconcile_scopes WHERE workpackage_id=?", (wp_id,))


work.register_delete_guard(_delete_guard)
