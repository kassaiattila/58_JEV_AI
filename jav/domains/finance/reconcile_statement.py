"""145 (backlog F-reconciliation E3b; DECISIONS 131, 132, 133, 145): a reconciliation package's result - its statement,
its approval as an unchangeable version that locks its lines, and its download.

- **The statement** (`build`) is computed in code from the package's workspace (`jav/domains/finance/reconcile_package.py`): every own
  invoice of the page with its result - paid, partly paid, settled by a credit note, a proposal still to decide, no
  payment found in the covered period, not covered by statements - and the lines that paid it; every statement line of
  the scope with its result - paired, partly paired, needs no invoice with its reason, left out by the code with its
  reason, open - and the invoices it paid; another party's invoice only when a line of the scope paid it, named with its
  party (133); and the warnings: a statement whose balances do not check out, and a month of a scope account without a
  statement (DECISIONS 132, 137: warnings, not blockers). Its fingerprint is the hash of its content.
- **What changed since the approval** (227, DECISIONS 224, the owner's choice "only a change of content warns"): the
  statement holds the reconciliation's rule fingerprint and engine version, and its fingerprint covers them (176), so
  a rule change alone changed every approved statement's fingerprint. `current` compares the content without them
  (`content_fingerprint`) and says apart whether the content changed or only the rules it was computed with.
- **The approval** (`approve`) records the statement the person saw (the request carries its fingerprint; a change
  since is a conflict) as the package's next version. It needs every source document from an approved run, or accepted
  by a person when it came from an evaluation on the command line (`accept_sources`, DECISIONS 132), and no decision
  left on a replaced statement (139). Open lines do not block it; the statement lists them (DECISIONS 131).
- **The lock** (enforced by `jav/domains/finance/reconcile_package.py`): the lines of an approved version take no new decision and lose
  none, in any package, and its package takes no decision and keeps its scope, until a person reopens the version with
  a reason (`reopen`); the version stays as an earlier one, and the next approval makes a new one (DECISIONS 132). An
  invoice is not locked: a payment from another account may still be recorded (an allocation never exceeds its amount).
- **The download** (`xlsx`, DECISIONS 145): an Excel workbook with two sheets, the invoices and the lines, each under a
  heading block naming the package, its party, period, accounts and version (or "draft"). The labels are data
  (`configs/reports.json` `reconcile_statement`; the column names of the fields from `configs/field_labels.json`), and
  a text is never written as a formula. Since 178 the statement is built as the output contract's data
  (`statement_data`, `configs/outputs.json`) and laid out by the built-in template (`jav/app/outputs/builtin.py`); an
  approved version's file is stored when it is approved and again when it is reopened, and its download returns the
  stored bytes. A version approved before 178 is made from its stored statement until `backfill_files`
  (`reconcile-versions-backfill`) records its file.
- 186 (plan G-full-move T2d): the versions and their files are the package's own versions in the shared version store
  (`jav/app/package_release.py`: `record_own`, `reopen_own`, `store_own_files`, `own_version`, `own_file`); this module
  decides what is approved, what blocks it, and how its file is made. 224: it approves and reopens through the shared
  steps (`approve_own`, `reopen_logged`).

Nothing here calls an AI model or the network. Layer: UI/CLI → **this** (application operation) →
`jav.domains.finance.reconcile_package` (the workspace, the decisions and the approval tables) and `jav.app.work` (the package and its log).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal
from typing import Any, Iterable

from jav.app import naming, package_release, work
from jav.core import activity_kinds, cfg, decisions, identity, store, values
from jav.domains.finance import reconcile_package as rp
from jav.app.outputs import builtin, contract, templates
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now

# 175 (plan 170 E4): the actions this module records in the package log (`jav/core/activity_kinds.py`)
activity_kinds.register_events("package", ("reconcile_approve", "reconcile_reopen", "reconcile_accept_sources"), __name__)

FORMAT = 1  # the statement's content layout; a new layout bumps it (a stored version keeps its own)

# 178 (plan 170 L4): an approved version's download as it was made - when approved, and again when reopened (its heading
# then names it an earlier version) - so a later change of a label, the layout or a template never changes it; 186: in
# the shared version store's files (`package_release.store_own_files`, the states approved and earlier)
INVOICE_RESULTS = ("paid", "partly_paid", "credited", "undecided", "no_payment_found", "not_covered")
LINE_RESULTS = ("paired", "partly_paired", "needs_no_invoice", "left_out", "open")
# the engine's invoice state (jav/domains/finance/reconcile.py STATUSES) -> the result, when no allocation decides it
_INVOICE_RESULT = {"confirmed": "paid", "credited": "credited", "partly_paid": "partly_paid", "proposed": "undecided",
                   "amount_only": "undecided", "amount_differs": "undecided", "rate_missing": "undecided",
                   "no_payment_found": "no_payment_found", "partly_covered": "not_covered", "not_covered": "not_covered"}
_LINE_RESULT = {"allocated": "paired", "partly_allocated": "partly_paired", "marked": "needs_no_invoice",
                "excluded": "left_out", "proposed": "open", "amount_only": "open", "open": "open"}
_INVOICE_FACTS = ("number", "supplier_name", "supplier_tax_id", "issue_date", "fulfillment_date", "due_date", "amount",
                  "currency", "payment_method", "file")
_LINE_FACTS = ("account", "statement_type", "currency", "booking_date", "value_date", "direction", "amount",
               "original_amount", "original_currency", "counterparty_name", "counterparty_account", "memo", "description",
               "bank_reference", "card_number", "purchase_date", "file", "statement_verified")


def fingerprint(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


# 227: what a statement was computed with, not what it says
RULE_KEYS = ("engine_version", "config_hash")


def content_fingerprint(content: dict[str, Any]) -> str:
    """The fingerprint of a statement's content without the rules it was computed with (`RULE_KEYS`)."""
    return fingerprint({k: v for k, v in content.items() if k not in RULE_KEYS})


def since_approval(wp_id: str, content: dict[str, Any], approval: dict[str, Any]) -> dict[str, bool] | None:
    """227: what changed since the approved version, measured on the statement as it stands now (`content`): its
    content (`content_changed`, a warning) or only its rules (`rules_changed`: the rule file or the engine's version,
    a note). None while nothing is approved."""
    if not (active := approval.get("active")):
        return None
    approved = approved_version(wp_id, active["version"])["statement"]
    return {"content_changed": content_fingerprint(approved) != content_fingerprint(content),
            "rules_changed": any(approved.get(k) != content.get(k) for k in RULE_KEYS)}


# --- the statement ---------------------------------------------------------------------------------------------------------


def _invoice_result(row: dict[str, Any]) -> str:
    amount, allocated = values.stored_decimal(row.get("amount")), values.stored_decimal(row.get("allocated")) or Decimal(0)
    if row.get("state") == "credited":
        return "credited"
    if row.get("state") == "confirmed" or (amount is not None and allocated >= amount > 0):
        return "paid"
    if allocated > 0:
        return "partly_paid"
    return _INVOICE_RESULT.get(str(row.get("state")), "not_covered")


def build(ws: dict[str, Any], name: str) -> dict[str, Any]:
    """The statement of a package's workspace (`reconcile_package.workspace`); `name` is the package's name."""
    lines = {ln["id"]: ln for ln in ws["lines"]}
    rows = {r["id"]: r for r in ws["invoices"]}
    timing = (ws.get("overview") or {}).get("invoices") or {}
    paid_by_scope = {a["invoice_id"] for ln in ws["lines"] for a in ln["allocations"]}
    invoices = []
    for r in ws["invoices"]:
        if not r["own"] and r["id"] not in paid_by_scope:
            continue  # 133: another party's invoice only when a line of the scope paid it
        facts = timing.get(r["id"]) or {}
        paid_by = []
        for a in r["allocations"]:
            ln = lines.get(a["line_id"])
            paid_by.append({"line_id": a["line_id"], "line_amount": a["line_amount"], "invoice_amount": a["invoice_amount"],
                            "booking_date": ln.get("booking_date") if ln else None, "account": ln.get("account") if ln else None,
                            "in_scope": ln is not None})
        invoices.append({"id": r["id"], **{k: r.get(k) for k in _INVOICE_FACTS}, "result": _invoice_result(r),
                         "engine_state": r.get("state"), "allocated": r.get("allocated"), "rest": r.get("rest"),
                         "paid_by": paid_by, "paid_on": facts.get("paid_on"), "days_from_due": facts.get("days_from_due"),
                         "overdue_days": facts.get("overdue_days"), "double_payment": bool(facts.get("double_payment")),
                         "credited_by": (r.get("credited_by") or {}).get("number"),
                         "other_party": None if r["own"] else (r.get("party") or {}).get("name"), "source": r.get("source")})
    out_lines = []
    for ln in ws["lines"]:
        mark = ln.get("mark") or {}
        out_lines.append({"id": ln["id"], **{k: ln.get(k) for k in _LINE_FACTS}, "result": _LINE_RESULT.get(ln["state"], "open"),
                          "engine_state": ln["state"], "reason": mark.get("category") or ln.get("excluded_reason"),
                          "note": mark.get("note"), "allocated": ln.get("allocated"), "rest": ln.get("rest"),
                          "pays": [{"invoice_id": a["invoice_id"], "number": (rows.get(a["invoice_id"]) or {}).get("number"),
                                    "supplier_name": (rows.get(a["invoice_id"]) or {}).get("supplier_name"),
                                    "line_amount": a["line_amount"], "invoice_amount": a["invoice_amount"]}
                                   for a in ln["allocations"]]})
    out_lines.sort(key=lambda ln: (ln["account"] or "", str(ln["booking_date"] or "")))  # per account, by day (stable)
    warnings = [{"code": w["code"], "doc_id": w["doc_id"], "file": w["file"]} for w in ws["warnings"]]
    warnings += [{"code": "month_without_statement", "account": c["account"], "month": c["month"]}
                 for c in ws["coverage"] if not c["statements"]]
    sc = ws["scope"]
    out = {"format": FORMAT, "package": {"id": ws["workpackage_id"], "name": name},
           "party": (sc.get("party") or {}).get("name"), "period": [sc["period_start"], sc["period_end"]],
           "accounts": list(sc["accounts"]), "engine_version": ws.get("engine_version"), "config_hash": ws.get("config_hash"),
           "invoices": invoices, "lines": out_lines, "warnings": warnings,
           "counts": {"invoices": dict(sorted(Counter(i["result"] for i in invoices).items())),
                      "lines": dict(sorted(Counter(ln["result"] for ln in out_lines).items())),
                      "open_lines": ws["counts"]["open_lines"]}}
    # 169: what a person left out of the package, recorded with the version (only when there is any, so the
    # fingerprint of a package without one stays as it was)
    if left := ws.get("left_out"):
        out["left_out"] = [{k: r.get(k) for k in ("id", "kind", "file", "reason", "actor", "left_out_at")} for r in left]
    return out


@store.one_connection
def current(wp_id: str) -> dict[str, Any]:
    """The package's statement as it stands now, its fingerprint, what blocks its approval, its warnings, the
    package's approval (`reconcile_package.approval`) and what changed since it (227, `since_approval`)."""
    ws = rp.workspace(wp_id)
    content = build(ws, work.get(wp_id)["name"])
    return {"statement": content, "fingerprint": fingerprint(content), "blockers": ws["blockers"],
            "warnings": content["warnings"], "approval": ws["approval"],
            "since_approval": since_approval(wp_id, content, ws["approval"])}


def approved_version(wp_id: str, n: int, c: Any = None) -> dict[str, Any]:
    """An approved version of the package's statement as it was approved (KeyError: no such version)."""
    rp.scope(wp_id)
    found = package_release.own_version(wp_id, n, c)
    return {"statement": found.pop("content"), **found}


# --- the approval -------------------------------------------------------------------------------------------------------


def approve(wp_id: str, *, fingerprint: str, actor: identity.Who) -> dict[str, Any]:
    """Approves the statement the person saw (its `fingerprint`) as the package's next version and locks its lines.
    `work.NotReady` with the blockers; `work.RevisionConflict` when the statement or a decision changed meanwhile."""
    state = rp._decision_state()  # read before the statement: a decision recorded after it is a conflict
    view = current(wp_id)
    if active := view["approval"]["active"]:
        raise explained(rp.PackageError, "version {{version}} is approved; reopen it before approving again",
                        version=active["version"])
    if view["blockers"]:
        raise explained(work.NotReady, "the statement cannot be approved yet",
                        [{"code": b["code"], "message": b["file"] or b["doc_id"][:12]} for b in view["blockers"]])
    if fingerprint != view["fingerprint"]:
        raise explained(work.RevisionConflict, "the statement changed since it was shown; reload it and check it again")
    content, line_ids = view["statement"], [ln["id"] for ln in view["statement"]["lines"]]

    def write(c) -> int:
        # 178: the version's file as approved, made from the statement as stored (the download read it so before)
        return package_release.approve_own(
            c, wp_id, event="reconcile", content=content, fingerprint=fingerprint, locks=line_ids, actor=actor,
            files=lambda c, n: _store_file(c, wp_id, approved_version(wp_id, n, c), chosen=True),
            details={"lines": len(line_ids)}, step=(step := _approving_step(wp_id, c)),
            basis=_basis(wp_id, step, c))  # D0-d: what the pairing builds on, as approved
    n = rp._write(state, write)
    return {k: v for k, v in approved_version(wp_id, n).items() if k != "statement"}


def reopen(wp_id: str, *, note: str, actor: identity.Who) -> dict[str, Any]:
    """Reopens the approved version with a reason: its lock goes, it stays as an earlier version."""
    note = (note or "").strip()
    if not note:
        raise explained(rp.PackageError, "reopening needs a reason")
    rp.scope(wp_id)
    def earlier(c, n: int) -> None:
        # 178: the version's file as an earlier one (its heading names who reopened it, when and why)
        made = package_release.own_file(wp_id, n, package_release.APPROVED, c)
        _store_file(c, wp_id, approved_version(wp_id, n, c),
                    made={k: made[k] for k in ("template", "template_version")} if made else None)

    with store.connect() as c:
        store.begin_immediate(c)
        if package_release.reopen_logged(c, wp_id, event="reconcile", note=note, actor=actor, files=earlier,
                                         step=_approving_step(wp_id, c)) is None:
            raise explained(rp.PackageError, "the package has no approved statement to reopen")
    return rp.approval(wp_id)


def _basis(wp_id: str, step: str | None, c: Any) -> dict[str, int] | None:
    """D0-d: the result versions of the steps the pairing builds on (None: a package that is no case's)."""
    from jav.app import process_runtime  # lazy: the process runtime builds on the packages and their versions

    return process_runtime.basis_of(wp_id, step, c) if step else None


def _approving_step(wp_id: str, c: Any) -> str | None:
    """D0-b: the case's pairing step, whose version and task the statement's approval is (the pairing keeps its state
    for the whole case, so a pack has one); None for a package that is no case's."""
    from jav.app import process_runtime  # lazy: the process runtime builds on the packages and their versions

    return process_runtime.step_using(wp_id, "pairing", c)


def accept_sources(wp_id: str, doc_ids: Iterable[str], *, actor: identity.Who, expected_state: int | None = None) -> int:
    """Accepts the current results of source documents from an evaluation on the command line as sources (DECISIONS
    132): each must be such a blocker of the package; who and when is recorded. Returns how many were accepted. 187: a
    newly accepted result goes into the decision journal (one accepted before, in any package, stays as it was)."""
    ids = list(dict.fromkeys(doc_ids))
    if not ids:
        raise explained(rp.PackageError, "no document to accept")
    ws = rp.kept_workspace(wp_id)  # 174 (review 160 M-15): read only
    blocking = {b["doc_id"] for b in ws["blockers"] if b["code"] == "source_no_run"}
    if unknown := [d for d in ids if d not in blocking]:
        raise explained(rp.PackageError, "not a command-line source of this package: {{items}}",
                        items=", ".join((d[:12] for d in unknown)))
    snap, _sc = rp.scoped_snapshot(wp_id)
    results = {d["id"]: str(d.get("flow_run_id")) for d in [*snap["invoices"], *snap["statements"]]}
    with store.connect() as c:
        store.begin_immediate(c)
        decisions.check_package(c, wp_id, rp.DECISION_KINDS, expected_state)
        now = _now()
        for d in ids:
            if c.execute("INSERT INTO reconcile_source_acceptances(doc_id, flow_run_id, workpackage_id, actor,"
                         " actor_id, accepted_at) VALUES (?,?,?,?,?,?) ON CONFLICT DO NOTHING", (d, results[d], wp_id, identity.name_of(actor), identity.id_of(actor), now)).rowcount:
                decisions.record(c, rp.SOURCE_KIND, f"{d}#{results[d]}", "accept", actor=actor, workpackage_id=wp_id, at=now)
        work.record_event(c, wp_id, "reconcile_accept_sources", actor, {"documents": ids})
    return len(ids)


# --- the download -------------------------------------------------------------------------------------------------------


def _labels() -> dict[str, Any]:
    return cfg.load("reports")["reconcile_statement"]


def _yes_no(value: Any, lab: dict[str, Any]) -> str | None:
    return None if value is None else lab["yes"] if value else lab["no"]


def _join(parts: Iterable[Any]) -> str | None:
    text = "; ".join(str(p) for p in parts if p not in (None, ""))
    return text or None


def _invoice_table(st: dict[str, Any], lab: dict[str, Any]) -> tuple[list[str], list[list[Any]], list[str | None]]:
    fields, col = cfg.load("field_labels")["fields"], lab["columns"]
    head = [fields["invoice_number"], fields["supplier_name"], fields["supplier_tax_id"], fields["issue_date"],
            fields["fulfillment_date"], fields["due_date"], col["amount"], fields["currency"], fields["payment_method"],
            col["result"], col["allocated"], col["rest"], col["paid_on"], col["days_from_due"], col["overdue_days"],
            col["paid_by"], col["other_party"], col["source"], col["file"]]
    kinds = [None] * 6 + ["money", None, None, None, "money", "money", None, "number", "number", None, None, None, None]
    rows = [[i["number"], i["supplier_name"], i["supplier_tax_id"], i["issue_date"], i["fulfillment_date"], i["due_date"],
             i["amount"], i["currency"], i["payment_method"], lab["invoice_results"].get(i["result"], i["result"]),
             i["allocated"], i["rest"], i["paid_on"], i["days_from_due"], i["overdue_days"],
             _join(f"{p['booking_date'] or ''} {p['line_amount']}".strip() for p in i["paid_by"]), i["other_party"],
             lab["sources"].get(i["source"], i["source"]), i["file"]] for i in st["invoices"]]
    return head, rows, kinds


def _line_table(st: dict[str, Any], lab: dict[str, Any]) -> tuple[list[str], list[list[Any]], list[str | None]]:
    names, col = cfg.load("field_labels"), lab["columns"]
    cols = names["columns"]
    head = [cols["booking_date"], cols["value_date"], col["account"], cols["direction"], cols["amount"],
            names["fields"]["currency"], cols["original_amount"], cols["original_currency"], cols["counterparty_name"],
            cols["counterparty_account"], cols["memo"], cols["description"], col["result"], col["reason"], col["note"],
            col["allocated"], col["rest"], col["pays"], col["statement_file"], col["statement_verified"]]
    kinds = [None, None, None, None, "money", None, "money"] + [None] * 8 + ["money", "money", None, None, None]
    rows = [[ln["booking_date"], ln["value_date"], ln["account"], cols.get(f"direction={ln['direction']}", ln["direction"]),
             ln["amount"], ln["currency"], ln["original_amount"], ln["original_currency"], ln["counterparty_name"],
             ln["counterparty_account"], ln["memo"], ln["description"], lab["line_results"].get(ln["result"], ln["result"]),
             lab["reasons"].get(ln["reason"], ln["reason"]) if ln["reason"] else None, ln["note"], ln["allocated"], ln["rest"],
             _join(f"{p['number'] or ''} {p['supplier_name'] or ''} {p['line_amount']}".strip() for p in ln["pays"]),
             ln["file"], _yes_no(ln["statement_verified"], lab)] for ln in st["lines"]]
    return head, rows, kinds


def _values(st: dict[str, Any], state: str, lab: dict[str, Any]) -> tuple[contract.Value, ...]:
    h = lab["heading"]
    return (contract.Value("package", h["package"], st["package"]["name"]), contract.Value("party", h["party"], st["party"] or ""),
            contract.Value("period", h["period"], " – ".join(st["period"])),
            contract.Value("accounts", h["accounts"], ", ".join(st["accounts"])), contract.Value("state", h["state"], state))


# 178 (plan 170 L4): the column keys of the statement's tables (`configs/outputs.json` `reconcile_statement`), in order
def sample_heads() -> dict[str, dict[str, str]]:
    """185 (plan G-full-move T1e): the built-in headers of the statement's tables, for a template's marker list and
    preview (`jav/app/outputs/samples.py`, through `parts.OutputLabels`; until then read there by name)."""
    lab = _labels()
    empty: dict[str, Any] = {"invoices": [], "lines": []}
    return {"invoices": dict(zip(INVOICE_COLUMNS, _invoice_table(empty, lab)[0])),
            "lines": dict(zip(LINE_COLUMNS, _line_table(empty, lab)[0]))}


def sample_values() -> dict[str, str]:
    """185: the labels of the statement's values."""
    h = _labels()["heading"]
    return {k: h[k] for k in ("package", "party", "period", "accounts", "state")}


INVOICE_COLUMNS = ("number", "supplier_name", "supplier_tax_id", "issue_date", "fulfillment_date", "due_date", "amount", "currency",
                   "payment_method", "result", "allocated", "rest", "paid_on", "days_from_due", "overdue_days", "paid_by",
                   "other_party", "source", "file")
LINE_COLUMNS = ("booking_date", "value_date", "account", "direction", "amount", "currency", "original_amount", "original_currency",
                "counterparty_name", "counterparty_account", "memo", "description", "result", "reason", "note", "allocated", "rest",
                "pays", "statement_file", "statement_verified")


def statement_data(st: dict[str, Any], state: str) -> contract.OutputData:
    """178 (plan 170 L4): the statement's data as the output contract describes it (`reconcile_statement`): the heading's
    values and the two tables, the invoices and the lines."""
    lab = _labels()
    tables = []
    for key, title, columns, (head, rows, kinds) in (("invoices", lab["sheets"]["invoices"], INVOICE_COLUMNS, _invoice_table(st, lab)),
                                                     ("lines", lab["sheets"]["lines"], LINE_COLUMNS, _line_table(st, lab))):
        tables.append(contract.Table(key=key, title=title, columns=columns, head=tuple(head), kinds=tuple(kinds), rows=rows))
    return contract.OutputData("reconcile_statement", _values(st, state, lab), tuple(tables))


def _shown(stamp: str | None) -> str:
    """A stored UTC time as the heading shows it (to the minute)."""
    return (stamp or "")[:16].replace("T", " ")


def _named(st: dict[str, Any], state: str, suffix: str, lab: dict[str, Any]) -> tuple[contract.OutputData, str]:
    slug = naming.safe_part(st["package"]["name"], limit=40) or st["package"]["id"]  # accents folded (078)
    return statement_data(st, state), f"{lab['file']['prefix']}-{slug}-{suffix}.xlsx"


def _version_state(v: dict[str, Any]) -> str:
    """An approved version's file state: `approved` while it holds, `earlier` once reopened."""
    return "approved" if v["reopened_at"] is None else "earlier"


def _version_data(v: dict[str, Any]) -> tuple[contract.OutputData, str]:
    """An approved version's data from its stored statement (its heading names its state) and its file name."""
    lab, n = _labels(), v["version"]
    if v["reopened_at"] is None:
        state = lab["heading"]["approved"].format(n=n, by=v["approved_by"], at=_shown(v["approved_at"]))
    else:
        state = lab["heading"]["earlier"].format(n=n, by=v["reopened_by"], at=_shown(v["reopened_at"]), note=v["reopen_note"] or "")
    return _named(v["statement"], state, lab["file"]["version"].format(n=n), lab)


def _version_file(v: dict[str, Any]) -> tuple[bytes, str]:
    """A version approved before 178 without a stored file: made now with the built-in template, as before."""
    data, name = _version_data(v)
    return builtin.render(data), name


def _store_file(c: Any, wp_id: str, v: dict[str, Any], *, chosen: bool = False, made: dict[str, str] | None = None,
                backfilled_at: str | None = None) -> None:
    """178: records an approved version's file in its current state, in the caller's transaction: with the package's
    chosen template (`chosen`), with a recorded one (`made`: a reopened version keeps its approval's), or the built-in.
    186: in the shared version store (`package_release.store_own_files`)."""
    data, name = _version_data(v)
    if made is not None:
        content = templates.render_with(data, made["template"], made["template_version"])
    elif chosen:
        content, made = templates.render(data, wp_id, c)
    else:
        content, made = builtin.render(data), {"template": templates.BUILTIN,
                                               "template_version": templates.builtin_version("reconcile_statement")}
    rows = len(v["statement"].get("invoices") or []) + len(v["statement"].get("lines") or [])
    package_release.store_own_files(c, wp_id, v["version"], _version_state(v), [(name, rows, content, made)],
                                    backfilled_at=backfilled_at)


def xlsx(wp_id: str, *, version: int | None = None) -> tuple[bytes, str]:
    """The statement as an Excel workbook (DECISIONS 145: invoices and lines on two sheets) and its file name: the
    current draft, or an approved version's file as it was stored when approved or reopened (178). A version approved
    before 178 is made from its stored statement until `backfill_files` records its file."""
    lab = _labels()
    if version is None:  # 178: the draft with the package's chosen template
        data, name = _named(current(wp_id)["statement"], lab["heading"]["draft"], lab["file"]["draft"], lab)
        return templates.render(data, wp_id)[0], name
    v = approved_version(wp_id, version)
    stored = package_release.own_file(wp_id, version, _version_state(v))
    return (stored["content"], stored["name"]) if stored else _version_file(v)


def backfill_files(*, dry_run: bool = False) -> list[dict[str, Any]]:
    """178: every approved version without the file of its current state (approved or reopened before 178) gets it,
    made now from its stored statement as the download made it, marked as recorded afterwards (`backfilled_at`).
    Idempotent."""
    out = []
    for missing in package_release.own_missing_files():
        wp_id, n = missing["workpackage_id"], missing["version"]
        if not rp.holds_reconciliation(work.get(wp_id)):  # 186: another logic pack's own version (231: or case's)
            continue
        with store.connect() as c:
            store.begin_immediate(c)
            v = approved_version(wp_id, n, c)
            state = _version_state(v)
            if package_release.own_file(wp_id, n, state, c) is not None:
                continue
            if not dry_run:
                _store_file(c, wp_id, v, backfilled_at=_now())
        out.append({"workpackage_id": wp_id, "version": n, "state": state})
    return out
