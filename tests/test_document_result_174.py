"""174 (plan 170 L2 = plan 160-E S5): the reconciliation, the duplicate search, the role history and the statements read
each document's counted result, the same rule as the package's current result, across every package the document is
in: an approved live run's result, else a live run's, else a trial run's; a command-line result (a measurement) only
when no run has finished the document; a document removed from every package drops out (decision 160 D3). Until now
they read the store's latest result row, a later trial's too. Synthetic rows only."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

import pytest

from jav import duplicates, package_result, party_history, reconcile, store, work, work_runs
from jav.runtime import calls

WP, OTHER = "wp-000000000174", "wp-000000000175"
NOW = "2026-10-18T08:00:00+00:00"


def _id(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "document-result.sqlite"):
        with store.connect() as c:
            for wp in (WP, OTHER):
                c.execute("INSERT INTO workpackages(id, name, source_kind, created_at, updated_at) VALUES (?,?,?,?,?)",
                          (wp, "synthetic", "manual", NOW, NOW))
        yield


def _item(wp: str, name: str) -> None:
    doc = _id(name)
    with store.connect() as c:
        c.execute("INSERT OR IGNORE INTO workpackage_items(workpackage_id, item_id, kind, source_path, sha256, added_revision)"
                  " VALUES (?,?,?,?,?,?)", (wp, doc, "document", f"C:/synthetic/{name}.pdf", doc, 1))


def _run(run_id: str, results: dict[str, dict | None], *, mode: str = "apply", approved: bool = False, at: str,
         wp: str = WP, status: str = "done", item_status: str = "done", doc_type: str = "invoice_hu") -> None:
    """A run of `wp` whose items (by name) ended with these values; None: the item ended without a result row."""
    with store.connect() as c:
        c.execute("INSERT INTO runs(run_id, workpackage_id, dedup_key, mode, assignment_revision, recipe_id, recipe_version,"
                  " recipe_hash, recipe, params, input, input_hash, status, approval, actor, created_at)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (run_id, wp, run_id, mode, 1, "processing", 1, "h", "{}", "{}",
                   json.dumps({"items": [{"item_id": _id(n), "kind": "document"} for n in results]}), "h", status,
                   "approved" if approved else None, "Reviewer One", at))
        for name in results:
            c.execute("INSERT INTO run_items(run_id, item_id, status, final_status, flow_run_id, updated_at) VALUES (?,?,?,?,?,?)",
                      (run_id, _id(name), item_status, "done", work_runs.flow_run_id(run_id, _id(name)), at))
    for name, values in results.items():
        _item(wp, name)
        if values is not None:
            _save(name, values, flow=work_runs.flow_run_id(run_id, _id(name)), doc_type=doc_type)


def _save(name: str, values: dict, *, flow: str, doc_type: str = "invoice_hu") -> None:
    store.insert_datapoints(run_id=flow, doc_id=_id(name), doc_type=doc_type, arm="S", datapoints=values, field_conf={},
                            validation=[], route="auto", review_reasons=[], final_status="done")


def _inv(number: str, gross: str = "100.00") -> dict:
    return {"invoice_number": number, "supplier_name": "Example Supplier Kft.", "supplier_tax_id": "12345676-2-41",
            "buyer_tax_id": "87654320-2-13", "gross_total": gross, "currency": "HUF", "issue_date": "2026-04-01"}


def _numbers() -> dict[str, str]:
    """Per document (by its id), the invoice number the reconciliation reads."""
    return {i["id"]: i["number"] for i in reconcile.snapshot()["invoices"]}


def _counted() -> dict[str, tuple[str | None, str]]:
    with store.connect() as c:
        return {d: (x.work_run, x.tier) for d, x in package_result.counted_documents(c).items()}


def test_an_approved_result_in_one_package_beats_a_later_trial_in_another(db) -> None:
    _run("run-approved", {"invoice": _inv("INV-APPROVED")}, approved=True, at="2026-10-18T09:00:00+00:00")
    _run("run-trial", {"invoice": _inv("INV-TRIAL")}, mode="shadow", at="2026-10-18T12:00:00+00:00", wp=OTHER)
    assert _numbers() == {_id("invoice"): "INV-APPROVED"}
    assert _counted() == {_id("invoice"): ("run-approved", "approved")}
    assert [d.fields["invoice_number"] for d in duplicates.documents(("invoice_number",))] == ["INV-APPROVED"]


def test_a_live_result_beats_a_trial_and_of_equal_runs_the_later_one_counts(db) -> None:
    _run("run-trial", {"a": _inv("A-TRIAL"), "b": _inv("B-TRIAL-1")}, mode="shadow", at="2026-10-18T12:00:00+00:00")
    _run("run-live", {"a": _inv("A-LIVE")}, at="2026-10-18T09:00:00+00:00")
    _run("run-trial-2", {"b": _inv("B-TRIAL-2")}, mode="shadow", at="2026-10-18T13:00:00+00:00", wp=OTHER)
    assert _numbers() == {_id("a"): "A-LIVE", _id("b"): "B-TRIAL-2"}


def test_a_measurement_counts_only_when_no_run_has_finished_the_document(db) -> None:
    _run("run-trial", {"processed": _inv("FROM-RUN")}, mode="shadow", at="2026-10-18T09:00:00+00:00")
    _save("processed", _inv("FROM-COMMAND-LINE"), flow="cli-processed")  # stored later, still does not count
    _save("measured", _inv("ONLY-MEASURED"), flow="cli-measured")
    assert _numbers() == {_id("processed"): "FROM-RUN", _id("measured"): "ONLY-MEASURED"}
    assert _counted()[_id("measured")] == (None, "measurement")


def test_a_stopped_run_and_a_failed_item_do_not_count(db) -> None:
    _run("run-first", {"a": _inv("A-FIRST"), "b": _inv("B-FIRST")}, mode="shadow", at="2026-10-18T09:00:00+00:00")
    _run("run-stopped", {"a": _inv("A-STOPPED")}, at="2026-10-18T10:00:00+00:00", status="cancelled")
    _run("run-failed", {"b": _inv("B-FAILED")}, at="2026-10-18T11:00:00+00:00", item_status="failed")
    assert _numbers() == {_id("a"): "A-FIRST", _id("b"): "B-FIRST"}


def test_a_run_that_left_no_result_row_gives_way_to_an_earlier_one_that_did(db) -> None:
    """A run that ended before the data points (a to-do, e.g. an exhausted budget) has no result to read; a document a
    later run read as another type leaves the reconciliation (its counted result is of that type)."""
    _run("run-trial", {"invoice": _inv("INV-1"), "retyped": _inv("INV-2")}, mode="shadow", at="2026-10-18T09:00:00+00:00")
    _run("run-live", {"invoice": None}, at="2026-10-18T10:00:00+00:00")
    _run("run-live-2", {"retyped": {"title": "Minutes"}}, at="2026-10-18T10:00:00+00:00", doc_type="meeting_minutes")
    assert _numbers() == {_id("invoice"): "INV-1"}
    assert _counted()[_id("retyped")] == ("run-live-2", "live")


def test_a_document_removed_from_every_package_drops_out_and_one_still_in_use_keeps_counting(db) -> None:
    _run("run-a", {"kept": _inv("KEPT-A"), "gone": _inv("GONE")}, approved=True, at="2026-10-18T09:00:00+00:00")
    _run("run-b", {"kept": _inv("KEPT-B")}, mode="shadow", at="2026-10-18T10:00:00+00:00", wp=OTHER)
    _save("gone", _inv("GONE-MEASURED"), flow="cli-gone")
    work.remove_items(WP, [_id("kept"), _id("gone")], expected_revision=work.get(WP)["revision"], actor="Reviewer One",
                      reason="added by mistake")
    assert _numbers() == {_id("kept"): "KEPT-B"}
    work.restore_items(WP, [_id("gone")], expected_revision=work.get(WP)["revision"], actor="Reviewer One")
    assert _numbers() == {_id("kept"): "KEPT-B", _id("gone"): "GONE"}


def test_a_store_without_work_tables_reads_the_latest_row_as_before(tmp_path) -> None:
    """A measurement store (an evaluation's own store) has no runs: every row is a measurement, the latest counts."""
    with store.use_store(tmp_path / "measurement.sqlite"):
        _save("invoice", _inv("FIRST"), flow="cli-1")
        _save("invoice", _inv("SECOND"), flow="cli-2")
        with store.connect() as c:
            for table in ("run_items", "runs", "workpackage_items"):
                c.execute(f"DROP TABLE {table}")
        assert _numbers() == {_id("invoice"): "SECOND"}


def test_the_corrections_of_the_counted_run_item_apply(db) -> None:
    from jav import corrections

    _run("run-live", {"invoice": _inv("INV-1", gross="999.00")}, at="2026-10-18T09:00:00+00:00")
    _run("run-trial", {"invoice": _inv("INV-1", gross="555.00")}, mode="shadow", at="2026-10-18T10:00:00+00:00", wp=OTHER)
    corrections.save("run-live", _id("invoice"), fields={"gross_total": "100"}, expected_revision=0, actor="Reviewer One")
    corrections.save("run-trial", _id("invoice"), fields={"gross_total": "200"}, expected_revision=0, actor="Reviewer One")
    assert [i["amount"] for i in reconcile.snapshot()["invoices"]] == ["100"]


def test_the_role_history_counts_each_earlier_document_by_its_counted_result(db) -> None:
    swapped = {**_inv("S"), "supplier_tax_id": "87654320-2-13", "buyer_tax_id": "12345676-2-41"}
    _run("run-approved", {"old": _inv("OLD")}, approved=True, at="2026-10-18T09:00:00+00:00")
    _run("run-trial", {"old": swapped}, mode="shadow", at="2026-10-18T12:00:00+00:00", wp=OTHER)
    calls.set_budget("run-now", "jev", Decimal("0.01"))
    with calls.use_run(budget_scope="run-now"):
        counts = party_history.orientation(_id("new"), "invoice_hu", ("supplier_tax_id", "buyer_tax_id"),
                                           ("12345676-2-41", "87654320-2-13"))
    assert counts == (0, 1)  # the approved result stood alike; the later trial's swapped reading does not count


def test_the_workspace_mark_sees_a_removal_and_a_run_mode_or_state(db) -> None:
    from jav import reconcile_package

    _run("run-trial", {"invoice": _inv("INV-1")}, mode="shadow", at="2026-10-18T09:00:00+00:00")
    marks = [reconcile_package.inputs_mark(keep_seconds=10**9)]
    work.remove_items(WP, [_id("invoice")], expected_revision=work.get(WP)["revision"], actor="Reviewer One", reason="mistake")
    marks.append(reconcile_package.inputs_mark(keep_seconds=10**9))
    with store.connect() as c:
        c.execute("UPDATE runs SET status='cancelled' WHERE run_id='run-trial'")
    marks.append(reconcile_package.inputs_mark(keep_seconds=10**9))
    with store.connect() as c:
        c.execute("UPDATE runs SET mode='apply' WHERE run_id='run-trial'")
    marks.append(reconcile_package.inputs_mark(keep_seconds=10**9))
    assert len(set(marks)) == 4
