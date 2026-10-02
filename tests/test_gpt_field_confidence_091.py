"""091 (GPT field confidence, the owner's decision of 2026-10-02: token probability + code evidence, the weaker
counts): on the G path without JEV every extracted field gets a confidence, so the review's "uncertain" filter works.

- The token probability of the value (the measure is named in `configs/policy.json`) is capped by the code's evidence:
  a value not printed on the document, or printed only next to another field's label, or one that failed its field
  check, is capped (`gpt_field_confidence`).
- Without a token probability (an answer saved before 091) only a cap below 1 is shown; a located value alone does not
  make a confident estimate.
- No new to-do comes from the confidence: the band is set after the paid measurement (owner decision).
- The JEV path keeps its own confidence (1 - the strongest flag).

Stand-in models; no paid call.
"""

from __future__ import annotations

import pytest

from jav import policy
from tests.test_gpt_extract_logprobs_091 import _LogprobAgent
from tests.test_no_jev_085 import GOOD

CONF = policy.GPT_FIELD_CONFIDENCE


def _tp(p: float) -> dict[str, float | int]:
    return {"joint": p, "min": p, "first": p, "n": 1}


@pytest.mark.parametrize(("token", "status", "failed", "expected"), [
    (0.97, "located", False, 0.97),
    (0.97, "not_found", False, CONF["evidence"]["not_found"]),
    (0.30, "not_found", False, 0.30),  # the weaker counts
    (0.97, "context_rejected", False, CONF["evidence"]["context_rejected"]),
    (0.97, "located", True, CONF["failed_check"]),
    (0.88, "no_value", False, 0.88),  # an empty field: the probability of null
    (0.97, "no_layer", False, 0.97),  # no word layer: no evidence either way
    (None, "located", False, None),  # without a token probability a located value is no estimate
    (None, "not_found", False, CONF["evidence"]["not_found"]),
])
def test_the_weaker_of_token_probability_and_evidence(token, status, failed, expected):
    tp = _tp(token) if token is not None else None
    assert policy.gpt_field_confidence(tp, status, failed_check=failed) == expected


def test_the_measure_is_configured():
    assert CONF["measure"] in {"joint", "min", "first"}
    tp = {"joint": 0.5, "min": 0.7, "first": 0.9, "n": 3}
    assert policy.gpt_field_confidence(tp, "located", failed_check=False) == tp[CONF["measure"]]


def _run_g_with(tmp_path, values, p=0.99, monkeypatch=None):
    """`_run_g` with an agent that answers with token log-probabilities."""
    import tests.test_no_jev_085 as base

    tmp_path.mkdir(exist_ok=True)
    monkeypatch.setattr(base, "_FakeAgent", lambda pack, vals: _LogprobAgent(pack, vals, p=p))
    return base._run_g(tmp_path, values, jev=False)


def test_without_jev_every_extracted_field_gets_a_confidence(tmp_path, monkeypatch):
    data = _run_g_with(tmp_path, GOOD, p=0.999, monkeypatch=monkeypatch)
    prov = data.provenance
    shown = {f: e["confidence"] for f, e in prov.items() if f in GOOD}
    assert shown and all(c is not None for c in shown.values())
    located = [f for f, e in prov.items() if f in GOOD and e["status"] == "located"]
    assert located and all(prov[f]["confidence"] > 0.9 for f in located)
    assert prov["invoice_number"]["confidence_basis"]["measure"] == CONF["measure"]
    assert data.llm_token_p["invoice_number"]["n"] > 0


def test_a_value_not_on_the_document_is_capped(tmp_path, monkeypatch):
    data = _run_g_with(tmp_path, {**GOOD, "invoice_number": "XYZ-404"}, p=0.999, monkeypatch=monkeypatch)
    entry = data.provenance["invoice_number"]
    assert entry["status"] == "not_found" and entry["confidence"] == CONF["evidence"]["not_found"]


def test_no_new_to_do_comes_from_the_confidence(tmp_path, monkeypatch):
    low = _run_g_with(tmp_path / "a", GOOD, p=0.9, monkeypatch=monkeypatch)
    high = _run_g_with(tmp_path / "b", GOOD, p=0.999, monkeypatch=monkeypatch)
    assert sorted(low.review_reasons) == sorted(high.review_reasons)
