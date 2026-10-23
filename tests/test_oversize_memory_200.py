"""200 (Q-tul-nagy-keres): a JEV request the service refused as too large is remembered, so it is not sent again.

A request over the service's token limit gets `max_tokens_exceeded`; the request-size frame (`jav/ai/jev_budget.py`) then
asks once with a tighter request, whose answer is cached. The full request had no answer to cache, so every later run
sent it again: one failed call and one reservation kept in the run's budget each time, and a free round (earlier
answers only) left the case without a result. The adapter now remembers that request's key, for the concrete model
version that refused it, and refuses it again without a call, with the same reason; the frame goes on to the tighter
request at once. A request that was answered keeps its key and its cached answer. Offline, with a fake client.
"""

from pathlib import Path

import pytest
from typesafe_sdk import Noul, SystemOneResponse
from typesafe_sdk._core.errors import TypeSafeBadRequestError

from jav.core import store
from jav.ai.jev import JevAdapter, JevUnavailableError
from jav.ai.jev_budget import ask_within_budget

REASON = "TypeSafeBadRequestError:400:max_tokens_exceeded"


class SizeLimitedClient:
    """Answers a request whose state has at most `limit` lines; a larger one is refused as the service does."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.calls: list[int] = []

    def system_one(self, *, state, questions, model):
        self.calls.append(len(state["lines"]))
        if len(state["lines"]) > self.limit:
            raise TypeSafeBadRequestError(400, {"detail": {"error_type": "max_tokens_exceeded"}}, {})
        answers = {qid: {"type": "noul", "noul": 0.1} for qid in questions}
        return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 100, "output_tokens": 1},
                                                 "answers": answers})


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    return tmp_path


QS = {"flag": Noul(instructions="is it?")}


def _fit(budget):
    """The call site's own fitting: the whole document within the budget, otherwise its first `budget` lines."""
    lines = [f"L{i:02d}: line {i}" for i in range(1, 11)]
    return {"lines": lines if budget is None or budget >= len(lines) else lines[:budget]}, QS


def _size(state, questions):
    return len(state["lines"])


def test_a_refused_request_is_not_sent_again(isolated: Path):
    client = SizeLimitedClient(limit=6)
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.14.0")
    first, state, _ = ask_within_budget(jev, "t", _fit, 10, _size, run_id="run-1")
    assert client.calls == [10, 6]  # the full request refused, the tighter one (10 x 0.6) answered
    assert len(state["lines"]) == 6
    second, state2, _ = ask_within_budget(jev, "t", _fit, 10, _size, run_id="run-2")
    assert client.calls == [10, 6]  # no call at all: the full request is known to be too large, the tighter one cached
    assert second.cached and second.cache_key == first.cache_key and state2 == state
    skipped = [r for r in store.ledger_for_run("run-2") if r["error"]]
    assert len(skipped) == 1 and skipped[0]["cached"] == 1 and skipped[0]["cost_usd"] == 0
    assert skipped[0]["error"] == f"known_too_large:{REASON}"


def test_the_refusal_without_a_call_keeps_its_reason(isolated: Path):
    client = SizeLimitedClient(limit=6)
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.14.0")
    big, _ = _fit(None)
    with pytest.raises(JevUnavailableError) as live:
        jev.ask("t", big, QS, run_id="run-1")
    with pytest.raises(JevUnavailableError) as known:
        jev.ask("t", big, QS, run_id="run-2")
    assert live.value.reason == known.value.reason == REASON  # the same to-do as the live refusal
    assert client.calls == [10]


def test_another_model_version_tries_the_request_again(isolated: Path):
    client = SizeLimitedClient(limit=6)
    big, _ = _fit(None)
    with pytest.raises(JevUnavailableError):
        JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.14.0").ask("t", big, QS)
    client.limit = 20  # a later version takes larger requests
    answer = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.15.0").ask("t", big, QS)
    assert client.calls == [10, 10] and not answer.cached


def test_asking_everything_again_sends_it_again(isolated: Path):
    """A determinism measurement (`use_cache=False` inside `no_cache_write()`) asks live and remembers nothing."""
    client = SizeLimitedClient(limit=6)
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.14.0")
    big, _ = _fit(None)
    with jev.no_cache_write():
        for _ in range(2):
            with pytest.raises(JevUnavailableError):
                jev.ask("t", big, QS, use_cache=False)
    assert client.calls == [10, 10]
    with pytest.raises(JevUnavailableError):
        jev.ask("t", big, QS)
    assert client.calls == [10, 10, 10]  # nothing was remembered under no_cache_write()


def test_another_refusal_is_not_remembered(isolated: Path):
    class Unavailable(SizeLimitedClient):
        def system_one(self, *, state, questions, model):
            self.calls.append(len(state["lines"]))
            raise TypeSafeBadRequestError(400, {"detail": {"error_type": "invalid_request"}}, {})

    client = Unavailable(limit=6)
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.14.0")
    small, _ = _fit(3)
    for _ in range(2):
        with pytest.raises(JevUnavailableError):
            jev.ask("t", small, QS)
    assert client.calls == [3, 3]


def test_an_answered_request_keeps_its_key(isolated: Path):
    client = SizeLimitedClient(limit=20)
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.14.0")
    big, _ = _fit(None)
    first = jev.ask("t", big, QS)
    again = jev.ask("t", big, QS)
    assert again.cached and again.cache_key == first.cache_key and client.calls == [10]
    assert sorted(p.name for p in (isolated / "cache").iterdir()) == [f"{first.cache_key}.json"]
