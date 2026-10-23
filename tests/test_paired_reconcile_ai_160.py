"""160 (plan F-csak-gpt, Sz3): the reconciliation's AI proposal works with both engines.

The kind of an incoming statement line is proposed by JEV or by GPT (`reconcile-ai --engine jev|gpt`), each stored per
line and engine. The GPT engine runs with JEV switched off, so it cannot ask JEV even by mistake: such a question is
refused and recorded as that line's error. Stand-in engines, made-up lines, no paid call.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from jav.ai import gpt_choice
from jav.domains.finance import reconcile_ai
from jav.ai import jev as jev_mod
from tests.test_incoming_kinds_158 import KindJev, _credit, _package, _stored, db  # noqa: F401 - pytest fixture
from tests.test_runtime_worker import FakeClient
from typesafe_sdk import Noul

ENGINES = ("jev", "gpt")
LIMITS = {"jev": {"jev": Decimal("0.10")}, "gpt": {"openai": Decimal("0.10")}}


def _gpt_kind(request_id, instructions, prompt, fields, *, run_id, limits):
    assert json.loads(prompt)["line"]["direction"] == "incoming (a credit)"
    return SimpleNamespace(values={"line_kind": "customer_payment"}, probabilities={"line_kind": {"customer_payment": 0.9}},
                           confidence={"line_kind": 0.9}, measured=True, call=SimpleNamespace(model="gpt-test", cost_usd=0.0))


@pytest.mark.parametrize("engine", ENGINES)
def test_an_incoming_lines_kind_is_proposed_by_either_engine(db, monkeypatch, tmp_path, engine):  # noqa: F811
    wp = _package(_credit("Example Customer Kft", "250.00", memo="INV-0012"))
    jev = KindJev()
    monkeypatch.setattr(reconcile_ai, "get_adapter", lambda: jev)
    monkeypatch.setattr(gpt_choice, "ask", _gpt_kind)
    reconcile_ai.run(wp, engines=[engine], limits=LIMITS[engine], out_dir=tmp_path)
    (row,) = _stored(engine).values()
    assert row["kind"] == "customer_payment" and row["error"] is None
    assert (len(jev.asked) == 1) is (engine == "jev")


@pytest.mark.jev_refusal
def test_the_gpt_engine_cannot_ask_jev(db, monkeypatch, tmp_path):  # noqa: F811
    wp = _package(_credit("Example Customer Kft", "250.00", memo="INV-0012"))
    client = FakeClient()

    def forgetful(line, invoices, facts, *, run_id):
        jev_mod.get_adapter().ask("reconcile_line", {"x": 1}, {"q": Noul(instructions="?")}, run_id=run_id)
        raise AssertionError("JEV answered the GPT engine's question")

    monkeypatch.setattr(reconcile_ai, "ask_gpt", forgetful)
    with jev_mod.use_adapter(jev_mod.JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")):
        reconcile_ai.run(wp, engines=["gpt"], limits=LIMITS["gpt"], out_dir=tmp_path)
    (row,) = _stored("gpt").values()
    assert "disabled" in row["error"] and client.calls == 0
