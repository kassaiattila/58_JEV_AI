"""Offline provider adapters must preserve real reservation/replay behavior."""
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
import os

import pytest

from jav import store
from jav.config import OPENAI_MODEL
from jav.readers.interpretation import ProposedExtraction, ground
from jav.readers.pipeline import read_files
from jav.readers.providers import extract_gpt, select_jev, verify_jev
from jav.readers.receipts import InterpretationRejected
from jav.runtime import calls

pytest.importorskip("docx", reason="Native reader dependencies await integration")
pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows Job Object reader boundary")


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.txt"
    path.write_text("Order code: 0007\nQuantity: 3", encoding="utf-8")
    return read_files([path])


def proposed():
    return ProposedExtraction.model_validate_json('''{"facts":[{"entity":"order","property":"code","value":"0007",
      "state":"stated","citations":[{"occurrence_id":"o0","element_id":"e0","quote":"Order code: 0007"}]}]}''')


class FakeAgent:
    def __init__(self):
        self.calls = 0

    def run_sync(self, prompt, **kwargs):
        self.calls += 1
        return SimpleNamespace(output=proposed(), usage=SimpleNamespace(input_tokens=100, output_tokens=40),
                               response=SimpleNamespace(model_name=OPENAI_MODEL))


def test_gpt_uses_existing_reservation_and_replays_without_a_second_call(source, tmp_path):
    path = tmp_path / "trial.sqlite"
    agent = FakeAgent()
    with store.use_store(path), calls.measurement("native-synthetic", {"openai": Decimal("1")}):
        first = extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)
        again = extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)
        assert first == again
        with store.connect() as conn:
            assert conn.execute("SELECT count(*) FROM invocations WHERE status='succeeded'").fetchone()[0] == 1
    assert agent.calls == 1
    assert first.execution == "synthetic_test"


def test_gpt_refuses_missing_provider_budget_before_calling(source, tmp_path):
    agent = FakeAgent()
    path = tmp_path / "trial.sqlite"
    with store.use_store(path), calls.measurement("only-jev", {"jev": Decimal("0.1")}):
        with pytest.raises(ValueError, match="sub-budget"):
            extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)
    assert agent.calls == 0


def test_rejected_native_answer_is_not_an_interpretation_and_is_not_called_again(source, tmp_path):
    from pydantic_ai import Agent, NativeOutput
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.usage import RequestUsage

    requests = []

    def respond(messages, info):
        requests.append(1)
        return ModelResponse([TextPart('{"facts":[{"entity":"order"}]}')],
                             usage=RequestUsage(input_tokens=100, output_tokens=40))

    agent = Agent(FunctionModel(respond, model_name=OPENAI_MODEL),
                  output_type=NativeOutput(ProposedExtraction), retries=0)
    path = tmp_path / "trial.sqlite"
    with store.use_store(path), calls.measurement("native-invalid", {"openai": Decimal("1")}):
        for _ in range(2):
            with pytest.raises(InterpretationRejected, match="private receipt"):
                extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)
        assert calls.budget_usage("native-invalid")["committed_usd"] == Decimal("0.000255")
    assert requests == [1]


@pytest.mark.parametrize("requested", [False, True])
def test_production_gpt_factory_sends_strict_native_schema(source, tmp_path, monkeypatch, requested):
    import asyncio
    import json
    import httpx2
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from jav import config

    requests = []
    sizes = []
    estimated = []
    original_estimate = calls.estimate_max_cost

    def estimate(**kwargs):
        estimated.append(kwargs["input_bytes"])
        return original_estimate(**kwargs)

    monkeypatch.setattr(calls, "estimate_max_cost", estimate)

    def respond(request):
        requests.append(json.loads(request.content))
        sizes.append(len(request.content))
        return httpx2.Response(200, json={"id": "synthetic-completion", "object": "chat.completion",
            "created": 1700000000, "model": OPENAI_MODEL,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": proposed().model_dump_json()}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}})

    client = AsyncOpenAI(api_key="synthetic-not-a-real-key", max_retries=0,
                         http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)))
    model = OpenAIChatModel(OPENAI_MODEL, provider=OpenAIProvider(openai_client=client))
    monkeypatch.setattr(config, "openai_chat_model", lambda: model)
    path = tmp_path / "trial.sqlite"
    try:
        with store.use_store(path), calls.measurement("strict-wire", {"openai": Decimal("1")}):
            result = extract_gpt(source, run_id="trial", isolated_store=path,
                **({"fields": {"code": "order identifier"}, "entity": "order"} if requested else {}))
    finally:
        asyncio.run(client.close())
    assert result.facts[0].grounding == "literal_match"
    assert len(requests) == 1
    if requested:
        assert any('"requested_fields"' in message["content"] for message in requests[0]["messages"])
    assert estimated[0] >= sizes[0]
    wire = requests[0]["response_format"]["json_schema"]
    assert wire["strict"] is True
    from jav.readers.providers import gpt_response_format
    assert requests[0]["response_format"] == gpt_response_format()
    schema = wire["schema"]
    assert set(schema["properties"]) == {"facts", "gaps"}
    for shape in [schema, *schema["$defs"].values()]:
        assert shape["additionalProperties"] is False
        assert set(shape["required"]) == set(shape["properties"])
        assert all("default" not in prop for prop in shape["properties"].values())


def test_requested_task_changes_replay_identity(source, tmp_path):
    path = tmp_path / "trial.sqlite"
    agent = FakeAgent()
    with store.use_store(path), calls.measurement("task-key", {"openai": Decimal("1")}):
        extract_gpt(source, run_id="trial", isolated_store=path, agent=agent)
        for _ in range(2):
            extract_gpt(source, run_id="trial", isolated_store=path, agent=agent,
                        fields={"code": "order identifier"}, entity="order")
        with pytest.raises(ValueError, match="one to twenty"):
            extract_gpt(source, run_id="trial", isolated_store=path, agent=agent, fields={}, entity="order")
    assert agent.calls == 2


class FakeJev:
    def no_cache_write(self):
        return nullcontext()

    def ask(self, request_id, state, questions, **kwargs):
        answers = {key: SimpleNamespace(choice="c0", noul=0.8) for key in questions}
        return SimpleNamespace(response=SimpleNamespace(answers=answers, model="jev-test"), cached=False)


def test_jev_selection_and_support_are_distinct_from_correctness(source, tmp_path):
    path = tmp_path / "trial.sqlite"
    with store.use_store(path), calls.measurement("jev-arms", {"jev": Decimal("0.1")}):
        selected = select_jev(source, {"code": "order identifier"}, entity="order", run_id="trial",
                              isolated_store=path, adapter=FakeJev())
        assert selected.facts[0].proposal.value == "0007"
        initial = ground(source, proposed(), provider="offline", model="fixture", execution="synthetic_test")
        verified = verify_jev(source, initial, run_id="trial", isolated_store=path, adapter=FakeJev())
    assert verified.facts[0].semantic_support == 0.8
    assert verified.correctness == "not_established"
    assert verified.review_status == "not_reviewed"
