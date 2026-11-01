"""265 (code review CORE-10): a provider's per-minute limit is counted in the call's own reservation, with an index.

A connector's limit was counted before the reservation and without an index: two callers at once could both pass a
count taken before either reserved. Now `calls.invoke(per_minute=)` counts the provider's calls of the last minute in
the reservation's write transaction (`RateLimited`, the network never reached), on an index of (provider, time).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from jav.core import calls, store


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "rate.sqlite"):
        yield tmp_path


def _free(step: str) -> calls.Result:
    return calls.invoke(run_id="connector:x", step_id=step, provider="x", model=None, max_cost_usd=Decimal(0),
                        fn=lambda: calls.Outcome(response={"ok": True}, cost_usd=Decimal(0)), repeatable=True, per_minute=2)


def test_the_limit_is_counted_in_the_reservation(db) -> None:
    _free("a")
    _free("b")
    reached: list[str] = []
    with pytest.raises(calls.RateLimited):
        calls.invoke(run_id="connector:x", step_id="c", provider="x", model=None, max_cost_usd=Decimal(0),
                     fn=lambda: reached.append("c") or calls.Outcome(response={}, cost_usd=Decimal(0)), repeatable=True,
                     per_minute=2)
    assert reached == []
    with store.connect() as c:
        names = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "ix_invocations_provider_at" in names


def test_a_reused_answer_is_not_held_back_by_the_limit_nor_counted(db) -> None:
    """272 (K2, the rest of CORE-10): the limit was counted before an earlier answer was looked for, so a free reused
    answer could be refused at the limit; and a reused answer counted as a call."""
    def ask(run: str, step: str) -> calls.Result:
        return calls.invoke(run_id=run, step_id=step, provider="y", model="m", max_cost_usd=Decimal(0),
                            fn=lambda: calls.Outcome(response={"n": step}, cost_usd=Decimal(0)), request_hash="same-question",
                            reusable=True, per_minute=1)

    ask("r1", "a")  # the one call this minute allows
    with calls.use_run(budget_scope=None, reuse=True):
        reused = ask("r2", "b")
        again = ask("r3", "c")
    assert reused.reused_from is not None and again.reused_from is not None
    with store.connect() as c:
        rows = c.execute("SELECT note FROM invocations WHERE provider='y' ORDER BY id").fetchall()
    assert [calls.is_reused(r["note"]) for r in rows] == [False, True, True]
