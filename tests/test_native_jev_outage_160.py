"""160 (review AI-5): on the native path a JEV outage keeps the paid GPT interpretation.

The native reader asks GPT for the facts, then JEV for its support of each fact. When JEV did not answer (no key, no
budget left, a provider error), the whole interpretation was discarded: the GPT call was paid for, the item ended with
`native:interpretation:failed`, and the rule of the other flows (a `jev_unavailable:<reason>` to-do, the flow goes on)
did not hold. Now the GPT facts are published without JEV support, with that to-do. Synthetic GPT, no paid call.
"""

from decimal import Decimal

from jav import flow_native, native_results, store
from jav.adapters import jev as jev_mod
from jav.runtime import calls
from tests.native_fixtures_109 import runtime_source, synthetic_gpt

import pytest


@pytest.fixture
def isolated(tmp_path):
    with store.use_store(tmp_path / "native.sqlite"):
        yield tmp_path


def _no_key(**_kwargs):
    raise jev_mod.MissingAPIKeyError("no TypeSafe key")  # the class the adapter knows, even after a config reload


def _run(source, ref, monkeypatch):
    monkeypatch.setattr(jev_mod, "make_client", _no_key)  # JEV is unavailable (missing_key)
    app = flow_native.build_app(work_run_id="native-run", item_id="native-item", graph_id="native-graph",
        source_path=str(source), read_path=str(source), original_name="original.txt", expected_sha256=ref.source_sha256,
        recipe_hash="a" * 16, jev=True, use_cache=False)
    with calls.measurement("native-run", {"openai": Decimal("1"), "jev": Decimal("1")}):
        _, _, state = app.run(halt_after=flow_native.TERMINALS)
    return state.data


def test_a_jev_outage_keeps_the_gpt_facts_with_a_to_do(isolated, monkeypatch):
    path, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch)
    state = _run(path, ref, monkeypatch)
    publication = native_results.get_publication("native-run", "native-item")
    assert publication.interpretation_outcome.status == "succeeded"
    fact = native_results.machine_facts(publication)[0]
    assert fact.proposal.value == "0012" and fact.semantic_support is None
    assert "jev_unavailable:missing_key" in state.review_reasons
    assert not any(r.startswith("native:interpretation:") for r in state.review_reasons)
    assert state.final_status == "needs_review" and len(requests) == 1


def test_the_to_do_survives_a_resume_after_the_publication(isolated, monkeypatch):
    """The reason is kept with the saved outcome, not only in the graph's state."""
    path, ref = runtime_source(isolated, monkeypatch)
    synthetic_gpt(monkeypatch)
    _run(path, ref, monkeypatch)
    publication = native_results.get_publication("native-run", "native-item")
    assert publication.interpretation_outcome.reason == "jev_unavailable:missing_key"
