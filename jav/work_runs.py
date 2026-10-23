"""Runs (202, plan G-core-generalisation M3b; until then part of `jav/work.py`): start (idempotent), the items' states
and results, to-dos and their resolution, cancellation, approval and superseding a trial run.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from jav import item_kinds
from jav.core import store
from jav.core import calls, queue
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now
from jav import work, work_readiness, work_recipes


@store.one_connection
def start_run(wp_id: str, *, mode: str, expected_assignment_revision: int, input_hash: str, actor: str,
              rerun_of: str | None = None, scope: str = "all") -> dict[str, Any]:
    """Idempotent start with a pinned input: one queue job per item, with a run-level cost budget.

    Rerun (057): for the same input and recipe, starting returns the existing run; `rerun_of` (the run being repeated)
    asks for a new run. A repeated request with the same `rerun_of` still yields only one new run (against double
    clicks); an active run cannot be rerun.

    160-C S3: `scope="pending"` takes only the package's pending items in `mode`, with the input hash, budget and plan
    of the readiness check's `supplement` for that mode. It does not start while another run of the package is queued
    or running (its items would be pending there too); a repeated request returns the same run, and once that run was
    stopped or failed, the same pending items can be started again."""
    if mode not in ("shadow", "apply"):
        raise ValueError("mode must be shadow or apply")
    if scope not in ("all", "pending"):
        raise ValueError("scope must be all or pending")
    if scope == "pending" and rerun_of is not None:
        raise ValueError("a run over the pending items is not a rerun")
    if rerun_of is not None:
        prev = get_run(rerun_of)
        if prev["workpackage_id"] != wp_id:
            raise ValueError("rerun_of belongs to another workpackage")
        if prev["status"] in ("queued", "running"):
            raise explained(ValueError, "run is still active; stop it before rerunning")
    ready = work_readiness.readiness(wp_id, verify=True)
    if ready["assignment_revision"] != expected_assignment_revision:
        raise explained(work.RevisionConflict, "assignment is at revision {{assignment_revision}}, not {{expected_assignment_revision}}",
                        assignment_revision=ready["assignment_revision"], expected_assignment_revision=expected_assignment_revision)
    if scope == "pending":
        offer = ready.get("supplement", {}).get(mode)
        if offer is None or offer["input_hash"] != input_hash:
            raise explained(work.RevisionConflict, "the package's pending items changed since the readiness check")
        ready = {**ready, **{k: offer[k] for k in ("ready", "blockers", "budget", "plan")}}
    elif ready["input_hash"] != input_hash:
        raise explained(work.RevisionConflict, "workpackage input changed since readiness check")
    if not ready["ready"]:
        raise explained(work.NotReady, "workpackage is not ready", ready["blockers"])
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    with store.connect() as c:
        work._begin(c)
        # 066 Á19: the frozen input is read under the write lock (nobody else can write meanwhile), and it is exactly
        # what the readiness check saw; an edit in between is a conflict, not a run with an unchecked input
        wp = work.get(wp_id)
        a = wp["assignment"]
        if scope == "pending":
            pending = set(pending_items(wp_id, mode, wp))
            snapshot = work_readiness._input_snapshot(wp, [i for i in wp["items"] if i["item_id"] in pending])
        else:
            snapshot = work_readiness._input_snapshot(wp)
        if (a["revision"] if a else 0) != expected_assignment_revision or work_readiness._snapshot_hash(snapshot) != input_hash:
            raise explained(work.RevisionConflict, "workpackage changed while the run was being started")
        if a is None:  # 080: the default settings the readiness check used are saved, in the starter's name
            d = work_recipes.default_recipe()
            # data (the assignment history, shown in the UI as written), not a label
            # 160-D: with the engine the readiness check (its budget) used, even if the application's changed since
            work_recipes._insert_assignment(c, wp_id, d, work_recipes.default_params(d, "jev" if ready["plan"]["jev"] else "gpt"), expected_revision=0, actor=actor,
                               note="alapbeállítás, a futás indításakor mentve")
            a = work_recipes.current_assignment(wp_id, c)
        r = work_recipes.recipe(a["recipe_id"])
        dedup = f"{wp_id}:{a['revision']}:{input_hash}:{mode}" + (f":rerun:{rerun_of}" if rerun_of else "")
        if scope == "pending":
            # a stopped or failed run over the same pending items does not stand in the way of a new one: the key
            # counts them (a double click meanwhile counts the same, so it gets the run the first click started)
            ended = c.execute("SELECT COUNT(*) FROM runs WHERE workpackage_id=? AND mode=? AND status IN ('cancelled','failed')",
                              (wp_id, mode)).fetchone()[0]
            dedup += f":pending:{ended}"
        existing = c.execute("SELECT run_id, input FROM runs WHERE dedup_key=?", (dedup,)).fetchone()
        if not existing and scope == "pending" and c.execute(
                "SELECT 1 FROM runs WHERE workpackage_id=? AND status IN ('queued','running')", (wp_id,)).fetchone():
            raise explained(work.NotReady, "another run of the package is still going; start the pending items after it",
                            [{"code": "run_active", "message": "Another run of the package is still going."}])
        if not existing:
            c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version, recipe_hash,"
                      " recipe, params, input, input_hash, status, actor, created_at, plan, scope) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,?,?)",
                      (run_id, wp_id, dedup, mode, a["revision"], r["id"], r["version"], work_recipes.recipe_hash(r), work._canon(r), work._canon(a["params"]),
                       work._canon(snapshot), input_hash, actor, _now(), work._canon(ready["plan"]), "pending" if scope == "pending" else None))
    if existing:
        # 063: if the previous start broke off after the run row, the repeated start fills in the budget and the jobs
        _ensure_run_work(existing["run_id"], json.loads(existing["input"])["items"], ready["budget"], replace_budget=False)
        return {"run_id": existing["run_id"], "deduped": True}
    _ensure_run_work(run_id, snapshot["items"], ready["budget"], replace_budget=True)
    return {"run_id": run_id, "deduped": False}


def _ensure_run_work(run_id: str, items: list[dict[str, Any]], budget: dict[str, Decimal], *, replace_budget: bool) -> None:
    """The run's budget and one queue job per item. Idempotent: the job is created once per `dedup_key`, and an
    existing budget does not change when filling in (063)."""
    for provider, amount in budget.items():
        (calls.set_budget if replace_budget else calls.ensure_budget)(run_id, provider, amount)
    for item in items:
        queue.enqueue(work.JOB_KIND, run_id=run_id, dedup_key=f"{run_id}:{item['item_id']}",
                      payload={"run_id": run_id, "item_id": item["item_id"]})


@store.one_connection
def get_run(run_id: str) -> dict[str, Any]:
    with store.connect() as c:
        row = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        items = [dict(r) for r in c.execute("SELECT * FROM run_items WHERE run_id=? ORDER BY item_id", (run_id,))]
    out = dict(row)
    for k in ("recipe", "params", "input"):
        out[k] = json.loads(out[k])
    out["plan"] = json.loads(out["plan"]) if out.get("plan") else None  # 082: None for a run started before it was saved
    out["excluded_items"] = json.loads(out["excluded_items"]) if out.get("excluded_items") else []
    out["items"] = items
    out["jobs"] = queue.counts(run_id=run_id)
    return out


def run_rows(wp_id: str | None = None) -> list[dict[str, Any]]:
    """Runs as list rows, in one query, without truncation (056 U1 dataset): package name, item count, the finished
    items and the run's own open to-do reasons (the item's flow identifier starts with `<run>:`)."""
    sql = ("SELECT r.run_id, r.workpackage_id, w.name AS workpackage_name, r.recipe_id, r.recipe_version, r.mode, r.status,"
           " r.approval, r.approved_by, r.actor, r.created_at, r.finished_at, r.scope,"
           " json_array_length(r.input, '$.items') AS items,"
           " (SELECT COUNT(*) FROM run_items i WHERE i.run_id=r.run_id) AS items_done,"
           # 153 (review B4): a range on the item flow ids `<run>:...` (';' follows ':'), so the index is used
           " (SELECT COUNT(*) FROM review_reasons x WHERE x.status='open' AND x.run_id >= r.run_id || ':'"
           " AND x.run_id < r.run_id || ';'"
           # 160-C (decision 163 D7): not the to-dos of an item left out of the release (as `excluded_items` says)
           " AND NOT EXISTS (SELECT 1 FROM workpackage_items wi WHERE r.approval IS NULL AND wi.workpackage_id=r.workpackage_id"
           " AND wi.removed_revision IS NOT NULL AND x.run_id = r.run_id || ':' || substr(wi.item_id, 1, 16))"
           " AND NOT EXISTS (SELECT 1 FROM json_each(COALESCE(r.excluded_items, '[]')) e WHERE r.approval IS NOT NULL"
           " AND x.run_id = r.run_id || ':' || substr(e.value, 1, 16))) AS open_reasons"
           " FROM runs r JOIN workpackages w ON w.id=r.workpackage_id")
    args: tuple = ()
    if wp_id is not None:
        sql, args = sql + " WHERE r.workpackage_id=?", (wp_id,)
    with store.connect() as c:
        rows = [dict(r) for r in c.execute(sql + " ORDER BY r.created_at DESC, r.rowid DESC", args)]
    for r in rows:  # 058: a stored "needs review" after to-dos closed without a refresh is really done (queue empty)
        if r["status"] == "needs_review" and not r["open_reasons"]:
            r["status"] = "done"
    return rows


def pending_items(wp_id: str, mode: str, wp: dict[str, Any] | None = None) -> list[str]:
    """160-C S2/S3 (pending item): the package's items in use that no run of the package in `mode` (shadow / apply)
    has finished — a cancelled or superseded run does not count, a failed item stays pending. In package order. `wp`:
    the package already read (`get`), if at hand."""
    with store.connect() as c:
        done = {r["item_id"] for r in c.execute(
            "SELECT DISTINCT ri.item_id FROM run_items ri JOIN runs r ON r.run_id=ri.run_id WHERE r.workpackage_id=?"
            " AND r.mode=? AND r.status<>'cancelled' AND ri.status='done'", (wp_id, mode))}
    return [i["item_id"] for i in (wp or work.get(wp_id))["items"] if i["item_id"] not in done]


def item_states(wp_id: str, items: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """168 (plan F-item-list-and-adding; the rule of plan F-flexible work package S4): per item, its state in the package
    and the run whose result counts now (`package_result.counted_results`, 171: the rule in one place): the latest
    finished one of an approved live run, else of a live run, else of a trial run; a stopped or superseded run does not
    count. State: `approved` / `live` / `trial` by that result; `running` while a queued or running run still has the
    item to do (the counted result stays beside it); otherwise `failed` if a run failed it, else `pending`."""
    from jav import package_result

    with store.connect() as c:
        counted = package_result.counted_results(wp_id, c)
        failed = {r["item_id"] for r in c.execute(
            "SELECT DISTINCT ri.item_id FROM run_items ri JOIN runs r ON r.run_id=ri.run_id"
            " WHERE r.workpackage_id=? AND r.status<>'cancelled' AND ri.status='failed'", (wp_id,))}
        active = [(r["run_id"], json.loads(r["input"])) for r in c.execute(
            "SELECT run_id, input FROM runs WHERE workpackage_id=? AND status IN ('queued', 'running')", (wp_id,))]
        finished = {(r["run_id"], r["item_id"]) for r in c.execute(
            "SELECT ri.run_id, ri.item_id FROM run_items ri JOIN runs r ON r.run_id=ri.run_id"
            " WHERE r.workpackage_id=? AND r.status IN ('queued', 'running') AND ri.status='done'", (wp_id,))}
    running = {i["item_id"] for run_id, given in active for i in given["items"] if (run_id, i["item_id"]) not in finished}
    out = {}
    for item in items:
        iid = item["item_id"]
        best = counted.get(iid)
        state = ("running" if iid in running else best.tier if best else "failed" if iid in failed else "pending")
        out[iid] = {"state": state, "run_id": best.run_id if best else None, "mode": best.mode if best else None,
                    "run_at": best.created_at if best else None, "final_status": best.final_status if best else None}
    return out


def runs(wp_id: str) -> list[dict[str, Any]]:
    with store.connect() as c:
        ids = [r["run_id"] for r in c.execute("SELECT run_id FROM runs WHERE workpackage_id=? ORDER BY created_at DESC, rowid DESC", (wp_id,))]
    return [get_run(i) for i in ids]


def record_item_result(run_id: str, item_id: str, *, status: str, final_status: str | None = None,
                       flow_run_id: str | None = None, error: str | None = None) -> None:
    with store.connect() as c:
        c.execute("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, error, updated_at) VALUES (?,?,?,?,?,?,?)"
                  " ON CONFLICT(run_id, item_id) DO UPDATE SET status=excluded.status, final_status=excluded.final_status,"
                  " flow_run_id=excluded.flow_run_id, error=excluded.error, updated_at=excluded.updated_at",
                  (run_id, item_id, status, final_status, flow_run_id, error, _now()))


def flow_run_id(run_id: str, item_id: str) -> str:
    """The item's flow identifier (the worker builds the Burr application with it; the to-dos get it as `run_id`)."""
    return f"{run_id}:{item_id[:16]}"


def review_subject(item: dict[str, Any]) -> tuple[str, str]:
    """The subject of the item's to-dos: for a document, the content hash; for an email, the message identifier (= the
    name of the email's folder, written by the receiver and used by the email flow, 048 T2). 177: the item kind's
    (`jav/item_kinds.py`)."""
    return item_kinds.of(item).subject(item)


def is_own_reason(reason: dict[str, Any], own: str) -> bool:
    """Whether the to-do reason was raised for the item in this run: under the item's flow identifier, or under one of
    its stages (`<identifier>-<stage>`, e.g. detection in document processing: `-doc_detect`; 066 Á02: until then it
    counted as "earlier")."""
    rid = reason.get("run_id") or ""
    return rid == own or rid.startswith(own + "-")


def item_reasons(run_id: str, item_id: str, item: dict[str, Any] | None = None) -> dict[str, list[dict[str, Any]]]:
    """An item's open to-do reasons split in two: raised in this run (`run`) and earlier (`earlier`).

    The earlier reasons (from old measurements or earlier runs on the same document) stay open on the document and are
    shown, but they are not about this run's result, so they do not affect the run's status or approval (040 K3 live
    trial)."""
    if item is None:
        item = next((i for i in get_run(run_id)["input"]["items"] if i["item_id"] == item_id), {"item_id": item_id})
    return items_reasons(run_id, [{**item, "item_id": item_id}])[item_id]


def items_reasons(run_id: str, items: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """`item_reasons` for several items, with one store query (061: instead of the list views' per-item queries).
    150: an earlier reason carries `trial`: it was raised by a trial run (the interface hides those by default)."""
    by_subject = store.review_open_reasons_many([review_subject(i) for i in items])
    trial = trial_runs(r["run_id"] for rs in by_subject.values() for r in rs)
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for i in items:
        own = flow_run_id(run_id, i["item_id"])
        split: dict[str, list[dict[str, Any]]] = {"run": [], "earlier": []}
        for r in by_subject[review_subject(i)]:
            if is_own_reason(r, own):
                split["run"].append(r)
            else:
                split["earlier"].append({**r, "trial": owning_run(r) in trial})
        out[i["item_id"]] = split
    return out


def owning_run(reason: dict[str, Any]) -> str:
    """The work run a to-do reason was raised in (its flow identifier is `<run>:<item>`); a command-line measurement's
    identifier has no such part and names no run."""
    return (reason.get("run_id") or "").split(":", 1)[0]


def trial_runs(flow_run_ids: Iterable[str | None]) -> set[str]:
    """150: which of the work runs behind these flow identifiers are trial runs."""
    owners = sorted({(rid or "").split(":", 1)[0] for rid in flow_run_ids} - {""})
    found: set[str] = set()
    with store.connect() as c:
        for start in range(0, len(owners), 500):  # stays under the SQLite parameter limit
            chunk = owners[start:start + 500]
            found |= {r["run_id"] for r in c.execute(
                f"SELECT run_id FROM runs WHERE mode='shadow' AND run_id IN ({','.join('?' * len(chunk))})", chunk)}
    return found


def _removed_from_package(c: sqlite3.Connection, run: dict[str, Any]) -> list[str]:
    """The run's input items that are removed from its package now, in input order."""
    removed = {r["item_id"] for r in c.execute("SELECT item_id FROM workpackage_items WHERE workpackage_id=?"
                                               " AND removed_revision IS NOT NULL", (run["workpackage_id"],))}
    return [i["item_id"] for i in run["input"]["items"] if i["item_id"] in removed]


def excluded_items(run: dict[str, Any]) -> list[str]:
    """160-C (decision 163 D7): the run's items whose result is not released. For an approved run, those removed from
    its package before the approval (recorded with it, so a later removal or restore changes nothing: decision 160
    D1); for any other run, those removed now."""
    if run.get("approval"):
        return list(run.get("excluded_items") or [])
    with store.connect() as c:
        return _removed_from_package(c, run)


def released_items(run: dict[str, Any]) -> list[dict[str, Any]]:
    """160-C: the run's input items whose result counts (the input without `excluded_items`)."""
    excluded = set(excluded_items(run))
    return [i for i in run["input"]["items"] if i["item_id"] not in excluded]


@store.one_connection
def open_reasons_for_run(run_id: str) -> int:
    """The run's OWN open to-do reasons (the reasons raised under the items' flow identifiers). 160-C: an item removed
    from the package does not count; its result is not released (decision 163 D7)."""
    run = get_run(run_id)
    return sum(len(s["run"]) for s in items_reasons(run_id, released_items(run)).values())


# 204 (R1i): the planner takes the run's primary key (one row), whose lookup reads the row past its frozen input
_RUN_STATE = "INDEXED BY ix_runs_state"


@store.one_connection
def refresh_run_status(run_id: str) -> str:
    """The run's status from the queue and the to-dos: running → failed / needs review / done.

    204 (R1i): read from which states the run's jobs are in (`queue.states`), not from every item and job of the run
    (`get_run`). The worker refreshes the status after each item, so each item cost more than the one before: 31 ms per
    refresh in a synthetic run of 10,000 items. The run's size is read only once none of its jobs is queued or claimed
    (an item without a job, and the run's own open to-dos). The run's state is read and written through its index
    (`ix_runs_state`): its row holds the frozen input before those columns, and an unchanged status is not written."""
    with store.connect() as c:
        row = c.execute(f"SELECT status, stopped_at FROM runs {_RUN_STATE} WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    jobs = queue.states(run_id=run_id)
    pending = bool(jobs & {"queued", "claimed"})
    if not pending and row["status"] != "cancelled":
        # 063: an item without a job (an interrupted start) is pending too — until then the run cannot be "done"
        with store.connect() as c:
            items = c.execute("SELECT json_array_length(input, '$.items') FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
        pending = items > sum(queue.counts(run_id=run_id).values())
    if row["status"] == "cancelled":
        status = "cancelled"
    elif pending:
        status = "running" if jobs & {"claimed", "done", "dead"} else "queued"
    elif row["stopped_at"]:  # 160 (review R-4): a person's stop ends as stopped, whatever an earlier item did
        status = "cancelled"
    elif "dead" in jobs:
        status = "failed"
    elif "cancelled" in jobs:
        status = "cancelled"
    else:
        status = "needs_review" if open_reasons_for_run(run_id) else "done"
    with store.connect() as c:
        # 066 Á32: a run cancelled between computing and writing stays cancelled (condition in the write, not before);
        # 204: a write that would change nothing is left out (the status and whether it has finished are as they would be)
        c.execute(f"UPDATE runs {_RUN_STATE} SET status=?1, finished_at=CASE WHEN ?1 IN ('queued','running') THEN NULL"
                  " ELSE COALESCE(finished_at, ?2) END WHERE run_id=?3 AND (status <> 'cancelled' OR ?1 = 'cancelled')"
                  " AND NOT (status = ?1 AND (finished_at IS NULL) = (?1 IN ('queued','running')))", (status, _now(), run_id))
        return c.execute(f"SELECT status FROM runs {_RUN_STATE} WHERE run_id=?", (run_id,)).fetchone()["status"]


@store.one_connection
def resolve_reason(reason_id: int, *, actor: str, resolution: dict[str, Any] | None, note: str | None) -> dict[str, Any]:
    """Human resolution of one to-do reason, then a refresh of the owning run's status (058: after the last reason is
    closed the run is "done", and the list badge does not stay at "needs review"). A reason from an earlier
    measurement is not owned by a run."""
    with store.connect() as c:
        row = c.execute("SELECT status, run_id FROM review_reasons WHERE id=?", (reason_id,)).fetchone()
    if row is None:
        raise KeyError(reason_id)
    if row["status"] != "open":
        raise explained(work.RevisionConflict, "review reason {{reason_id}} is already {{status}}",
                        reason_id=reason_id, status=row["status"])
    store.review_resolve(reason_id, actor=actor, resolution=resolution, note=note)
    owner = (row["run_id"] or "").split(":", 1)[0]
    run_status = None
    with store.connect() as c:
        hit = c.execute("SELECT status FROM runs WHERE run_id=?", (owner,)).fetchone()
    if hit is not None and hit["status"] in ("needs_review", "done"):
        run_status = refresh_run_status(owner)
    return {"reason_id": reason_id, "status": "resolved", "actor": actor, "run_status": run_status}


STOPPABLE = ("queued", "running")  # 160 (review R-3): a finished run is superseded instead (`supersede_run`)


def cancel_run(run_id: str, *, actor: str | None = None) -> dict[str, int]:
    """Queued items stop at once, an active one at the next step boundary. 066 Á35: the actor (if any) goes into the
    package's event log. 082: the run's jobs are stopped in one step (`queue.cancel_run_jobs`); with an item still
    running, the run's status is refreshed here too (the worker's own refresh after that item ends it as cancelled).

    160 (review R-3): only a queued or running run can be stopped (`RevisionConflict` otherwise, also when it finishes
    meanwhile: the write is conditional). R-4: the stop is noted on the run (`stopped_at`, `stopped_by`), so it ends
    cancelled even when an earlier item failed."""
    with store.connect() as c:
        store.begin_immediate(c)
        row = c.execute("SELECT workpackage_id, status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        if row["status"] not in STOPPABLE:
            raise explained(work.RevisionConflict, "the run is {{status}}: only a queued or running run can be stopped; supersede a finished one instead",
                            status=row["status"])
        c.execute("UPDATE runs SET stopped_at=?, stopped_by=? WHERE run_id=?", (_now(), actor, run_id))
        if actor is not None:
            work._event(c, row["workpackage_id"], "run_cancel", actor, {"run_id": run_id})
    out = queue.cancel_run_jobs(run_id)
    if out.get("cancel_requested"):
        refresh_run_status(run_id)
    else:
        with store.connect() as c:
            c.execute("UPDATE runs SET status='cancelled', finished_at=? WHERE run_id=? AND status IN ('queued','running')",
                      (_now(), run_id))
    return out


SUPERSEDABLE = ("needs_review", "done", "failed")  # a finished run (151; 200: a trial run too)


def _superseding_run(c: sqlite3.Connection, run: dict[str, Any]) -> str | None:
    """151: the latest LATER live run of the same package that has finished (to-dos raised, not cancelled) and has
    every item of `run` among its own items; None if there is none. 200: a trial run is superseded by a later run of
    either kind, since a trial result is only viewed; a live run only by a later live run."""
    items = {i["item_id"] for i in run["input"]["items"]}
    rows = c.execute("SELECT r.run_id, r.input FROM runs r, runs o WHERE o.run_id=? AND r.workpackage_id=o.workpackage_id"
                     " AND (r.mode='apply' OR o.mode='shadow') AND r.status IN ('needs_review','done')"
                     " AND (r.created_at, r.rowid) > (o.created_at, o.rowid)"
                     " ORDER BY r.created_at DESC, r.rowid DESC", (run["run_id"],)).fetchall()
    for r in rows:
        if items <= {i["item_id"] for i in json.loads(r["input"])["items"]}:
            return r["run_id"]
    return None


def _supersedable(c: sqlite3.Connection, run_id: str) -> bool:
    """151: an unapproved, finished live run. 200 (decision of 2026-10-22): a finished trial run too, while it has open
    reasons, since closing them is all superseding does for a trial."""
    row = c.execute("SELECT mode, approval, status FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None or row["approval"] is not None or row["status"] not in SUPERSEDABLE:
        return False
    return row["mode"] == "apply" or (row["mode"] == "shadow" and _own_reason_count(c, run_id, "open") > 0)


def _own_reason_count(c: sqlite3.Connection, run_id: str, status: str) -> int:
    """The run's reasons in `status` (raised under its items' flow identifiers `<run>:<item>[-stage]`)."""
    return c.execute("SELECT COUNT(*) FROM review_reasons WHERE status=? AND substr(run_id, 1, ?) = ?",
                     (status, len(run_id) + 1, run_id + ":")).fetchone()[0]


def supersede_info(run_id: str) -> dict[str, Any] | None:
    """151: whether a person can supersede this run, and what the confirmation shows: the later live run that processed
    the same items again (`by`), the run's own open reasons that would close, and the human work done on it (closed
    reasons, corrected items), which stays with this run and is not carried over. None if it cannot be superseded:
    an approved or an active run, a trial run without open reasons (200), or no later finished run covers its items
    (`_superseding_run`)."""
    from jav import corrections  # noqa: F401 - registers the corrections table

    run = get_run(run_id)
    with store.connect() as c:
        if not _supersedable(c, run_id):
            return None
        by = _superseding_run(c, run)
        if by is None:
            return None
        corrected = c.execute("SELECT COUNT(DISTINCT item_id) FROM run_item_corrections WHERE run_id=?", (run_id,)).fetchone()[0]
        return {"by": by, "open_reasons": _own_reason_count(c, run_id, "open"),
                "resolved_reasons": _own_reason_count(c, run_id, "resolved"), "corrected_items": corrected}


def open_live_runs(wp_id: str) -> list[str]:
    """160-C S3: the package's open live runs, oldest first: finished (to-dos raised, done, or failed), not approved,
    not stopped, and not repeated on all their items by a later finished live run (such a run is to be superseded, not
    reviewed: `supersede_info`). Each waits for a person; with a run over the pending items a package can have more
    than one, and its step is not done while one is open."""
    with store.connect() as c:
        rows = c.execute("SELECT run_id, input FROM runs WHERE workpackage_id=? AND mode='apply' AND approval IS NULL"
                         " AND status IN (?, ?, ?) ORDER BY created_at, rowid", (wp_id, *SUPERSEDABLE)).fetchall()
        return [r["run_id"] for r in rows
                if _superseding_run(c, {"run_id": r["run_id"], "input": json.loads(r["input"])}) is None]


def supersedable_runs(wp_id: str) -> list[dict[str, Any]]:
    """152: the package's older live runs a person can supersede, oldest first, each with the offer of its own page
    (`supersede_info`) and its start, so the package's processing section can offer them too. 200: older trial runs
    with open reasons too, each with its `mode`."""
    with store.connect() as c:
        rows = c.execute("SELECT run_id, mode, created_at FROM runs WHERE workpackage_id=? AND mode IN ('apply','shadow')"
                         " AND approval IS NULL AND status IN (?, ?, ?) ORDER BY created_at, rowid",
                         (wp_id, *SUPERSEDABLE)).fetchall()
    out = []
    for row in rows:
        info = supersede_info(row["run_id"])
        if info is not None:
            out.append({"run_id": row["run_id"], "mode": row["mode"], "created_at": row["created_at"], **info})
    return out


def supersede_run(run_id: str, *, actor: str) -> dict[str, Any]:
    """151 (decision of 2026-10-12): a person supersedes an older live run that a later live run has repeated. The run
    is kept as cancelled, its own open reasons close as `superseded` (they stay in the store), and the package's event
    log records who did it and which run superseded it. Checked and done in one transaction; `NotReady` if the run
    cannot be superseded (see `supersede_info`). The pin of 066 stays: no run closes another run's reasons by itself.
    200 (decision of 2026-10-22): an older trial run with open reasons too, repeated by a later run of either kind."""
    run = get_run(run_id)
    with store.connect() as c:
        work._begin(c)
        by = _superseding_run(c, run) if _supersedable(c, run_id) else None
        if by is None:
            raise explained(work.NotReady, "only a finished run that a later finished run has repeated can be superseded: "
                                      "an unapproved live run, or a trial run with open to-dos")
        c.execute("UPDATE runs SET status='cancelled', finished_at=COALESCE(finished_at, ?) WHERE run_id=?", (_now(), run_id))
        closed = store.close_run_reasons(c, run_id, status="superseded")
        detail = {"run_id": run_id, "superseded_by": by, "reasons_closed": closed}
        work._event(c, run["workpackage_id"], "run_supersede", actor, detail)
    return detail


def superseded(run_id: str) -> dict[str, Any] | None:
    """151: who superseded the run, when and by which run (from the package's event log); None if it was not."""
    with store.connect() as c:
        row = c.execute("SELECT e.actor, e.detail, e.created_at FROM workpackage_events e JOIN runs r ON r.workpackage_id=e.workpackage_id"
                        " WHERE r.run_id=? AND e.action='run_supersede' AND json_extract(e.detail, '$.run_id')=?"
                        " ORDER BY e.rowid DESC LIMIT 1", (run_id, run_id)).fetchone()
    if row is None:
        return None
    detail = json.loads(row["detail"])
    return {"by": detail["superseded_by"], "actor": row["actor"], "at": row["created_at"], "reasons_closed": detail["reasons_closed"]}


@store.one_connection
def approve_run(run_id: str, *, actor: str, review_version: str | None = None,
                confirm_removed: int | None = None) -> dict[str, Any]:
    """Approval of a live run: only with finished items and no open to-do; who approved it and when is recorded.
    `review_version` (085, re-audit A01): the version of the result the approver saw (`corrections.review_version`);
    if a correction changed it since, `RevisionConflict`. Checked and recorded in one transaction, so a correction
    cannot slip between the check and the approval (and none is written after it: `corrections`).

    160-C (decision 163 D7): items removed from the package since the run started are left out of the approval: their
    results are not released and their to-dos do not block it. Then the approver confirms how many were removed
    (`confirm_removed`, the count shown); a missing or different count is `NotReady` (`removed_items`), so a removal
    made after the page was loaded is never approved unseen. The left-out items are recorded with the approval."""
    from jav import corrections

    run = get_run(run_id)
    if run["mode"] != "apply":
        raise explained(ValueError, "only apply runs can be approved")
    status = refresh_run_status(run_id)
    if status != "done":
        raise explained(work.NotReady, "run is {{status}}; approval needs a finished run without open review reasons",
                        status=status)
    done = {i["item_id"] for i in get_run(run_id)["items"] if i["status"] == "done"}
    if any(i["item_id"] not in done for i in released_items(run)):  # 063: every input item has a finished result
        raise explained(work.NotReady, "run has input items without a finished result")
    with store.connect() as c:
        work._begin(c)
        from jav.documents import native_results

        # Recheck the run, its items and its open reasons under the approval's write lock (153, review: the check above
        # ran before it, so a run superseded or stopped in between ended both cancelled and approved)
        latest = c.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if latest["status"] != "done":
            raise explained(work.NotReady, "The run is no longer ready for approval")
        removed = _removed_from_package(c, run)
        if removed and confirm_removed != len(removed):
            raise explained(work.NotReady, "{{removed}} of the run's items were removed from the package; their results are not released. Confirm the count to approve the rest.",
                            [{"code": "removed_items", "message": "Items were removed from the package after the run started", "count": str(len(removed))}], removed=len(removed))
        kept = [i for i in run["input"]["items"] if i["item_id"] not in set(removed)]
        for item in kept:
            result = c.execute("SELECT status FROM run_items WHERE run_id=? AND item_id=?",
                               (run_id, item["item_id"])).fetchone()
            if result is None or result["status"] != "done":
                raise explained(work.NotReady, "The run has an unfinished input item")
            subject_kind, subject_id = review_subject(item)
            # 167 (review R-10): the subject drives the join (`store.SUBJECT_REASONS`), not every open reason of the store
            reasons = c.execute("SELECT r.run_id FROM " + store.SUBJECT_REASONS
                                + " WHERE q.subject_kind=? AND q.subject_id=? AND r.status='open'",
                                (subject_kind, subject_id)).fetchall()
            if any(is_own_reason(dict(reason), flow_run_id(run_id, item["item_id"])) for reason in reasons):
                raise explained(work.NotReady, "The run still has open review reasons")
        native_items = [i for i in kept if native_results.native_item(run_id, i, c)]
        if native_items:
            if review_version is None:
                raise explained(work.RevisionConflict, "Native approval requires the exact reviewed version")
            for item in native_items:
                publication = native_results.get_publication(run_id, item["item_id"], c=c)
                if publication is None or publication.interpretation_outcome.status != "succeeded":
                    raise explained(work.NotReady, "Every native item needs a published successful interpretation")
                if publication.reading.status not in {"complete", "partial"}:
                    raise explained(work.NotReady, "The source reading is not suitable for approval")
                native_results.verify_publication(publication, c=c)
        if review_version is not None and corrections.review_version(run_id, c) != review_version:
            raise explained(work.RevisionConflict, "the result of run {{run_id}} changed since it was reviewed; review it again",
                            run_id=run_id)
        c.execute("UPDATE runs SET approval='approved', approved_by=?, approved_at=?, excluded_items=? WHERE run_id=?"
                  " AND approval IS NULL AND status='done'", (actor, _now(), json.dumps(removed) if removed else None, run_id))
    approved = get_run(run_id)
    rule = work.package_rule(run["workpackage_id"])
    if rule is not None and rule.after_approval is not None and approved["approval"]:
        try:
            rule.after_approval(approved)
        except Exception:  # noqa: BLE001 - the approval stands; the rule's failure is logged with its traceback
            logging.getLogger("jav.work").exception("the approval rule of package %s failed", run["workpackage_id"])
    return approved
