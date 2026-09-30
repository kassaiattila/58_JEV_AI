"""075 (repeated security audit, S01, and the Azure recipe switch): Azure DI recognition goes through the shared call
log and the run's budget.

Before 075 the escalation called the legacy sidecar's /parse directly: no reservation, no call-log row, no ledger row,
even with zero budget. Now, in a worker run, a document reserves its page count at the Azure price from the run's
Azure budget first; without an Azure budget (recipe switch off) or with too little of it, the network is never reached
and the local text goes on (a budget shortfall also raises a to-do). The sidecar is replaced by a fake; no network.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal
from unittest.mock import patch

import pytest

from jav import ocr, store, work
from jav.pdf import PdfText
from jav.runtime import calls
from tests.pdfgen import INVOICE_LINES, write_text_pdf

EVIDENCE = {"model_id": "prebuilt-read", "api_version": "2024-11-30", "pages": [{"unit": "inch", "words": [
    {"content": "Fizetendő", "polygon": [0.5, 1.0, 1.2, 1.0, 1.2, 1.15, 0.5, 1.15], "confidence": 0.99},
    {"content": "1000", "polygon": [1.3, 1.0, 1.8, 1.0, 1.8, 1.15, 1.3, 1.15], "confidence": 0.98}]}]}


@pytest.fixture
def azure_env(tmp_path, monkeypatch):
    """A weak local OCR result, escalation on, the sidecar's data root in tmp_path, and a fake sidecar."""
    source = tmp_path / "scan.pdf"
    write_text_pdf(source, INVOICE_LINES)
    (tmp_path / "evidence.json").write_text(json.dumps(EVIDENCE), encoding="utf-8")
    monkeypatch.setattr(ocr, "_CFG", {**ocr._CFG, "azure_di": {**ocr._CFG["azure_di"], "data_root": str(tmp_path)}})
    monkeypatch.delenv(ocr.ENGINE_ENV, raising=False)
    monkeypatch.setattr(ocr, "ESCALATION", {"enabled": True, "engine": "azure_di"})
    monkeypatch.setattr(ocr, "CACHE_DIR", tmp_path / "ocr-cache")
    real_ocr_pdf = ocr.ocr_pdf
    local = PdfText(path=str(source), text="gyenge", ocr={"engine": "native", "mean_conf": 0.5, "low_conf_ratio": 0.5})

    def ocr_pdf(path, **kwargs):
        return real_ocr_pdf(path, **kwargs) if kwargs.get("engine_name") == "azure_di" else local

    monkeypatch.setattr(ocr, "ocr_pdf", ocr_pdf)
    requests: list[dict] = []

    class _Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, **kwargs):
        requests.append(json.loads(request.data))
        return _Reply(json.dumps({"provider_used": "azure_di", "evidence_ref": {"path": "evidence.json"}}).encode())

    with store.use_store(tmp_path / "w.sqlite"), patch("urllib.request.urlopen", fake_urlopen):
        yield source, requests


def _rows(sql: str) -> list:
    with store.connect() as c:
        return c.execute(sql).fetchall()


def test_recipe_switch_off_never_reaches_the_sidecar(azure_env):
    source, requests = azure_env
    with calls.use_run(budget_scope="run-off"):  # a run with no Azure budget: the recipe switch is off
        pdf, escalated = ocr.ocr_with_escalation(source, use_cache=False)
    assert not escalated and not requests
    assert pdf.ocr["escalation_blocked"] == "off" and ocr.escalation_review_reasons(pdf.ocr) == []
    assert _rows("SELECT COUNT(*) FROM invocations")[0][0] == 0


def test_too_small_budget_never_reaches_the_sidecar_and_raises_a_todo(azure_env):
    source, requests = azure_env
    calls.set_budget("run-small", "azure_di", Decimal("0.000001"))
    with calls.use_run(budget_scope="run-small"):
        pdf, escalated = ocr.ocr_with_escalation(source, use_cache=False)
    assert not escalated and not requests
    assert ocr.escalation_review_reasons(pdf.ocr) == ["ocr:escalation_blocked:budget_exceeded"]


def test_budgeted_call_is_reserved_logged_and_priced_per_page(azure_env):
    source, requests = azure_env
    calls.set_budget("run-on", "azure_di", Decimal("0.02"))
    with calls.use_run(budget_scope="run-on"):
        pdf, escalated = ocr.ocr_with_escalation(source, use_cache=False)
    assert escalated and pdf.ocr["engine"] == "azure_di" and len(requests) == 1
    (status, max_cost, cost), = _rows("SELECT status, max_cost_usd, cost_usd FROM invocations WHERE provider='azure_di'")
    assert status == "succeeded" and Decimal(cost) == ocr.AZURE_USD_PER_PAGE * 1 and Decimal(max_cost) >= Decimal(cost)
    (provider, ledger_cost), = _rows("SELECT provider, cost_usd FROM ledger WHERE provider='azure_di'")
    assert ledger_cost == pytest.approx(float(ocr.AZURE_USD_PER_PAGE))


def test_uncertain_attempt_is_not_repeated_automatically(azure_env):
    source, requests = azure_env
    calls.set_budget("run-crash", "azure_di", Decimal("0.02"))
    with calls.use_run(budget_scope="run-crash"):
        with patch.object(ocr, "azure_words", side_effect=KeyboardInterrupt):  # the process "dies" mid-call
            with pytest.raises(KeyboardInterrupt):
                ocr.ocr_with_escalation(source, use_cache=False)
    with store.connect() as c:  # a crash leaves the reservation behind; the worker start marks it uncertain
        c.execute("UPDATE invocations SET status='reserved' WHERE provider='azure_di'")
    calls.recover_uncertain()
    with calls.use_run(budget_scope="run-crash"):
        pdf, escalated = ocr.ocr_with_escalation(source, use_cache=False)
    assert not escalated and not requests
    assert ocr.escalation_review_reasons(pdf.ocr) == ["ocr:escalation_blocked:uncertain_attempt"]


def test_command_line_call_is_ledgered(azure_env):
    source, requests = azure_env
    pdf, escalated = ocr.ocr_with_escalation(source, use_cache=False)  # no run context: the measurement path
    assert escalated and len(requests) == 1
    assert tuple(_rows("SELECT provider, step FROM ledger")[0]) == ("azure_di", "ocr_azure")


def test_recipe_switch_sets_the_azure_item_budget():
    r = work.recipe("document-processing")
    on = work.item_budget(r, {"arm": "auto", "azure_ocr": "on"}, "document")
    off = work.item_budget(r, {"arm": "auto", "azure_ocr": "off"}, "document")
    legacy = work.item_budget(r, {"arm": "auto"}, "document")  # an assignment made before the switch existed
    assert on["azure_di"] == Decimal("0.02") and "azure_di" not in off and legacy["azure_di"] == Decimal("0.02")
    email = work.recipe("email-intent")
    assert "azure_di" not in work.item_budget(email, {"arm": "auto", "azure_ocr": "on"}, "email")
    assert work.item_budget(email, {"arm": "auto", "azure_ocr": "on"}, "document")["azure_di"] == Decimal("0.02")
