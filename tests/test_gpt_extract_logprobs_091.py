"""091 (GPT field confidence): the extraction asks for a native structured answer with token log-probabilities, and
keeps them with the answer, so each top-level value gets a measured probability.

The saved answer has a format mark: an answer saved before 091 (the plain extraction) is still read, without
probabilities. Stand-in models only; no paid call.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic_ai import NativeOutput

from jav import extract_llm, store
from jav.runtime import calls
from jav.typepack import get as get_pack
from tests.test_no_jev_085 import GOOD


def _logprobs_for(text: str, p: float = 0.9) -> list[dict]:
    """One token per character with probability `p` (enough to locate every value)."""
    return [{"token": ch, "logprob": math.log(p), "top_logprobs": []} for ch in text]


class _LogprobAgent:
    """A GPT stand-in that answers with the given extraction and its token log-probabilities."""

    def __init__(self, pack, values, p: float = 0.9):
        self.out = pack.llm_model().model_validate(values)
        self.p = p
        self.calls = 0

    def run_sync(self, prompt, **_kw):
        self.calls += 1
        text = json.dumps(self.out.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))
        return SimpleNamespace(output=self.out, usage=SimpleNamespace(input_tokens=100, output_tokens=50),
                               response=SimpleNamespace(model_name="gpt-5.4-mini",
                                                        provider_details={"logprobs": _logprobs_for(text, self.p)}))


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "r.sqlite"):
        yield tmp_path


def test_the_agent_asks_for_a_native_answer_with_log_probabilities(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")  # 120: building the agent only; no call is made
    agent = extract_llm.get_agent("invoice_hu")
    assert isinstance(agent.output_type, NativeOutput)
    assert agent.model_settings["openai_logprobs"] is True
    assert agent.model_settings["openai_top_logprobs"] == extract_llm.TOP_LOGPROBS


def test_scored_extraction_gives_the_values_and_their_probabilities(isolated):
    pack = get_pack("invoice_hu")
    with extract_llm.use_agent_factory(lambda p: _LogprobAgent(p, GOOD, p=0.99)):
        scored = extract_llm.extract_scored("Invoice number: MINTA-1", run_id="adhoc", pack=pack)
    assert scored.output["invoice_number"] == GOOD["invoice_number"]
    tp = scored.token_p["invoice_number"]
    # one token per printed character, quotes included
    n = len(json.dumps(GOOD["invoice_number"]))
    assert tp["n"] == n and tp["joint"] == pytest.approx(0.99 ** n, abs=1e-3) and tp["min"] == pytest.approx(0.99, abs=1e-4)
    assert set(scored.token_p) <= set(pack.llm_model().model_fields)


def test_a_worker_run_saves_the_marked_answer_and_extract_stays_a_plain_dict(isolated):
    pack = get_pack("invoice_hu")
    calls.set_budget("run-a", "openai", Decimal("1"))
    with extract_llm.use_agent_factory(lambda p: _LogprobAgent(p, GOOD)), calls.use_run(budget_scope="run-a"):
        plain = extract_llm.extract("Invoice number: MINTA-1", run_id="run-a", pack=pack)
    assert plain["invoice_number"] == GOOD["invoice_number"] and "logprobs" not in plain
    saved = calls.journal("run-a")[0]
    assert saved["status"] == "succeeded"


def test_an_answer_saved_before_the_change_is_read_without_probabilities():
    old = {"invoice_number": "MINTA-1", "gross_total": "12 700"}
    assert extract_llm.decode_answer(old) == (old, None)
    new = extract_llm.encode_answer(old, _logprobs_for('{"invoice_number":"MINTA-1"}'))
    output, token_p = extract_llm.decode_answer(new)
    assert output == old and set(token_p) == {"invoice_number"}


def test_the_reuse_key_differs_from_the_tool_answer_of_090(isolated):
    """An earlier answer of the tool-output request (no probabilities) is not reused for the native request."""
    pack = get_pack("invoice_hu")
    agent = _LogprobAgent(pack, GOOD)
    calls.set_budget("run-a", "openai", Decimal("1"))
    prompt = extract_llm.USER_PREFIX + "Invoice number: MINTA-1"
    schema = json.dumps(pack.llm_model().model_json_schema(), ensure_ascii=False)
    from jav.config import OPENAI_MODEL, OPENAI_SETTINGS, load_prompt

    old_key = calls.answer_key("openai", OPENAI_MODEL, load_prompt(pack.prompt_file), schema,
                               json.dumps(OPENAI_SETTINGS, sort_keys=True), str(extract_llm.RUN_MAX_OUTPUT_TOKENS), prompt)
    calls.invoke(run_id="run-0", step_id="openai:extract_llm:old", provider="openai", model=OPENAI_MODEL,
                 max_cost_usd=Decimal("0.05"), request_hash=old_key, reusable=True,
                 fn=lambda: calls.Outcome(response={"invoice_number": "OLD-1"}, model=OPENAI_MODEL, cost_usd=Decimal("0.01")))
    with extract_llm.use_agent_factory(lambda p: agent), calls.use_run(budget_scope="run-a", reuse=True):
        scored = extract_llm.extract_scored("Invoice number: MINTA-1", run_id="run-a", pack=pack)
    assert agent.calls == 1 and scored.output["invoice_number"] == GOOD["invoice_number"] and scored.token_p
