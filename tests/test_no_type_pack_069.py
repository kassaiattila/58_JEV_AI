"""069 (decision of 2026-09-29): if a document falls into a category without a detailed type pack (payment reminder,
certificate of completion, unknown document), a to-do is raised: there is no data extraction for this type. Until now
the item stopped without a to-do, so the live run could be approved (066: "document without a detailed type").
Synthetic document, fake JEV."""

from pathlib import Path

import pytest
from typesafe_sdk import Choice, SystemOneResponse

from jav import store, work
from jav.adapters import jev as jev_mod
from jav.detect import DetectResult
from jav.flow_detect import DetectState, _resolve_detail, save
from jav.runtime import worker
from tests.pdfgen import write_text_pdf


def test_category_without_type_pack_opens_a_task(tmp_path):
    with store.use_store(tmp_path / "d.sqlite"):
        for doc_id, broad in (("d1", "payment_reminder"), ("d2", "unknown")):
            result = DetectResult.model_construct(doc_type=broad, confidence=0.99, issuer_hu=0.9, probabilities={}, language="hu",
                                                  parent=None, parent_prob=None)
            state = DetectState(source_path="synthetic.pdf", doc_id=doc_id, page_count=1, run_id="r1", text_source="pdf",
                                text="Fizetési felszólítás", result=result, uncertain=False)
            _resolve_detail(state, None)
            save(state)
        assert [r["reason"] for r in store.review_open_reasons("document", "d1")] == ["detect:no_type_pack:payment_reminder"]
        assert [r["reason"] for r in store.review_open_reasons("document", "d2")] == ["detect:no_type_pack:unknown"]


class ReminderClient:
    """Type detection says payment reminder (with high confidence); for any other question, the first option."""

    def system_one(self, *, state, questions, model):
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                pick = "payment_reminder" if qid == "doc_type" else next(iter(q.criteria))
                answers[qid] = {"type": "choice", "choice": pick, "confidence": 0.97,
                                "probabilities": {k: (0.97 if k == pick else 0.03 / max(len(q.criteria) - 1, 1)) for k in q.criteria}}
            else:
                answers[qid] = {"type": "noul", "noul": 0.95}
        return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 500, "output_tokens": 0}, "answers": answers})


def test_document_run_with_such_an_item_cannot_be_approved(tmp_path: Path):
    folder = tmp_path / "bejovo"
    folder.mkdir()
    write_text_pdf(folder / "felszolitas.pdf", ["Minta Kft.", "FIZETÉSI FELSZÓLÍTÁS", "Kérjük, rendezze a lejárt tartozást.",
                                                "Számla sorszáma: MINTA-2026-001", "Tartozás összege: 12 500 Ft"])
    adapter = jev_mod.JevAdapter(client=ReminderClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="Felszólítás")
        # 120: with the unknown-document setting off, the earlier stop and the blocked approval hold
        work.assign_recipe(wp["id"], "processing", params={"arm": "S", "unknown_documents": "review"},
                           expected_revision=0, actor="t")
        r = work.readiness(wp["id"])
        run_id = work.start_run(wp["id"], mode="apply", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")["run_id"]
        assert worker.run_worker(once=True)["results"] == {"done": 1}
        item = work.get_run(run_id)["items"][0]
        assert item["final_status"] == "needs_review"
        assert [x["reason"] for x in store.review_open_reasons("document", item["item_id"])] == ["detect:no_type_pack:payment_reminder"]
        assert work.refresh_run_status(run_id) == "needs_review"
        with pytest.raises(work.NotReady):
            work.approve_run(run_id, actor="t")
