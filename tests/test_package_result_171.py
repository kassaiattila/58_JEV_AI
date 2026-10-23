"""171 (plan 170, L1 = plan 160-E S4): the package's current result in one place. Per item, the run whose result
counts is the latest finished one of an approved live run, else of a live run, else of a trial run; a stopped or
superseded run and an unfinished item do not count. The effective value is the machine value with the latest
correction over it. Synthetic rows only."""

from __future__ import annotations

import json

import pytest

from jav.app import package_result, work_runs
from jav.core import store

WP = "wp-000000000172"
OTHER = "wp-000000000173"
A, B, C = "a" * 64, "b" * 64, "c" * 64


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "package-result.sqlite"):
        with store.connect() as c:
            for wp in (WP, OTHER):
                c.execute("INSERT INTO workpackages(id, name, source_kind, created_at, updated_at) VALUES (?,?,?,?,?)",
                          (wp, "synthetic", "manual", "2026-10-18T08:00:00+00:00", "2026-10-18T08:00:00+00:00"))
        yield


def _run(run_id: str, *, mode: str = "apply", approved: bool = False, status: str = "done", at: str,
         items: dict[str, str], wp: str = WP) -> None:
    """A run with its items: item id -> run item status (`done`, `failed`, `queued`)."""
    with store.connect() as c:
        c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version,"
                  " recipe_hash, recipe, params, input, input_hash, status, approval, actor, created_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, wp, run_id, mode, 1, "processing", 1, "h", "{}", "{}",
                   json.dumps({"items": [{"item_id": i, "kind": "document"} for i in items]}), "h", status,
                   "approved" if approved else None, "Reviewer One", at))
        for item, item_status in items.items():
            c.execute("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, updated_at) VALUES (?,?,?,?,?,?)",
                      (run_id, item, item_status, "auto_approved" if item_status == "done" else None,
                       work_runs.flow_run_id(run_id, item), at))


def _counted() -> dict[str, tuple[str, str]]:
    return {item: (r.run_id, r.tier) for item, r in package_result.counted_results(WP).items()}


def test_approved_live_beats_live_beats_trial_whatever_the_order(db) -> None:
    _run("run-trial-late", mode="shadow", at="2026-10-18T12:00:00+00:00", items={A: "done", B: "done", C: "done"})
    _run("run-live", at="2026-10-18T10:00:00+00:00", items={A: "done", B: "done"})
    _run("run-approved", approved=True, at="2026-10-18T09:00:00+00:00", items={A: "done"})
    assert _counted() == {A: ("run-approved", "approved"), B: ("run-live", "live"), C: ("run-trial-late", "trial")}


def test_of_two_equal_runs_the_later_one_counts(db) -> None:
    _run("run-first", mode="shadow", at="2026-10-18T09:00:00+00:00", items={A: "done"})
    _run("run-second", mode="shadow", at="2026-10-18T10:00:00+00:00", items={A: "done"})
    assert _counted() == {A: ("run-second", "trial")}


def test_of_two_runs_started_at_the_same_moment_the_one_stored_later_counts(db) -> None:
    _run("run-z", mode="shadow", at="2026-10-18T09:00:00+00:00", items={A: "done"})
    _run("run-a", mode="shadow", at="2026-10-18T09:00:00+00:00", items={A: "done"})
    assert _counted() == {A: ("run-a", "trial")}


def test_a_stopped_run_an_unfinished_item_and_another_package_do_not_count(db) -> None:
    _run("run-stopped", status="cancelled", approved=False, at="2026-10-18T11:00:00+00:00", items={A: "done"})
    _run("run-failing", at="2026-10-18T10:00:00+00:00", items={A: "failed", B: "queued"})
    _run("run-elsewhere", approved=True, at="2026-10-18T12:00:00+00:00", items={C: "done"}, wp=OTHER)
    _run("run-trial", mode="shadow", at="2026-10-18T09:00:00+00:00", items={B: "done"})
    assert _counted() == {B: ("run-trial", "trial")}


def test_the_counted_result_carries_its_run_and_final_status(db) -> None:
    _run("run-live", at="2026-10-18T10:00:00+00:00", items={A: "done"})
    counted = package_result.counted_results(WP)[A]
    assert (counted.run_id, counted.mode, counted.approval, counted.created_at, counted.final_status, counted.flow_run_id) == (
        "run-live", "apply", None, "2026-10-18T10:00:00+00:00", "auto_approved", work_runs.flow_run_id("run-live", A))


def test_the_effective_values_are_the_machine_values_with_the_correction_over_them() -> None:
    machine = {"invoice_number": "INV-1", "gross_total": "100.00", "currency": "HUF"}
    assert package_result.effective_values(machine, {"gross_total": "110.00", "buyer_name": "Example Kft."}) == {
        "invoice_number": "INV-1", "gross_total": "110.00", "currency": "HUF", "buyer_name": "Example Kft."}
    assert package_result.effective_values(None, None) == {}
    assert package_result.effective_values(machine, None) == machine
    assert package_result.effective_values(machine, {}) is not machine  # a new dict, the machine values stay as they are


def test_a_package_of_500_items_and_three_runs_is_read_in_one_quick_query(db) -> None:
    """Plan 160 S4 test list: the counted results of a large package come from one query, not one per item."""
    import time

    items = {f"{n:064x}": "done" for n in range(500)}
    _run("run-trial", mode="shadow", at="2026-10-18T09:00:00+00:00", items=items)
    _run("run-live", at="2026-10-18T10:00:00+00:00", items=dict(list(items.items())[:300]))
    _run("run-approved", approved=True, at="2026-10-18T11:00:00+00:00", items=dict(list(items.items())[:100]))
    started = time.perf_counter()
    counted = package_result.counted_results(WP)
    assert time.perf_counter() - started < 1.0
    tiers = [r.tier for r in counted.values()]
    assert len(counted) == 500 and (tiers.count("approved"), tiers.count("live"), tiers.count("trial")) == (100, 200, 200)
