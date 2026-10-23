"""160 (review AI-6): on the G path without JEV, an accounting field whose GPT confidence cannot be measured is a to-do.

The 092 rule opens a `gpt:low_conf:<field>:<p>` to-do below 0.98, but a field without a token probability added
nothing: an answer without log-probabilities (one saved before 091, another provider or model) passed every accounting
field unchecked. Such a field now gets `gpt:confidence_unavailable:<field>`, as the type and the intent recognised by
GPT already do. On the 091 measurement (70 golden documents) every accounting field with a value had a token
probability, so a normal answer gets none. Stand-in GPT only, no paid call.
"""

from __future__ import annotations

from jav.ai.typepack import get as get_pack
from tests.test_gpt_todo_092 import _run
from tests.test_no_jev_085 import GOOD, _DownJev, _run_g

PACK = get_pack("invoice_hu")
SCOPE = set(PACK.strict_scored) | set(PACK.high_stakes)


def _unmeasured(state) -> set[str]:
    return {r.split(":")[2] for r in state.review_reasons if r.startswith("gpt:confidence_unavailable:")}


def test_an_answer_without_token_probabilities_flags_each_accounting_field(tmp_path):
    state = _run_g(tmp_path, {**GOOD, "supplier_address": "Minta utca 1. 1111 Budapest"}, jev=False)
    expected = {f for f in PACK.header_fields if f in SCOPE and GOOD.get(f) not in (None, "")}
    assert _unmeasured(state) == expected and expected
    assert "supplier_address" not in _unmeasured(state)  # an informational field opens no to-do
    assert state.route == "human"


def test_a_measured_answer_gets_no_such_to_do(tmp_path, monkeypatch):
    state = _run(tmp_path, GOOD, p=0.9999, jev=False, monkeypatch=monkeypatch)
    assert _unmeasured(state) == set()


def test_a_field_whose_check_failed_or_that_is_empty_adds_nothing(tmp_path):
    values = {**GOOD, "invoice_number": "INVENTED-999"}
    values.pop("due_date")
    state = _run_g(tmp_path, values, jev=False)
    assert "due_date" not in _unmeasured(state)
    assert "source:not_found:invoice_number" in state.review_reasons


def test_a_run_with_jev_never_gets_it(tmp_path):
    state = _run_g(tmp_path, GOOD, jev=True, adapter=_DownJev())
    assert _unmeasured(state) == set()
