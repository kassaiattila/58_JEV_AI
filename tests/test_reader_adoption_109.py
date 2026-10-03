"""Synthetic witnesses for gaps found while adopting the shared native readers."""
from decimal import Decimal
from io import BytesIO
import asyncio

import httpx2 as httpx
from openai import AsyncOpenAI
import pytest
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from jav import store
from jav.config import OPENAI_MODEL
from jav.readers import native
from jav.readers.interpretation import ProposedExtraction
from jav.readers.limits import DEFAULT_LIMITS
from jav.readers.pipeline import read_files
from jav.readers.providers import extract_gpt
from jav.readers.receipts import InterpretationRejected, run_gpt_once
from jav.runtime import calls


@pytest.mark.parametrize("placement", ["body", "inline", "header"])
def test_word_content_controls_cannot_claim_complete_reading(placement):
    from docx import Document
    from docx.oxml import parse_xml

    document = Document()
    paragraph = document.add_paragraph("Visible heading")
    fragment = "<w:r><w:t>Unmapped content control value</w:t></w:r>"
    if placement != "inline":
        fragment = f"<w:p>{fragment}</w:p>"
    control = parse_xml(
        '<w:sdt xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:sdtContent>{fragment}</w:sdtContent></w:sdt>"
    )
    if placement == "body":
        document.element.body.insert(1, control)
    elif placement == "inline":
        paragraph._p.append(control)
    else:
        document.sections[0].header._element.append(control)
    source = BytesIO()
    document.save(source)

    result = native.read(source.getvalue(), "content-control.docx", DEFAULT_LIMITS)

    assert result["status"] == "partial"
    assert any(issue["code"] == "unread_content" and "sdt" in issue["message"] for issue in result["issues"])
    assert any(element["text"] == "Visible heading" for element in result["elements"])


@pytest.mark.parametrize("response_kind", ["refusal", "empty", "schema"])
def test_received_rejected_gpt_response_is_saved_costed_and_replayed(tmp_path, response_kind):
    requests = []
    message = {"role": "assistant", "content": None}
    if response_kind == "refusal":
        message["refusal"] = "Synthetic refusal"
    elif response_kind == "schema":
        message["content"] = '{"facts":[{"entity":"order"}]}'

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "synthetic-rejected-response", "object": "chat.completion", "created": 1700000000,
            "model": OPENAI_MODEL,
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
        })

    source_path = tmp_path / "source.txt"
    source_path.write_text("Order code: 0007", encoding="utf-8")
    source = read_files([source_path])
    client = AsyncOpenAI(api_key="synthetic-not-a-real-key", max_retries=0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        agent = Agent(OpenAIChatModel(OPENAI_MODEL, provider=OpenAIProvider(openai_client=client)),
                      output_type=NativeOutput(ProposedExtraction), retries=0)
        database = tmp_path / "trial.sqlite"
        with store.use_store(database), calls.measurement("rejection", {"openai": Decimal("1")}):
            errors = []
            for _ in range(2):
                with pytest.raises(InterpretationRejected, match="private receipt") as rejected:
                    extract_gpt(source, run_id="same-request", isolated_store=database, agent=agent)
                errors.append(str(rejected.value))
            assert errors[0] == errors[1]
            journal = calls.journal("same-request")
            assert len(journal) == 1
            row = journal[0]
            assert (row["status"], row["input_tokens"], row["output_tokens"], row["cost_known"]) == (
                "succeeded", 100, 40, 1)
            assert calls.budget_usage("rejection")["committed_usd"] == Decimal("0.000255")

            def must_not_call():
                raise AssertionError("A received rejection must replay without a physical request")

            replay = calls.invoke(run_id="same-request", step_id=row["step_id"], provider="openai",
                model=OPENAI_MODEL, max_cost_usd=Decimal("0.1"), budget_scope="rejection", fn=must_not_call)
            assert replay.replayed
            assert replay.response["proposal"] is None
            assert replay.response["validation_error"]
            responses = replay.response["provider_responses"]
            assert len(responses) == 1
            assert responses[0]["usage"]["input_tokens"] == 100
            if response_kind == "refusal":
                assert responses[0]["provider_details"]["refusal"] == "Synthetic refusal"
            elif response_kind == "empty":
                assert responses[0]["parts"] == []
            else:
                assert responses[0]["parts"][0]["content"] == message["content"]
    finally:
        asyncio.run(client.close())
    assert len(requests) == 1


def test_gpt_transport_without_a_response_stays_uncertain(tmp_path):
    class NoResponse:
        def run_sync(self, *args, **kwargs):
            raise TimeoutError("Synthetic transport timeout")

    with store.use_store(tmp_path / "trial.sqlite"), calls.measurement("transport", {"openai": Decimal("1")}):
        with pytest.raises(TimeoutError):
            calls.invoke(run_id="timeout", step_id="request", provider="openai", model=OPENAI_MODEL,
                max_cost_usd=Decimal("0.1"), budget_scope="transport",
                fn=lambda: run_gpt_once(NoResponse(), "Synthetic input", {}, OPENAI_MODEL))
        row = calls.journal("timeout")[0]
        assert row["status"] == "uncertain"
        assert row["cost_known"] == 0
        assert calls.budget_usage("transport")["committed_usd"] == Decimal("0.1")
