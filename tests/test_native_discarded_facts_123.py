"""A single malformed fact no longer discards the whole native answer (123, Q-native-discard).

A received answer whose only defect is the presence rule of some facts keeps its
valid facts; the left-out facts are recorded and open a review item. Any other
defect still rejects the whole answer, and the request sent to the model is unchanged.
"""
from decimal import Decimal

import pytest

from jav import flow_native, native_results, store
from jav.readers.interpretation import DiscardedFact, Interpretation, ProposedExtraction, salvage
from jav.readers.pipeline import digest, json_bytes
from jav.runtime import calls
from native_fixtures_109 import runtime_source, synthetic_gpt

VALID = {"entity": "order", "property": "code", "value": "0012", "state": "stated",
         "citations": [{"occurrence_id": "o0", "element_id": "e0", "quote": "Order code: 0012"}]}
# An unfilled dotted line quoted as the value of a fact marked missing (the 122 M9 case).
MISSING_WITH_VALUE = {"entity": "declaration", "property": "signature place", "value": "..........",
                      "state": "missing", "citations": []}
STATED_WITHOUT_CITATION = {"entity": "order", "property": "quantity", "value": "3", "state": "stated",
                           "citations": []}


@pytest.fixture
def isolated(tmp_path):
    with store.use_store(tmp_path / "native.sqlite"):
        yield tmp_path


def build(source, ref):
    return flow_native.build_app(work_run_id="native-run", item_id="native-item", graph_id="native-graph",
        source_path=str(source), read_path=str(source), original_name="original.txt", expected_sha256=ref.source_sha256,
        recipe_hash="a" * 16, jev=False, use_cache=False)


def test_salvage_keeps_valid_facts_and_records_the_left_out_ones():
    raw = json_bytes({"facts": [VALID, MISSING_WITH_VALUE, STATED_WITHOUT_CITATION], "gaps": []}).decode()
    proposal, discarded = salvage(raw)
    assert [fact.property for fact in proposal.facts] == ["code"]
    assert discarded == (
        DiscardedFact(entity="declaration", property="signature place", state="missing",
                      reason="Missing facts cannot invent a value"),
        DiscardedFact(entity="order", property="quantity", state="stated",
                      reason="A proposed value needs its source citations"))


@pytest.mark.parametrize("raw", [
    "not json",
    "{}",
    '{"facts": [{"entity": "order"}]}',
    json_bytes({"facts": [VALID, {**MISSING_WITH_VALUE, "state": "unknown"}]}).decode(),
    json_bytes({"facts": [VALID], "gaps": [], "extra": 1}).decode(),
    json_bytes({"facts": [VALID], "gaps": []}).decode(),
])
def test_salvage_refuses_any_other_defect(raw):
    assert salvage(raw) is None


def test_interpretation_without_left_out_facts_keeps_its_serialised_identity():
    empty = Interpretation(source_bundle_sha256="a" * 64, request_sha256="b" * 64, provider="openai",
                           model="m", execution="synthetic_test", facts=(), gaps=())
    assert "discarded_facts" not in empty.model_dump(mode="json")
    left_out = empty.model_copy(update={"discarded_facts": (DiscardedFact(
        entity="e", property="p", state="missing", reason="Missing facts cannot invent a value"),)})
    assert left_out.model_dump(mode="json")["discarded_facts"][0]["property"] == "p"


def test_the_schema_sent_to_the_model_is_unchanged():
    # Pinned: a different schema means new answer keys and a paid re-measurement.
    from jav.readers.providers import gpt_response_format
    assert digest(json_bytes(gpt_response_format())) == "94a056bf1a6da4a6c5bb80474f3260f8a2596a3db4e0eb81d2cf5e3e5ce5f958"
    assert ProposedExtraction.model_json_schema()["$defs"]["ProposedFact"]["title"] == "ProposedFact"


def test_one_malformed_fact_is_left_out_with_a_review_item(isolated, monkeypatch):
    path, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch, payload={"facts": [VALID, MISSING_WITH_VALUE], "gaps": []})
    with calls.measurement("native-run", {"openai": Decimal("1")}):
        _, _, state = build(path, ref).run(halt_after=flow_native.TERMINALS)
    publication = native_results.get_publication("native-run", "native-item")
    assert publication.interpretation_outcome.status == "succeeded"
    assert [fact.proposal.value for fact in native_results.machine_facts(publication)] == ["0012"]
    assert [d.property for d in publication.interpretation.discarded_facts] == ["signature place"]
    assert "native:discarded_facts:1" in state.data.review_reasons
    assert state.data.final_status == "needs_review" and len(requests) == 1
    # The service projection (jav/corrections.py) carries the left-out facts to the interface.
    from jav.native_contracts import InterpretationView
    view = InterpretationView.model_validate_json(json_bytes({
        "interpretation_id": "i0", "payload_sha256": "c" * 64, "status": "completed",
        **publication.interpretation.model_dump(mode="json", include={
            "provider", "model", "execution", "gaps", "review_status", "correctness", "discarded_facts"})}))
    assert view.discarded_facts[0].reason == "Missing facts cannot invent a value"


def test_only_malformed_facts_give_an_empty_interpretation_not_a_rejection(isolated, monkeypatch):
    path, ref = runtime_source(isolated, monkeypatch)
    synthetic_gpt(monkeypatch, payload={"facts": [MISSING_WITH_VALUE, STATED_WITHOUT_CITATION], "gaps": []})
    with calls.measurement("native-run", {"openai": Decimal("1")}):
        _, _, state = build(path, ref).run(halt_after=flow_native.TERMINALS)
    publication = native_results.get_publication("native-run", "native-item")
    assert publication.interpretation_outcome.status == "succeeded"
    assert {"native:no_facts", "native:discarded_facts:2"} <= set(state.data.review_reasons)


def test_a_saved_answer_with_a_malformed_fact_is_salvaged_without_a_second_call(isolated, monkeypatch):
    from jav.readers import providers
    from jav.readers.pipeline import read_files
    path = isolated / "source.txt"
    path.write_text("Order code: 0012", encoding="utf-8")
    source = read_files([path])
    requests = synthetic_gpt(monkeypatch, payload={"facts": [VALID, MISSING_WITH_VALUE], "gaps": []})
    database = store.active_path()
    with calls.measurement("native-replay", {"openai": Decimal("1")}):
        first = providers.extract_gpt(source, run_id="same", isolated_store=database)
        again = providers.extract_gpt(source, run_id="same", isolated_store=database)
        assert calls.budget_usage("native-replay")["committed_usd"] == Decimal("0.000255")
    assert len(requests) == 1
    assert first.discarded_facts == again.discarded_facts and len(first.discarded_facts) == 1
    assert again.execution == "synthetic_test"
