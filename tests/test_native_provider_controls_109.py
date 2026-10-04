"""Native application provider budgets, receipts, reuse and uncertain outcomes."""
from decimal import Decimal

import pytest

from jav import native_processing, native_results, store
from jav.native_contracts import NativeLimits
from jav.readers import providers
from jav.runtime import calls
from native_fixtures_109 import runtime_source, synthetic_gpt


@pytest.fixture
def isolated(tmp_path):
    with store.use_store(tmp_path / "native.sqlite"):
        yield tmp_path


def run_interpretation(ref, *, graph="native-graph", jev=False, use_cache=False, limits=None):
    return native_processing.interpret(work_run_id="native-run", item_id="native-item", graph_id=graph,
        reading_id=ref.reading_id, jev=jev, use_cache=use_cache,
        limits=limits or native_processing.estimate_limits({"jev": "on" if jev else "off"}))


@pytest.mark.parametrize("mode,expected", [("valid", "succeeded"), ("invalid", "rejected"), ("empty", "rejected"), ("timeout", "uncertain")])
def test_received_and_uncertain_outcomes_are_saved_without_automatic_retry(isolated, monkeypatch, mode, expected):
    _, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch, mode=mode)
    with calls.measurement("native-run", {"openai": Decimal("1")}):
        outcome_id = run_interpretation(ref)
        assert run_interpretation(ref) == outcome_id
    _, outcome, interpretation = native_results.load_outcome(outcome_id)
    assert outcome.status == expected and len(requests) == 1
    assert (interpretation is not None) == (expected == "succeeded")
    assert len(outcome.receipt_refs) == 1
    receipt = outcome.receipt_refs[0]
    if expected == "uncertain":
        assert receipt.cost_usd is None and not receipt.cost_known and receipt.response_sha256 is None
        assert calls.budget_usage("native-run")["committed_usd"] > 0
    else:
        assert receipt.cost_known and receipt.cost_usd > 0 and receipt.response_sha256
    publication = native_results.publish(run_id="native-run", item_id="native-item", source_sha256=ref.source_sha256,
        recipe_hash="a" * 16, reading_id=ref.reading_id, outcome=outcome, interpretation=interpretation)
    native_results.verify_publication(publication)


def test_jev_off_has_no_budget_call_or_cache_access(isolated, monkeypatch):
    _, ref = runtime_source(isolated, monkeypatch)
    synthetic_gpt(monkeypatch)
    monkeypatch.setattr(providers, "verify_jev", lambda *_a, **_k: pytest.fail("JEV off called verifier"))
    limits = native_processing.estimate_limits({"jev": "off"})
    assert set(limits.provider_limits_usd) == {"openai"}
    with calls.measurement("native-run", limits.provider_limits_usd):
        _, outcome, _ = native_results.load_outcome(run_interpretation(ref, limits=limits))
    assert outcome.status == "succeeded"
    assert {r.provider for r in outcome.receipt_refs} == {"openai"}


def test_missing_budget_is_failed_before_any_model_request(isolated, monkeypatch):
    _, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch)
    with calls.use_run(budget_scope="native-run"):
        _, outcome, interpretation = native_results.load_outcome(run_interpretation(ref))
    assert outcome.status == "failed" and interpretation is None
    assert not requests and not calls.journal("native-graph")


def test_request_transfer_limit_prevents_wire_request(isolated, monkeypatch):
    _, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch)
    limits = NativeLimits(max_transfer_bytes=100, provider_limits_usd={"openai": Decimal("1")})
    with calls.measurement("native-run", limits.provider_limits_usd):
        _, outcome, _ = native_results.load_outcome(run_interpretation(ref, limits=limits))
    assert outcome.status == "failed" and not requests and "transfer limit" in outcome.reason


def test_explicit_reuse_uses_existing_receipt_but_live_setting_calls_again(isolated, monkeypatch):
    _, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch)
    with calls.measurement("native-run", {"openai": Decimal("2")}):
        run_interpretation(ref, graph="first", use_cache=False)
        _, second, _ = native_results.load_outcome(run_interpretation(ref, graph="second", use_cache=True))
        assert len(requests) == 1
        assert second.receipt_refs[0].replayed and second.receipt_refs[0].reused_from is not None
        assert second.receipt_refs[0].cost_usd == 0
        run_interpretation(ref, graph="third", use_cache=False)
    assert len(requests) == 2


def test_s_path_is_rejected_before_budget_or_provider_work():
    with pytest.raises(ValueError, match="S path"):
        native_processing.estimate_limits({"arm": "S"})


def test_provider_receipt_tamper_blocks_result_verification(isolated, monkeypatch):
    _, ref = runtime_source(isolated, monkeypatch)
    synthetic_gpt(monkeypatch)
    with calls.measurement("native-run", {"openai": Decimal("1")}):
        _, outcome, interpretation = native_results.load_outcome(run_interpretation(ref))
    publication = native_results.publish(run_id="native-run", item_id="native-item", source_sha256=ref.source_sha256,
        recipe_hash="a" * 16, reading_id=ref.reading_id, outcome=outcome, interpretation=interpretation)
    with store.connect() as c:
        c.execute("UPDATE artifacts SET payload='{}' WHERE kind='invocation_response'")
    with pytest.raises(native_results.NativeIntegrityError, match="receipt artifact"):
        native_results.verify_publication(publication)


@pytest.mark.parametrize("mode,expected", [("valid", "succeeded"), ("invalid", "rejected"), ("timeout", "uncertain")])
def test_crash_between_paid_receipt_and_outcome_save_never_repeats_wire(isolated, monkeypatch, mode, expected):
    _, ref = runtime_source(isolated, monkeypatch)
    requests = synthetic_gpt(monkeypatch, mode=mode)
    original = native_results.save_outcome
    failed = []

    def interrupt(**kwargs):
        if not failed:
            failed.append(1)
            raise OSError("Synthetic outcome write interruption")
        return original(**kwargs)

    monkeypatch.setattr(native_results, "save_outcome", interrupt)
    with calls.measurement("native-run", {"openai": Decimal("1")}):
        with pytest.raises(OSError, match="interruption"):
            run_interpretation(ref)
        _, outcome, _ = native_results.load_outcome(run_interpretation(ref))
    assert outcome.status == expected and len(requests) == 1
    if expected != "uncertain":
        assert outcome.receipt_refs[0].replayed and outcome.receipt_refs[0].cost_usd > 0


def test_actual_jev_adapter_cache_live_control_and_cost_receipts(isolated, monkeypatch):
    from typesafe_sdk import SystemOneResponse
    from jav.adapters import jev

    _, ref = runtime_source(isolated, monkeypatch)
    synthetic_gpt(monkeypatch)
    requests = []

    class Client:
        def system_one(self, *, state, questions, model):
            requests.append((state, questions))
            return SystemOneResponse.model_validate({"model": "jev-9.9.9", "usage": {"input_tokens": 100},
                "answers": {key: {"type": "noul", "noul": 0.8} for key in questions}})

    original = jev.JevAdapter
    monkeypatch.setattr(jev, "JevAdapter", lambda **kwargs: original(client=Client(), model="jev-9.9.9", **kwargs))
    with calls.measurement("native-run", {"openai": Decimal("2"), "jev": Decimal("2")}):
        _, first, interpretation = native_results.load_outcome(run_interpretation(ref, graph="jev-first", jev=True, use_cache=True))
        assert first.status == "succeeded" and interpretation.facts[0].semantic_support == 0.8
        assert len(requests) == 1 and first.receipt_refs[-1].provider == "jev"
        assert first.receipt_refs[-1].cost_usd > 0
        _, cached, _ = native_results.load_outcome(run_interpretation(ref, graph="jev-cached", jev=True, use_cache=True))
        assert len(requests) == 1
        assert cached.receipt_refs[-1].kind == "saved_cache" and cached.receipt_refs[-1].cost_usd == 0
        assert not [row for row in calls.journal("jev-cached") if row["provider"] == "jev"]
        run_interpretation(ref, graph="jev-live", jev=True, use_cache=False)
        assert len(requests) == 2
    assert (isolated / "native" / "provider_cache").is_dir()
