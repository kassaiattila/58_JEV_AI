"""265 (code review CORE-01): the running worker's recovery settles a stopped worker's paid calls before it requeues
the stopped worker's items.

Only the start-up recovery settled the reservations of a stopped process (`calls.recover_uncertain`); the recovery a
running worker makes for a dead neighbour requeued its items, which then met their own call still reserved and got a
false `uncertain_attempt` to-do. Now every recovery settles the calls first. No processing runs.
"""

from __future__ import annotations

from types import SimpleNamespace

from jav.runtime import worker


def test_every_recovery_settles_the_calls_before_the_items(monkeypatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(worker.calls, "recover_uncertain", lambda: order.append("calls") or 2)
    monkeypatch.setattr(worker.queue, "recover_orphans",
                        lambda: order.append("items") or SimpleNamespace(requeued=1, dead=[], cancelled=[]))
    assert worker._recover() == {"orphans_requeued": 1, "orphans_dead": 0, "orphans_cancelled": 0, "uncertain_marked": 2}
    assert order == ["calls", "items"]
    order.clear()
    assert worker.startup()["uncertain_marked"] == 2 and order == ["calls", "items"]
