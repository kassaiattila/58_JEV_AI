"""265 (code review SEC-05): an email is suspicious by its stored signals, not by the route its result went to.

The attachments of an email routed by an injected-instruction signal are marked (154). Whether it was is read from
the result's route, which a route that may be set for other reasons can share (an installation's default route set to
the same person's queue): an ordinary email was marked, or a marked one missed. Now the stored signals decide, through
the same band as the routing (`email_rules.email_signal_route`). Synthetic results; no AI call.
"""

from __future__ import annotations

import pytest

from jav.app import work_runs
from jav.core import store
from jav.domains.email import email_rules, email_store, mailbox_bridge


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "signals.sqlite"):
        yield tmp_path


def _result(item: str, *, signals: dict, next_flow: str) -> None:
    email_store.upsert_email_result(run_id=work_runs.flow_run_id("run-000000000001", item), message_id=item, intent="other",
                                    intent_conf=0.9, signals=signals, next_flow=next_flow, attachments=[], body=None)


def test_the_stored_signals_decide_not_the_route(db) -> None:
    [(signal, route)] = list(email_rules.EMAIL_SIGNAL_ROUTES.items())
    _result("calm", signals={signal: 0.01}, next_flow=route)  # the route alone (another reason led there)
    _result("injected", signals={signal: 0.99}, next_flow="human:inbox")
    assert mailbox_bridge.suspicious_email("run-000000000001", "calm") is False
    assert mailbox_bridge.suspicious_email("run-000000000001", "injected") is True
