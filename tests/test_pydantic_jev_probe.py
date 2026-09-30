"""The real Pydantic AI translation through the shared JEV gate; only the network is fake."""
import pytest
from typesafe_sdk import Choice, Noul, Score, SystemOneResponse

from jav import store
from jav.adapters.jev import JevAdapter
from jav.experiments.pydantic_jev import run_typed


class MixedClient:
    def __init__(self):
        self.calls = []

    def system_one(self, *, state, questions, model):
        self.calls.append((state, questions))
        answers = {}
        for name, question in questions.items():
            if isinstance(question, Choice):
                answers[name] = dict(type="choice", choice="en", confidence=.91,
                                     probabilities={"en": .95, "other": .05})
            elif isinstance(question, Noul):
                answers[name] = dict(type="noul", noul=.37)
            else:
                answers[name] = dict(type="score", score=1.45, confidence=.11, legend={0: "none", 1: "routine", 2: "immediate"},
                                     probabilities={0: .05, 1: .45, 2: .50})
        return SystemOneResponse.model_validate(dict(model=model, answers=answers,
                                                      usage=dict(input_tokens=321, output_tokens=0)))


def test_typed_answers_preserve_raw_signals_and_use_existing_cache_and_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "store.sqlite")
    client = MixedClient()
    adapter = JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.13.0")
    questions = {
        "language": Choice(instructions="Which language?", criteria={"en": "English", "other": "Other"}),
        "requires_action": Noul(instructions="Is action required?", criteria={"true": "act", "false": "information"}),
        "urgency": Score(instructions="How urgent?", criteria=["none", "routine", "immediate"]),
    }
    first = run_typed("Please reply.", questions, adapter=adapter, run_id="first", config_hash="trial-v1")
    second = run_typed("Please reply.", questions, adapter=adapter, run_id="second", config_hash="trial-v1")
    assert first.output["language"] == "en"
    assert first.output["requires_action"] == .37  # the Noul is not rounded to a bool
    assert first.output["urgency"] == 1  # expected value, rounded; the mode is 2!
    assert first.details["scores"]["urgency"] == 1.45
    assert first.details["probabilities"]["urgency"]["2"] == .50
    assert first.calls[0].response.scores["urgency"].probabilities[2] == .50
    assert len(client.calls) == 1 and len(first.calls) == len(second.calls) == 1
    assert second.calls[0].cached and second.calls[0].call.cost_usd == 0
    assert first.model == "jev-1.13.0"
    ledger = store.ledger_for_run("second")
    assert len(ledger) == 1 and ledger[0]["cached"] and ledger[0]["config_hash"] == "trial-v1"
    compiled = client.calls[0][1]
    assert compiled["language"].criteria == questions["language"].criteria
    assert "information" in str(compiled["requires_action"].instructions)


def test_service_failure_remains_ledgered_and_no_success_is_returned(tmp_path, monkeypatch):
    from typesafe_sdk import TypeSafeAPIConnectionError
    from jav.adapters.jev import JevUnavailableError

    class BrokenClient:
        def system_one(self, **kwargs):
            raise TypeSafeAPIConnectionError("offline probe")

    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "store.sqlite")
    adapter = JevAdapter(client=BrokenClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with pytest.raises(JevUnavailableError):
        run_typed("hello", {"present": Noul(instructions="Is there text?")},
                  adapter=adapter, run_id="failure", config_hash="failure-v1")
    rows = store.ledger_for_run("failure")
    assert len(rows) == 1 and "TypeSafeAPIConnectionError" in rows[0]["error"]
    assert not list((tmp_path / "cache").glob("*.json"))
