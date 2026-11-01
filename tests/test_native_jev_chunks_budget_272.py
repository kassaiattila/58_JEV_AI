"""272 (K2, the rest of AI-01): JEV's check of a native reading in several parts is asked only when the budget covers it.

265 (AI-01) made the GPT reading check the budget left for every part before the first. JEV's check of the facts
was left as it was: it asks one request per part, while the native item's JEV budget prices one request, so the
second part was refused after the first was paid for. The check now adds up what every part not answered before would
reserve at most (`JevAdapter.unanswered_cost`, the same bound the call reserves) and, when that is more than the
budget left, asks nothing: the GPT facts stay, with the `jev_unavailable:budget_exceeded` to-do. Synthetic source,
a stand-in JEV client; no paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from typesafe_sdk import SystemOneResponse

from jav.ai import native_verification
from jav.ai.jev import JevAdapter, JevUnavailableError, call_max_cost
from jav.core import calls, store
from jav.documents.readers.interpretation import ground
from tests.test_reader_providers import proposed, source  # noqa: F401 (the fixture)


class _Client:
    def __init__(self) -> None:
        self.asked = 0

    def system_one(self, *, state, questions, model):
        self.asked += 1
        return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 100, "output_tokens": 0},
                                                 "answers": {q: {"type": "noul", "noul": 0.8} for q in questions}})


def _parts(monkeypatch: pytest.MonkeyPatch, times: int) -> None:
    real = native_verification.verification_chunks

    def many(view, questions, facts, limit):
        (part, batch), = real(view, questions, facts, limit)
        return [({**part, "part": n}, batch) for n in range(times)]  # distinct parts: distinct questions

    monkeypatch.setattr(native_verification, "verification_chunks", many)


def _verify(src, tmp_path, scope: str, limit: Decimal, client: _Client, *, use_cache: bool = False):
    calls.set_budget(scope, "jev", limit)
    adapter = JevAdapter(client=client, cache_dir=tmp_path / "jev-cache", model="jev-1.14.0")
    initial = ground(src, proposed(), provider="offline", model="fixture", execution="synthetic_test")
    with calls.use_run(budget_scope=scope):
        return native_verification.verify_jev(src, initial, run_id=scope, isolated_store=store.active_path(),
                                              adapter=adapter, use_cache=use_cache)


def test_a_budget_for_one_part_asks_nothing_of_several(source, tmp_path, monkeypatch):  # noqa: F811
    _parts(monkeypatch, 3)
    client = _Client()
    with store.use_store(tmp_path / "t.sqlite"):
        one = call_max_cost({"x": "y"}, {})  # far below one real part's bound
        with pytest.raises(JevUnavailableError) as raised:
            _verify(source, tmp_path, "small", one, client)
        assert raised.value.reason == "budget_exceeded"
        assert client.asked == 0 and calls.budget_usage("small")["committed_usd"] == Decimal(0)


def test_a_budget_for_every_part_asks_them_all(source, tmp_path, monkeypatch):  # noqa: F811
    _parts(monkeypatch, 3)
    client = _Client()
    with store.use_store(tmp_path / "t.sqlite"):
        verified = _verify(source, tmp_path, "room", Decimal("5"), client)
    assert client.asked == 3 and verified.facts[0].semantic_support == 0.8


def test_parts_answered_before_count_nothing(source, tmp_path, monkeypatch):  # noqa: F811
    _parts(monkeypatch, 3)
    with store.use_store(tmp_path / "t.sqlite"):
        _verify(source, tmp_path, "first", Decimal("5"), _Client(), use_cache=True)  # answers kept in the cache
        again = _Client()
        _verify(source, tmp_path, "again", call_max_cost({"x": "y"}, {}), again, use_cache=True)
    assert again.asked == 0
