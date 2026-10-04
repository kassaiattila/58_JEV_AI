"""Resume and publication boundaries for the actual synthetic native Burr graph."""
from decimal import Decimal

import pytest

from jav import flow_native, native_results, store
from jav.runtime import calls
from jav.runtime.worker import StatePersister
from native_fixtures_109 import runtime_source, synthetic_gpt


@pytest.fixture
def isolated(tmp_path):
    with store.use_store(tmp_path / "native.sqlite"):
        yield tmp_path


def build(source, ref, persister=None, **kwargs):
    return flow_native.build_app(work_run_id="native-run", item_id="native-item", graph_id="native-graph",
        source_path=str(source), read_path=str(source), original_name="original.txt", expected_sha256=ref.source_sha256,
        recipe_hash="a" * 16, jev=False, use_cache=False, persister=persister, **kwargs)


def test_actual_graph_publishes_source_bound_facts_without_source_text_in_state(isolated, monkeypatch):
    path, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch)
    with calls.measurement("native-run", {"openai": Decimal("1")}):
        _, _, state = build(path, ref).run(halt_after=flow_native.TERMINALS)
    publication = native_results.get_publication("native-run", "native-item")
    assert publication.interpretation.execution == "synthetic_test"
    assert native_results.machine_facts(publication)[0].proposal.value == "0012"
    assert len(requests) == 1 and state.data.final_status == "done"
    assert "Order code" not in state.data.model_dump_json()


def test_resume_after_reading_uses_saved_reading_and_one_interpretation(isolated, monkeypatch):
    path, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch)
    persister = StatePersister(str(isolated / "burr_state.sqlite"))
    persister.initialize()
    try:
        with calls.measurement("native-run", {"openai": Decimal("1")}):
            build(path, ref, persister).run(halt_after=["read_native"])
            progress = native_results.unpublished_state("native-run", "native-item")
            assert progress.interpretation_outcome.status == "running"
            assert progress.reading.status == "complete"
            monkeypatch.setattr(native_results, "prepare_reading", lambda *_a, **_k: pytest.fail("Resume reread source"))
            _, _, state = build(path, ref, persister).run(halt_after=flow_native.TERMINALS)
        assert state.data.final_status == "done" and len(requests) == 1
    finally:
        persister.cleanup()


def test_crash_after_publication_resumes_without_second_provider_call(isolated, monkeypatch):
    path, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch)
    original = native_results.publish
    interrupted = []

    def publish_then_crash(**kwargs):
        result = original(**kwargs)
        if not interrupted:
            interrupted.append(1)
            raise RuntimeError("Synthetic interruption after durable publication")
        return result

    monkeypatch.setattr(native_results, "publish", publish_then_crash)
    persister = StatePersister(str(isolated / "burr_state.sqlite"))
    persister.initialize()
    try:
        with calls.measurement("native-run", {"openai": Decimal("1")}):
            with pytest.raises(RuntimeError, match="durable publication"):
                build(path, ref, persister).run(halt_after=flow_native.TERMINALS)
            publication = native_results.get_publication("native-run", "native-item")
            assert publication is not None
            _, _, state = build(path, ref, persister).run(halt_after=flow_native.TERMINALS)
        assert state.data.result_version == publication.result_version and len(requests) == 1
    finally:
        persister.cleanup()


def test_rejected_response_finishes_with_review_and_without_fake_interpretation(isolated, monkeypatch):
    path, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch, mode="invalid")
    with calls.measurement("native-run", {"openai": Decimal("1")}):
        _, _, state = build(path, ref).run(halt_after=flow_native.TERMINALS)
    publication = native_results.get_publication("native-run", "native-item")
    assert state.data.final_status == "needs_review" and len(requests) == 1
    assert publication.interpretation is None and publication.interpretation_outcome.status == "rejected"
    assert "native:interpretation:rejected" in state.data.review_reasons


def test_s_path_fails_before_graph_execution(isolated, monkeypatch):
    path, ref = runtime_source(isolated, monkeypatch)
    with pytest.raises(ValueError, match="G path"):
        build(path, ref, requested_arm="S")
