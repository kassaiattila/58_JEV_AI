"""121: Azure Document Intelligence is called directly, and an escalation that cannot run raises a to-do.

Before 121 the escalation of a weak scan went only through the legacy sidecar, which sees only the legacy project's
data folder. Every document from the owner's own folders failed before the network, was logged as a failed Azure
call, and its weak local text went on without a to-do (18 of 18 attempts on 2026-10-06). Now, with an endpoint and a
key in the environment, the REST API is called directly with the document's bytes; without them nothing is called
(279: the sidecar route is gone). When the recipe's Azure switch is on but the escalation cannot run, the item gets a
to-do. The HTTP client is replaced by a fake (`tests/azure_fake.py`); no network.
"""

from __future__ import annotations

import io
import urllib.error
from decimal import Decimal
from unittest.mock import patch

import pytest

from jav.documents import ocr
from jav.core import store
from jav.documents import azure_di
from jav.documents.pdf import PdfText
from jav.core import calls
from tests.azure_fake import ENDPOINT, OPERATION, FakeAzure
from tests.pdfgen import INVOICE_LINES, write_text_pdf


@pytest.fixture
def weak_scan(tmp_path, monkeypatch):
    """A weak local OCR result for a document in one of the owner's own folders, escalation on, a fresh store."""
    source = tmp_path / "own-folder" / "scan.pdf"
    source.parent.mkdir()
    write_text_pdf(source, INVOICE_LINES)
    monkeypatch.delenv(ocr.ENGINE_ENV, raising=False)
    monkeypatch.setattr(ocr, "ESCALATION", {"enabled": True, "engine": "azure_di"})
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "ocr-cache")
    real_ocr_pdf = ocr.ocr_pdf
    local = PdfText(path=str(source), text="gyenge", ocr={"engine": "native", "mean_conf": 0.5, "low_conf_ratio": 0.5})

    def ocr_pdf(path, **kwargs):
        return real_ocr_pdf(path, **kwargs) if kwargs.get("engine_name") == "azure_di" else local

    monkeypatch.setattr(ocr, "ocr_pdf", ocr_pdf)
    with store.use_store(tmp_path / "w.sqlite"):
        yield source


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv(azure_di.ENDPOINT_ENV, ENDPOINT)
    monkeypatch.setenv(azure_di.KEY_ENV, "test-key-not-real")


def _invocations() -> list:
    with store.connect() as c:
        return [tuple(r) for r in c.execute("SELECT status, error FROM invocations WHERE provider='azure_di'")]


def _escalate(source, scope: str = "run-on"):
    calls.set_budget(scope, "azure_di", Decimal("0.02"))
    with calls.use_run(budget_scope=scope), patch.object(azure_di.time, "sleep"):
        return ocr.ocr_with_escalation(source, use_cache=False)


def test_tests_never_see_the_azure_keys():
    import os

    assert not os.environ.get(azure_di.ENDPOINT_ENV) and not os.environ.get(azure_di.KEY_ENV)
    assert not azure_di.configured()


def test_direct_call_reads_a_document_from_any_folder(weak_scan, keys):
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(weak_scan)
    assert escalated and pdf.ocr["engine"] == "azure_di" and pdf.ocr["api_version"] == "2024-11-30"
    assert [w["text"] for w in pdf.words[0]] == ["Payable", "1000"] and "Payable 1000" in pdf.lines
    post, *polls = fake.requests
    assert post.get_method() == "POST" and post.full_url == (
        "https://example-di.cognitiveservices.azure.com/documentintelligence/documentModels/prebuilt-read:analyze?api-version=2024-11-30")
    assert post.data == weak_scan.read_bytes() and post.get_header("Content-type") == "application/octet-stream"
    assert all(r.get_header("Ocp-apim-subscription-key") == "test-key-not-real" for r in fake.requests)
    assert len(polls) == 2 and all(r.full_url == OPERATION for r in polls)
    assert _invocations() == [("succeeded", None)]


def test_the_key_is_never_sent_to_another_host(weak_scan, keys):
    fake = FakeAzure(operation="https://attacker.example.com/analyzeResults/abc")
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(weak_scan)
    assert not escalated and [r.get_method() for r in fake.requests] == ["POST"]
    # the analysis was accepted (it is paid) but its answer is not read: the outcome is unknown, never repeated by itself
    assert _invocations()[0][0] == "uncertain"
    assert ocr.escalation_review_reasons(pdf.ocr) == ["ocr:escalation_blocked:unavailable"]


def test_an_error_response_is_a_definite_failure_with_a_todo(weak_scan, keys):
    refused = urllib.error.HTTPError(ENDPOINT, 401, "Unauthorized", {}, io.BytesIO(b'{"error": {"code": "401"}}'))
    with patch("urllib.request.urlopen", FakeAzure(post=refused)):
        pdf, escalated = _escalate(weak_scan)
    assert not escalated and _invocations()[0][0] == "failed"
    with store.connect() as c:  # 279: a refused start analysed nothing, so the call log settles it at 0
        assert [tuple(r) for r in c.execute("SELECT cost_usd, cost_known FROM invocations")] == [("0", 1)]
    assert ocr.escalation_review_reasons(pdf.ocr) == ["ocr:escalation_blocked:unavailable"]


def test_a_failed_analysis_is_a_definite_failure(weak_scan, keys):
    with patch("urllib.request.urlopen", FakeAzure([{"status": "failed", "error": {"code": "InvalidContent"}}])):
        pdf, escalated = _escalate(weak_scan)
    assert not escalated and _invocations()[0][0] == "failed"
    assert pdf.ocr["escalation_blocked"] == "unavailable"


def test_a_lost_answer_after_acceptance_is_uncertain_and_not_repeated(weak_scan, keys):
    with patch("urllib.request.urlopen", FakeAzure([urllib.error.URLError("connection reset")])):
        pdf, escalated = _escalate(weak_scan)
    assert not escalated and _invocations()[0][0] == "uncertain"
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):  # the same document again: the earlier outcome is unknown
        pdf, escalated = _escalate(weak_scan)
    assert not escalated and not fake.requests
    assert ocr.escalation_review_reasons(pdf.ocr) == ["ocr:escalation_blocked:uncertain_attempt"]


def test_an_analysis_that_never_finishes_is_uncertain(weak_scan, keys, monkeypatch):
    monkeypatch.setattr(ocr, "_CFG", {**ocr._CFG, "azure_di": {**ocr._CFG["azure_di"], "timeout_s": 0}})
    with patch("urllib.request.urlopen", FakeAzure([{"status": "running"}] * 3)):
        pdf, escalated = _escalate(weak_scan)
    assert not escalated and _invocations()[0][0] == "uncertain"


def test_without_keys_nothing_is_called_and_the_document_gets_a_todo(weak_scan):
    # 279: no legacy sidecar route is left; without this installation's endpoint and key Azure is not set up here
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(weak_scan)
    assert not escalated and not fake.requests and _invocations() == []  # not a "failed paid call"
    assert ocr.escalation_review_reasons(pdf.ocr) == ["ocr:escalation_blocked:not_configured"]


def test_switch_off_still_needs_no_todo(weak_scan, keys):
    fake = FakeAzure()
    with calls.use_run(budget_scope="run-off"), patch("urllib.request.urlopen", fake):
        pdf, escalated = ocr.ocr_with_escalation(weak_scan, use_cache=False)
    assert not escalated and not fake.requests
    assert pdf.ocr["escalation_blocked"] == "off" and ocr.escalation_review_reasons(pdf.ocr) == []


def test_the_azure_cache_key_is_unchanged():
    # every Azure text cached before 121 was read with API version 2024-11-30 (the legacy sidecar's SDK 1.0.2); the
    # direct route uses the same version, so those texts are reused and no page is paid for again
    assert ocr.engine_version("azure_di") == "azure_di prebuilt-read"
    settings = ocr.output_settings(ocr._CFG)["azure_di"]
    assert "api_version" not in settings and "poll_interval_s" not in settings


def test_an_endpoint_without_https_is_refused(monkeypatch, tmp_path):
    monkeypatch.setenv(azure_di.ENDPOINT_ENV, "http://example-di.cognitiveservices.azure.com/")
    monkeypatch.setenv(azure_di.KEY_ENV, "test-key-not-real")
    doc = tmp_path / "a.pdf"
    doc.write_bytes(b"%PDF-1.4")
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake), pytest.raises(azure_di.AzureDiError):
        azure_di.analyze_read(doc, model="prebuilt-read", api_version="2024-11-30", timeout_s=5, poll_s=0)
    assert not fake.requests
