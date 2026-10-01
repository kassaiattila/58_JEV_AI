"""066 review (Á01, Á02): a live run can be approved only if every item has been reviewed.

- Á01: the reasons of a document without text (`needs_ocr`) used to stay only in the flow state and never became
  to-dos, so the run became "done" and could be approved although it extracted nothing.
- Á02: the detection stage of document processing runs under the `<item>-doc_detect` identifier; the run saw its
  reasons as "earlier", so even a detailed type left open did not hold the run back.

Synthetic PDF, fake JEV client, no paid calls.
"""

from pathlib import Path

import pytest
from typesafe_sdk import Choice, SystemOneResponse

from jav import ocr, store, work
from jav.adapters import jev as jev_mod
from jav.runtime import queue, worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf


class Client:
    """Every Choice picks the first option; the confidence of the detected type (`doc_type`) is `type_conf`, the rest
    0.97."""

    def __init__(self, type_conf: float = 0.97) -> None:
        self.type_conf = type_conf

    def system_one(self, *, state, questions, model):
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                pick, conf = next(iter(q.criteria)), (self.type_conf if qid == "doc_type" else 0.97)
                answers[qid] = {"type": "choice", "choice": pick, "confidence": conf,
                                "probabilities": {k: (conf if k == pick else (1 - conf) / max(len(q.criteria) - 1, 1)) for k in q.criteria}}
            else:
                answers[qid] = {"type": "noul", "noul": 0.95}
        return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 10, "output_tokens": 0}, "answers": answers})


def _no_ocr(*_a, **_k):
    raise ocr.OcrUnavailableError("nincs OCR-motor (teszt)")


def _run(tmp_path: Path, *, recipe: str, params: dict, lines: list[str], client: Client, mode: str = "apply") -> str:
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    folder = tmp_path / "be"
    folder.mkdir()
    write_text_pdf(folder / "irat.pdf", lines)
    with jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="Mesterséges irat")
        work.assign_recipe(wp["id"], recipe, params=params, expected_revision=0, actor="t")
        r = work.readiness(wp["id"])
        run_id = work.start_run(wp["id"], mode=mode, expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")["run_id"]
        worker.process(queue.claim("t", kinds=(work.JOB_KIND,)))
    return run_id


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield tmp_path


def test_text_less_document_blocks_approval_with_an_ocr_reason(isolated, monkeypatch):
    monkeypatch.setattr(ocr, "ocr_with_escalation", _no_ocr)
    run_id = _run(isolated, recipe="invoice-extraction", params={"arm": "S", "doc_type": "invoice_hu"}, lines=[], client=Client())
    item = work.get_run(run_id)["items"][0]
    assert item["final_status"] == "needs_ocr"
    own = work.items_reasons(run_id, work.get_run(run_id)["input"]["items"])[item["item_id"]]["run"]
    assert any(r["reason"].startswith("ocr:") for r in own)
    assert work.refresh_run_status(run_id) == "needs_review"
    with pytest.raises(work.NotReady):
        work.approve_run(run_id, actor="t")


def test_text_less_document_in_document_recipe_blocks_approval(isolated, monkeypatch):
    monkeypatch.setattr(ocr, "ocr_with_escalation", _no_ocr)
    run_id = _run(isolated, recipe="processing", params={"arm": "S"}, lines=[], client=Client())
    assert work.refresh_run_status(run_id) == "needs_review"
    with pytest.raises(work.NotReady):
        work.approve_run(run_id, actor="t")


def test_detect_stage_reasons_belong_to_the_run(isolated):
    run_id = _run(isolated, recipe="processing", params={"arm": "S"}, lines=INVOICE_LINES, client=Client(type_conf=0.40))
    run = work.get_run(run_id)
    split = work.items_reasons(run_id, run["input"]["items"])[run["items"][0]["item_id"]]
    assert any(r["reason"].startswith("detect:low_conf:") for r in split["run"])
    assert not split["earlier"]
    assert all(r["run_id"].startswith(run["items"][0]["flow_run_id"]) for r in split["run"])
    assert work.refresh_run_status(run_id) == "needs_review"
    with pytest.raises(work.NotReady):
        work.approve_run(run_id, actor="t")


def test_reason_of_another_item_with_a_similar_prefix_is_not_the_runs():
    own = work.flow_run_id("run-abc", "0123456789abcdef-extra")
    assert work.is_own_reason({"run_id": own}, own)
    assert work.is_own_reason({"run_id": f"{own}-doc_detect"}, own)
    assert not work.is_own_reason({"run_id": f"{own}x"}, own)
    assert not work.is_own_reason({"run_id": "run-older:0123456789abcdef"}, own)
    assert not work.is_own_reason({"run_id": None}, own)


# --- Á06 (decision of 2026-09-29): the reason of an unapproved live run does not move away -------------------------


def _two_runs(tmp_path: Path, first_mode: str, *, second_client: Client | None = None) -> tuple[str, str, str]:
    """Two runs in a row on the same document; the first one's detection is uncertain (to-do), the second uses
    `second_client`."""
    folder = tmp_path / "be"
    folder.mkdir()
    write_text_pdf(folder / "irat.pdf", INVOICE_LINES)
    runs = []
    for mode, client in ((first_mode, Client(type_conf=0.40)), ("shadow", second_client or Client(type_conf=0.40))):
        adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / f"cache-{len(runs)}", model="jev-1.13.0")
        with jev_mod.use_adapter(adapter):
            if not runs:
                wp = work.create_from_folder(folder, name="Mesterséges irat")
                work.assign_recipe(wp["id"], "processing", params={"arm": "S"}, expected_revision=0, actor="t")
            r = work.readiness(wp["id"])
            runs.append(work.start_run(wp["id"], mode=mode, expected_assignment_revision=1, input_hash=r["input_hash"], actor="t",
                                       **({"rerun_of": runs[-1]} if runs else {}))["run_id"])
            worker.process(queue.claim("t", kinds=(work.JOB_KIND,)))
    item_id = work.get_run(runs[0])["input"]["items"][0]["item_id"]
    return runs[0], runs[1], item_id


def _own(run_id: str, item_id: str) -> list[str]:
    return [r["reason"] for r in work.item_reasons(run_id, item_id)["run"]]


def test_later_run_does_not_take_over_the_reason_of_an_unapproved_live_run(isolated):
    live, later, item = _two_runs(isolated, "apply")
    assert any(r.startswith("detect:low_conf:") for r in _own(live, item))
    assert any(r.startswith("detect:low_conf:") for r in _own(later, item))
    assert work.refresh_run_status(live) == "needs_review"
    with pytest.raises(work.NotReady):
        work.approve_run(live, actor="t")


def test_later_confident_run_does_not_close_the_reason_of_an_unapproved_live_run(isolated):
    live, later, item = _two_runs(isolated, "apply", second_client=Client())
    assert not any(r.startswith("detect:low_conf:") for r in _own(later, item))
    assert any(r.startswith("detect:low_conf:") for r in _own(live, item))
    with pytest.raises(work.NotReady):
        work.approve_run(live, actor="t")


def test_trial_run_reason_still_moves_to_the_latest_run(isolated):
    trial, later, item = _two_runs(isolated, "shadow")
    assert not any(r.startswith("detect:low_conf:") for r in _own(trial, item))
    assert any(r.startswith("detect:low_conf:") for r in _own(later, item))
    open_on_doc = [r["reason"] for r in store.review_open_reasons("document", item) if r["reason"].startswith("detect:low_conf:")]
    assert len(open_on_doc) == 1  # no duplicated to-do
