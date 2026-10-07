"""124 (F-azure-text-native, steps 2-6): an unknown scanned PDF is read from its Azure recognition.

When document detection's weak local text was escalated to Azure, detection names the kept original recognition,
and the worker hands that name to the general (native) extraction. The native reader maps the original word
polygons onto the frozen PDF pages, checks them against the document, and keeps the recognition as evidence, so the
reading can be complete. Synthetic documents, a fake Azure client and in-process models; no network, no paid call.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from unittest.mock import patch

import pytest

from jav import flow_detect, ocr
from jav.adapters import azure_di
from jav.pdf import PdfText
from jav.runtime import calls, worker
from tests.test_azure_direct_121 import RESULT, FakeAzure, keys, weak_scan  # noqa: F401 - fixtures


def _detect_ocr(source, scope: str = "run-on"):
    calls.set_budget(scope, "azure_di", Decimal("0.02"))
    state = flow_detect.DetectState(source_path=str(source), doc_id=hashlib.sha256(source.read_bytes()).hexdigest(),
                                    page_count=1)
    with calls.use_run(budget_scope=scope), patch.object(azure_di.time, "sleep"):
        return flow_detect.ocr_pdf(state)


def test_detection_names_the_azure_recognition_whose_text_went_on(weak_scan, keys):  # noqa: F811
    with patch("urllib.request.urlopen", FakeAzure()):
        state = _detect_ocr(weak_scan)
    assert "Payable 1000" in state.lines
    assert state.ocr_recognition == ocr.recognition_digest(azure_di.evidence(RESULT["analyzeResult"]))


def test_detection_names_no_recognition_when_local_text_went_on(weak_scan, monkeypatch):  # noqa: F811
    local = PdfText(path=str(weak_scan), text="good", lines=["good"], text_source="ocr",
                    ocr={"engine": "native", "mean_conf": 0.97, "low_conf_ratio": 0.01})
    monkeypatch.setattr(ocr, "ocr_pdf", lambda path, **kwargs: local)
    state = _detect_ocr(weak_scan)
    assert state.lines == ["good"] and state.ocr_recognition is None


DETECTED_SCAN = {"final_status": "done", "text_source": "ocr", "result": {"doc_type": "unknown"}, "detail": None,
                 "detail_reasons": []}
SCAN_ITEM = {"kind": "document", "source_path": "C:/synthetic/scan.pdf"}


@pytest.mark.parametrize("recognition", ["c" * 64, None])
def test_the_worker_hands_the_named_recognition_to_the_native_stage(recognition, monkeypatch):
    from jav import flow_native

    params = worker.native_fallback({"unknown_documents": "facts", "jev": "on", "arm": "auto"}, SCAN_ITEM,
                                    {**DETECTED_SCAN, "ocr_recognition": recognition})
    assert params["native_ocr"] is True and params.get("native_recognition") == recognition
    seen = {}
    monkeypatch.setattr(flow_native, "build_app", lambda **kwargs: seen.update(kwargs) or "app")
    worker._build({"flow": "native"}, params, "C:/synthetic/scan.pdf", "graph-1", None, run_id="run-1",
                  item={"item_id": "a" * 64, "sha256": "a" * 64}, recipe_hash="b" * 16)
    assert seen["ocr"] is True and seen["recognition"] == recognition


def test_a_saved_native_state_without_a_recognition_still_loads():
    from jav.flow_native import NativeState

    saved = {"work_run_id": "r", "item_id": "i", "graph_id": "g", "source_path": "s.pdf", "read_path": "s.pdf",
             "original_name": "s.pdf", "expected_sha256": "a" * 64, "recipe_hash": "b" * 16, "jev": True,
             "use_cache": True, "limits": {}, "ocr": True}
    assert NativeState.model_validate(saved).recognition is None


# --- steps 3-4: the reader takes the recognition over -----------------------------------------------------------


def scan_pdf(folder, pages: int = 1):
    """An image-only PDF: 600 x 200 pixels at 150 DPI, so every page is 288 x 96 points (4 x 1.3333 inches)."""
    from io import BytesIO

    from PIL import Image, ImageDraw, ImageFont

    pictures = []
    for number in range(1, pages + 1):
        picture = Image.new("RGB", (600, 200), "white")
        ImageDraw.Draw(picture).text((40, 60), f"PAGE {number}", fill="black", font=ImageFont.load_default(size=40))
        pictures.append(picture)
    buffer = BytesIO()
    pictures[0].save(buffer, "PDF", resolution=150, save_all=True, append_images=pictures[1:])
    path = folder / "scan.pdf"
    path.write_bytes(buffer.getvalue())
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def azure_page(number: int, *words: tuple[str, float, float, float], width: float = 4.0,
               height: float = 1.3333, unit: str = "inch") -> dict:
    """`words`: (text, left inch, top inch, confidence); every word is 0.8 x 0.3 inches."""
    return {"page_number": number, "width": width, "height": height, "unit": unit, "angle": 0.0, "words_present": True,
            "words": [{"content": text, "confidence": conf, "span": {"offset": 0, "length": len(text)},
                       "polygon": [x, y, x + 0.8, y, x + 0.8, y + 0.3, x, y + 0.3]} for text, x, y, conf in words],
            "lines": [" ".join(w[0] for w in words)]}


def azure_recognition(*pages: dict) -> dict:
    return {"provider": "azure_di", "content": "\n".join(p["lines"][0] for p in pages), "model_id": "prebuilt-read",
            "api_version": "2024-11-30", "pages": list(pages)}


SCAN_TEXT = azure_page(1, ("Declaration", 0.3, 0.4, 0.99), ("2026", 1.2, 0.4, 0.98))


@pytest.fixture
def no_local_ocr(monkeypatch):
    from jav.readers import visual_ocr

    def refuse():
        raise AssertionError("local OCR must not run when an Azure recognition is taken over")

    monkeypatch.setattr(visual_ocr.LocalOCR, "discover", refuse)


def read_scan(folder, recognition: dict, *, pages: int = 1):
    from jav import native_results, store

    path, sha = scan_pdf(folder, pages)
    with store.use_store(folder / "native.sqlite"):
        digest = ocr.save_recognition(recognition)
        ref = native_results.prepare_reading(path, original_name="scan.pdf", expected_sha256=sha, recognition=digest)
        delivery = native_results.load_reading(ref.reading_id)
    return ref, delivery, sha, digest


def test_a_scan_read_from_its_azure_recognition_is_complete(tmp_path, no_local_ocr):
    ref, delivery, sha, digest = read_scan(tmp_path, azure_recognition(SCAN_TEXT))
    result = delivery.bundle.results[0]
    assert ref.reading.status == "complete" and result.issues == ()
    assert [e.text for e in result.elements if e.text] == ["Declaration 2026"]
    external = result.attempt.external_recognition
    assert (external.provider, external.request_sha256, external.response_sha256) == ("azure_di", sha, digest)
    assert result.attempt.recognition_protections is None
    summary = ref.reading.results[0].recognition
    assert (summary.provider, summary.pages, summary.words) == ("azure_di", (1,), 2)
    assert (summary.mean_conf, summary.low_conf_ratio) == (0.985, 0.0)


def _needs_ocr(result) -> list[str]:
    return [i.message for i in result.issues if i.code == "needs_ocr"]


def test_a_page_whose_size_differs_stays_explicitly_unread(tmp_path, no_local_ocr):
    rotated = azure_page(1, ("Declaration", 0.3, 0.4, 0.99), width=1.3333, height=4.0)
    ref, delivery, _sha, _digest = read_scan(tmp_path, azure_recognition(rotated))
    result = delivery.bundle.results[0]
    assert ref.reading.status == "partial" and not [e.text for e in result.elements if e.text]
    assert _needs_ocr(result) == ["Azure recognition was not taken over for page 1: its page size differs from the "
                                  "PDF page (a rotated or cropped page)"]
    assert ref.reading.results[0].recognition.pages == ()


def test_a_partly_covering_recognition_leaves_the_other_pages_unread(tmp_path, no_local_ocr):
    ref, delivery, _sha, _digest = read_scan(tmp_path, azure_recognition(SCAN_TEXT), pages=2)
    result = delivery.bundle.results[0]
    assert [e.text for e in result.elements if e.text] == ["Declaration 2026"]
    assert _needs_ocr(result) == ["Azure recognition was not taken over for page 2: the recognition does not cover "
                                  "this page"]
    assert ref.reading.status == "partial" and ref.reading.results[0].recognition.pages == (1,)


@pytest.mark.parametrize("recognition,reason", [
    (azure_recognition(SCAN_TEXT, azure_page(2, ("Extra", 0.3, 0.4, 0.9))),
     "the recognition's pages do not match the document's pages"),
    (azure_recognition(azure_page(1, ("Outside", 3.9, 0.4, 0.9))), "a recognised word lies outside the page"),
    (azure_recognition(azure_page(1, ("Pixels", 0.3, 0.4, 0.9), unit="pixel")), "its unit is not inch"),
])
def test_a_recognition_that_does_not_fit_the_document_is_not_taken_over(tmp_path, no_local_ocr, recognition, reason):
    ref, delivery, _sha, _digest = read_scan(tmp_path, recognition)
    assert ref.reading.status == "partial"
    assert _needs_ocr(delivery.bundle.results[0]) == [f"Azure recognition was not taken over for page 1: {reason}"]


def test_a_changed_kept_recognition_is_refused_on_loading(tmp_path, no_local_ocr):
    from jav import native_results, store

    ref, _delivery, _sha, digest = read_scan(tmp_path, azure_recognition(SCAN_TEXT))
    with store.use_store(tmp_path / "native.sqlite"):
        kept = native_results._path(ref.artifact_relpath) / "recognitions" / digest
        kept.write_bytes(kept.read_bytes().replace(b"Declaration", b"Declarati0n"))
        with pytest.raises(native_results.NativeIntegrityError, match="damaged or missing evidence"):
            native_results.load_reading(ref.reading_id)


def test_the_recognition_is_part_of_the_reading_identity_and_must_exist(tmp_path, no_local_ocr):
    from jav import native_results, store

    ref, _delivery, _sha, _digest = read_scan(tmp_path, azure_recognition(SCAN_TEXT))
    other = azure_recognition(azure_page(1, ("Declaration", 0.3, 0.4, 0.5)))
    path, sha = scan_pdf(tmp_path)
    with store.use_store(tmp_path / "native.sqlite"):
        second = native_results.prepare_reading(path, original_name="scan.pdf", expected_sha256=sha,
                                                recognition=ocr.save_recognition(other))
        with pytest.raises(native_results.NativeIntegrityError, match="missing or changed"):
            native_results.prepare_reading(path, original_name="scan.pdf", expected_sha256=sha, recognition="0" * 64)
    assert second.reading_id != ref.reading_id
    assert second.reading.results[0].recognition.mean_conf == 0.5


def test_the_source_contract_binds_an_external_recognition_to_its_source():
    from jav.readers.contracts import ParseAttempt, Protections
    from jav.readers.external_recognition import describe
    from jav.readers.limits import DEFAULT_LIMITS
    from jav.readers.pipeline import json_bytes

    enforced = Protections(**dict.fromkeys(Protections.model_fields, "enforced"))
    external = describe(json_bytes(azure_recognition(SCAN_TEXT)), "a" * 64)
    base = dict(attempt_id="read:o0", occurrence_id="o0", source_sha256="a" * 64, parser_name="pdf",
                parser_version="native-1:x", config_sha256="b" * 64, models_sha256="c" * 64, execution="reader",
                limits=DEFAULT_LIMITS, protections=enforced)
    plain, taken = ParseAttempt(**base), ParseAttempt(**base, external_recognition=external)
    assert "external_recognition" not in plain.model_dump(mode="json") and plain.reader_key() != taken.reader_key()
    with pytest.raises(ValueError, match="of the frozen source"):
        ParseAttempt(**{**base, "source_sha256": "d" * 64}, external_recognition=external)
    with pytest.raises(ValueError, match="excludes local recognition"):
        ParseAttempt(**base, parser_protections=enforced, recognition_protections=enforced,
                     external_recognition=external)


def test_the_native_graph_reads_the_handed_over_recognition(tmp_path, monkeypatch):
    from jav import flow_native, native_results, store

    asked = []

    def prepare(read_path, **kwargs):
        asked.append((kwargs.get("ocr"), kwargs.get("recognition")))
        raise RuntimeError("stop after the reading request")

    monkeypatch.setattr(native_results, "prepare_reading", prepare)
    with store.use_store(tmp_path / "native.sqlite"):
        app = flow_native.build_app(work_run_id="r", item_id="i", graph_id="g", source_path="C:/s/scan.pdf",
                                    read_path="C:/s/scan.pdf", original_name="scan.pdf", expected_sha256="a" * 64,
                                    recipe_hash="b" * 16, jev=False, ocr=True, recognition="c" * 64)
        with pytest.raises(RuntimeError):
            app.run(halt_after=flow_native.TERMINALS)
    assert asked == [(True, "c" * 64)]


# --- steps 5-6: the native step's own Azure call, and the to-dos -------------------------------------------------


def scan_result(*pages: dict) -> dict:
    """The REST answer whose evidence is `azure_recognition(*pages)`."""
    return {"status": "succeeded", "analyzeResult": {
        "apiVersion": "2024-11-30", "modelId": "prebuilt-read", "content": "\n".join(p["lines"][0] for p in pages),
        "pages": [{"pageNumber": p["page_number"], "angle": p["angle"], "width": p["width"], "height": p["height"],
                   "unit": p["unit"], "words": p["words"], "lines": [{"content": line} for line in p["lines"]]}
                  for p in pages]}}


@pytest.fixture
def scan_run(tmp_path, monkeypatch):
    """A scanned PDF as a frozen run item, an in-process reader and GPT; Azure needs `keys` and a budget."""
    from jav import store
    from native_fixtures_109 import runtime_source, synthetic_gpt

    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "ocr-cache")
    with store.use_store(tmp_path / "native.sqlite"):
        pdf, _sha = scan_pdf(tmp_path)
        source, ref = runtime_source(tmp_path, monkeypatch, name="frozen.pdf", content=pdf.read_bytes())
        requests = synthetic_gpt(monkeypatch, payload={"facts": [{
            "entity": "declaration", "property": "year", "value": "2026", "state": "stated",
            "citations": [{"occurrence_id": "o0", "element_id": "e1", "quote": "Declaration 2026"}]}], "gaps": []})
        yield source, ref, requests


class LocalScanOCR:
    fingerprint = "a" * 64

    def recognise(self, png, limits, *, timeout):
        return ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                "5\t1\t1\t1\t1\t1\t40\t60\t220\t42\t95\tLOCAL\n")


def run_native(source, ref, *, budgets: dict, recognition: str | None = None, fake=None):
    from jav import flow_native

    app = flow_native.build_app(work_run_id="native-run", item_id="native-item", graph_id="native-graph",
        source_path=str(source), read_path=str(source), original_name="original.pdf",
        expected_sha256=ref.source_sha256, recipe_hash="a" * 16, jev=False, use_cache=False, ocr=True,
        recognition=recognition)
    with calls.measurement("native-run", budgets), patch("urllib.request.urlopen", fake or FakeAzure()), \
            patch.object(azure_di.time, "sleep"):
        _, _, state = app.run(halt_after=flow_native.TERMINALS)
    return state.data


def _azure_calls() -> list:
    from jav import store

    with store.connect() as c:
        return [r[0] for r in c.execute("SELECT status FROM invocations WHERE provider='azure_di'")]


def test_a_scan_without_an_azure_text_is_recognised_within_the_run_budget(scan_run, keys, no_local_ocr):  # noqa: F811
    source, ref, _requests = scan_run
    fake = FakeAzure(polls=[{"status": "running"}, scan_result(SCAN_TEXT)])
    state = run_native(source, ref, budgets={"openai": Decimal("1"), "azure_di": Decimal("0.02")}, fake=fake)
    assert state.recognition == ocr.recognition_digest(azure_recognition(SCAN_TEXT))
    assert state.recognition_blocked is None and _azure_calls() == ["succeeded"]
    assert state.final_status == "done" and state.review_reasons == []


def test_without_an_azure_budget_the_scan_keeps_local_ocr_without_a_new_to_do(scan_run, keys, monkeypatch):  # noqa: F811
    from jav.readers import visual_ocr

    monkeypatch.setattr(visual_ocr.LocalOCR, "discover", lambda: LocalScanOCR())
    source, ref, _requests = scan_run
    state = run_native(source, ref, budgets={"openai": Decimal("1")})
    assert (state.recognition, state.recognition_blocked, _azure_calls()) == (None, "off", [])
    assert "native:reading:partial" in state.review_reasons
    assert not any(r.startswith("native:recognition") for r in state.review_reasons)


def test_an_azure_call_the_budget_does_not_allow_leaves_local_ocr_and_a_to_do(scan_run, keys, monkeypatch):  # noqa: F811
    from jav.readers import visual_ocr

    monkeypatch.setattr(visual_ocr.LocalOCR, "discover", lambda: LocalScanOCR())
    source, ref, _requests = scan_run
    state = run_native(source, ref, budgets={"openai": Decimal("1"), "azure_di": Decimal("0.000001")})
    assert state.recognition is None and _azure_calls() == []
    assert "native:recognition:azure_blocked:budget_exceeded" in state.review_reasons


def test_a_weak_azure_recognition_is_complete_but_opens_a_to_do(scan_run):
    from jav import store

    source, ref, _requests = scan_run
    weak = azure_recognition(azure_page(1, ("Declaration", 0.3, 0.4, 0.5), ("2026", 1.2, 0.4, 0.4)))
    with store.use_store(store.active_path()):
        digest = ocr.save_recognition(weak)
    state = run_native(source, ref, budgets={"openai": Decimal("1")}, recognition=digest)
    assert "native:reading:complete" not in state.review_reasons
    assert {"native:recognition:low_confidence:0.45", "native:recognition:low_conf_words:1.00"} <= set(
        state.review_reasons)
    assert state.final_status == "needs_review" and _azure_calls() == []
