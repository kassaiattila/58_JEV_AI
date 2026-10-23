"""150: the to-dos of trial runs.

A trial run cannot be approved, so its open to-dos never close by themselves. After a trial the package's next step is
the live run, with the trial's count only as information; on a run's review page the reasons left by trial runs are
marked (`trial`), so that the interface hides them by default. A trial run's own page is unchanged. Synthetic data, no
paid calls.
"""

from pathlib import Path

import pytest

from jav.app import datasets, work, work_readiness, work_recipes, work_runs, work_views
from jav.core import store
from jav.app.work_views import next_step
from tests.pdfgen import INVOICE_LINES, write_text_pdf

WP = {"items": [{"item_id": "a"}], "assignment": {"recipe_id": "r"}}


def _row(**kw):
    return {"status": "needs_review", "mode": "shadow", "open_reasons": 0, "approval": None, "items": 3, "items_done": 3, **kw}


def test_after_a_trial_with_todos_the_next_step_is_the_live_run():
    step = next_step(WP, _row(open_reasons=462))
    assert step == {"code": "go_live", "label": "Próba kész: éles futás", "stage": "process", "params": {"trial_reasons": 462}}
    live = next_step(WP, _row(mode="apply", open_reasons=5))
    assert live["code"] == "review" and live["params"] == {"n": 5}  # a live run's to-dos are still the next step
    assert next_step(WP, _row(status="done"))["params"] == {}  # a trial without to-dos: as before


@pytest.fixture()
def runs(tmp_path: Path):
    """One document, a trial run and a later live run on it (not processed: the reasons are raised directly)."""
    with store.use_store(tmp_path / "w.sqlite"):
        folder = tmp_path / "in"
        folder.mkdir()
        write_text_pdf(folder / "doc.pdf", INVOICE_LINES)
        wp = work.create_from_folder(folder, name="Synthetic package")
        work_recipes.assign_recipe(wp["id"], "processing", params={"arm": "S"}, expected_revision=0, actor="t")
        ready = work_readiness.readiness(wp["id"])
        start = {"expected_assignment_revision": 1, "input_hash": ready["input_hash"], "actor": "t"}
        trial = work_runs.start_run(wp["id"], mode="shadow", **start)["run_id"]
        live = work_runs.start_run(wp["id"], mode="apply", **start)["run_id"]
        item = work_runs.get_run(live)["input"]["items"][0]["item_id"]

        def raise_reason(run_id: str, reason: str, producer: str) -> None:
            store.review_enqueue(subject_kind="document", subject_id=item, run_id=run_id, reasons=[reason], producer=producer)

        raise_reason(work_runs.flow_run_id(trial, item), "detect:low_conf:invoice_hu", "detect")
        raise_reason(work_runs.flow_run_id(live, item), "validator:tax_number", "m2")
        raise_reason("old-measurement-S-r1", "pick:seller_name", "legacy")  # a command-line measurement: no run
        yield {"wp": wp["id"], "trial": trial, "live": live, "item": item}


def _reasons(view, key, item):
    return {r["reason"]: r for r in view[key].get(item, [])}


def test_reasons_left_by_a_trial_run_are_marked_on_another_runs_page(runs):
    view = work_views.run_view(runs["live"])
    assert list(_reasons(view, "open_reasons", runs["item"])) == ["validator:tax_number"]
    earlier = _reasons(view, "earlier_open_reasons", runs["item"])
    assert earlier["detect:low_conf:invoice_hu"]["trial"] is True
    assert earlier["pick:seller_name"]["trial"] is False  # not a run's: shown as before


def test_a_trial_runs_own_page_is_unchanged(runs):
    view = work_views.run_view(runs["trial"])
    assert list(_reasons(view, "open_reasons", runs["item"])) == ["detect:low_conf:invoice_hu"]
    earlier = _reasons(view, "earlier_open_reasons", runs["item"])
    assert earlier["validator:tax_number"]["trial"] is False
    assert earlier["pick:seller_name"]["trial"] is False


def test_the_run_items_earlier_count_leaves_out_trial_reasons(runs):
    _cols, rows = datasets.rows("run_items", {"run_id": runs["live"]})
    assert rows[0]["open_reasons"] == 1 and rows[0]["earlier_reasons"] == 1  # the measurement's, not the trial's


def test_the_state_report_splits_the_open_reasons_by_run_kind(runs):
    from jav.devtools import admin

    assert admin.reasons_by_run_kind() == {"live": 1, "trial": 1, "no_run": 1}


def test_the_item_result_marks_the_earlier_trial_reasons(runs):
    from jav.app import corrections

    result = corrections.item_result(runs["live"], runs["item"])
    marks = {r["reason"]: r["trial"] for r in result["earlier_open_reasons"]}
    assert marks == {"detect:low_conf:invoice_hu": True, "pick:seller_name": False}
