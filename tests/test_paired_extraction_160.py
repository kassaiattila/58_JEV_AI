"""160 (plan F-csak-gpt, Sz3): the extraction of every type pack runs with both engines.

The G path of each extractable type pack (24 now: invoices, utility bills, statements, outgoing invoices, the
pro-forma invoice and the older types) is run once with JEV (a fake client) and once with GPT only. Until now only the
Hungarian invoice was tested without JEV. On both engines a value printed nowhere on the document is flagged, each in
its own words (with JEV the code's evidence check decides before any question, `jev:unsupported`; without it the code's
own source check, `source:not_found`), a printed value is not, the run asks the verification call site of the pack
with JEV, and never asks JEV without it (the safety net and the test guard in `tests/conftest.py`). Stand-in GPT and a
fake JEV client, made-up values, no paid call.
"""

from __future__ import annotations

import contextlib
from pathlib import Path

import pytest

from jav.flows import flow
from jav.ai import extract_llm, typepack
from jav.core import store
from jav.ai import jev as jev_mod
from jav.ai.jev_verify import site_for
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_no_jev_085 import _FakeAgent
from tests.test_runtime_worker import FakeClient

ENGINES = ("jev", "gpt")
PACKS = sorted(typepack.extractable_keys())
INVENTED = "Zxqv Invented 7781"
PRINTED = "Minta Kereskedelmi Kft."


def _text_field(pack_key: str) -> str:
    """The pack's first free-text field that takes a made-up value."""
    pack = typepack.get(pack_key)
    for field in pack.header_fields:
        if pack.kind(field) in ("text", "name", "invoice_number"):
            with contextlib.suppress(ValueError):
                pack.llm_model().model_validate({field: INVENTED})
                return field
    raise AssertionError(f"{pack_key} has no free-text field")


def _run(tmp_path: Path, pack_key: str, values: dict, engine: str):
    pdf = write_text_pdf(tmp_path / "doc.pdf", INVOICE_LINES)
    client = FakeClient()
    adapter = jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    scoped = jev_mod.use_adapter(adapter) if engine == "jev" else contextlib.nullcontext()
    with store.use_store(tmp_path / "s.sqlite"), extract_llm.use_agent_factory(lambda pack: _FakeAgent(pack, values)), scoped:
        app = flow.build_app(str(pdf), "c1", "G", tracker=False, doc_type=pack_key, jev=engine == "jev")
        _, _, state = app.run(halt_after=flow.TERMINALS)
    return state.data, client


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("pack_key", PACKS)
def test_a_value_printed_nowhere_is_flagged_on_both_engines(tmp_path, pack_key, engine):
    field = _text_field(pack_key)
    state, client = _run(tmp_path, pack_key, {field: INVENTED}, engine)
    expected = f"jev:unsupported:{field}" if engine == "jev" else f"source:not_found:{field}"
    assert expected in state.review_reasons
    assert state.route == "human" and state.final_status == "needs_review"
    if engine == "jev":
        assert client.calls >= 1 and state.verdicts.source != "code"
        assert any(c.request_id == site_for(pack_key).request_id for c in state.jev_calls)
    else:
        assert client.calls == 0 and state.verdicts.source == "code" and state.jev_calls == []
        assert not any(r.startswith("jev") for r in state.review_reasons)


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("pack_key", PACKS)
def test_a_printed_value_is_not_flagged_as_missing_on_either_engine(tmp_path, pack_key, engine):
    field = _text_field(pack_key)
    state, _ = _run(tmp_path, pack_key, {field: PRINTED}, engine)
    assert f"jev:unsupported:{field}" not in state.review_reasons
    assert f"source:not_found:{field}" not in state.review_reasons
