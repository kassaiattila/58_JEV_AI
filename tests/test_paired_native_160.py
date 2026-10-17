"""160 (plan F-csak-gpt, Sz3): the native reader (Word, Excel, text, an unknown PDF) runs with both engines.

GPT proposes the source-bound facts on both engines; with JEV, JEV then gives its support of each fact, and without it
the facts are published without support (the code's literal grounding stays). Neither engine fails the item, and
without JEV the reader's own JEV adapter is never asked (the safety net, and the guard of `tests/conftest.py`).
Synthetic source and models, no paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav import flow_native, native_results, store
from jav.adapters import jev as jev_mod
from jav.runtime import calls
from tests.native_fixtures_109 import runtime_source, synthetic_gpt
from tests.test_runtime_worker import FakeClient

ENGINES = ("jev", "gpt")


@pytest.fixture
def isolated(tmp_path):
    with store.use_store(tmp_path / "native.sqlite"):
        yield tmp_path


@pytest.mark.parametrize("engine", ENGINES)
def test_the_native_facts_are_published_on_both_engines(isolated, monkeypatch, engine):
    path, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch)
    client = FakeClient()  # every support Noul at 0.95
    monkeypatch.setattr(jev_mod, "make_client", lambda **_k: client)
    app = flow_native.build_app(work_run_id="native-run", item_id="native-item", graph_id="native-graph",
        source_path=str(path), read_path=str(path), original_name="original.txt", expected_sha256=ref.source_sha256,
        recipe_hash="a" * 16, jev=engine == "jev", use_cache=False)
    limits = {"openai": Decimal("1"), **({"jev": Decimal("1")} if engine == "jev" else {})}
    with calls.measurement("native-run", limits):
        _, _, state = app.run(halt_after=flow_native.TERMINALS)
    publication = native_results.get_publication("native-run", "native-item")
    fact = native_results.machine_facts(publication)[0]
    assert fact.proposal.value == "0012" and fact.grounding == "literal_match" and len(requests) == 1
    assert state.data.final_status == "done", state.data.review_reasons
    if engine == "jev":
        assert fact.semantic_support == pytest.approx(0.95) and client.calls >= 1
        assert publication.interpretation.provider.endswith("+jev")
    else:
        assert fact.semantic_support is None and client.calls == 0
        assert "+jev" not in publication.interpretation.provider


@pytest.mark.parametrize("engine", ENGINES)
def test_a_multi_format_run_finishes_on_both_engines(isolated, monkeypatch, engine):
    """Through the worker: the run's budget names only the engine's providers, and the item is not failed."""
    from jav import work
    from jav.readers import native, pipeline
    from jav.runtime import worker

    monkeypatch.setattr(pipeline, "run", lambda data, name, limits, **kw: native.read(data, name, limits, **kw))
    synthetic_gpt(monkeypatch)
    client = FakeClient()
    monkeypatch.setattr(jev_mod, "make_client", lambda **_k: client)
    source = isolated / "order.txt"
    source.write_text("😀 Order code: 0012\n", encoding="utf-8")
    wp = work.create_from_files([source], name="Native")
    work.assign_recipe(wp["id"], "multi-format-processing", params={"jev": "on" if engine == "jev" else "off"},
                       expected_revision=0, actor="t")
    ready = work.readiness(wp["id"])
    run_id = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=ready["input_hash"],
                            actor="t")["run_id"]
    assert calls.has_budget(run_id, "jev") is (engine == "jev") and calls.has_budget(run_id, "openai")
    assert worker.run_worker(once=True)["results"] == {"done": 1}
    (item,) = work.get_run(run_id)["items"]
    assert item["final_status"] in ("done", "needs_review")
    assert (client.calls > 0) is (engine == "jev")
