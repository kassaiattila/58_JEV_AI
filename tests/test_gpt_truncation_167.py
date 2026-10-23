"""167 (review AI-7): a GPT extraction cut off at its output cap is not asked again.

A long document (over about 30 statement lines) made the answer stop at the 4000-token cap; its JSON was cut off,
Pydantic AI retried it as a validation error, and each retry was another paid request cut off at the same place,
ending in `llm:failed`. Now the cut-off answer ends the call at once with its own to-do, `llm:truncated`, and the
ledger records it with its tokens. The cap moved into `configs/gpt_extract.json` with its value unchanged, so the
requests and the reuse key of earlier answers stay as they were.

The OpenAI transport is a local stand-in (`httpx.MockTransport`): no paid call.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from jav.ai import extract_llm
from jav.core import cfg, store
from jav.core.config import OPENAI_MODEL, OPENAI_SETTINGS, OPENAI_USD_PER_MTOK
from jav.ai.models import FlowState
from jav.core import calls
from jav.ai.typepack import get as get_pack
from tests.test_no_jev_085 import GOOD

PACK = get_pack("invoice_hu")


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "t.sqlite"):
        yield tmp_path


class _Transport:
    """The OpenAI chat endpoint as a local stand-in: records each request body, answers with `finish_reason`."""

    def __init__(self, finish_reason: str = "stop"):
        self.finish_reason = finish_reason
        self.bodies: list[dict] = []

    def __call__(self, request):
        self.bodies.append(json.loads(request.content))
        full = json.dumps(PACK.llm_model().model_validate(GOOD).model_dump(mode="json"), ensure_ascii=False)
        content = full if self.finish_reason == "stop" else full[: len(full) // 2]  # a cut-off answer is cut-off JSON
        return httpx.Response(200, json={
            "id": "synthetic-completion", "object": "chat.completion", "created": 1700000000, "model": OPENAI_MODEL,
            "choices": [{"index": 0, "finish_reason": self.finish_reason, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 4000 if self.finish_reason == "length" else 200,
                      "total_tokens": 5000}})


def _run(transport: _Transport, build, *, limited: bool = True):
    client = AsyncOpenAI(api_key="synthetic-not-a-real-key", max_retries=0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    try:
        agent = build(OpenAIChatModel(OPENAI_MODEL, provider=OpenAIProvider(openai_client=client)))
        return extract_llm._physical(agent, extract_llm.USER_PREFIX + "Invoice number: MINTA-1", run_id="r-t",
                                     pack=PACK, limited=limited)
    finally:
        asyncio.run(client.close())


def _unguarded(model) -> Agent:
    """The extraction agent as it was built before 167: the same settings, without the truncation stop."""
    settings = OpenAIChatModelSettings(openai_reasoning_effort=OPENAI_SETTINGS["reasoning_effort"],
                                       temperature=OPENAI_SETTINGS["temperature"], openai_logprobs=True,
                                       openai_top_logprobs=extract_llm.TOP_LOGPROBS)
    return Agent(model, output_type=NativeOutput(PACK.llm_model()), instructions=extract_llm.instructions(PACK),
                 model_settings=settings, retries=OPENAI_SETTINGS["retries"])


def test_the_cap_is_configuration_with_its_earlier_value():
    assert cfg.load("gpt_extract")["max_output_tokens"] == 4000 == extract_llm.RUN_MAX_OUTPUT_TOKENS


def test_the_request_on_the_wire_is_unchanged(isolated):
    guarded, plain = _Transport(), _Transport()
    _run(guarded, lambda m: extract_llm.build_agent(PACK, m))
    _run(plain, _unguarded)
    assert len(guarded.bodies) == len(plain.bodies) == 1
    assert guarded.bodies[0] == plain.bodies[0]
    assert guarded.bodies[0]["max_completion_tokens"] == 4000


def test_the_reuse_key_of_an_ordinary_extraction_is_unchanged(isolated):
    """The key of 091 with the cap written as the literal of before 167."""
    text = "Invoice number: MINTA-1"
    prompt = extract_llm.USER_PREFIX + text
    schema = json.dumps(PACK.llm_model().model_json_schema(), ensure_ascii=False)
    expected = calls.answer_key("openai", OPENAI_MODEL, extract_llm.instructions(PACK), schema,
                                json.dumps(OPENAI_SETTINGS, sort_keys=True), "4000", prompt,
                                extract_llm.ANSWER_FORMAT, str(extract_llm.TOP_LOGPROBS))
    agent = SimpleNamespace(run_sync=lambda p, **kw: SimpleNamespace(
        output=PACK.llm_model().model_validate(GOOD), usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        response=SimpleNamespace(model_name=OPENAI_MODEL, provider_details={})))
    calls.set_budget("run-k", "openai", Decimal("1"))
    with extract_llm.use_agent_factory(lambda p: agent), calls.use_run(budget_scope="run-k"):
        extract_llm.extract_scored(text, run_id="run-k", pack=PACK)
    with store.connect() as c:
        assert c.execute("SELECT request_hash FROM invocations WHERE run_id='run-k'").fetchone()[0] == expected


def test_a_cut_off_answer_is_not_asked_again(isolated):
    guarded = _Transport("length")
    with pytest.raises(extract_llm.OutputTruncated):
        _run(guarded, lambda m: extract_llm.build_agent(PACK, m))
    assert len(guarded.bodies) == 1  # before 167: every validation retry was another paid request (below)
    row = store.ledger_for_run("r-t")[0]
    assert row["error"] == "OutputTruncated" and (row["input_tokens"], row["output_tokens"]) == (1000, 4000)
    price_in, price_out = OPENAI_USD_PER_MTOK[OPENAI_MODEL]
    assert row["cost_usd"] == pytest.approx((1000 * price_in + 4000 * price_out) / 1_000_000)

    plain = _Transport("length")
    with pytest.raises(Exception) as caught:
        _run(plain, _unguarded)
    assert not isinstance(caught.value, extract_llm.OutputTruncated)
    assert len(plain.bodies) == extract_llm.ROUNDS


class _CutOff:
    """A GPT stand-in whose answer is cut off at the cap."""

    def __init__(self):
        self.calls = 0

    def run_sync(self, prompt, **_kw):
        self.calls += 1
        raise extract_llm.OutputTruncated(OPENAI_MODEL, SimpleNamespace(input_tokens=1000, output_tokens=4000))


def test_the_flow_gives_a_cut_off_answer_its_own_to_do(isolated):
    from jav.flow import extract_llm as extract_step

    agent = _CutOff()
    calls.set_budget("run-f", "openai", Decimal("1"))
    with extract_llm.use_agent_factory(lambda p: agent), calls.use_run(budget_scope="run-f"):
        state = extract_step(FlowState(doc_type="invoice_hu", source_path="synthetic.pdf", case_id="t", arm="G", run_id="run-f",
                                       text="Invoice number: MINTA-1"))
    assert state.llm_output is None and state.needs_review
    assert "llm:truncated" in state.review_reasons
    assert not any(r.startswith("llm:failed") for r in state.review_reasons)
    assert agent.calls == 1
    journal = calls.journal("run-f")
    assert [(j["status"], j["error"]) for j in journal] == [("failed", "OutputTruncated")]


def test_a_named_copy_of_a_cut_off_extraction_goes_to_the_review_folder():
    """The to-do is about the whole document, like `llm:failed` (configs/naming.json reason_scope)."""
    from tests.test_naming_078 import INVOICE, _review

    assert _review(["llm:truncated"], corrected=list(INVOICE)) == ["todo:*"]
