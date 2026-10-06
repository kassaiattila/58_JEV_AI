"""120: a text PDF whose type has no fitting type pack continues into source-bound general facts.

The decision of 2026-10-06: on by default in both document recipes, switchable per package. The type stays as
recognised and its uncertainty to-dos stay open; only the "no extraction for this type" to-do no longer applies.
Synthetic document, fake JEV and an in-process GPT agent; no paid call.
"""
import json
from types import SimpleNamespace

import pytest
from typesafe_sdk import Choice, SystemOneResponse

from jav import corrections, export, store, work
from jav.adapters import jev as jev_mod
from jav.readers import providers
from jav.readers.interpretation import ProposedExtraction
from jav.runtime import worker
from tests.pdfgen import write_text_pdf

LINES = ["Minta Kft.", "FIZETESI FELSZOLITAS", "Kerjuk, rendezze a lejart tartozast.",
         "Szamla sorszama: MINTA-2026-001", "Tartozas osszege: 12 500 Ft", "Fizetesi hatarido: 2026.10.15."]  # ASCII: tests/pdfgen.py


class Client:
    """The coarse type is `broad`; a detailed-type question answers "none of these"; every Noul is 0.95."""

    def __init__(self, broad: str, confidence: float = 0.97):
        self.broad, self.confidence = broad, confidence

    def system_one(self, *, state, questions, model):
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                if qid == "doc_type":
                    pick = self.broad
                else:
                    pick = "none" if "none" in q.criteria else next(iter(q.criteria))
                rest = (1 - self.confidence) / max(len(q.criteria) - 1, 1)
                answers[qid] = {"type": "choice", "choice": pick, "confidence": self.confidence,
                                "probabilities": {k: (self.confidence if k == pick else rest) for k in q.criteria}}
            else:
                answers[qid] = {"type": "noul", "noul": 0.95}
        return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 500, "output_tokens": 0},
                                                 "answers": answers})


class FactAgent:
    """GPT's place: one fact citing the element that holds the amount."""

    def __init__(self):
        self.calls = 0

    def run_sync(self, prompt, **kwargs):
        self.calls += 1
        view = json.loads(prompt)
        row = next(e for e in view["elements"] if "12 500 Ft" in e["text"])
        proposal = ProposedExtraction.model_validate_json(json.dumps({"facts": [{
            "entity": "reminder", "property": "amount due", "value": "12 500 Ft", "state": "stated",
            "citations": [{"occurrence_id": row["occurrence_id"], "element_id": row["element_id"],
                           "quote": "12 500 Ft"}]}]}))
        return SimpleNamespace(output=proposal, usage=SimpleNamespace(input_tokens=100, output_tokens=40),
                               response=SimpleNamespace(model_name="synthetic-model"))


@pytest.fixture()
def isolated(tmp_path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield tmp_path


def run_package(tmp_path, monkeypatch, *, broad, recipe="processing", params=None, confidence=0.97):
    folder = tmp_path / "incoming"
    folder.mkdir()
    write_text_pdf(folder / "document.pdf", LINES)
    client = Client(broad, confidence)
    original = jev_mod.JevAdapter
    adapter = original(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    monkeypatch.setattr(jev_mod, "JevAdapter", lambda **kw: original(client=client, model="jev-1.13.0", **kw))
    agent = FactAgent()
    extract = providers.extract_gpt
    monkeypatch.setattr(providers, "extract_gpt", lambda *a, **kw: extract(*a, agent=agent, **kw))
    with jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="Unknown documents")
        work.assign_recipe(wp["id"], recipe, params=params or {}, expected_revision=0, actor="t")
        ready = work.readiness(wp["id"])
        run_id = work.start_run(wp["id"], mode="apply", expected_assignment_revision=1,
                                input_hash=ready["input_hash"], actor="t")["run_id"]
        assert worker.run_worker(once=True)["results"] == {"done": 1}
    item = work.get_run(run_id)["items"][0]
    reasons = [r["reason"] for r in store.review_open_reasons("document", item["item_id"])]
    return run_id, item, reasons, agent


def test_a_type_without_a_pack_yields_source_bound_facts(isolated, monkeypatch):
    run_id, item, reasons, agent = run_package(isolated, monkeypatch, broad="payment_reminder")
    assert agent.calls == 1
    assert not any(r.startswith("detect:no_type_pack") for r in reasons)
    result = corrections.item_result(run_id, item["item_id"])
    assert result["result_kind"] == "native"
    assert [f["proposal"]["value"] for f in result["native_facts"]] == ["12 500 Ft"]
    assert result["native_facts"][0]["grounding"] == "literal_match"
    assert [r["file"] for r in export.native_records(run_id)] == ["document.pdf"]
    with store.connect() as c:  # the recognised type is kept as it was
        assert c.execute("SELECT doc_type FROM documents WHERE doc_id=?", (item["item_id"],)).fetchone()[0] == "payment_reminder"
    with pytest.raises(work.RevisionConflict):  # the native approval path: it needs the exact reviewed version
        work.approve_run(run_id, actor="t")


def test_other_without_a_fitting_pack_keeps_its_type_to_do_beside_the_facts(isolated, monkeypatch):
    run_id, item, reasons, agent = run_package(isolated, monkeypatch, broad="other", recipe="multi-format-processing")
    assert agent.calls == 1
    assert "detect:detail_open:other" in reasons
    assert item["final_status"] == "needs_review"
    assert corrections.item_result(run_id, item["item_id"])["result_kind"] == "native"


def test_an_unknown_type_keeps_its_uncertainty_beside_the_facts(isolated, monkeypatch):
    run_id, item, reasons, agent = run_package(isolated, monkeypatch, broad="unknown")
    assert agent.calls == 1
    assert any(r.startswith("detect:low_conf:unknown") for r in reasons)
    assert corrections.item_result(run_id, item["item_id"])["result_kind"] == "native"


def test_the_review_setting_keeps_the_earlier_stop(isolated, monkeypatch):
    run_id, item, reasons, agent = run_package(isolated, monkeypatch, broad="payment_reminder",
                                               params={"unknown_documents": "review"})
    assert agent.calls == 0
    assert reasons == ["detect:no_type_pack:payment_reminder"]
    assert corrections.item_result(run_id, item["item_id"]).get("result_kind") != "native"


@pytest.mark.parametrize("recipe", ["processing", "multi-format-processing"])
def test_both_document_recipes_default_to_general_facts(recipe):
    assert work.recipe(recipe)["params"]["unknown_documents"] == {"allowed": ["facts", "review"], "default": "facts"}


@pytest.mark.parametrize("detect,expected", [
    ({"final_status": "done", "text_source": "pdf", "result": {"doc_type": "payment_reminder"},
      "detail": {"key": None, "method": "no_candidate"}, "detail_reasons": []}, True),
    ({"final_status": "done", "text_source": "pdf", "result": {"doc_type": "unknown"}, "detail": None,
      "detail_reasons": []}, True),
    ({"final_status": "done", "text_source": "ocr", "result": {"doc_type": "payment_reminder"},
      "detail": {"key": None, "method": "no_candidate"}, "detail_reasons": []}, True),  # a scan: local OCR
    ({"final_status": "done", "text_source": None, "result": {"doc_type": "unknown"}, "detail": None,
      "detail_reasons": []}, False),
    ({"final_status": "done", "text_source": "pdf", "result": {"doc_type": "other"},
      "detail": {"key": None, "method": "no_jev"}, "detail_reasons": ["jev_unavailable:timeout"]}, False),
    ({"final_status": "jev_unavailable", "text_source": "pdf", "result": None, "detail": None,
      "detail_reasons": []}, False),
])
def test_only_a_readable_pdf_without_a_fitting_pack_continues(detect, expected):
    params = {"unknown_documents": "facts", "jev": "on", "arm": "auto"}
    item = {"kind": "document", "source_path": "C:/synthetic/document.pdf"}
    assert (worker.native_fallback(params, item, detect) is not None) == expected
    assert worker.native_fallback({**params, "unknown_documents": "review"}, item, detect) is None


@pytest.mark.parametrize("text_source,ocr", [("pdf", False), ("ocr", True)])
def test_a_scanned_pdf_continues_with_the_readers_local_ocr(text_source, ocr):
    detect = {"final_status": "done", "text_source": text_source, "result": {"doc_type": "unknown"}, "detail": None,
              "detail_reasons": []}
    params = worker.native_fallback({"unknown_documents": "facts", "jev": "on", "arm": "S"},
                                    {"kind": "document", "source_path": "C:/synthetic/scan.pdf"}, detect)
    assert params["arm"] == "G" and params["native_ocr"] is ocr


def test_the_continuing_stage_asks_the_native_graph_for_local_ocr(monkeypatch):
    from jav import flow_native

    seen = {}

    def build_app(**kwargs):
        seen.update(kwargs)
        return "app"

    monkeypatch.setattr(flow_native, "build_app", build_app)
    app, _ = worker._build({"flow": "native"}, {"arm": "G", "jev": "on", "native_ocr": True}, "C:/synthetic/scan.pdf",
                           "graph-1", None, run_id="run-1", item={"item_id": "a" * 64, "sha256": "a" * 64},
                           recipe_hash="b" * 16)
    assert app == "app" and seen["ocr"] is True and seen["requested_arm"] == "G"


def test_an_ocr_reading_has_its_own_identity_and_a_plain_reading_keeps_its_old_one(tmp_path, monkeypatch):
    import hashlib
    from jav import native_results
    from jav.readers import pipeline
    from jav.readers.limits import DEFAULT_LIMITS
    from jav.readers.pipeline import digest, json_bytes

    source = tmp_path / "statement.txt"
    source.write_bytes(b"Statement: 0012\n")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    asked = []
    original = pipeline.read_files
    monkeypatch.setattr(pipeline, "read_files", lambda paths, **kw: asked.append(kw["ocr"]) or original(paths, **kw))
    with store.use_store(tmp_path / "native.sqlite"):
        plain = native_results.prepare_reading(source, original_name="statement.txt", expected_sha256=sha)
        recognised = native_results.prepare_reading(source, original_name="statement.txt", expected_sha256=sha, ocr=True)
    old_key = digest(json_bytes({"source": sha, "name": "statement.txt", "reader": pipeline.implementation_version(),
                                 "limits": DEFAULT_LIMITS.model_dump(mode="json")}))
    assert asked == [False, True]
    assert plain.reading_id == "reading:" + old_key and recognised.reading_id != plain.reading_id


def test_the_native_graph_reads_with_ocr_only_when_asked(tmp_path, monkeypatch):
    from jav import flow_native, native_results

    asked = []

    def prepare(read_path, **kwargs):
        asked.append(kwargs.get("ocr", False))
        raise RuntimeError("stop after the reading request")

    monkeypatch.setattr(native_results, "prepare_reading", prepare)
    with store.use_store(tmp_path / "native.sqlite"):
        for ocr in (False, True):
            app = flow_native.build_app(work_run_id="r", item_id="i", graph_id=f"g{ocr}", source_path="C:/s/scan.pdf",
                                        read_path="C:/s/scan.pdf", original_name="scan.pdf", expected_sha256="a" * 64,
                                        recipe_hash="b" * 16, jev=False, ocr=ocr)
            with pytest.raises(RuntimeError):
                app.run(halt_after=flow_native.TERMINALS)
    assert asked == [False, True]

