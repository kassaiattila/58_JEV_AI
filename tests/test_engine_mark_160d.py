"""160-D (F-csak-gpt Sz6, L6; decision 160, D3): which AI engine produced a result is shown with it.

A run names the engine its frozen settings ran with (`work_readiness.run_engine`): GPT only when its `jev` setting is off, JEV
and GPT otherwise, a recipe without the setting included. The run view carries it, so the approval and the review
show it, and an item's result carries the engine of the run that produced it: a document's and a native file's are
the run's; an email's intent taken from another run has no engine here (that run's settings are not this one's), and a
statement read by code has none. Synthetic data, no paid calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jav import corrections, store, work, work_readiness, work_recipes, work_runs, work_views
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_email_results import _email_run
from tests.test_mailbox import env  # noqa: F401 - pytest fixture


@pytest.fixture()
def package(tmp_path: Path):
    with store.use_store(tmp_path / "w.sqlite"):
        folder = tmp_path / "in"
        folder.mkdir()
        write_text_pdf(folder / "a.pdf", INVOICE_LINES)
        yield work.create_from_folder(folder, name="Synthetic package")["id"]


def _run(wp_id: str, params: dict, revision: int) -> str:
    work_recipes.assign_recipe(wp_id, "processing", params=params, expected_revision=revision - 1, actor="t")
    ready = work_readiness.readiness(wp_id)
    return work_runs.start_run(wp_id, mode="shadow", expected_assignment_revision=revision, input_hash=ready["input_hash"],
                          actor="t")["run_id"]


def test_a_run_names_the_engine_it_ran_with(package):
    with_jev = _run(package, {"jev": "on"}, 1)
    gpt_only = _run(package, {"jev": "off"}, 2)
    assert work_readiness.run_engine(work_runs.get_run(with_jev)) == "jev"
    assert work_readiness.run_engine(work_runs.get_run(gpt_only)) == "gpt"
    assert work_views.run_view(with_jev)["engine"] == "jev" and work_views.run_view(gpt_only)["engine"] == "gpt"


def test_a_recipe_without_the_setting_runs_with_jev():
    assert work_readiness.run_engine({"recipe": {"params": {}}, "params": {}}) == "jev"
    assert work_readiness.run_engine({"recipe": {"params": {"jev": {"default": "off"}}}, "params": {}}) == "gpt"


def test_a_document_result_names_its_runs_engine(package):
    run_id = _run(package, {"jev": "off"}, 1)
    item = work_runs.get_run(run_id)["input"]["items"][0]["item_id"]
    assert corrections.item_result(run_id, item)["engine"] == "gpt"


def test_an_email_result_names_its_runs_engine_only_when_it_is_its_own(env):  # noqa: F811
    _wp, run_id, items = _email_run(env)
    item_id = items[0]["item_id"]
    assert corrections.item_result(run_id, item_id)["engine"] == "jev"
    with store.connect() as c:  # the frozen settings decide, not the application's engine of today
        params = json.loads(c.execute("SELECT params FROM runs WHERE run_id=?", (run_id,)).fetchone()["params"])
        c.execute("UPDATE runs SET params=? WHERE run_id=?", (json.dumps({**params, "jev": "off"}), run_id))
    assert corrections.item_result(run_id, item_id)["engine"] == "gpt"
    flow_id = work_runs.flow_run_id(run_id, item_id)
    with store.connect() as c:  # the intent shown now comes from another run
        message_id = c.execute("SELECT message_id FROM email_results WHERE run_id=?", (flow_id,)).fetchone()["message_id"]
        c.execute("DELETE FROM email_results WHERE run_id=?", (flow_id,))
        c.execute("UPDATE emails SET run_id=? WHERE message_id=?", ("run-other:0123456789abcdef", message_id))
    view = corrections.item_result(run_id, item_id)
    assert view["email"]["result"]["from_this_run"] is False and view["engine"] is None
