"""An item interrupted under the old module names resumes and finishes on today's code (212, plan G-process-core P0).

Plain-language summary: the worker saves an item's state after every step, naming each typed value's class by its
module. Since 208 the modules live in their layers' folders, and the saved-state test of 208 shows that an old state is
read back. That is not yet proof that an item interrupted before the move carries on: here the worker "dies" after the
item's JEV step, the saved states are rewritten to the module names they had before 208, and a restarted worker
finishes the item from the saved step, without asking JEV again, with the same data as a run that was never
interrupted. Synthetic PDFs, a fake JEV client, no paid call.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from typesafe_sdk import Choice, SystemOneResponse

from jav.ai import jev as jev_mod
from jav.app import corrections, work, work_readiness, work_recipes, work_runs
from jav.core import calls, queue, store
from jav.flows.persistence import MOVED_CLASSES, MOVED_MODULES
from jav.runtime import worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf


class FakeClient:
    """Answers every question with its first option (or a high probability), and counts the calls."""

    def __init__(self) -> None:
        self.calls = 0

    def system_one(self, *, state, questions, model):
        self.calls += 1
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                first = next(iter(q.criteria))
                answers[qid] = {"type": "choice", "choice": first, "confidence": 0.97,
                                "probabilities": {k: (0.97 if k == first else 0.03 / max(len(q.criteria) - 1, 1)) for k in q.criteria}}
            else:
                answers[qid] = {"type": "noul", "noul": 0.95}
        return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 500, "output_tokens": 0}, "answers": answers})


class Crash(BaseException):
    """Process death: the worker must not catch it as an ordinary error."""


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(worker, "PRUNE_FINISHED_STATE", False)  # the saved steps are what this test reads
    client = FakeClient()
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    folder = tmp_path / "incoming"
    folder.mkdir()
    write_text_pdf(folder / "invoice_1.pdf", INVOICE_LINES)
    write_text_pdf(folder / "invoice_2.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-002") for line in INVOICE_LINES])
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        yield {"wp": _package(folder), "client": client, "folder": folder, "tmp": tmp_path}


def _package(folder: Path) -> dict:
    wp = work.create_from_folder(folder, name="Invented invoices")
    work_recipes.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S", "doc_type": "invoice_hu"},
                               expected_revision=0, actor="t")
    return wp


def _start(wp_id: str) -> str:
    r = work_readiness.readiness(wp_id)
    return work_runs.start_run(wp_id, mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"],
                               actor="t")["run_id"]


def _as_saved_before_the_move(text: str) -> str:
    """A saved state as the code before 208 wrote it: a moved class at its old module, then every moved module's name."""
    for (old, name), new in MOVED_CLASSES.items():
        text = text.replace(f'"jav.{new}.{name}"', f'"jav.{old}.{name}"')
    for old, new in MOVED_MODULES.items():
        text = text.replace(f'"jav.{new}.', f'"jav.{old}.')
    return text


def test_an_item_interrupted_under_the_old_names_finishes_on_the_new_code(env):
    run_id = _start(env["wp"]["id"])
    worker.startup()

    def crash_after_select(action_name: str) -> None:
        if action_name == "jev_select":
            raise Crash("simulated crash")

    job = queue.claim("w1")
    with pytest.raises(Crash):  # the worker "dies" after the item's JEV step, with an unsettled claim
        worker.process(job, after_step=crash_after_select)
    calls_before = env["client"].calls

    with sqlite3.connect(worker.persister_path()) as db:  # only the interrupted item has saved steps so far
        rows = db.execute("SELECT rowid, state FROM burr_state").fetchall()
        saved = [text for _, text in rows]
        old = [_as_saved_before_the_move(text) for text in saved]
        db.executemany("UPDATE burr_state SET state = ? WHERE rowid = ?", [(text, rowid) for text, (rowid, _) in zip(old, rows)])
    assert old != saved and any('"jav.models.' in text for text in old)
    assert not any('"jav.ai.' in text or '"jav.documents.layout.' in text for text in old)

    assert worker.startup()["orphans_requeued"] == 1  # the restart puts the interrupted claim back in the queue
    assert worker.run_worker(once=True)["results"].get("done") == 2

    items = {i["item_id"]: i for i in work_runs.get_run(run_id)["items"]}
    resumed = items[job.payload["item_id"]]
    assert all(j["attempt"] == 1 for j in calls.journal(resumed["flow_run_id"]))  # its JEV step was not repeated
    other = next(i for i in items.values() if i["item_id"] != job.payload["item_id"])
    assert env["client"].calls - calls_before == len(calls.journal(other["flow_run_id"]))  # new calls: the other item's
    with sqlite3.connect(worker.persister_path()) as db:
        positions = [r[0] for r in db.execute("SELECT position FROM burr_state WHERE app_id = ? ORDER BY sequence_id",
                                              (resumed["flow_run_id"],))]
    assert positions.count("load_pdf") == 1 and positions.count("jev_select") == 1  # it went on from the saved step

    machine = corrections.datapoints_row(run_id, resumed["item_id"])["datapoints"]
    path = next(i["source_path"] for i in work.get(env["wp"]["id"])["items"] if i["item_id"] == resumed["item_id"])

    # the same documents in a fresh store, never interrupted (the answers come from the cache): the same data
    fresh = env["tmp"] / "fresh"
    fresh.mkdir()
    with store.use_store(fresh / "w.sqlite"):
        wp = _package(env["folder"])
        again = _start(wp["id"])
        assert worker.run_worker(once=True)["results"].get("done") == 2
        item_id = next(i["item_id"] for i in work.get(wp["id"])["items"] if i["source_path"] == path)
        uninterrupted = next(i for i in work_runs.get_run(again)["items"] if i["item_id"] == item_id)
        assert machine and machine == corrections.datapoints_row(again, item_id)["datapoints"]
    assert uninterrupted["final_status"] == resumed["final_status"]
