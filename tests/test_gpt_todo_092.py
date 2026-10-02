"""092: on the G path without JEV, a field GPT is not sure enough of opens a to-do (the owner's decisions of 2026-10-02:
below `gpt_field_confidence.review_below`, only the accounting fields: the scored, not informational ones and the high-
stakes ones). Addresses and other informational fields only show it (colour and filter). A run with JEV never gets this
to-do, not even when JEV does not answer and the code's own check stands in. Stand-in GPT and JEV only, no paid call.
"""

from __future__ import annotations

from jav import policy
from jav.typepack import get as get_pack
from tests.test_gpt_extract_logprobs_091 import _LogprobAgent
from tests.test_no_jev_085 import GOOD

PACK = get_pack("invoice_hu")
SCOPE = set(PACK.strict_scored) | set(PACK.high_stakes)


def _run(tmp_path, values, *, p, jev, monkeypatch):
    import tests.test_no_jev_085 as base

    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setattr(base, "_FakeAgent", lambda pack, vals: _LogprobAgent(pack, vals, p=p))
    return base._run_g(tmp_path, values, jev=jev, adapter=base._DownJev() if jev else None)


def _gpt_reasons(state) -> dict[str, str]:
    return {r.split(":")[2]: r for r in state.review_reasons if r.startswith("gpt:low_conf:")}


def test_a_field_gpt_is_not_sure_of_opens_a_to_do(tmp_path, monkeypatch):
    values = {**GOOD, "supplier_address": "Minta utca 1. 1111 Budapest"}
    state = _run(tmp_path, values, p=0.9, jev=False, monkeypatch=monkeypatch)
    got = _gpt_reasons(state)
    expected = {f for f in PACK.header_fields if f in SCOPE and values.get(f) not in (None, "")}
    assert set(got) == expected and expected  # the accounting fields with a value, each once
    assert "supplier_address" not in got  # an address only shows its confidence
    token = state.llm_token_p["invoice_number"][policy.GPT_FIELD_CONFIDENCE["measure"]]
    assert got["invoice_number"] == f"gpt:low_conf:invoice_number:{token:.2f}"
    assert state.route == "human"


def test_a_sure_answer_opens_no_such_to_do(tmp_path, monkeypatch):
    state = _run(tmp_path, GOOD, p=0.9999, jev=False, monkeypatch=monkeypatch)
    assert _gpt_reasons(state) == {}


def test_a_run_with_jev_never_gets_it_even_when_jev_does_not_answer(tmp_path, monkeypatch):
    state = _run(tmp_path, GOOD, p=0.9, jev=True, monkeypatch=monkeypatch)
    assert any(r.startswith("jev_unavailable:") for r in state.review_reasons)  # the stand-in JEV did not answer
    assert _gpt_reasons(state) == {}


def test_the_threshold_is_configured():
    assert policy.GPT_FIELD_CONFIDENCE["review_below"] == 0.98
