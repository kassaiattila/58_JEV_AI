"""The package's current result (plan 170, L1 = plan 160-E S4): which run's result counts for each item, and the
effective value of a field, each decided in one place.

Plain-language summary: a package can be processed several times (trials, live runs, approved live runs). For each of
its items, one result counts now: the latest finished one of an approved live run, else of a live run, else of a trial
run. A stopped or superseded run does not count, and neither does an item a run has not finished. The value of a field
is the machine's value with the latest correction a person made over it. Until now the item list, the export, the
reconciliation and the duplicate search each wrote these rules by hand.

- `counted_results(wp_id)`: per item, the counted run, in one query (a window over the package's finished run items).
- `in_use(wp)`: the same for the items in use only, in the package's item order (172: the package's result tables).
- `effective_values(machine, correction)`: the one merge of a machine result and the fields a person corrected.
- 174 (plan 170 L2 = plan 160-E S5): `counted_documents()`: per document, the result row that counts now across every
  package, with a command-line result (a measurement) below a trial; `result_rows`, `run_documents` and
  `latest_corrections` read those rows. The reconciliation, the duplicate search, the own-tax scan, the role history
  and the statements read them; before, each read the store's latest result row, a later trial's too.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from jav.core import store

TIERS = ("measurement", "trial", "live", "approved")  # in rising order; a measurement: a command-line result (174)

# The tier of a finished run item: approved live (2) > live (1) > trial (0). Of equal tiers the run started later
# counts, and of runs started at the same moment the one stored later (the order `work_runs.item_states` used since 168).
_COUNTED = """
SELECT item_id, final_status, flow_run_id, run_id, mode, approval, created_at FROM (
    SELECT ri.item_id, ri.final_status, ri.flow_run_id, r.run_id, r.mode, r.approval, r.created_at,
           ROW_NUMBER() OVER (PARTITION BY ri.item_id ORDER BY
               CASE WHEN r.mode <> 'apply' THEN 0 WHEN r.approval = 'approved' THEN 2 ELSE 1 END DESC,
               r.created_at DESC, r.rowid DESC) AS pick
    FROM run_items ri JOIN runs r ON r.run_id = ri.run_id
    WHERE r.workpackage_id = ? AND r.status <> 'cancelled' AND ri.status = 'done')
WHERE pick = 1
"""


@dataclass(frozen=True)
class Counted:
    """The result that counts now for one item of a package."""

    item_id: str
    run_id: str
    mode: str
    approval: str | None
    created_at: str
    final_status: str | None
    flow_run_id: str | None

    @property
    def tier(self) -> str:
        if self.mode != "apply":
            return "trial"
        return "approved" if self.approval == "approved" else "live"


def counted_results(wp_id: str, c: sqlite3.Connection | None = None) -> dict[str, Counted]:
    """Per item of the package, the result that counts now; an item no run has finished is missing."""
    def read(conn: sqlite3.Connection) -> dict[str, Counted]:
        return {r["item_id"]: Counted(r["item_id"], r["run_id"], r["mode"], r["approval"], r["created_at"],
                                      r["final_status"], r["flow_run_id"])
                for r in conn.execute(_COUNTED, (wp_id,))}

    if c is not None:
        return read(c)
    with store.connect() as conn:
        return read(conn)


def in_use(wp: Mapping[str, Any], c: sqlite3.Connection | None = None) -> dict[str, Counted]:
    """172: the counted result of each item in use (`wp["items"]`), in the package's item order; an item removed from
    the package, or one no run has finished, is left out."""
    counted = counted_results(wp["id"], c)
    return {i["item_id"]: counted[i["item_id"]] for i in wp["items"] if i["item_id"] in counted}


def effective_values(machine: Mapping[str, Any] | None, correction: Mapping[str, Any] | None) -> dict[str, Any]:
    """The value of each field: the machine's, with the latest correction's fields over it (a new dict)."""
    return {**(machine or {}), **(correction or {})}


# --- 174 (plan 170 L2 = plan 160-E S5): a document's counted result, across every package ---------------------------


@dataclass(frozen=True)
class CountedDocument:
    """The result row that counts now for one document (`counted_documents`)."""

    doc_id: str
    seq: int  # its result row (`datapoints.rowid`), which is also the order of processing
    tier: str  # one of `TIERS`
    work_run: str | None  # the run whose item produced it; None for a measurement
    item_id: str | None


# Per document, the counted result row of a run across every package it is in use in, in the order of `_COUNTED`, of
# the finished run items that left one. A run item whose package item was removed does not count (decision 160 D3); a
# run item of no package item (only in synthetic test stores) does.
_DOCUMENT_RUNS = """
SELECT item_id, seq, run_id, mode, approval FROM (
    SELECT ri.item_id, d.rowid AS seq, r.run_id, r.mode, r.approval,
           ROW_NUMBER() OVER (PARTITION BY ri.item_id ORDER BY
               CASE WHEN r.mode <> 'apply' THEN 0 WHEN r.approval = 'approved' THEN 2 ELSE 1 END DESC,
               r.created_at DESC, r.rowid DESC) AS pick
    FROM run_items ri JOIN runs r ON r.run_id = ri.run_id
    JOIN datapoints d ON d.run_id = ri.flow_run_id AND d.doc_id = ri.item_id
    WHERE r.status <> 'cancelled' AND ri.status = 'done' AND NOT EXISTS (
        SELECT 1 FROM workpackage_items wi WHERE wi.workpackage_id = r.workpackage_id AND wi.item_id = ri.item_id
        AND wi.removed_revision IS NOT NULL){only})
WHERE pick = 1
"""


def _tier(mode: str, approval: str | None) -> str:
    if mode != "apply":
        return "trial"
    return "approved" if approval == "approved" else "live"


def _has_table(c: sqlite3.Connection, name: str) -> bool:
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _only(column: str, ids: list[str] | None) -> tuple[str, list[str]]:
    """An `AND column IN (...)` filter for a few documents (none: every document)."""
    if ids is None:
        return "", []
    return f" AND {column} IN ({','.join('?' * len(ids))})", ids


def counted_documents(c: sqlite3.Connection, doc_ids: Iterable[str] | None = None) -> dict[str, CountedDocument]:
    """Per document, the result row that counts now (decisions 160 D4, 170 K17): of the runs that left a result for it,
    across every package it is in use in, an approved live run's, else a live run's, else a trial run's (of equal tiers
    the run started later); else its latest command-line result (a measurement). A run that ended without a result row
    (a to-do before the data points, e.g. an exhausted budget) gives way to an earlier one that left one. A document
    removed from every package it was in has none, a measurement of it neither (decision 160 D3). A store without the
    work tables (an evaluation's own store) holds measurements only. `doc_ids`: only these documents (a few, e.g. one
    review page)."""
    ids = None if doc_ids is None else sorted(set(doc_ids))
    if ids is not None and len(ids) > 400:  # below SQLite's parameter limit; a long list is filtered afterwards
        return {d: x for d, x in counted_documents(c).items() if d in set(ids)}
    where, params = _only("doc_id", ids)
    rows = c.execute(f"SELECT rowid, run_id, doc_id FROM datapoints WHERE 1=1{where} ORDER BY rowid", params).fetchall()
    out: dict[str, CountedDocument] = {}
    if not _has_table(c, "run_items"):
        for seq, _flow, doc in rows:  # in rising order: the latest stays
            out[doc] = CountedDocument(doc, int(seq), "measurement", None, None)
        return out
    where, params = _only("item_id", ids)
    for r in c.execute(_DOCUMENT_RUNS.format(only=_only("ri.item_id", ids)[0]), params):
        out[r["item_id"]] = CountedDocument(r["item_id"], int(r["seq"]), _tier(r["mode"], r["approval"]), r["run_id"],
                                            r["item_id"])
    run_rows = {(r[0], r[1]) for r in c.execute(f"SELECT flow_run_id, item_id FROM run_items WHERE 1=1{where}", params)}
    removed = {r[0] for r in c.execute(
        f"SELECT item_id FROM workpackage_items WHERE 1=1{where} GROUP BY item_id"
        " HAVING COUNT(removed_revision) = COUNT(*)", params)} if _has_table(c, "workpackage_items") else set()
    counted = set(out)
    for seq, flow, doc in rows:  # the measurements, in rising order: the latest stays
        if doc not in counted and doc not in removed and (flow, doc) not in run_rows:
            out[doc] = CountedDocument(doc, int(seq), "measurement", None, None)
    return out


def run_documents(c: sqlite3.Connection, run_id: str) -> dict[str, CountedDocument]:
    """The result rows of one run's finished items, whatever counts now (an approved run's own result)."""
    out: dict[str, CountedDocument] = {}
    for r in c.execute("SELECT d.rowid, d.doc_id, r.run_id, r.mode, r.approval FROM run_items ri"
                       " JOIN runs r ON r.run_id = ri.run_id JOIN datapoints d ON d.run_id = ri.flow_run_id AND d.doc_id = ri.item_id"
                       " WHERE ri.run_id = ? AND ri.status = 'done'", (run_id,)):
        out[r["doc_id"]] = CountedDocument(r["doc_id"], int(r[0]), _tier(r["mode"], r["approval"]), r["run_id"], r["doc_id"])
    return out


def result_rows(c: sqlite3.Connection, counted: Mapping[str, CountedDocument], columns: str = "",
                params: Iterable[Any] = (), types: Iterable[str] | None = None) -> list[sqlite3.Row]:
    """The counted result rows in the order of processing: `seq`, `run_id` (the flow run), `doc_id`, `doc_type` and
    `columns` (an SQL select list over `datapoints`, with its `params`); only of `types` when given."""
    wanted = None if types is None else set(types)
    extra = f", {columns}" if columns else ""
    seqs = sorted(x.seq for x in counted.values())
    out: list[sqlite3.Row] = []
    for start in range(0, len(seqs), 500):  # below SQLite's parameter limit
        chunk = seqs[start:start + 500]
        out += [r for r in c.execute(f"SELECT rowid AS seq, run_id, doc_id, doc_type{extra} FROM datapoints"
                                     f" WHERE rowid IN ({','.join('?' * len(chunk))})", (*params, *chunk))
                if wanted is None or r["doc_type"] in wanted]
    return sorted(out, key=lambda r: r["seq"])


def latest_corrections(c: sqlite3.Connection) -> dict[tuple[str, str], dict[str, Any]]:
    """The fields of the latest correction of every corrected run item: (run, item) -> fields. A store without the
    corrections table (an evaluation's own store) has none."""
    if not _has_table(c, "run_item_corrections"):
        return {}
    return {(r["run_id"], r["item_id"]): json.loads(r["fields"]) for r in c.execute(
        "SELECT c.run_id, c.item_id, c.fields FROM run_item_corrections c JOIN"
        " (SELECT run_id, item_id, MAX(revision) AS m FROM run_item_corrections GROUP BY run_id, item_id) l"
        " ON l.run_id = c.run_id AND l.item_id = c.item_id AND l.m = c.revision")}
