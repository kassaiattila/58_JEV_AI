"""Exercise the actual native-output validator without network access."""
from decimal import Decimal
import json

import pytest
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from jav import store
from jav.config import OPENAI_MODEL
from jav.readers.interpretation import ProposedExtraction
from jav.readers.receipts import run_gpt_once
from jav.runtime import calls


def payload():
    return {"facts": [{"entity": "order", "property": "code", "value": "0007",
            "state": "stated", "citations": [{"occurrence_id": "o0", "element_id": "e0",
            "quote": "Order code: 0007"}]}], "gaps": []}


@pytest.mark.parametrize("invalid", [False, True])
def test_actual_native_output_keeps_receipt_cost_and_replays(tmp_path, invalid):
    count = []
    value = payload()
    if invalid:
        value["facts"][0]["state"] = "missing"

    def respond(messages, info):
        count.append(1)
        return ModelResponse([TextPart(json.dumps(value))],
                             usage=RequestUsage(input_tokens=100, output_tokens=40))

    agent = Agent(FunctionModel(respond, model_name=OPENAI_MODEL),
                  output_type=NativeOutput(ProposedExtraction), retries=0)
    with store.use_store(tmp_path / "trial.sqlite"), calls.measurement("wire", {"openai": Decimal("1")}):
        def invoke():
            return calls.invoke(run_id="test", step_id="wire", provider="openai", model=OPENAI_MODEL,
                max_cost_usd=Decimal("0.1"), budget_scope="wire",
                fn=lambda: run_gpt_once(agent, "synthetic data", {"max_tokens": 4000}, OPENAI_MODEL))

        first = invoke()
        again = invoke()
        assert again.replayed and again.response == first.response
        with store.connect() as connection:
            row = connection.execute("SELECT status,input_tokens,output_tokens,cost_known,cost_usd FROM invocations").fetchone()
        assert tuple(row) == ("succeeded", 100, 40, 1, "0.000255")
        assert calls.budget_usage("wire")["committed_usd"] == Decimal("0.000255")
    assert count == [1]
    receipt = first.response
    assert receipt["provider_responses"][0]["parts"][0]["content"] == json.dumps(value)
    if invalid:
        assert receipt["proposal"] is None
        assert receipt["validation_error"]["validation"] == [{"type": "value_error", "location": ["facts", 0]}]
    else:
        assert receipt["validation_error"] is None
        assert receipt["proposal"]["facts"][0]["value"] == "0007"


def test_no_response_preserves_existing_transport_failure_path():
    class NoResponse:
        def run_sync(self, *args, **kwargs):
            raise TimeoutError("synthetic transport failure")

    with pytest.raises(TimeoutError):
        run_gpt_once(NoResponse(), "synthetic", {}, OPENAI_MODEL)


def test_malformed_json_is_saved_and_an_unknown_price_keeps_the_reservation(tmp_path):
    def respond(messages, info):
        return ModelResponse([TextPart('{"facts":[')], usage=RequestUsage(input_tokens=100, output_tokens=40))

    agent = Agent(FunctionModel(respond, model_name="unpriced-test-model"),
                  output_type=NativeOutput(ProposedExtraction), retries=0)
    with store.use_store(tmp_path / "trial.sqlite"), calls.measurement("wire", {"openai": Decimal("1")}):
        result = calls.invoke(run_id="test", step_id="invalid", provider="openai", model="unpriced-test-model",
            max_cost_usd=Decimal("0.1"), budget_scope="wire",
            fn=lambda: run_gpt_once(agent, "synthetic", {}, "unpriced-test-model"))
        assert result.response["validation_error"]["validation"][0]["type"] == "json_invalid"
        assert result.response["provider_responses"][0]["parts"][0]["content"] == '{"facts":['
        assert calls.budget_usage("wire")["committed_usd"] == Decimal("0.1")


def test_openai_transport_and_native_schema_accept_the_same_valid_response():
    import asyncio
    import httpx2 as httpx
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "synthetic-completion", "object": "chat.completion",
            "created": 1700000000, "model": OPENAI_MODEL,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(payload())}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140}})

    client = AsyncOpenAI(api_key="synthetic-not-a-real-key", max_retries=0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        model = OpenAIChatModel(OPENAI_MODEL, provider=OpenAIProvider(openai_client=client))
        agent = Agent(model, output_type=NativeOutput(ProposedExtraction), retries=0)
        result = run_gpt_once(agent, "synthetic", {"max_tokens": 4000}, OPENAI_MODEL)
    finally:
        asyncio.run(client.close())
    assert len(requests) == 1
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert result.response["validation_error"] is None
    assert result.response["proposal"]["facts"][0]["value"] == "0007"
