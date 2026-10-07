"""The real flows on the shared trial runner: identical input, durable resume."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from typesafe_sdk import Choice, SystemOneResponse

from jav import store
from jav.adapters.jev import JevAdapter
from jav.experiments.stack_trial import trial_services, TypedAdapter


class DetectClient:
    def __init__(self):
        self.requests = []

    def system_one(self, *, state, questions, model):
        self.requests.append((state, questions))
        answers = {}
        for name, q in questions.items():
            if isinstance(q, Choice):
                value = "invoice_hu" if name == "doc_type" else "hu"
                answers[name] = dict(type="choice", choice=value, confidence=.99,
                                     probabilities={k: .99 if k == value else .01/(len(q.criteria)-1) for k in q.criteria})
            else:
                answers[name] = dict(type="noul", noul=.99)
        return SystemOneResponse.model_validate(dict(model=model, answers=answers,
                                                      usage=dict(input_tokens=123, output_tokens=0)))


def test_existing_detection_uses_typed_adapter_and_isolated_store(tmp_path):
    from jav.detect import detect
    from jav.pdf import PdfText
    from jav.adapters.jev import get_adapter
    client = DetectClient()
    base = JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    adapted = TypedAdapter(base)
    original = get_adapter()
    pdf = PdfText(path="example.pdf", text="Számla magyar kiállítótól", lines=["Számla magyar kiállítótól"], page_count=1)
    with trial_services(adapted, tmp_path / "trial.sqlite"):
        result = detect(get_adapter(), pdf, "example.pdf", run_id="typed")
        assert result.doc_type == "invoice_hu" and result.issuer_hu == .99
        assert store.ledger_for_run("typed")[0]["step"] == "detect"
    assert get_adapter() is original
    assert len(client.requests) == 1
    # The canonical JSON text used on both branches gets no extra layer of quoting.
    assert json.loads(client.requests[0][0])["filename"] == "example.pdf"


def test_real_burr_flow_resumes_after_model_and_saves_only_once(tmp_path, monkeypatch):
    from jav.experiments.stack_trial import run_trial, DirectAdapter
    from jav.pdf import PdfText
    source = tmp_path / "example.pdf"
    source.write_bytes(b"fake pdf read at the file boundary")
    monkeypatch.setattr("jav.pdf.read_pdf", lambda path: PdfText(path=str(path), text="Számla magyar kiállítótól",
                         lines=["Számla magyar kiállítótól"], page_count=1, has_text_layer=True, text_source="pdf"))
    client = DetectClient()
    adapter = DirectAdapter(JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0"))
    first = run_trial("detect", str(source), tmp_path, "same-run", adapter, halt_after=["detect"])
    assert first.result.doc_type == "invoice_hu" and first.final_status is None
    resumed = run_trial("detect", str(source), tmp_path, "same-run", adapter)
    again = run_trial("detect", str(source), tmp_path, "same-run", adapter)
    assert resumed.final_status == again.final_status == "done"
    assert len(client.requests) == 1  # An AI step that is already saved does not run again.
    with store.use_store(tmp_path / "business.sqlite"):
        assert store.stats()["documents"] == 1
        assert len(store.ledger_for_run("same-run")) == 1
    source.write_bytes(b"changed input")
    import pytest
    with pytest.raises(ValueError, match="identity"):
        run_trial("detect", str(source), tmp_path, "same-run", adapter)


@pytest.mark.parametrize("point,expected_calls", [
    ("before_action:detect", 1), ("after_wire", 2),
    ("after_action:detect", 1), ("before_action:save", 1), ("after_action:save", 1),
])
def test_process_kill_resume_preserves_one_document(tmp_path, point, expected_calls):
    args = [sys.executable, str(Path(__file__).resolve()), str(tmp_path), point]
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
    first = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=30, env=env)
    assert first.returncode == 79, first.stderr
    second = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=30, env=env)
    assert second.returncode == 0, second.stderr
    evidence = json.loads((tmp_path / "recovery.json").read_text())
    assert evidence == {"documents": 1, "review_open": 0, "model_calls": expected_calls, "status": "done"}


@pytest.mark.parametrize("kind", ["timeout", "rate_limit", "malformed", "missing_answer"])
@pytest.mark.parametrize("typed", [False, True])
def test_provider_failure_is_saved_for_review_without_automatic_acceptance(tmp_path, monkeypatch, kind, typed):
    from typesafe_sdk import TypeSafeAPITimeoutError, TypeSafeRateLimitError
    import httpx2
    from jav.experiments.stack_trial import run_trial, DirectAdapter
    from jav.pdf import PdfText
    source = tmp_path / "failure.pdf"
    source.write_bytes(b"failure test")
    monkeypatch.setattr("jav.pdf.read_pdf", lambda path: PdfText(path=str(path), text="Example invoice",
                       lines=["Example invoice"], page_count=1, has_text_layer=True, text_source="pdf"))

    class FailureClient:
        calls = 0

        def system_one(self, **kwargs):
            self.calls += 1
            if kind == "timeout":
                raise TypeSafeAPITimeoutError("synthetic timeout")
            if kind == "rate_limit":
                raise TypeSafeRateLimitError(429, {"detail": "synthetic"}, httpx2.Headers({"retry-after-ms": "10"}))
            if kind == "missing_answer":
                return SystemOneResponse.model_validate({"model": "jev-1.13.0", "usage": {"input_tokens": 1, "output_tokens": 0}, "answers": {}})
            return SystemOneResponse.model_validate({"answers": {"doc_type": {"type": "choice", "choice": []}}})

    client = FailureClient()
    cls = TypedAdapter if typed else DirectAdapter
    adapter = cls(JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0"))
    result = run_trial("detect", str(source), tmp_path, "failed", adapter)
    assert result.uncertain and result.result is None and result.final_status == "jev_unavailable"
    assert client.calls == 1
    with store.use_store(tmp_path / "business.sqlite"):
        assert store.stats()["review_open"] == 1
        assert store.ledger_for_run("failed")[0]["error"]


@pytest.mark.parametrize("typed", [False, True])
def test_invoice_write_then_crash_replays_without_duplicate_datapoints(tmp_path, monkeypatch, typed):
    from jav.experiments.stack_trial import run_trial, DirectAdapter
    from jav.pdf import PdfText
    from jav.models import LineLayout, CellLayout
    source = tmp_path / "invoice.pdf"
    source.write_bytes(b"invoice fixture")
    texts = ["Seller Kft.", "Buyer Kft.", "Szamla TEST-2026-1", "2026.01.01.",
             "Netto 1000 HUF", "Afa 270 HUF", "Osszesen 1270 HUF"]
    layout = [LineLayout(no=i, page=1, text=t, cells=[CellLayout(text=t, x0=30, x1=300)]) for i, t in enumerate(texts, 1)]
    monkeypatch.setattr("jav.pdf.read_pdf", lambda path: PdfText(path=str(path), text="\n".join(texts),
        lines=texts, layout=layout, page_count=1, has_text_layer=True, text_source="pdf"))

    class Client:
        calls = 0

        def system_one(self, *, state, questions, model):
            self.calls += 1
            answers = {}
            for key, q in questions.items():
                if isinstance(q, Choice):
                    choice = next(k for k in q.criteria if k != "none")
                    answers[key] = dict(type="choice", choice=choice, confidence=.8,
                        probabilities={k: 1. if k == choice else 0. for k in q.criteria})
                else:
                    answers[key] = dict(type="noul", noul=.99)
            return SystemOneResponse.model_validate(dict(model=model, answers=answers, usage=dict(input_tokens=123, output_tokens=0)))

    client = Client()
    adapter = (TypedAdapter if typed else DirectAdapter)(JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0"))
    def fault(point):
        if point == "after_action:save":
            raise RuntimeError("simulated interruption after business commit")
    with pytest.raises(RuntimeError, match="simulated interruption"):
        run_trial("invoice", str(source), tmp_path, "invoice-run", adapter, fault=fault)
    calls = client.calls
    state = run_trial("invoice", str(source), tmp_path, "invoice-run", adapter)
    assert state.invoice is not None
    from datetime import date
    from decimal import Decimal
    assert state.invoice.issue_date == date(2026, 1, 1)
    assert isinstance(state.invoice.net_total, Decimal)
    assert client.calls == calls
    with store.use_store(tmp_path / "business.sqlite"):
        stats = store.stats()
        assert stats["documents"] == stats["datapoints"] == stats["review_open"] == 1


def test_summary_does_not_call_empty_invoice_or_uncertain_label_correct():
    from jav.experiments.run_stack_trial import summarize
    base = dict(arm="sdk", split="evaluation", repeat=0, mode="live", wall_seconds=1,
                cost_usd=0, input_tokens=0, calls=0, cached_calls=0)
    rows = [dict(base, case_id="missing", flow="invoice", correct=False, automatic=False,
                 error="offline", field_checks={"gross_total": False, "due_date": False}, expected_line_count=2),
            dict(base, case_id="ambiguous", flow="detect", correct=None, automatic=True, actual="receipt")]
    result = summarize(rows)
    assert result["invoice/sdk/evaluation"]["total_fields"] == 2
    assert result["invoice/sdk/evaluation"]["correct_fields"] == 0
    assert result["invoice/sdk/evaluation"]["complete_document_correct"] == 0
    assert result["detect/sdk/evaluation"]["scored_documents"] == 0
    assert result["detect/sdk/evaluation"]["unscored_automatic"] == 1


def _crash_worker(directory, point):
    import jav.pdf
    from jav.pdf import PdfText
    from jav.experiments.stack_trial import run_trial, DirectAdapter
    source = directory / "source.pdf"
    source.write_bytes(b"fixed test file")
    jav.pdf.read_pdf = lambda path: PdfText(path=str(path), text="Invoice example company",
        lines=["Invoice example company"], page_count=1, has_text_layer=True, text_source="pdf")

    def fault(current):
        marker = directory / "crashed"
        if current == point and not marker.exists():
            marker.write_text(current)
            os._exit(79)  # A real process kill, no finally / cleanup.

    class Client(DetectClient):
        def system_one(self, **kwargs):
            counter = directory / "calls.json"
            counter.write_text(str(int(counter.read_text())+1 if counter.exists() else 1))
            response = super().system_one(**kwargs)
            fault("after_wire")  # After the external answer, before the local cache / ledger.
            return response

    adapter = DirectAdapter(JevAdapter(client=Client(), cache_dir=directory / "cache", model="jev-1.13.0"))
    result = run_trial("detect", str(source), directory, "crash-run", adapter, fault=fault)
    with store.use_store(directory / "business.sqlite"):
        stats = store.stats()
    (directory / "recovery.json").write_text(json.dumps({"documents": stats["documents"],
        "review_open": stats["review_open"], "model_calls": int((directory / "calls.json").read_text()),
        "status": result.final_status}))


if __name__ == "__main__":
    _crash_worker(Path(sys.argv[1]), sys.argv[2])
