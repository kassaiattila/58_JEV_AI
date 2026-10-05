"""Synthetic regressions for Excel sources and bounded interpretation."""
from io import BytesIO
from decimal import Decimal
import json
import zipfile
from types import SimpleNamespace
import pytest

from openpyxl import Workbook

from jav.readers.native import read
from jav.readers.limits import DEFAULT_LIMITS, ReadFailure
from jav import native_processing, native_results, store
from jav.readers import providers
from jav.readers.interpretation import ProposedExtraction
from jav.readers.interpretation import ground, source_view
from jav.runtime import calls
from native_fixtures_109 import runtime_source
from native_fixtures_109 import synthetic_gpt


def workbook(*, rows=1, hyperlink=False):
    book = Workbook()
    sheet = book.active
    sheet.title = "Orders"
    sheet.append(["Reference", "Amount"])
    for index in range(rows):
        sheet.append([f"Order {index:04d}", index + 10])
    if hyperlink:
        sheet["A2"].hyperlink = "https://example.invalid/reference"
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_excel_hyperlink_keeps_cells_and_reports_unfollowed_target():
    result = read(workbook(hyperlink=True), "orders.xlsx", DEFAULT_LIMITS)
    assert any(e["text"] == "Order 0000" for e in result["elements"])
    assert result["status"] == "partial"
    assert any("not followed" in issue["message"] for issue in result["issues"])


class RecordingAgent:
    def __init__(self):
        self.views = []

    def run_sync(self, prompt, **kwargs):
        view = json.loads(prompt)
        self.views.append(view)
        row = view["elements"][-1]
        proposal = ProposedExtraction.model_validate_json(json.dumps({"facts": [{
            "entity": "order", "property": "amount", "value": row["text"], "state": "stated",
            "citations": [{"occurrence_id": row["occurrence_id"], "element_id": row["element_id"], "quote": row["text"]}]}]}))
        return SimpleNamespace(output=proposal, usage=SimpleNamespace(input_tokens=100, output_tokens=40),
                               response=SimpleNamespace(model_name="synthetic-model"))


def test_large_excel_reaches_provider_in_bounded_chunks_without_lost_cells(tmp_path, monkeypatch):
    with store.use_store(tmp_path / "native.sqlite"):
        _, ref = runtime_source(tmp_path, monkeypatch, name="orders.xlsx", content=workbook(rows=250))
        delivery = native_results.load_reading(ref.reading_id)
        agent = RecordingAgent()
        original = providers.extract_gpt
        monkeypatch.setattr(providers, "extract_gpt", lambda *a, **kw: original(*a, agent=agent, **kw))
        with calls.measurement("native-run", {"openai": Decimal("3")}):
            outcome_id = native_processing.interpret(work_run_id="native-run", item_id="native-item",
                graph_id="native-graph", reading_id=ref.reading_id, jev=False, use_cache=False,
                limits=native_processing.estimate_limits({"jev": "off"}))
        _, outcome, interpretation = native_results.load_outcome(outcome_id)
        assert outcome.status == "succeeded"
        assert len(agent.views) > 1
        expected = {(r.attempt.occurrence_id, e.element_id) for r in delivery.bundle.results for e in r.elements if e.text}
        seen = {(r["occurrence_id"], r["element_id"]) for view in agent.views for r in view["elements"]}
        assert seen == expected
        assert len(outcome.receipt_refs) == len(agent.views)
        assert interpretation.source_bundle_sha256 == delivery.bundle.digest()
        assert all(f.grounding == "literal_match" for f in interpretation.facts)


def test_large_excel_jev_checks_every_fact_in_bounded_requests(tmp_path, monkeypatch):
    from jav.adapters import jev
    from typesafe_sdk import SystemOneResponse

    requests = []

    class Client:
        def system_one(self, *, state, questions, model):
            requests.append({"state": state, "questions": {k: q.model_dump(mode="json") for k, q in questions.items()}, "model": model})
            return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 100},
                "answers": {key: {"type": "noul", "noul": 0.8} for key in questions}})

    original_adapter = jev.JevAdapter
    monkeypatch.setattr(jev, "JevAdapter", lambda **kw: original_adapter(client=Client(), model="jev-9.9.9", **kw))
    with store.use_store(tmp_path / "native.sqlite"):
        _, ref = runtime_source(tmp_path, monkeypatch, name="orders.xlsx", content=workbook(rows=250))
        agent = RecordingAgent()
        original = providers.extract_gpt
        monkeypatch.setattr(providers, "extract_gpt", lambda *a, **kw: original(*a, agent=agent, **kw))
        with calls.measurement("native-run", {"openai": Decimal("3"), "jev": Decimal("1")}):
            result = native_processing.interpret(work_run_id="native-run", item_id="native-item",
                graph_id="native-graph", reading_id=ref.reading_id, jev=True, use_cache=False,
                limits=native_processing.estimate_limits({}))
        _, outcome, interpretation = native_results.load_outcome(result)
        assert outcome.status == "succeeded"
        assert all(f.semantic_support == 0.8 for f in interpretation.facts)
        assert sum(len(r["questions"]) for r in requests) == len(interpretation.facts)
        assert all(len(json.dumps(r).encode()) <= 80_000 for r in requests)


def formula_workbook():
    book = Workbook()
    book.active["A1"] = "=2+3"
    output = BytesIO()
    book.save(output)
    book.close()
    fixed = BytesIO()
    with zipfile.ZipFile(BytesIO(output.getvalue())) as source, zipfile.ZipFile(fixed, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "xl/worksheets/sheet1.xml":
                data = data.replace(b"<v></v>", b"<v>5</v>")
            target.writestr(name, data)
    return fixed.getvalue()


def test_saved_formula_result_reaches_interpretation_and_resolves_to_original_cell(tmp_path, monkeypatch):
    from jav.native_contracts import Succeeded

    with store.use_store(tmp_path / "native.sqlite"):
        _, ref = runtime_source(tmp_path, monkeypatch, name="formula.xlsx", content=formula_workbook())
        delivery = native_results.load_reading(ref.reading_id)
        row = source_view(delivery)["elements"][0]
        assert row["cell"]["formula"] == "=2+3"
        assert row["cell"]["cached_value"]["lexical"] == "5"
        assert row["cell"]["cached_state"] == "unverified"
        proposal = ProposedExtraction.model_validate_json(json.dumps({"facts": [{"entity": "order",
            "property": "total", "value": "5", "state": "stated", "citations": [{
                "occurrence_id": row["occurrence_id"], "element_id": row["element_id"], "quote": "5"}]}]}))
        result = ground(delivery, proposal, provider="synthetic", model="test", execution="synthetic_test")
        assert result.facts[0].grounding == "literal_match"
        assert any("not recalculated" in reason for reason in result.facts[0].reasons)
        publication = native_results.publish(run_id="native-run", item_id="native-item",
            source_sha256=ref.source_sha256, recipe_hash="a" * 16, reading_id=ref.reading_id,
            outcome=Succeeded(), interpretation=result)
        assert native_results.machine_facts(publication)[0].native_citations[0].locator.cell == "A1"


@pytest.mark.parametrize("property_name,warning", [("hours", True), ("hourly rate", False), ("\u00f3rasz\u00e1m", True)])
def test_currency_cannot_silently_be_accepted_as_hours(tmp_path, monkeypatch, property_name, warning):
    from jav import flow_native

    with store.use_store(tmp_path / "native.sqlite"):
        source, ref = runtime_source(tmp_path, monkeypatch, name="hours.csv", content=b"Hours\n2 million HUF/month")
        synthetic_gpt(monkeypatch, payload={"facts": [{"entity": "work", "property": property_name,
            "value": "2 million HUF/month", "state": "stated", "citations": [{
                "occurrence_id": "o0", "element_id": "e1", "quote": "2 million HUF/month"}]}]})
        with calls.measurement("native-run", {"openai": Decimal("1")}):
            _, _, state = flow_native.build_app(work_run_id="native-run", item_id="native-item", graph_id="native-graph",
                source_path=str(source), read_path=str(source), original_name="hours.csv", expected_sha256=ref.source_sha256,
                recipe_hash="a" * 16, jev=False, use_cache=False).run(halt_after=flow_native.TERMINALS)
        fact = native_results.get_publication("native-run", "native-item").interpretation.facts[0]
        assert fact.grounding == "literal_match"
        assert any("Currency" in reason for reason in fact.reasons) == warning
        assert (state.data.final_status == "needs_review") == warning


def test_legacy_interpretation_digest_does_not_gain_new_optional_fields(tmp_path, monkeypatch):
    from jav.readers.interpretation import Interpretation
    from jav.readers.pipeline import digest, json_bytes
    from native_fixtures_109 import publish_runtime

    with store.use_store(tmp_path / "native.sqlite"):
        _, ref = runtime_source(tmp_path, monkeypatch)
        publication = publish_runtime(ref)
        legacy = publication.interpretation.model_dump(mode="json", exclude={"coverage"})
        restored = Interpretation.model_validate_json(json_bytes(legacy))
        assert restored.digest() == digest(json_bytes(legacy))


@pytest.mark.parametrize("part,body", [
    ("xl/vbaProject.bin", b"synthetic macro"),
    ("xl/externalLinks/externalLink1.xml", b"<externalLink><ddeLink/></externalLink>"),
    ("xl/worksheets/_rels/sheet2.xml.rels", b'<Relationships><Relationship Type="unknown" TargetMode="External" Target="https://example.invalid"/></Relationships>'),
])
def test_active_and_unknown_external_parts_remain_excluded(part, body):
    data = BytesIO(workbook(hyperlink=True))
    with zipfile.ZipFile(data, "a") as archive:
        archive.writestr(part, body)
    with pytest.raises(ReadFailure) as error:
        read(data.getvalue(), "active.xlsx", DEFAULT_LIMITS)
    assert error.value.status == "excluded"


def test_external_workbook_link_does_not_hide_local_values():
    data = BytesIO(workbook())
    with zipfile.ZipFile(data, "a") as archive:
        archive.writestr("xl/externalLinks/externalLink1.xml", b"<externalLink><externalBook/></externalLink>")
        archive.writestr("xl/externalLinks/_rels/externalLink1.xml.rels", b'<Relationships><Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath" TargetMode="External" Target="file:///unavailable.xlsx"/></Relationships>')
    result = read(data.getvalue(), "linked.xlsx", DEFAULT_LIMITS)
    assert any(e["text"] == "Order 0000" for e in result["elements"])
    assert any("not followed" in issue["message"] for issue in result["issues"])


def test_oversized_row_is_rejected_before_any_provider_call(tmp_path, monkeypatch):
    with store.use_store(tmp_path / "native.sqlite"):
        _, ref = runtime_source(tmp_path, monkeypatch, name="large.csv", content=("x" * 90_000).encode())
        agent = RecordingAgent()
        with calls.measurement("native-run", {"openai": Decimal("1")}):
            with pytest.raises(ValueError, match="transfer bound"):
                providers.extract_gpt(native_results.load_reading(ref.reading_id), run_id="oversized",
                    isolated_store=store.active_path(), agent=agent)
        assert not agent.views and not calls.journal("oversized")


def test_interrupted_chunk_keeps_receipts_and_never_retries_automatically(tmp_path, monkeypatch):
    class InterruptedAgent(RecordingAgent):
        def run_sync(self, prompt, **kwargs):
            if len(self.views) == 1:
                self.views.append(json.loads(prompt))
                raise TimeoutError("Synthetic interrupted second chunk")
            return super().run_sync(prompt, **kwargs)

    with store.use_store(tmp_path / "native.sqlite"):
        _, ref = runtime_source(tmp_path, monkeypatch, name="orders.xlsx", content=workbook(rows=250))
        agent = InterruptedAgent()
        original = providers.extract_gpt
        monkeypatch.setattr(providers, "extract_gpt", lambda *a, **kw: original(*a, agent=agent, **kw))
        params = dict(work_run_id="native-run", item_id="native-item", graph_id="native-graph",
            reading_id=ref.reading_id, jev=False, use_cache=False, limits=native_processing.estimate_limits({"jev": "off"}))
        with calls.measurement("native-run", {"openai": Decimal("3")}):
            first = native_processing.interpret(**params)
            assert native_processing.interpret(**params) == first
        _, outcome, interpretation = native_results.load_outcome(first)
        assert outcome.status == "uncertain" and interpretation is None
        assert len(agent.views) == 2 and len(outcome.receipt_refs) == 2


def test_chunked_requests_fit_the_actual_openai_wire_envelope(tmp_path, monkeypatch):
    import asyncio
    import httpx2
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from jav import config

    sizes, seen = [], set()

    def respond(request):
        sizes.append(len(request.content))
        wire = json.loads(request.content)
        view = json.loads(next(m["content"] for m in wire["messages"] if m["role"] == "user"))
        seen.update((row["occurrence_id"], row["element_id"]) for row in view["elements"])
        assert wire["response_format"]["json_schema"]["strict"] is True
        return httpx2.Response(200, json={"id": "synthetic", "object": "chat.completion", "created": 1700000000,
            "model": config.OPENAI_MODEL, "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"facts":[],"gaps":[]}'}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})

    client = AsyncOpenAI(api_key="synthetic-not-a-key", max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(respond)))
    model = OpenAIChatModel(config.OPENAI_MODEL, provider=OpenAIProvider(openai_client=client))
    monkeypatch.setattr(config, "openai_chat_model", lambda: model)
    try:
        with store.use_store(tmp_path / "native.sqlite"):
            _, ref = runtime_source(tmp_path, monkeypatch, name="orders.xlsx", content=workbook(rows=250))
            delivery = native_results.load_reading(ref.reading_id)
            with calls.measurement("native-run", {"openai": Decimal("1")}):
                result = providers.extract_gpt(delivery, run_id="wire", isolated_store=store.active_path())
        assert len(sizes) > 1 and max(sizes) <= 80_000
        assert result.coverage.submitted_elements == len(seen) == 502
    finally:
        asyncio.run(client.close())
