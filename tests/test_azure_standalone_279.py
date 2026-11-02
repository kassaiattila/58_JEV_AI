"""279: Azure Document Intelligence works on its own, without the legacy project.

The owner's decisions of 2026-11-02: the legacy routes (the sidecar, the Docker engine) are gone; Azure is reached
only directly with this installation's endpoint and key; it reads at most as many pages as the local recognition (12);
a start the service refuses for load is repeated; a refused start costs nothing; the endpoint and key can be checked
for free; an installation can switch Azure off; with no local engine Azure stands in. The service is a fake
(`tests/azure_fake.py`); no network, no paid call.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from jav.core import calls, store
from jav.documents import azure_di, ocr
from jav.documents.pdf import PdfText
from tests.azure_fake import ENDPOINT, HOST, FakeAzure, http_error, result
from tests.pdfgen import INVOICE_LINES, write_text_pdf

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def scan(tmp_path, monkeypatch):
    """A weak local OCR result for a PDF, escalation on, this installation's Azure endpoint and key, a fresh store, and
    the Azure engine's real `ocr_pdf` (only the local engine is stood in for)."""
    source = tmp_path / "scan.pdf"
    write_text_pdf(source, INVOICE_LINES)
    monkeypatch.setenv(azure_di.ENDPOINT_ENV, ENDPOINT)
    monkeypatch.setenv(azure_di.KEY_ENV, "test-key-not-real")
    monkeypatch.delenv(ocr.ENGINE_ENV, raising=False)
    monkeypatch.delenv("JAV_PROVIDERS_OFF", raising=False)
    monkeypatch.setattr(ocr, "ESCALATION", {"enabled": True, "engine": "azure_di"})
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "ocr-cache")
    monkeypatch.setattr(ocr, "AZURE_CHECK_FILE", tmp_path / "azure-check.json")
    real_ocr_pdf = ocr.ocr_pdf
    local = PdfText(path=str(source), text="gyenge", ocr={"engine": "native", "mean_conf": 0.5, "low_conf_ratio": 0.5})

    def ocr_pdf(path, **kwargs):
        return real_ocr_pdf(path, **kwargs) if kwargs.get("engine_name") == "azure_di" else local

    monkeypatch.setattr(ocr, "ocr_pdf", ocr_pdf)
    with store.use_store(tmp_path / "w.sqlite"), patch.object(azure_di.time, "sleep"):
        yield source


def _escalate(source, budget: str = "0.02", scope: str = "run-279"):
    calls.set_budget(scope, "azure_di", Decimal(budget))
    with calls.use_run(budget_scope=scope):
        return ocr.ocr_with_escalation(source, use_cache=False)


def _invocations() -> list[tuple]:
    with store.connect() as c:
        return [tuple(r) for r in c.execute("SELECT status, max_cost_usd, cost_usd FROM invocations WHERE provider='azure_di'")]


# --- independence -----------------------------------------------------------------------------------------------------


def test_nothing_of_the_legacy_ocr_routes_is_left_in_the_framework():
    conf = json.loads((ROOT / "configs" / "ocr.json").read_text(encoding="utf-8"))
    assert "docker" not in conf and not {"sidecar_url", "container_root", "data_root"} & set(conf["azure_di"])
    providers = json.loads((ROOT / "configs" / "providers.json").read_text(encoding="utf-8"))["providers"]
    assert "key_fallback" not in providers["azure_di"]
    for path in (ROOT / "jav").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "aiflow-v4-sidecar" not in text and "127.0.0.1:8800" not in text and "/parse" not in text, path
    assert not hasattr(ocr, "azure_alias") and not hasattr(ocr, "docker_available")


def test_the_docker_engine_is_refused_by_name(monkeypatch):
    ocr.engine.cache_clear()
    try:
        with pytest.raises(ocr.NoOcrEngine, match="removed in 279"):
            ocr.engine("docker")
    finally:
        ocr.engine.cache_clear()


def test_the_status_names_azure_without_the_key(scan):
    state = ocr.status()
    assert "docker_image" not in state and "azure_sidecar" not in state
    azure = state["azure"]
    assert azure["configured"] and azure["enabled"] and azure["host"] == HOST and azure["max_pages"] == 12
    assert "test-key-not-real" not in json.dumps(state)


# --- the page limit (the owner's decision of 2026-11-02: at most 12 pages) ------------------------------------------------


def test_a_long_scan_is_read_and_reserved_for_twelve_pages_only(scan, monkeypatch):
    monkeypatch.setattr(ocr, "page_sizes", lambda path: [(612.0, 792.0)] * 30)
    fake = FakeAzure([result(12)])
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(scan, budget="0.02")  # 30 pages would need 0.045 USD; 12 need 0.018
    assert escalated and "pages=1-12" in fake.post_requests[0].full_url
    (status, max_cost, cost), = _invocations()
    assert status == "succeeded" and Decimal(max_cost) == Decimal("0.018") and Decimal(cost) == Decimal("0.018")


def test_a_short_scan_is_sent_whole(scan):
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        _escalate(scan)
    assert "pages=" not in fake.post_requests[0].full_url
    assert Decimal(_invocations()[0][1]) == ocr.AZURE_USD_PER_PAGE


def test_an_unreadable_page_count_reserves_the_limit_instead_of_failing(scan, monkeypatch):
    # until 279 this path read a setting that does not exist (`max_pages` of the input limits) and stopped the item
    monkeypatch.setattr(ocr, "page_sizes", lambda path: [])
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(scan)
    assert escalated and "pages=1-12" in fake.post_requests[0].full_url
    assert Decimal(_invocations()[0][1]) == ocr.AZURE_USD_PER_PAGE * 12


# --- repeats and refusals ---------------------------------------------------------------------------------------------


def test_a_throttled_start_is_repeated_and_paid_once(scan):
    fake = FakeAzure(post=[http_error(429, {"Retry-After": "1"}), http_error(503)])
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(scan)
    assert escalated and len(fake.post_requests) == 3
    assert [s for s, *_ in _invocations()] == ["succeeded"]


def test_a_start_still_throttled_after_the_repeats_costs_nothing(scan):
    fake = FakeAzure(post=[http_error(429)] * 4)
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(scan)
    assert not escalated and len(fake.post_requests) == 4  # the first and three repeats
    (status, _max, cost), = _invocations()
    assert status == "failed" and Decimal(cost) == 0
    assert ocr.escalation_review_reasons(pdf.ocr) == ["ocr:escalation_blocked:unavailable"]


def test_a_wrong_key_is_not_repeated(scan):
    fake = FakeAzure(post=[http_error(401)])
    with patch("urllib.request.urlopen", fake):
        _escalate(scan)
    assert len(fake.post_requests) == 1


def test_a_throttled_read_of_the_result_is_read_again(scan):
    fake = FakeAzure([http_error(429), {"status": "running"}, result()])
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(scan)
    assert escalated and [s for s, *_ in _invocations()] == ["succeeded"]


def test_a_file_the_service_does_not_read_is_never_sent(scan, tmp_path):
    doc = tmp_path / "letter.docx"
    doc.write_bytes(b"PK not a pdf")
    fake = FakeAzure()
    calls.set_budget("run-docx", "azure_di", Decimal("0.02"))
    with patch("urllib.request.urlopen", fake), calls.use_run(budget_scope="run-docx"), \
            pytest.raises(ocr.AzureBlocked, match="not_sendable"):
        ocr.azure_recognise(doc)
    assert not fake.requests and _invocations() == []


def test_a_file_over_the_size_limit_is_never_sent(scan, monkeypatch):
    conf = copy.deepcopy(ocr._CFG)
    conf["azure_di"]["max_file_mb"] = 0.000001
    monkeypatch.setattr(ocr, "_CFG", conf)
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(scan)
    assert not escalated and not fake.requests and _invocations() == []
    assert ocr.escalation_review_reasons(pdf.ocr) == ["ocr:escalation_blocked:not_sendable"]


# --- the installation's switch ----------------------------------------------------------------------------------------


def test_an_installation_that_switched_azure_off_sends_nothing_and_raises_no_todo(scan, monkeypatch):
    monkeypatch.setenv("JAV_PROVIDERS_OFF", "azure_di")
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(scan)
    assert not escalated and not fake.requests and _invocations() == []
    assert pdf.ocr["escalation_blocked"] == "switched_off" and ocr.escalation_review_reasons(pdf.ocr) == []


# --- no local engine --------------------------------------------------------------------------------------------------


@pytest.fixture
def no_local_engine(scan, monkeypatch):
    """The `scan` fixture with no local engine: asking it raises `NoOcrEngine`, as on a machine without tesseract."""
    with_azure = ocr.ocr_pdf  # the scan fixture's stand-in, which passes Azure requests to the real recognition

    def ocr_pdf(path, **kwargs):
        if kwargs.get("engine_name") != "azure_di":
            raise ocr.NoOcrEngine("no OCR engine (auto): the native tesseract is not installed")
        return with_azure(path, **kwargs)

    monkeypatch.setattr(ocr, "ocr_pdf", ocr_pdf)
    return scan


def test_with_no_local_engine_azure_stands_in_within_the_budget(no_local_engine):
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        pdf, escalated = _escalate(no_local_engine)
    assert escalated and pdf.ocr["engine"] == "azure_di" and pdf.ocr["escalated_from"] is None
    assert ocr.escalation_rule(pdf.ocr["escalation"]) == {"attempt": True, "text": "escalated", "reasons": []}


def test_with_no_local_engine_and_no_azure_budget_the_missing_engine_stands(no_local_engine):
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake), calls.use_run(budget_scope="run-no-azure"), \
            pytest.raises(ocr.NoOcrEngine):
        ocr.ocr_with_escalation(no_local_engine, use_cache=False)
    assert not fake.requests


# --- the free check ---------------------------------------------------------------------------------------------------


def test_the_free_check_reads_the_resource_details_and_is_kept(scan):
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        found = ocr.check_azure()
    assert found["ok"] and found["host"] == HOST and found["custom_models"] == {"count": 0, "limit": 5000}
    (request,) = fake.requests
    assert request.get_method() == "GET"
    assert request.full_url == f"https://{HOST}/documentintelligence/info?api-version=2024-11-30"
    assert _invocations() == []  # nothing analysed, nothing in the call log
    assert ocr.status()["azure"]["last_check"]["ok"] is True
    assert "test-key-not-real" not in ocr.AZURE_CHECK_FILE.read_text(encoding="utf-8")


@pytest.mark.parametrize(("error", "reason"), [(http_error(401), "refused_key"), (http_error(404), "not_found"),
                                               (http_error(500), "http_500"), (OSError("no route"), "unreachable")])
def test_a_failed_check_names_its_reason(scan, error, reason):
    with patch("urllib.request.urlopen", FakeAzure(info=error)):
        found = ocr.check_azure()
    assert not found["ok"] and found["reason"] == reason


def test_without_keys_the_check_sends_nothing(scan, monkeypatch):
    monkeypatch.delenv(azure_di.KEY_ENV)
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        found = ocr.check_azure()
    assert not found["ok"] and found["reason"] == "not_configured" and not fake.requests


def test_a_switched_off_installation_is_not_checked(scan, monkeypatch):
    monkeypatch.setenv("JAV_PROVIDERS_OFF", "azure_di")
    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        assert ocr.check_azure()["reason"] == "switched_off"
    assert not fake.requests


def test_the_start_up_check_says_azure_s_state():
    from jav.devtools import preflight

    base = {"enabled": True, "configured": True, "host": HOST, "last_check": None}
    assert "not set up" in preflight.azure_notice({**base, "configured": False})
    assert "switched off" in preflight.azure_notice({**base, "enabled": False})
    assert "not checked yet" in preflight.azure_notice(base)
    assert "checked 2026" in preflight.azure_notice({**base, "last_check": {"ok": True, "at": "2026-11-02T10:00:00+00:00"}})
    assert "refused_key" in preflight.azure_notice({**base, "last_check": {"ok": False, "reason": "refused_key", "at": "x"}})


# --- the command line -------------------------------------------------------------------------------------------------


def _ocr_args(**kw):
    defaults = {"fetch_langs": False, "check_azure": False, "pdf": None, "engine": None, "azure_budget_usd": None,
                "force": False, "psm": None, "limit": 0}
    return type("A", (), {**defaults, **kw})()


def test_the_command_reads_with_azure_only_under_a_budget(scan, capsys):
    from jav.cli import maintenance_cli

    fake = FakeAzure()
    with patch("urllib.request.urlopen", fake):
        assert maintenance_cli.cmd_ocr(_ocr_args(pdf=str(scan), engine="azure_di")) == 2
        assert "no_budget" in capsys.readouterr().out and not fake.requests
        assert maintenance_cli.cmd_ocr(_ocr_args(pdf=str(scan), engine="azure_di", azure_budget_usd="0.01")) == 0
    assert len(fake.post_requests) == 1 and [s for s, *_ in _invocations()] == ["succeeded"]


def test_the_command_checks_azure(scan, capsys):
    from jav.cli import maintenance_cli

    with patch("urllib.request.urlopen", FakeAzure()):
        assert maintenance_cli.cmd_ocr(_ocr_args(check_azure=True)) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True


# --- the cache moves to the new key with no new OCR ---------------------------------------------------------------------


def test_the_cache_written_with_the_docker_section_moves_to_the_new_key(tmp_path):
    older = copy.deepcopy(ocr._CFG)
    older["docker"] = {"image": "aiflow-v4-sidecar", "note": "the legacy engine"}
    older["azure_di"].update(sidecar_url="http://127.0.0.1:8800", container_root="/data")
    old_key = ocr.output_hash(older)
    assert old_key != ocr.CACHE_HASH
    sha = "a" * 64
    for engine in ("tesseract_v5.4.0.20240606", "azure_di_prebuilt-read"):
        (tmp_path / f"{sha}_{old_key}_{engine}.json").write_text("{}", encoding="utf-8")
    assert ocr.rekey_cache(older, tmp_path) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == [f"{sha}_{ocr.CACHE_HASH}_azure_di_prebuilt-read.json",
                                                          f"{sha}_{ocr.CACHE_HASH}_tesseract_v5.4.0.20240606.json"]


def test_a_config_that_reads_differently_is_still_refused(tmp_path):
    older = copy.deepcopy(ocr._CFG)
    older["docker"] = {"image": "aiflow-v4-sidecar"}
    older["dpi"] = 200
    with pytest.raises(ValueError):
        ocr.rekey_cache(older, tmp_path)
