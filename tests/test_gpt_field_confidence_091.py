"""091 (GPT field confidence, the owner's decisions of 2026-10-02: token probability; after the paid measurement
"probability only, 0.98" and "display only, trial first"): on the G path without JEV every extracted field gets a
confidence, so the review's "uncertain" filter works.

- The confidence is the token probability of the value (the measure is named in `configs/policy.json`); a failed field
  check caps it (`gpt_field_confidence.failed_check`). The source location no longer caps it: GPT rewrites values
  ("Hungary" where the document has the Hungarian name), and the measurement showed many false alarms for few caught errors.
- Without a token probability (an answer saved before 091) only a cap below 1 is shown.
- GPT's confidence has its own display band (`gpt_field_confidence.bands`, served with the settings): below 0.98 it is
  "to check".
- No new to-do comes from the confidence (owner decision: trial on real work first).
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
    (0.97, "not_found", False, 0.97),  # the source location does not cap any more
    (0.97, "context_rejected", False, 0.97),
    (0.97, "located", True, CONF["failed_check"]),
    (0.30, "located", True, 0.30),  # the weaker counts
    (0.88, "no_value", False, 0.88),  # an empty field: the probability of null
    (None, "located", False, None),  # without a token probability a located value is no estimate
    (None, "not_found", False, None),
    (None, "located", True, CONF["failed_check"]),
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


def test_a_value_not_on_the_document_keeps_its_token_probability(tmp_path, monkeypatch):
    data = _run_g_with(tmp_path, {**GOOD, "invoice_number": "XYZ-404"}, p=0.999, monkeypatch=monkeypatch)
    entry = data.provenance["invoice_number"]
    assert entry["status"] == "not_found" and entry["confidence"] == data.llm_token_p["invoice_number"][CONF["measure"]]


def test_the_gpt_band_is_served_with_the_settings(tmp_path):
    from fastapi.testclient import TestClient

    from jav import api

    c = TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url="http://127.0.0.1:8930")
    bands = c.get("/api/settings").json()["confidence_bands"]
    assert bands["gpt"] == {"confident": 0.98, "check": 0.5} == CONF["bands"]
    assert {"confident", "check"} <= set(bands)


def test_only_the_low_confidence_to_do_differs_between_a_low_and_a_high_confidence(tmp_path, monkeypatch):
    """092 (turned round: until then no to-do came from the confidence): a low one adds its `gpt:low_conf` to-dos and
    nothing else."""
    low = _run_g_with(tmp_path / "a", GOOD, p=0.9, monkeypatch=monkeypatch)
    high = _run_g_with(tmp_path / "b", GOOD, p=0.9999, monkeypatch=monkeypatch)
    assert any(r.startswith("gpt:low_conf:") for r in low.review_reasons)
    assert sorted(r for r in low.review_reasons if not r.startswith("gpt:low_conf:")) == sorted(high.review_reasons)
