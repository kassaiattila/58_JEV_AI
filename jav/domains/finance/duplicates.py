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
fields are data (`configs/finance.json` `duplicates`; until 224 in `configs/policy.json`); a pro forma invoice is its own family, so it is never a copy of a
final invoice.

Where it shows: the later processed document gets a `duplicate:<kind>:<the other document's id prefix>` to-do in a
worker run (`review_reasons`, like `party_history`: measurements and the command line do not depend on the store). A
person decides: copy, modified version or not the same (`decide`); the decision belongs to the pair, closes the pair's
to-dos on both documents, is part of the reviewed result (`corrections.review_version`), and the pair never comes up
again. Nothing is deleted or merged: a confirmed copy is marked in the lists and the export (`marks`), and counts once
in the totals (`jav/domains/finance/report_utility.py`). `scan` lists the pairs already in the store and, on request, opens the same
to-do on documents of runs not yet approved (the owner's decision of 2026-10-07, DECISIONS 126). 218 (plan P3 P3b): the
decision is a pure rule (`duplicate_rule`) traced with the to-dos it opens (`finance.duplicate`, `jav.core.trace`).

Reuse: the legacy `orchestrator/framework/payablesquality.py` (supplier + number grouping, "same" only when every other
field matches, the differing fields listed) and `mattersuggest.py` (a human confirms; a rejected pair does not come up
again) are the pattern; no legacy code is imported.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any, Iterable

from jav.app import item_kinds, package_result
from jav.ai import fact_checks
from jav.core import cfg, decisions, identity, store, trace, type_roles
from jav.core.user_messages import explained

REASON = "duplicate"
PRODUCER = "duplicates"  # the producer of the to-dos opened by `scan`; the flow's own ones are the M2 step's
PREFIX = 16  # the other document's id prefix in the to-do (the length the flow identifiers use, `work_runs.flow_run_id`)
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
    actor_id      TEXT,               -- 229 (SZ2c): the stable id beside the name (`jav.core.identity`)
    note          TEXT,
    decided_at    TEXT NOT NULL
);
""")
store.register_migration("duplicate_actor_ids",
                         lambda conn: store.add_actor_ids(conn, "duplicate_decisions", ("actor",)))  # 229 (SZ2c)


class DecisionError(ValueError):
    """A decision that cannot be recorded (unknown decision, the document compared with itself)."""


@lru_cache(maxsize=None)
def _conf() -> dict[str, Any]:
    return dict(cfg.load("finance")["duplicates"])


def config_hash() -> str:
    return cfg.config_hash("finance")


def family(doc_type: str | None) -> str | None:
    """The family of an invoice-like type; None for any other type (175: the type's role, `jav/core/type_roles.py`)."""
    return type_roles.duplicate_family(doc_type)


def family_types() -> list[str]:
    return [t for types in type_roles.duplicate_families().values() for t in types]


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


def documents(fields: Iterable[str] | None = None, types: Iterable[str] | None = None) -> list[Document]:
    """Every invoice-like document's effective values: its counted result (of any type; a document re-read as another
    type drops out), with the latest correction of the run item that produced it. 174 (plan 170 L2): the package's
    current result across every package (`package_result.counted_documents`); before, the store's latest result row.
    157: another check can ask for its own fields and types (the own-tax scan of `jav/app/parties.py`); by default the
    duplicates' key fields and types."""
    fields = tuple(key_fields() if fields is None else fields)
    types = tuple(family_types() if types is None else types)
    extracts = ", ".join(f"json_extract(datapoints, '$.' || ?) AS f{i}" for i in range(len(fields)))
    with store.connect() as c:
        counted = package_result.counted_documents(c)
        rows = package_result.result_rows(c, counted, extracts, fields, types=types)
        corrected = package_result.latest_corrections(c)
    out = []
    for r in rows:
        x = counted[r["doc_id"]]
        values = {f: r[f"f{i}"] for i, f in enumerate(fields)}
        fix = corrected.get((x.work_run, x.item_id)) or {}
        values = package_result.effective_values(values, {f: v for f, v in fix.items() if f in values})
        out.append(Document(r["doc_id"], r["doc_type"], values, r["run_id"], x.work_run, x.item_id, int(r["seq"])))
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
    """The duplicate to-dos of the document being processed: against every earlier document in the store; a pair a
    person has already decided adds nothing. It reads the store: the check registry runs it in a worker run only
    (175, `jav/ai/checks.py`)."""
    found = traced(doc_id, doc_type, fields)
    return found.reasons if found is not None else []


# --- 218 (plan P3 P3b): the duplicate decision as a pure rule, traced with the to-dos it opens --------------------

DUPLICATE_POINT = "finance.duplicate"
TRACE_KEYS = {"finance.json": ("duplicates.families", "duplicates.number_field", "duplicates.supplier_tax_field",
                               "duplicates.supplier_name_field", "duplicates.compared_fields"),
              "fact_checks.json": ("parties.domestic_tax_stem_digits", "parties.domestic_tax_prefixes",
                                   "parties.ignore_tokens", "parties.min_subset_tokens")}


def decision_inputs(current: Document, candidates: Iterable[Document], decided: set[str]) -> dict[str, Any]:
    """What the duplicate decision reads: the document's key fields, and the other documents of its family with the
    same invoice number (their key fields, their order of processing, and whether a person decided the pair)."""
    number = number_key(current.fields.get(_conf()["number_field"]))
    fam = family(current.doc_type)
    others = sorted((d for d in candidates if d.doc_id != current.doc_id and family(d.doc_type) == fam
                     and number_key(d.fields.get(_conf()["number_field"])) == number), key=lambda d: d.seq)
    return {"doc_id": current.doc_id, "doc_type": current.doc_type, "fields": {f: current.fields.get(f) for f in key_fields()},
            "others": [{"doc_id": d.doc_id, "doc_type": d.doc_type, "fields": d.fields, "seq": d.seq,
                        "decided": pair_key(current.doc_id, d.doc_id) in decided} for d in others]}


def duplicate_rule(inputs: dict[str, Any]) -> dict[str, Any]:
    """The document's duplicate to-dos (`duplicate:<kind>:<other>`): each other document that is the same invoice by
    the key (family, number, supplier), with its kind (copy, variant, undecidable), unless a person decided the pair;
    `matches` lists every pair found, decided or not, with the differing and the missing fields."""
    current = Document(inputs["doc_id"], inputs["doc_type"], inputs["fields"])
    decided = {o["doc_id"] for o in inputs["others"] if o["decided"]}
    found = matches(current, [Document(o["doc_id"], o["doc_type"], o["fields"], seq=o["seq"]) for o in inputs["others"]])
    return {"reasons": [m.reason for m in found if m.other.doc_id not in decided],
            "matches": [{"doc_id": m.other.doc_id[:PREFIX], "kind": m.kind, "differing": list(m.differing),
                         "missing": list(m.missing), "decided": m.other.doc_id in decided} for m in found]}


def traced(doc_id: str | None, doc_type: str | None, fields: dict[str, Any]) -> Any:
    """The duplicate decision on the document being processed, against every other document in the store, as a
    `checks.Traced`; None when it does not apply (no family, no invoice number)."""
    from jav.ai import checks

    if not doc_id or family(doc_type) is None or number_key(fields.get(_conf()["number_field"])) is None:
        return None
    decided = {d["pair_key"] for d in decisions_for([doc_id])}
    inputs = decision_inputs(Document(doc_id, doc_type or "", fields), documents(), decided)
    return checks.Traced(duplicate_rule(inputs)["reasons"], DUPLICATE_POINT, inputs, TRACE_KEYS)


trace.register(trace.Point(
    DUPLICATE_POINT, owner=__name__, files=("finance.json", "fact_checks.json"), rule=duplicate_rule,
    what="whether an invoice-like document is the same invoice as another one in the store (the same family, number "
         "and supplier), and of which kind: a copy, a modified version, or undecidable for a missing field",
    not_for="a person's decision on the pair (copy, modified version, not the same: their own journal) or how the "
            "totals count a confirmed copy"))


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


# 187 (plan G-full-move T2c): a person's decisions on a pair of documents, in the shared decision journal
DECISION_KIND = "duplicate"
decisions.register(decisions.Kind(DECISION_KIND, ("decide",), __name__))


@store.one_connection
def decide(run_id: str, item_id: str, other_doc_id: str, *, decision: str, actor: identity.Who, note: str | None = None,
           expected_state: int | None = None) -> dict[str, Any]:
    """A person's decision on a pair, made on a run's item: `copy`, `variant` (a modified version) or `different` (not
    the same invoice). One decision per pair; it may be changed until the run it was made in is approved. The pair's
    open to-dos close on both documents. Frozen on an approved run (`work.RevisionConflict`), checked again in the
    writing transaction, as the task decisions are. 187: the change goes into the decision journal in the same
    transaction (the pair's row keeps only the latest), and a stale `expected_state` is refused. 215 (plan
    G-process-core P2c): the to-dos close in the decision's transaction too, so a stop between the two keeps neither."""
    from jav.app import work, work_runs

    if decision not in DECISIONS:
        raise explained(DecisionError, "unknown duplicate decision: {{decision}}", decision=decision)
    if other_doc_id == item_id:
        raise explained(DecisionError, "a document is not a duplicate of itself")
    run = work_runs.get_run(run_id)
    if run["approval"]:
        raise explained(work.RevisionConflict, "run {{run_id}} is approved; duplicate decisions are frozen",
                        run_id=run_id)
    if not any(i["item_id"] == item_id and item_kinds.of(i).record for i in run["input"]["items"]):
        raise KeyError(item_id)
    docs = {d.doc_id: d for d in documents() if d.doc_id in (item_id, other_doc_id)}
    if other_doc_id not in _file_names([other_doc_id]):
        raise KeyError(other_doc_id)
    suggested = (classify(docs[item_id].fields, docs[other_doc_id].fields)[0]
                 if item_id in docs and other_doc_id in docs else None)
    key = pair_key(item_id, other_doc_id)
    with store.connect() as c:
        store.begin_immediate(c)
        if decisions.run_approved(c, run_id):
            raise explained(work.RevisionConflict, "run {{run_id}} is approved; duplicate decisions are frozen",
                            run_id=run_id)
        before = c.execute("SELECT run_id FROM duplicate_decisions WHERE pair_key=?", (key,)).fetchone()
        if decisions.decided_in_approved_run(c, before["run_id"] if before else None, run_id):
            raise explained(work.RevisionConflict, "the pair was decided in an approved run; the decision is frozen")
        decisions.check(c, DECISION_KIND, key, expected_state)
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        c.execute("INSERT INTO duplicate_decisions(pair_key, doc_id, other_doc_id, decision, suggested, run_id, actor, actor_id,"
                  # a changed decision keeps the pair's direction: the repeat stays the document the to-do stood on
                  " note, decided_at) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(pair_key) DO UPDATE SET decision=excluded.decision,"
                  " suggested=excluded.suggested, run_id=excluded.run_id, actor=excluded.actor, actor_id=excluded.actor_id,"
                  " note=excluded.note, decided_at=excluded.decided_at",
                  (key, item_id, other_doc_id, decision, suggested, run_id, identity.name_of(actor), identity.id_of(actor), note, at))
        decisions.record(c, DECISION_KIND, key, "decide", actor=actor, value={"decision": decision, "suggested": suggested},
                         note=note, workpackage_id=run["workpackage_id"], run_id=run_id, at=at)
        resolution = {"duplicate": decision, "pair": key}
        for subject, other in ((item_id, other_doc_id), (other_doc_id, item_id)):
            for r in store.review_open_reasons("document", subject):
                parsed = parse_reason(r["reason"])
                if parsed is not None and other.startswith(parsed[1]):
                    work_runs.resolve_reason(r["id"], actor=actor, resolution=resolution, note=note)
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
        state = decisions.states(c, DECISION_KIND, [pair_key(item_id, o) for o in others])  # 187: sent back with a change
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
                    "decided_at": d["decided_at"] if d else None, "repeat": (d["doc_id"] == item_id) if d else True,
                    "decision_state": state[pair_key(item_id, other)]})
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


def mark_records(records: list[dict[str, Any]]) -> None:
    """126: the duplicate mark on each document record of a run's result (`duplicate`; a confirmed copy or modified
    version, a suspicion, the documents found different; None without one). 180 (plan 170 E7): the finance domain's
    record mark (`jav/app/outputs/parts.py`), until then written in `jav/app/export.py`."""
    found = marks({r["item_id"]: r["open_reasons"] for r in records})
    for r in records:
        r["duplicate"] = found.get(r["item_id"])


def duplicate_status(mark: dict[str, Any] | None) -> str | None:
    """126: the duplicate mark as one value: `copy` / `variant` when a person confirmed it, `suspected:<kind>` while the
    to-do is open; None without a mark (a pair found different has none)."""
    if not mark or "status" not in mark:
        return None
    return f"suspected:{mark['kind']}" if mark["status"] == "suspected" else mark["status"]


def column_values(records: list[dict[str, Any]]) -> list[tuple[str | None, str | None]]:
    """The documents table's two duplicate columns of each record: its mark (`duplicate_status`) and the other
    document's file name while it has a mark (180: the finance domain's columns, `jav/domains/finance/__init__.py`)."""
    out = []
    for r in records:
        mark = r.get("duplicate")
        status = duplicate_status(mark)
        out.append((status, (mark or {}).get("other_file") if status else None))
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
    from jav.app import work_runs

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
        by_number: dict[tuple[str | None, str | None], list[Document]] = defaultdict(list)
        for d in docs:
            by_number[(family(d.doc_type), number_key(d.fields.get(_conf()["number_field"])))].append(d)
        for doc, reasons in pending.values():
            # 218 (P3b): the to-dos and their decision's trace in one write; the others are the earlier documents
            earlier = [d for d in by_number[(family(doc.doc_type), number_key(doc.fields.get(_conf()["number_field"])))]
                       if d.seq < doc.seq]
            inputs = decision_inputs(doc, earlier, decided)
            with store.session(), store.connect() as c:
                store.begin_immediate(c)
                store.review_enqueue(subject_kind="document", subject_id=doc.doc_id, run_id=doc.flow_run_id or "",
                                     reasons=reasons, producer=PRODUCER)
                trace.record_in(c, DUPLICATE_POINT, subject=("document", doc.doc_id), inputs=inputs,
                                outcome=duplicate_rule(inputs), keys=TRACE_KEYS, run_id=doc.flow_run_id)
            written += len(reasons)
        for run_id in sorted({doc.run_id for doc, _ in pending.values() if doc.run_id}):
            work_runs.refresh_run_status(run_id)
    return {"documents": len(docs), "groups": len(groups), "files": sum(len(g) for g in groups), "pairs": dict(sorted(kinds.items())),
            "to_open": sum(len(r) for _, r in pending.values()), "written": written, "skipped": dict(sorted(skipped.items())),
            "group_sizes": sorted((len(g) for g in groups), reverse=True)}


__all__ = ["DECISIONS", "KINDS", "Document", "Match", "classify", "column_values", "decide", "documents", "duplicate_status",
           "family", "item_pairs", "mark_records", "marks", "matches", "number_key", "parse_reason", "review_reasons",
           "same_invoice", "same_supplier", "scan"]
