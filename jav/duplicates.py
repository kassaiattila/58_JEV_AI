"""126 (backlog F-duplicate): the same invoice twice in the store, found from the extracted and corrected data.

When the same invoice reaches the store twice (two different files, two packages, or an email and a folder), it goes on
as two separate documents and counts twice in a total. This module compares the invoice-like documents by code, with no
AI call, and names three kinds of suspicion (the owner's decisions of 2026-10-07, DECISIONS 124 and 126):

- `copy`: the normalised invoice number and the supplier match, and so do the issue date, the gross total and the
  currency;
- `variant` (a modified version): the number and the supplier match, but one of the compared fields differs;
- `undecidable`: the number and the supplier match, but a compared field is missing on one of them.

The supplier is the same when the tax-number keys match (`fact_checks.tax_party_key`, so the domestic and the EU form of
a Hungarian number are one party); without a tax number on either side, by the significant words of the name
(`fact_checks.same_party`). An invoice number without a digit ("N/A") never matches. The families and the compared
fields are data (`configs/policy.json` `duplicates`); a pro forma invoice is its own family, so it is never a copy of a
final invoice.

Where it shows: the later processed document gets a `duplicate:<kind>:<the other document's id prefix>` to-do in a
worker run (`review_reasons`, like `party_history`: measurements and the command line do not depend on the store). A
person decides: copy, modified version or not the same (`decide`); the decision belongs to the pair, closes the pair's
to-dos on both documents, is part of the reviewed result (`corrections.review_version`), and the pair never comes up
again. Nothing is deleted or merged: a confirmed copy is marked in the lists and the export (`marks`), and counts once
in the totals (`jav/report_utility.py`). `scan` lists the pairs already in the store and, on request, opens the same
to-do on documents of runs not yet approved (the owner's decision of 2026-10-07, DECISIONS 126).

Reuse: the legacy `orchestrator/framework/payablesquality.py` (supplier + number grouping, "same" only when every other
field matches, the differing fields listed) and `mattersuggest.py` (a human confirms; a rejected pair does not come up
again) are the pattern; no legacy code is imported.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterable

from jav import cfg, fact_checks, store
from jav.runtime import calls

REASON = "duplicate"
PRODUCER = "duplicates"  # the producer of the to-dos opened by `scan`; the flow's own ones are the M2 step's
PREFIX = 16  # the other document's id prefix in the to-do (the length the flow identifiers use, `work.flow_run_id`)
KINDS = ("copy", "variant", "undecidable")
DECISIONS = ("copy", "variant", "different")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

store.register_schema("duplicates", """
CREATE TABLE IF NOT EXISTS duplicate_decisions (
    pair_key      TEXT PRIMARY KEY,   -- the two document ids in order, joined by '|': one decision per pair
    doc_id        TEXT NOT NULL,      -- the repeat: the document the to-do stood on
    other_doc_id  TEXT NOT NULL,      -- the earlier document it was compared with
    decision      TEXT NOT NULL,      -- copy | variant | different
    suggested     TEXT,               -- the code's kind when the person decided
    run_id        TEXT,               -- the run in which the person decided
    actor         TEXT NOT NULL,
    note          TEXT,
    decided_at    TEXT NOT NULL
);
""")


class DecisionError(ValueError):
    """A decision that cannot be recorded (unknown decision, the document compared with itself)."""


@lru_cache(maxsize=None)
def _conf() -> dict[str, Any]:
    return dict(cfg.load("policy")["duplicates"])


def config_hash() -> str:
    return cfg.config_hash("policy")


def family(doc_type: str | None) -> str | None:
    """The family of an invoice-like type; None for any other type."""
    return next((name for name, types in _conf()["families"].items() if doc_type in types), None)


def family_types() -> list[str]:
    return [t for types in _conf()["families"].values() for t in types]


def key_fields() -> list[str]:
    """The fields the comparison reads: the number, the supplier's two fields and the compared fields."""
    c = _conf()
    return [c["number_field"], c["supplier_tax_field"], c["supplier_name_field"], *c["compared_fields"]]


def number_key(value: Any) -> str | None:
    """The invoice number's comparable form: letters and digits only, upper case. None without a digit (a placeholder
    such as "N/A" is no number)."""
    if value in (None, ""):
        return None
    key = re.sub(r"[^0-9A-Za-z]", "", str(value)).upper()
    return key if any(ch.isdigit() for ch in key) else None


def same_supplier(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Whether two documents name the same supplier: by the tax-number key when both have one, else by the name."""
    c = _conf()
    tax_a = fact_checks.tax_party_key(a.get(c["supplier_tax_field"]))
    tax_b = fact_checks.tax_party_key(b.get(c["supplier_tax_field"]))
    if tax_a is not None and tax_b is not None:
        return tax_a == tax_b
    return fact_checks.same_party(a.get(c["supplier_name_field"]), b.get(c["supplier_name_field"]))


def _comparable(value: Any) -> Decimal | str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if _NUMBER.fullmatch(text):
        return Decimal(text)  # "100" and "100.00" are one amount
    return text.casefold() or None


def classify(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """(kind, differing fields, missing fields) of two documents whose number and supplier already match. A known
    difference outweighs a missing field: it is a variant."""
    differing: list[str] = []
    missing: list[str] = []
    for f in _conf()["compared_fields"]:
        x, y = _comparable(a.get(f)), _comparable(b.get(f))
        if x is None or y is None:
            missing.append(f)
        elif x != y:
            differing.append(f)
    kind = "variant" if differing else "undecidable" if missing else "copy"
    return kind, tuple(differing), tuple(missing)


@dataclass(frozen=True)
class Document:
    """An invoice-like document's effective values (machine value + correction) and where they come from."""

    doc_id: str
    doc_type: str
    fields: dict[str, Any]
    flow_run_id: str | None = None  # the flow run that produced the values (`datapoints.run_id`)
    run_id: str | None = None  # the work run of that flow run, if it ran in one
    item_id: str | None = None
    seq: int = 0  # the order of processing (the store's row order)


@dataclass(frozen=True)
class Match:
    other: Document
    kind: str
    differing: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def reason(self) -> str:
        return f"{REASON}:{self.kind}:{self.other.doc_id[:PREFIX]}"


def same_invoice(a_type: str | None, a: dict[str, Any], b_type: str | None, b: dict[str, Any]) -> bool:
    """Whether two documents are the same invoice by the key: the same family, number and supplier."""
    fam = family(a_type)
    number = number_key(a.get(_conf()["number_field"]))
    return (fam is not None and number is not None and family(b_type) == fam
            and number_key(b.get(_conf()["number_field"])) == number and same_supplier(a, b))


def matches(current: Document, others: Iterable[Document]) -> list[Match]:
    """The documents among `others` that are the same invoice as `current` by the key, with their kind, in the order
    they were processed. The document itself never counts."""
    out = []
    for other in others:
        if other.doc_id == current.doc_id or not same_invoice(current.doc_type, current.fields, other.doc_type, other.fields):
            continue
        kind, differing, missing = classify(current.fields, other.fields)
        out.append(Match(other, kind, differing, missing))
    return sorted(out, key=lambda m: m.other.seq)


def parse_reason(code: str) -> tuple[str, str] | None:
    """(kind, the other document's id prefix) of a duplicate to-do; None for any other to-do."""
    parts = code.split(":")
    if len(parts) == 3 and parts[0] == REASON and parts[1] in KINDS and parts[2]:
        return parts[1], parts[2]
    return None


def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


# --- the store --------------------------------------------------------------------------------------------------


def enabled() -> bool:
    """The store is read only inside a worker run, as in `party_history`."""
    ctx = calls.current()
    # 127: a budgeted measurement has a budget scope too, but it is not a worker run
    return ctx is not None and ctx.budget_scope is not None and not ctx.measurement


def _has_table(c, name: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def documents() -> list[Document]:
    """Every invoice-like document's effective values: its latest result (of any type; a document re-read as another
    type drops out), with the latest correction of the run item that produced it."""
    fields, types = key_fields(), family_types()
    extracts = ", ".join("json_extract(d.datapoints, '$.' || ?)" for _ in fields)
    with store.connect() as c:
        rows = c.execute(
            f"SELECT d.rowid AS seq, d.doc_id, d.doc_type, d.run_id AS flow_run_id, ri.run_id AS work_run, ri.item_id, {extracts}"
            " FROM datapoints d JOIN (SELECT doc_id, MAX(rowid) AS m FROM datapoints GROUP BY doc_id) l ON l.m = d.rowid"
            " LEFT JOIN run_items ri ON ri.flow_run_id = d.run_id AND ri.item_id = d.doc_id"
            f" WHERE d.doc_type IN ({','.join('?' * len(types))}) ORDER BY d.rowid",
            (*fields, *types)).fetchall()
        corrected: dict[tuple[str, str], dict[str, Any]] = {}
        if _has_table(c, "run_item_corrections"):
            for r in c.execute("SELECT c.run_id, c.item_id, c.fields FROM run_item_corrections c JOIN"
                               " (SELECT run_id, item_id, MAX(revision) AS m FROM run_item_corrections GROUP BY run_id, item_id) l"
                               " ON l.run_id = c.run_id AND l.item_id = c.item_id AND l.m = c.revision"):
                corrected[(r["run_id"], r["item_id"])] = json.loads(r["fields"])
    out = []
    for r in rows:
        values = {f: r[6 + i] for i, f in enumerate(fields)}
        fix = corrected.get((r["work_run"], r["item_id"])) or {}
        values.update({f: v for f, v in fix.items() if f in values})
        out.append(Document(r["doc_id"], r["doc_type"], values, r["flow_run_id"], r["work_run"], r["item_id"], int(r["seq"])))
    return out


def decisions_for(doc_ids: Iterable[str], c=None) -> list[dict[str, Any]]:
    """The decisions on the pairs that include any of the documents, in a fixed order."""
    ids = sorted(set(doc_ids))
    if not ids:
        return []
    if c is None:
        with store.connect() as own:
            return decisions_for(ids, own)
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), 400):  # two placeholders per id: below SQLite's parameter limit
        chunk = ids[start:start + 400]
        marks = ",".join("?" * len(chunk))
        for r in c.execute(f"SELECT * FROM duplicate_decisions WHERE doc_id IN ({marks}) OR other_doc_id IN ({marks})",
                           (*chunk, *chunk)):
            out[r["pair_key"]] = dict(r)
    return [out[k] for k in sorted(out)]


def review_reasons(doc_id: str | None, doc_type: str | None, fields: dict[str, Any]) -> list[str]:
    """The duplicate to-dos of the document being processed: against every earlier document in the store, in a worker
    run only; a pair a person has already decided adds nothing."""
    if not enabled() or not doc_id or family(doc_type) is None or number_key(fields.get(_conf()["number_field"])) is None:
        return []
    found = matches(Document(doc_id, doc_type or "", fields), documents())
    decided = {d["pair_key"] for d in decisions_for([doc_id])}
    return [m.reason for m in found if pair_key(doc_id, m.other.doc_id) not in decided]


def resolve_prefix(prefix: str) -> str | None:
    """The full id of the document a to-do names by its prefix (None if unknown or ambiguous)."""
    with store.connect() as c:
        rows = c.execute("SELECT doc_id FROM documents WHERE substr(doc_id, 1, ?) = ? LIMIT 2", (len(prefix), prefix)).fetchall()
    return rows[0]["doc_id"] if len(rows) == 1 else None


def _file_names(doc_ids: Iterable[str]) -> dict[str, str]:
    from pathlib import Path

    ids = sorted(set(doc_ids))
    if not ids:
        return {}
    with store.connect() as c:
        rows = c.execute(f"SELECT doc_id, source_path FROM documents WHERE doc_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    return {r["doc_id"]: Path(r["source_path"] or "").name for r in rows}


def decide(run_id: str, item_id: str, other_doc_id: str, *, decision: str, actor: str, note: str | None = None) -> dict[str, Any]:
    """A person's decision on a pair, made on a run's item: `copy`, `variant` (a modified version) or `different` (not
    the same invoice). One decision per pair; it may be changed until the run it was made in is approved. The pair's
    open to-dos close on both documents. Frozen on an approved run (`work.RevisionConflict`), checked again in the
    writing transaction, as the task decisions are."""
    from jav import work

    if decision not in DECISIONS:
        raise DecisionError(f"unknown duplicate decision: {decision}")
    if other_doc_id == item_id:
        raise DecisionError("a document is not a duplicate of itself")
    run = work.get_run(run_id)
    if run["approval"]:
        raise work.RevisionConflict(f"run {run_id} is approved; duplicate decisions are frozen")
    if not any(i["item_id"] == item_id and i.get("kind") != "email" for i in run["input"]["items"]):
        raise KeyError(item_id)
    docs = {d.doc_id: d for d in documents() if d.doc_id in (item_id, other_doc_id)}
    if other_doc_id not in _file_names([other_doc_id]):
        raise KeyError(other_doc_id)
    suggested = (classify(docs[item_id].fields, docs[other_doc_id].fields)[0]
                 if item_id in docs and other_doc_id in docs else None)
    key = pair_key(item_id, other_doc_id)
    with store.connect() as c:
        store.begin_immediate(c)
        row = c.execute("SELECT approval FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is not None and row["approval"]:
            raise work.RevisionConflict(f"run {run_id} is approved; duplicate decisions are frozen")
        before = c.execute("SELECT run_id FROM duplicate_decisions WHERE pair_key=?", (key,)).fetchone()
        if before is not None and before["run_id"] != run_id:
            owner = c.execute("SELECT approval FROM runs WHERE run_id=?", (before["run_id"],)).fetchone()
            if owner is not None and owner["approval"]:
                raise work.RevisionConflict("the pair was decided in an approved run; the decision is frozen")
        c.execute("INSERT INTO duplicate_decisions(pair_key, doc_id, other_doc_id, decision, suggested, run_id, actor, note, decided_at)"
                  # a changed decision keeps the pair's direction: the repeat stays the document the to-do stood on
                  " VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(pair_key) DO UPDATE SET decision=excluded.decision,"
                  " suggested=excluded.suggested, run_id=excluded.run_id, actor=excluded.actor, note=excluded.note,"
                  " decided_at=excluded.decided_at",
                  (key, item_id, other_doc_id, decision, suggested, run_id, actor, note, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    resolution = {"duplicate": decision, "pair": key}
    for subject, other in ((item_id, other_doc_id), (other_doc_id, item_id)):
        for r in store.review_open_reasons("document", subject):
            parsed = parse_reason(r["reason"])
            if parsed is not None and other.startswith(parsed[1]):
                work.resolve_reason(r["id"], actor=actor, resolution=resolution, note=note)
    return next(d for d in decisions_for([item_id]) if d["pair_key"] == key)


# --- views ------------------------------------------------------------------------------------------------------


def item_pairs(item_id: str, reasons: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The pairs to show on a document's review page: one per open duplicate to-do (this run's or an earlier one) and
    per decision on the document, with both documents' compared values side by side."""
    reasons = list(reasons)
    others: dict[str, dict[str, Any]] = {}
    for r in reasons:
        parsed = parse_reason(r["reason"])
        full = resolve_prefix(parsed[1]) if parsed else None
        if parsed and full:
            others.setdefault(full, {"reason_id": r["id"], "suggested": parsed[0]})
    decided = {d["other_doc_id"] if d["doc_id"] == item_id else d["doc_id"]: d for d in decisions_for([item_id])}
    for other in decided:
        others.setdefault(other, {"reason_id": None, "suggested": decided[other]["suggested"]})
    if not others:
        return []
    docs = {d.doc_id: d for d in documents() if d.doc_id == item_id or d.doc_id in others}
    names = _file_names([*others, item_id])
    runs = sorted({d.run_id for d in docs.values() if d.run_id})
    with store.connect() as c:
        packages = {r["run_id"]: r["workpackage_id"] for r in c.execute(
            f"SELECT run_id, workpackage_id FROM runs WHERE run_id IN ({','.join('?' * len(runs))})", runs)} if runs else {}
    out = []
    for other, base in others.items():
        mine, theirs = docs.get(item_id), docs.get(other)
        kind = classify(mine.fields, theirs.fields) if mine and theirs else (base["suggested"], (), ())
        rows = [{"field": f, "value": (mine.fields.get(f) if mine else None), "other_value": (theirs.fields.get(f) if theirs else None),
                 "differs": f in kind[1], "missing": f in kind[2]} for f in key_fields()]
        d = decided.get(other)
        out.append({"other_doc_id": other, "other_file": names.get(other), "other_run_id": theirs.run_id if theirs else None,
                    "other_item_id": theirs.item_id if theirs else None,
                    "other_workpackage_id": packages.get(theirs.run_id) if theirs and theirs.run_id else None, "kind": kind[0], "reason_id": base["reason_id"],
                    "fields": rows, "decision": d["decision"] if d else None, "decided_by": d["actor"] if d else None,
                    "decided_at": d["decided_at"] if d else None, "repeat": (d["doc_id"] == item_id) if d else True})
    return sorted(out, key=lambda p: (p["decision"] is not None, p["other_file"] or ""))


def marks(items: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    """The duplicate mark of each document (item id -> its open to-do reasons): a confirmed copy or modified version
    when a person decided so with this document as the repeat, else a suspicion from an open to-do; `different` lists
    the documents a person found not to be the same. A document without any of these has no entry."""
    decisions = decisions_for(items)
    names = _file_names([d["other_doc_id"] for d in decisions] + [d["doc_id"] for d in decisions])
    out: dict[str, dict[str, Any]] = {}
    for item_id, reasons in items.items():
        mine = [d for d in decisions if item_id in (d["doc_id"], d["other_doc_id"])]
        different = sorted(d["other_doc_id"] if d["doc_id"] == item_id else d["doc_id"] for d in mine if d["decision"] == "different")
        confirmed = [d for d in mine if d["doc_id"] == item_id and d["decision"] in ("copy", "variant")]
        mark: dict[str, Any] | None = None
        if confirmed:
            d = confirmed[0]
            mark = {"status": d["decision"], "other_doc_id": d["other_doc_id"], "other_file": names.get(d["other_doc_id"])}
        else:
            for code in reasons:
                parsed = parse_reason(code)
                full = resolve_prefix(parsed[1]) if parsed else None
                if parsed and full:
                    mark = {"status": "suspected", "kind": parsed[0], "other_doc_id": full,
                            "other_file": _file_names([full]).get(full)}
                    break
        if mark is not None or different:
            out[item_id] = {**(mark or {}), "different": different}
    return out


# --- the documents already in the store --------------------------------------------------------------------------


def _groups(docs: list[Document]) -> list[list[Document]]:
    by_number: dict[tuple[str, str], list[Document]] = defaultdict(list)
    for d in docs:
        number = number_key(d.fields.get(_conf()["number_field"]))
        fam = family(d.doc_type)
        if number and fam:
            by_number[(fam, number)].append(d)
    groups = []
    for candidates in by_number.values():
        parent = {d.doc_id: d.doc_id for d in candidates}

        def root(x: str) -> str:
            while parent[x] != x:
                x = parent[x]
            return x

        for i, a in enumerate(candidates):
            for b in candidates[i + 1:]:
                if same_supplier(a.fields, b.fields):
                    parent[root(b.doc_id)] = root(a.doc_id)
        clusters: dict[str, list[Document]] = defaultdict(list)
        for d in candidates:
            clusters[root(d.doc_id)].append(d)
        groups += [sorted(c, key=lambda d: d.seq) for c in clusters.values() if len(c) > 1]
    return sorted(groups, key=lambda g: g[0].seq)


def scan(*, write: bool = False) -> dict[str, Any]:
    """The pairs already in the store (read only, no values printed), and with `write` the same to-do the processing
    would open, on the later processed document of each undecided pair, under the flow run that produced it. A document
    whose result is not from a work run, or whose run is approved, is skipped (an approved result never reopens)."""
    from jav import work

    docs = documents()
    groups = _groups(docs)
    decided = {d["pair_key"] for d in decisions_for(d.doc_id for g in groups for d in g)}
    with store.connect() as c:
        approved = {r["run_id"] for r in c.execute("SELECT run_id FROM runs WHERE approval IS NOT NULL")}
    already = {(subject, r["reason"], r["run_id"]) for (_kind, subject), rs in
               store.review_open_reasons_many([("document", d.doc_id) for g in groups for d in g]).items() for r in rs}
    kinds: dict[str, int] = defaultdict(int)
    pending: dict[str, tuple[Document, list[str]]] = {}
    skipped: dict[str, int] = defaultdict(int)
    for group in groups:
        for i, later in enumerate(group):
            for m in matches(later, group[:i]):
                kinds[m.kind] += 1
                if pair_key(later.doc_id, m.other.doc_id) in decided:
                    skipped["decided"] += 1
                elif later.run_id is None:
                    skipped["no_work_run"] += 1
                elif later.run_id in approved:
                    skipped["approved_run"] += 1
                elif (later.doc_id, m.reason, later.flow_run_id) in already:
                    skipped["already_open"] += 1  # an earlier --write (or the processing) opened it
                else:
                    pending.setdefault(later.doc_id, (later, []))[1].append(m.reason)
    written = 0
    if write:
        for doc, reasons in pending.values():
            store.review_enqueue(subject_kind="document", subject_id=doc.doc_id, run_id=doc.flow_run_id or "",
                                 reasons=reasons, producer=PRODUCER)
            written += len(reasons)
        for run_id in sorted({doc.run_id for doc, _ in pending.values() if doc.run_id}):
            work.refresh_run_status(run_id)
    return {"documents": len(docs), "groups": len(groups), "files": sum(len(g) for g in groups), "pairs": dict(sorted(kinds.items())),
            "to_open": sum(len(r) for _, r in pending.values()), "written": written, "skipped": dict(sorted(skipped.items())),
            "group_sizes": sorted((len(g) for g in groups), reverse=True)}


__all__ = ["DECISIONS", "KINDS", "Document", "Match", "classify", "decide", "documents", "family", "item_pairs", "marks",
           "matches", "number_key", "parse_reason", "review_reasons", "same_invoice", "same_supplier", "scan"]
