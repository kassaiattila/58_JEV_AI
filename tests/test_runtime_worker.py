"""Worker end to end (040 K1): synthetic PDF, fake JEV client, no paid calls.

Guarantees tested: a full run through the job queue; resuming after a crash from the saved step, without repeating JEV
calls; cancellation at a step boundary; refusal of a changed source; a document over a reader limit failing without a
retry; budget overrun caught before the network.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from typesafe_sdk import Choice, SystemOneResponse

from jav import corrections, isolated_pdf, page_image, pdf, store, work
from jav.adapters import jev as jev_mod
from jav.runtime import calls, queue, worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf


class FakeClient:
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


@pytest.fixture()
def env(tmp_path: Path):
    client = FakeClient()
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    folder = tmp_path / "bejovo"
    folder.mkdir()
    write_text_pdf(folder / "szamla_1.pdf", INVOICE_LINES)
    write_text_pdf(folder / "szamla_2.pdf", [line.replace("MINTA-2026-001", "MINTA-2026-002") for line in INVOICE_LINES])
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="Mesterséges számlák")
        work.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S", "doc_type": "invoice_hu"}, expected_revision=0, actor="t")
        yield {"wp": wp, "client": client, "tmp": tmp_path}


def _start(wp_id: str, mode: str = "shadow") -> str:
    r = work.readiness(wp_id)
    return work.start_run(wp_id, mode=mode, expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")["run_id"]


def test_full_run_through_queue(env):
    run_id = _start(env["wp"]["id"])
    info = worker.run_worker(once=True)
    assert info["processed"] == 2 and info["results"] == {"done": 2}
    run = work.get_run(run_id)
    assert run["status"] in ("done", "needs_review") and {i["status"] for i in run["items"]} == {"done"}
    assert all(i["final_status"] in ("done", "needs_review") for i in run["items"])
    journal = calls.journal(run["items"][0]["flow_run_id"])
    assert journal and {j["status"] for j in journal} == {"succeeded"} and journal[0]["budget_scope"] == run_id


def test_crash_mid_flow_resumes_without_repeating_jev(env, monkeypatch):
    monkeypatch.setattr(worker, "PRUNE_FINISHED_STATE", False)  # 064: this test is about saving the intermediate steps
    run_id = _start(env["wp"]["id"])
    worker.startup()

    class Crash(BaseException):  # process death: the worker must not catch it as an ordinary error
        pass

    def crash_after_select(action_name: str) -> None:
        if action_name == "jev_select":
            raise Crash("simulated crash")

    job = queue.claim("w1")
    with pytest.raises(Crash):  # the worker process "dies" after the JEV step, with an unsettled claim
        worker.process(job, after_step=crash_after_select)
    calls_before = env["client"].calls
    assert calls_before >= 1
    assert worker.startup()["orphans_requeued"] == 1  # restart: the interrupted claim goes back to the queue
    info = worker.run_worker(once=True)
    assert info["results"].get("done") == 2
    flow_run_id = next(i["flow_run_id"] for i in work.get_run(run_id)["items"] if i["item_id"] == job.payload["item_id"])
    assert all(j["attempt"] == 1 for j in calls.journal(flow_run_id))  # the successful JEV step was not repeated
    other = next(i["flow_run_id"] for i in work.get_run(run_id)["items"] if i["item_id"] != job.payload["item_id"])
    assert env["client"].calls - calls_before == len(calls.journal(other))  # all new calls belong to the OTHER item
    import sqlite3
    with sqlite3.connect(worker.persister_path()) as db:
        positions = [r[0] for r in db.execute("SELECT position FROM burr_state WHERE app_id=? ORDER BY sequence_id", (flow_run_id,))]
    assert positions.count("load_pdf") == 1 and positions.count("jev_select") == 1  # it resumed from the saved step


def test_cancel_stops_at_step_boundary(env):
    run_id = _start(env["wp"]["id"])
    job = queue.claim("w1")

    def cancel_after_load(action_name: str) -> None:
        if action_name == "load_pdf":
            work.cancel_run(run_id)

    assert worker.process(job, after_step=cancel_after_load) == "cancelled"
    assert env["client"].calls == 0
    assert work.refresh_run_status(run_id) == "cancelled"


def test_changed_source_is_refused(env):
    # the file processed is the item's source instance; its change is refused (a change to the original is not:
    # tests/test_source_instances_079.py)
    run_id = _start(env["wp"]["id"])
    work.source_file(env["wp"]["items"][0]).write_bytes(b"%PDF megvaltozott")
    info = worker.run_worker(once=True)
    assert info["results"] == {"dead": 1, "done": 1}
    failed = [i for i in work.get_run(run_id)["items"] if i["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["error"].startswith("instance_damaged")
    assert work.get_run(run_id)["status"] == "failed"


@pytest.mark.parametrize("error", [
    isolated_pdf.PdfReaderLimit("the PDF reader gave no answer within 60 s", reason="timeout"),
    pdf.DocumentTooLarge("szamla.pdf: 400 pages is over the 300 page input limit"),
], ids=["reader_limit", "too_large"])
def test_a_document_over_a_reader_limit_fails_without_retry(env, monkeypatch, error):
    """077: a retry would hit the same limit (and a timeout would hold the worker for as long again), so the item fails
    at once, with the named error."""
    def over_limit(path):
        raise error

    monkeypatch.setattr(pdf, "read_pdf", over_limit)
    run_id = _start(env["wp"]["id"])
    info = worker.run_worker(once=True)
    assert info["results"] == {"dead": 2}
    items = work.get_run(run_id)["items"]
    assert {i["status"] for i in items} == {"failed"}
    assert all(i["error"].startswith(type(error).__name__ + ":") for i in items)


@pytest.mark.parametrize("breakage", ["corrupt_file", "reader_limit"])
def test_item_view_survives_an_unreadable_source(env, monkeypatch, breakage):
    """077: a source the PDF reader cannot read (a parser error, or over its limits) leaves the page count empty in the
    item view (the word layer's count is used), instead of failing the whole view."""
    run_id = _start(env["wp"]["id"])
    worker.run_worker(once=True)
    item = work.get_run(run_id)["input"]["items"][0]
    if breakage == "corrupt_file":
        work.source_file(item).write_bytes(b"%PDF-1.4\nnot a PDF body at all\n%%EOF")
    else:
        def over_limit(path):
            raise isolated_pdf.PdfReaderLimit("the PDF reader gave no answer within 30 s", reason="timeout")

        monkeypatch.setattr(page_image, "page_count", over_limit)
    view = corrections.item_result(run_id, item["item_id"])
    assert view["page_count"] is None and view["kind"] == "document"


def test_budget_exhaustion_becomes_review_not_crash(env):
    run_id = _start(env["wp"]["id"])
    calls.set_budget(run_id, "jev", Decimal("0.0000001"))  # the budget is set to almost zero on purpose
    info = worker.run_worker(once=True)
    assert info["results"] == {"done": 2} and env["client"].calls == 0
    reasons = [r["reason"] for i in work.get_run(run_id)["input"]["items"] for r in store.review_open_reasons("document", i["item_id"])]
    assert any("budget_exceeded" in r for r in reasons)
    assert work.get_run(run_id)["status"] == "needs_review"


def test_document_recipe_detects_type_then_extracts_with_its_pack(env):
    """047 T1.3: the document-processing recipe first detects (coarse + detailed type), then extracts with the detailed
    type's pack; the saved data point belongs to the detected type."""
    wp = work.create_from_folder(env["tmp"] / "bejovo", name="Vegyes iratok")
    work.assign_recipe(wp["id"], "document-processing", params={"arm": "S"}, expected_revision=0, actor="t")
    run_id = _start(wp["id"])
    info = worker.run_worker(once=True)
    assert info["results"] == {"done": 2}
    run = work.get_run(run_id)
    assert {i["status"] for i in run["items"]} == {"done"}
    with store.connect() as c:
        rows = c.execute("SELECT d.doc_type, d.detail_type, p.doc_type FROM documents d JOIN datapoints p ON p.doc_id = d.doc_id"
                         " WHERE p.run_id LIKE ?", (run_id + ":%",)).fetchall()
    assert rows and all(r[1] == r[2] for r in rows)


def test_arm_falls_back_to_what_the_pack_supports():
    assert worker.arm_for("invoice_hu", "S") == "S"
    assert worker.arm_for("statement_cib", "S") == "G"  # a pack converted from a legacy type runs only on the G path
