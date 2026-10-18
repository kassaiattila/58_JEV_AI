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
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jav import store

TIERS = ("trial", "live", "approved")  # in rising order; a command-line result (a measurement) comes with L2

# The tier of a finished run item: approved live (2) > live (1) > trial (0). Of equal tiers the run started later
# counts, and of runs started at the same moment the one stored later (the order `work.item_states` used since 168).
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
