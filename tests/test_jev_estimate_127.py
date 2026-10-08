"""127: the free pre-estimate of a paid JEV measurement (`jav/experiments/jev_estimate.py`).

A cached question gets its saved answer; a missing one is counted with its size and answered by a stand-in, never
sent, and nothing is written to the cache. Offline: the cache is seeded with a fake client.
"""

from decimal import Decimal

from typesafe_sdk import Choice, Noul, Score, SystemOneResponse

from jav import evals, store
from jav.adapters import jev
from jav.adapters.jev import JevAdapter, get_adapter
from jav.experiments import jev_estimate
from jav.experiments.jev_estimate import EstimatingAdapter, only_adapter, runs_redirected, stand_in, summary


class _SeedClient:
    def system_one(self, *, state, questions, model):
        return SystemOneResponse.model_validate({"model": "jev-1.13.0", "usage": {"input_tokens": 100, "output_tokens": 1},
                                                 "answers": {k: {"type": "noul", "noul": 0.9} for k in questions}})


def test_a_cached_question_is_answered_and_a_missing_one_is_counted_not_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    cache = tmp_path / "cache"
    noul = {"a": Noul(instructions="Is it there?")}
    JevAdapter(client=_SeedClient(), cache_dir=cache, model="jev-1.13.0").ask("seeded", {"x": 1}, noul)
    assert len(list(cache.glob("*.json"))) == 1

    est = EstimatingAdapter("jev-1.13.0", cache_dir=cache)
    est.step = "step-1"
    hit = est.ask("seeded", {"x": 1}, noul)
    miss = est.ask("new", {"x": 2}, {"c": Choice(instructions="Which one?", criteria={"p": "first", "q": "second"})})
    assert hit.cached and hit.response.nouls["a"].noul == 0.9
    assert not miss.cached and miss.response.choices["c"].choice == "p"
    assert est._client is None  # no client was ever made: nothing can be sent
    assert len(list(cache.glob("*.json"))) == 1  # the stand-in answer is not cached

    s = summary(est.requests)
    step = s["steps"]["step-1"]
    assert (step["requests"], step["cached"], step["live"]) == (2, 1, 1)
    assert step["live_chars"] == est.requests[1].chars > 0
    assert Decimal(0) < step["expected_usd"] <= step["upper_usd"]
    assert step["max_reserve_usd"] >= step["upper_usd"]


def test_the_stand_in_answers_every_question_kind():
    questions = {"c": Choice(instructions="?", criteria={"a": "A", "b": "B"}), "n": Noul(instructions="?"),
                 "s": Score(instructions="?", criteria=["low", "mid", "high"])}
    r = stand_in(questions, "jev-1.13.0", 1000)
    assert r.choices["c"].choice == "a" and r.nouls["n"].noul == 0.5 and r.scores["s"] is not None
    assert r.usage.input_tokens == 400


def test_the_stand_in_is_the_only_adapter_and_runs_are_redirected_while_estimating(tmp_path):
    est = EstimatingAdapter("jev-1.13.0", cache_dir=tmp_path)
    before = jev._default_adapter
    with only_adapter(est):
        assert get_adapter() is est and jev._default_adapter() is est
    assert jev._default_adapter is before
    runs_before = evals.RUNS_DIR
    with runs_redirected(tmp_path):
        assert evals.RUNS_DIR == tmp_path
    assert evals.RUNS_DIR == runs_before


def test_an_unknown_step_is_refused(tmp_path):
    try:
        jev_estimate.run_step("everything", tmp_path)
    except ValueError as exc:
        assert "unknown step" in str(exc)
    else:
        raise AssertionError("an unknown step must not run")
