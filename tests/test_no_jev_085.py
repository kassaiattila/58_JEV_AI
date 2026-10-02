"""085: processing without JEV (backlog item F-jev). Synthetic documents and stand-in clients only; no paid call."""

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from jav import extract_llm, flow, store, typepack
from jav.adapters import jev as jev_mod
from jav.adapters.jev import JevAdapter, JevUnavailableError
from jav.config import MissingAPIKeyError
from jav.jev_verify import code_verdicts
from jav.models import LineLayout
from jav.runtime import calls
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_runtime_adapters import QS


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "a.sqlite"):
        yield tmp_path


def _no_key():
    raise MissingAPIKeyError("no TypeSafe API key (synthetic)")


# --- K1: a missing TypeSafe key is a to-do, not a failed item -------------------------------------------


def test_missing_key_is_jev_unavailable_before_any_reservation(isolated, monkeypatch):
    monkeypatch.setattr(jev_mod, "make_client", _no_key)
    jev = JevAdapter(cache_dir=isolated / "cache", model="jev-1.13.0")
    calls.set_budget("run-1", "jev", Decimal("1"))
    with calls.use_run(budget_scope="run-1"), pytest.raises(JevUnavailableError) as err:
        jev.ask("t", {"x": 1}, QS, run_id="run-1", use_cache=False)
    assert err.value.reason == "missing_key"
    assert calls.journal("run-1") == []  # nothing was reserved: no request could have left
    assert calls.budget_usage("run-1")["committed_usd"] == Decimal(0)


def test_missing_key_outside_a_run_is_jev_unavailable_too(isolated, monkeypatch):
    monkeypatch.setattr(jev_mod, "make_client", _no_key)
    jev = JevAdapter(cache_dir=isolated / "cache", model="jev-1.13.0")
    with pytest.raises(JevUnavailableError) as err:
        jev.ask("t", {"x": 1}, QS, run_id="adhoc", use_cache=False)
    assert err.value.reason == "missing_key"


# --- K2: the G path without JEV: the code's own source check ---------------------------------------------

GOOD = {"supplier_name": "Minta Kereskedelmi Kft.", "supplier_tax_id": "13570008-1-13", "buyer_name": "Proba Szolgaltato Bt.",
        "invoice_number": "MINTA-2026-001", "issue_date": "2026.09.01.", "fulfillment_date": "2026.09.01.",
        "due_date": "2026.09.15.", "currency": "HUF", "net_total": "10 000", "vat_total": "2 700", "gross_total": "12 700"}


class _FakeAgent:
    """A GPT stand-in: returns the given extraction through the pack's own output model."""

    def __init__(self, pack, values):
        self.out = pack.llm_model().model_validate(values)

    def run_sync(self, prompt, **_kw):
        return SimpleNamespace(output=self.out, usage=SimpleNamespace(input_tokens=100, output_tokens=50),
                               response=SimpleNamespace(model_name="gpt-5.4-mini"))


class _NoJev:
    """A JEV adapter that must not be called."""

    def ask(self, *a, **k):
        raise AssertionError("JEV was called on the path without JEV")


class _DownJev:
    def ask(self, *a, **k):
        raise JevUnavailableError("timeout")


def _run_g(tmp_path, values, *, jev: bool, adapter=None):
    pdf = write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)
    with store.use_store(tmp_path / "f.sqlite"), extract_llm.use_agent_factory(lambda pack: _FakeAgent(pack, values)), \
            jev_mod.use_adapter(adapter or _NoJev()):
        app = flow.build_app(str(pdf), "c1", "G", tracker=False, doc_type="invoice_hu", jev=jev)
        _, _, state = app.run(halt_after=flow.TERMINALS)
    return state.data


def test_code_verdicts_mark_a_value_not_printed_on_the_document():
    lines = [LineLayout(no=i + 1, page=1, text=t) for i, t in enumerate(INVOICE_LINES)]
    v = code_verdicts(lines, {**GOOD, "invoice_number": "INVENTED-999"}, pack=typepack.get("invoice_hu"))
    assert v.source == "code" and v.flags == {} and v.doc_flags == {}
    assert "invoice_number" in v.unsupported and "gross_total" not in v.unsupported


def test_g_path_without_jev_never_asks_jev_and_flags_an_invented_value(tmp_path):
    state = _run_g(tmp_path, {**GOOD, "invoice_number": "INVENTED-999"}, jev=False)
    assert state.verdicts is not None and state.verdicts.source == "code"
    assert "source:not_found:invoice_number" in state.review_reasons
    assert not any(r.startswith("jev") for r in state.review_reasons)


def test_g_path_without_jev_accepts_values_printed_on_the_document(tmp_path):
    state = _run_g(tmp_path, GOOD, jev=False)
    assert not any(r.startswith("source:not_found:") for r in state.review_reasons), state.review_reasons


def test_g_path_without_jev_still_requires_the_required_fields(tmp_path):
    state = _run_g(tmp_path, {k: v for k, v in GOOD.items() if k != "gross_total"}, jev=False)
    assert "llm:required_missing:gross_total" in state.review_reasons


def test_jev_outage_keeps_the_code_source_check_and_the_required_fields(tmp_path):
    """Before 085 a JEV outage on the G path dropped the code's own result too (no unsupported value, no required
    field check)."""
    values = {k: v for k, v in {**GOOD, "invoice_number": "INVENTED-999"}.items() if k != "gross_total"}
    state = _run_g(tmp_path, values, jev=True, adapter=_DownJev())
    assert "jev_unavailable:timeout" in state.review_reasons
    assert "source:not_found:invoice_number" in state.review_reasons
    assert "llm:required_missing:gross_total" in state.review_reasons


def test_s_path_is_refused_without_jev(tmp_path):
    pdf = write_text_pdf(tmp_path / "szamla.pdf", INVOICE_LINES)
    with pytest.raises(ValueError):
        flow.build_app(str(pdf), "c1", "S", tracker=False, doc_type="invoice_hu", jev=False)
