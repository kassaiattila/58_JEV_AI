"""204 (R1i, backlog Q-nagy-tablak): a run's bookkeeping does not grow with the run's size.

Plain-language summary: after every item the worker works out the run's status, and before every paid call it checks
the run's budget. Both used to read the whole run again: every item's result and every recorded call, so each item cost
more than the one before it, and a big run slowed itself down (measured on synthetic runs: a run of 3,000 items spent
309 s on this bookkeeping alone, 103 ms per item, against 35 ms per item in a run of 1,000). The status is now read
from which job states the run has, so it costs the same however big the run is; the budget check keeps its exact
sum (a running total is left to the budget redesign of plan G-process-core P4), and the look for an earlier overrun is
one index lookup. The decisions are the same as before: the old rules are kept here as the reference, and every state
and budget edge they cover is compared. The run list also counted a run's
open to-dos against every item of its package (10.4 s for one run of 10,000 items); an index on the removed items
answers that at once. Synthetic data, no paid calls; the size checks count the database's work, not the clock.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from jav import store, work, work_readiness, work_recipes, work_runs
from jav.clock import utc_stamp
from jav.runtime import calls, queue
from tests.pdfgen import INVOICE_LINES, write_text_pdf

# --- the rules before 204, kept as the reference ----------------------------------------------------------------


def _status_before_204(run_id: str) -> str:
    """The status `refresh_run_status` worked out before 204, from every item and job of the run (before the write)."""
    run = work_runs.get_run(run_id)
    jobs = run["jobs"]
    missing = max(0, len(run["input"]["items"]) - sum(jobs.values()))
    pending = jobs.get("queued", 0) + jobs.get("claimed", 0) + missing
    if run["status"] == "cancelled":
        return "cancelled"
    if pending:
        return "running" if (jobs.get("claimed") or any(v for k, v in jobs.items() if k in ("done", "dead"))) else "queued"
    if run.get("stopped_at"):
        return "cancelled"
    if jobs.get("dead"):
        return "failed"
    if jobs.get("cancelled"):
        return "cancelled"
    return "needs_review" if work_runs.open_reasons_for_run(run_id) else "done"


def _fits_before_204(scope: str, provider: str, amount: Decimal, limit: Decimal) -> bool:
    """The budget check before 204: every call of the scope added again, exactly."""
    with store.connect() as c:
        return not calls._committed(c, scope, provider) + amount > limit


# --- synthetic runs ----------------------------------------------------------------------------------------------


@pytest.fixture()
def small_run(tmp_path: Path):
    """A live run of two documents, started through the real operations."""
    folder = tmp_path / "in"
    folder.mkdir()
    for n in (1, 2):
        write_text_pdf(folder / f"doc_{n}.pdf", [line.replace("MINTA-2026-001", f"MINTA-2026-00{n}") for line in INVOICE_LINES])
    with store.use_store(tmp_path / "w.sqlite"):
        wp = work.create_from_folder(folder, name="Synthetic package")
        work_recipes.assign_recipe(wp["id"], "processing", params={"arm": "S"}, expected_revision=0, actor="t")
        ready = work_readiness.readiness(wp["id"])
        run_id = work_runs.start_run(wp["id"], mode="apply", expected_assignment_revision=1, input_hash=ready["input_hash"],
                                     actor="t")["run_id"]
        yield {"run": run_id, "wp": wp["id"], "items": [i["item_id"] for i in work_runs.get_run(run_id)["input"]["items"]]}


def _synthetic_run(db: Path, n: int, *, done: int, calls_per_item: int = 2) -> dict[str, Any]:
    """A run of n items written as the real operations write it (`start_run`, `queue.enqueue`, `record_item_result`,
    `calls.invoke`, `store.review_enqueue`), without n documents: the first `done` items finished, with their calls and
    a to-do on every fifth, the rest queued."""
    with store.use_store(db), store.session():
        wp = work.create_workpackage(name=f"synthetic {n}", source_kind="folder", source_ref=None)
        ids = [hashlib.sha256(f"{db.stem}-{k}".encode()).hexdigest() for k in range(n)]
        with store.connect() as c:
            c.executemany("INSERT INTO workpackage_items(workpackage_id, item_id, kind, source_path, sha256, added_revision)"
                          " VALUES (?,?,?,?,?,1)",
                          [(wp["id"], iid, "document", f"C:/synthetic/doc{k:05d}.pdf", iid) for k, iid in enumerate(ids)])
            c.execute("UPDATE workpackages SET revision=1 WHERE id=?", (wp["id"],))
        work_recipes.assign_recipe(wp["id"], "processing", params={"arm": "S"}, expected_revision=0, actor="t")
        full = work.get(wp["id"])
        a, r = full["assignment"], work_recipes.recipe(full["assignment"]["recipe_id"])
        snapshot = work_readiness._input_snapshot(full)
        run_id, now, ts = f"run-{uuid.uuid4().hex[:12]}", utc_stamp(), queue._ts()
        items = snapshot["items"]
        with store.connect() as c:
            c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version,"
                      " recipe_hash, recipe, params, input, input_hash, status, actor, created_at, plan)"
                      " VALUES (?,?,?,'apply',?,?,?,?,?,?,?,?,'running','t',?,?)",
                      (run_id, wp["id"], f"t:{run_id}", a["revision"], r["id"], r["version"], work_recipes.recipe_hash(r),
                       work._canon(r), work._canon(a["params"]), work._canon(snapshot), work_readiness._snapshot_hash(snapshot),
                       now, work._canon({"jev": True})))
            c.executemany("INSERT INTO jobs(kind, dedup_key, run_id, payload, status, available_at, created_at) VALUES (?,?,?,?,?,?,?)",
                          [(work.JOB_KIND, f"{run_id}:{i['item_id']}", run_id, json.dumps({"item_id": i["item_id"], "run_id": run_id}),
                            "done" if k < done else "queued", ts, ts) for k, i in enumerate(items)])
            c.executemany("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, updated_at) VALUES (?,?,'done','done',?,?)",
                          [(run_id, i["item_id"], work_runs.flow_run_id(run_id, i["item_id"]), now) for i in items[:done]])
        calls.set_budget(run_id, "jev", Decimal("1000"))
        for k, i in enumerate(items[:done]):
            fid = work_runs.flow_run_id(run_id, i["item_id"])
            for j in range(calls_per_item):
                calls.invoke(run_id=fid, step_id=f"select:{j}", provider="jev", model="jev-1", max_cost_usd=Decimal("0.002"),
                             budget_scope=run_id, fn=lambda: calls.Outcome(response={}, model="jev-1", cost_usd=Decimal("0.000123")))
            if k % 5 == 0:
                store.review_enqueue(subject_kind="document", subject_id=i["item_id"], run_id=fid, reasons=["pick:seller_name"],
                                     producer="m2")
    return {"db": db, "run": run_id, "wp": wp["id"], "items": [i["item_id"] for i in items]}


@contextmanager
def _counted() -> Iterator[dict[str, int]]:
    """The statements, the SQLite virtual machine instructions and the rows written on the session's connection: the
    database's work, without the clock. Used inside `store.session()`."""
    seen = {"statements": 0, "steps": 0, "writes": 0}

    def step() -> int:
        seen["steps"] += 1
        return 0

    def statement(_sql: str) -> None:
        seen["statements"] += 1

    with store.connect() as c:
        c.set_progress_handler(step, 1)
        c.set_trace_callback(statement)
        before = c.total_changes
        try:
            yield seen
        finally:
            seen["writes"] = c.total_changes - before
            c.set_progress_handler(None, 1)
            c.set_trace_callback(None)


# --- the run's status --------------------------------------------------------------------------------------------


FINISHED = "2026-10-22T11:00:00Z"


def _set_state(run_id: str, items: list[str], jobs: tuple[str | None, ...], *, run_status: str, finished: bool,
               stopped: bool, reason: bool) -> None:
    """One combination: each item's job state (None: the item has no job, as after an interrupted start), the run's
    stored status and finish time, a person's stop, and an open to-do of the run's own on the first item."""
    with store.connect() as c:
        for item, state in zip(items, jobs):
            c.execute("UPDATE jobs SET status=?, run_id=? WHERE dedup_key=?",
                      (state or "queued", run_id if state else "elsewhere", f"{run_id}:{item}"))
        c.execute("UPDATE runs SET status=?, stopped_at=?, finished_at=? WHERE run_id=?",
                  (run_status, "2026-10-22T10:00:00Z" if stopped else None, FINISHED if finished else None, run_id))
        c.execute("UPDATE review_reasons SET status=? WHERE run_id=?",
                  ("open" if reason else "resolved", work_runs.flow_run_id(run_id, items[0])))


def test_the_run_status_is_the_same_as_before_in_every_state(small_run):
    """Each item's job queued, claimed, done, dead, cancelled or missing; the run's stored status, with or without a
    finish time; stopped by a person or not; with or without an open to-do of its own: 1,440 states, each worked out
    as before 204, and the status and finish time written as before (a finish time already set is kept)."""
    run_id, items = small_run["run"], small_run["items"]
    store.review_enqueue(subject_kind="document", subject_id=items[0], run_id=work_runs.flow_run_id(run_id, items[0]),
                         reasons=["pick:seller_name"], producer="m2")
    store.review_enqueue(subject_kind="document", subject_id=items[1], run_id="measurement-1",  # an earlier one: never counts
                         reasons=["pick:seller_name"], producer="m2")
    differ = []
    with store.session():
        for jobs in itertools.product((*queue.STATES, None), repeat=2):
            for run_status, finished, stopped, reason in itertools.product(
                    ("queued", "running", "needs_review", "done", "cancelled"), (False, True), (False, True), (False, True)):
                _set_state(run_id, items, jobs, run_status=run_status, finished=finished, stopped=stopped, reason=reason)
                expected = _status_before_204(run_id)
                got = work_runs.refresh_run_status(run_id)
                with store.connect() as c:
                    stored = c.execute("SELECT status, finished_at FROM runs WHERE run_id=?", (run_id,)).fetchone()
                going = expected in ("queued", "running")
                finish_ok = stored["finished_at"] is None if going else (stored["finished_at"] == FINISHED if finished
                                                                          else stored["finished_at"] is not None)
                if (got, stored["status"]) != (expected, expected) or not finish_ok:
                    differ.append((jobs, run_status, finished, stopped, reason, expected, got, stored["finished_at"]))
    assert differ == []


def test_an_unknown_run_is_still_a_key_error(small_run):
    with pytest.raises(KeyError):
        work_runs.refresh_run_status("run-unknown")


def test_a_status_refresh_while_the_run_goes_does_the_same_work_for_10_or_400_items(tmp_path):
    """Measured on 2026-10-22 before the change: 0.55 ms at 100 items, 3.0 ms at 1,000, 31 ms at 10,000 per refresh.
    An unchanged status is not written again either: the run's row holds its frozen input, and rewriting it took 10 ms
    at 10,000 items."""
    work_done = {}
    for n in (10, 400):
        run = _synthetic_run(tmp_path / f"r{n}.sqlite", n, done=n // 2)
        with store.use_store(run["db"]), store.session():
            work_runs.refresh_run_status(run["run"])  # the store's structure is checked once, outside the count
            with _counted() as seen:
                assert work_runs.refresh_run_status(run["run"]) == "running"
        work_done[n] = seen
    assert work_done[400]["statements"] == work_done[10]["statements"]
    assert work_done[400]["steps"] <= work_done[10]["steps"] + 10, work_done
    assert work_done[400]["writes"] == work_done[10]["writes"] == 0


def test_the_end_of_a_run_still_counts_its_own_open_to_dos(tmp_path):
    """Once every job has ended, the status reads the run's own open to-dos (and an item left without a job keeps the
    run going), as before."""
    run = _synthetic_run(tmp_path / "r.sqlite", 30, done=30)
    with store.use_store(run["db"]):
        assert work_runs.refresh_run_status(run["run"]) == _status_before_204(run["run"]) == "needs_review"
        with store.connect() as c:
            c.execute("UPDATE review_reasons SET status='resolved'")
        assert work_runs.refresh_run_status(run["run"]) == _status_before_204(run["run"]) == "done"
        with store.connect() as c:
            c.execute("UPDATE runs SET status='running' WHERE run_id=?", (run["run"],))
            c.execute("DELETE FROM jobs WHERE id=(SELECT MAX(id) FROM jobs WHERE run_id=?)", (run["run"],))
        assert work_runs.refresh_run_status(run["run"]) == _status_before_204(run["run"]) == "running"


# --- the budget --------------------------------------------------------------------------------------------------


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "c.sqlite"):
        yield tmp_path


def _settled(scope: str, step: str, *, max_cost: str, cost: str | None, provider: str = "openai") -> None:
    calls.invoke(run_id="r1", step_id=step, provider=provider, model="m", max_cost_usd=Decimal(max_cost), budget_scope=scope,
                 fn=lambda: calls.Outcome(response={}, model="m", cost_usd=None if cost is None else Decimal(cost)))


def _decision(scope: str, *, max_cost: str, lean: str | None, provider: str = "openai") -> str:
    """What a reservation does now: `full`, `lean` or the refusal's message."""
    step = f"probe-{uuid.uuid4().hex[:8]}"
    try:
        inv_id, _ = calls._reserve(run_id="r1", step_id=step, provider=provider, model="m", max_cost_usd=Decimal(max_cost),
                                   budget_scope=scope, request_hash=None, lean_cost_usd=None if lean is None else Decimal(lean))
    except calls.BudgetExceeded as exc:
        return str(exc)
    with store.connect() as c:
        note = c.execute("SELECT note FROM invocations WHERE id=?", (inv_id,)).fetchone()["note"]
        c.execute("DELETE FROM invocations WHERE id=?", (inv_id,))  # the probe leaves the scope as it was
    return "lean" if note == calls.LEAN_NOTE else "full"


def _expected(scope: str, *, max_cost: str, lean: str | None, provider: str = "openai") -> str:
    with store.connect() as c:
        limit = Decimal(c.execute("SELECT limit_usd FROM budgets WHERE scope=? AND provider=?", (scope, provider)).fetchone()[0])
        committed = calls._committed(c, scope, provider)
    if _fits_before_204(scope, provider, Decimal(max_cost), limit):
        return "full"
    if lean is not None and _fits_before_204(scope, provider, Decimal(lean), limit):
        return "lean"
    return f"{scope}/{provider}: committed {committed} + max {Decimal(max_cost)} > limit {limit}"


@pytest.mark.parametrize(("limit", "settled", "max_cost", "lean"), [
    ("0.40", [("0.30", "0.30")], "0.10", None),                     # exactly at the cap: fits
    ("0.40", [("0.30", "0.30")], "0.100001", None),                 # just over it: refused
    ("0.40", [("0.30", None)], "0.10", None),                       # an unknown cost keeps its maximum
    ("1.1", [("0.2", "0.1")] * 10, "0.1", None),                    # ten tenths are not exactly 1.0 in floating point
    ("1.1", [("0.2", "0.1")] * 10, "0.100000000001", "0.1"),        # the lean bound fits exactly at the cap
    ("1.1", [("0.2", "0.1")] * 10, "0.2", "0.100000000001"),        # neither fits
    ("0.000001", [("0.0000005", "0.0000001")] * 3, "0.0000007", None),  # amounts written with an exponent (1E-7)
    ("1000", [], "1000", None),                                     # nothing committed yet
    ("0.05", [], "0.050000001", "0.05"),
])
def test_a_reservation_decides_as_before_at_the_edges_of_the_budget(isolated, limit, settled, max_cost, lean):
    calls.set_budget("trial", "openai", Decimal(limit))
    for n, (reserved, cost) in enumerate(settled):
        _settled("trial", f"s{n}", max_cost=reserved, cost=cost)
    assert _decision("trial", max_cost=max_cost, lean=lean) == _expected("trial", max_cost=max_cost, lean=lean)


def test_an_amount_that_is_no_number_fails_the_reservation_as_before(isolated):
    """A known cost without an amount (never written by the call log, only by hand) made the exact sum fail; it still
    does, rather than being counted as nothing."""
    calls.set_budget("trial", "openai", Decimal("1"))
    _settled("trial", "s1", max_cost="0.1", cost="0.05")
    with store.connect() as c:
        c.execute("UPDATE invocations SET cost_usd=NULL WHERE step_id='s1'")
    with pytest.raises(TypeError):
        _fits_before_204("trial", "openai", Decimal("0.1"), Decimal("1"))
    with pytest.raises(TypeError):
        _decision("trial", max_cost="0.1", lean=None)


def test_the_run_list_counts_open_to_dos_without_reading_every_item_of_the_package(tmp_path):
    """The left-out check reads only the package's removed items (`ix_workpackage_items_removed`); the count itself is
    unchanged: a removed item's to-do is not counted."""
    run = _synthetic_run(tmp_path / "r.sqlite", 20, done=20)
    with store.use_store(run["db"]):
        assert [r["open_reasons"] for r in work_runs.run_rows(run["wp"])] == [4]
        with store.connect() as c:
            c.execute("UPDATE workpackage_items SET removed_revision=2 WHERE item_id=?", (run["items"][0],))  # it has a to-do
            plan = " ".join(r["detail"] for r in c.execute(
                "EXPLAIN QUERY PLAN SELECT 1 FROM workpackage_items wi WHERE wi.workpackage_id=? AND wi.removed_revision IS NOT NULL"
                " AND ? = ? || ':' || substr(wi.item_id, 1, 16)", (run["wp"], "x", "y")))
        assert "ix_workpackage_items_removed" in plan
        assert [r["open_reasons"] for r in work_runs.run_rows(run["wp"])] == [3]
