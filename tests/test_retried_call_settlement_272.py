"""272 (K2, the check of X-12): a call that retries by itself is not settled at 0 on a "never sent" last error.

265 (X-12) settles a failed call at 0 when its error shows the request never reached the provider (the connection
could not be made). The JEV SDK retries by itself (`configs/models.json` `jev.retry`) and raises only its last
attempt's error, so a first attempt that was sent (and may have been processed) can be followed by a last one that
could not connect: the call was settled at 0 and its reservation released. A caller whose physical call retries
inside (`retried_inside`) now keeps the maximum committed, as before X-12; a single attempt is still settled at 0.
Offline: fake clients, no network.
"""

from __future__ import annotations

from decimal import Decimal

import httpx2 as httpx
import pytest
from typesafe_sdk import Noul
from typesafe_sdk._core.errors import TypeSafeAPIConnectionError

from jav.ai.jev import JevAdapter, JevUnavailableError
from jav.core import calls, store
from jav.core.config import JEV_RETRY
from tests.test_known_failed_cost_202 import MAX, _failing, _row, isolated  # noqa: F401 (the fixture)


def _invoke(run_id: str, exc: BaseException, *, retried_inside: bool) -> dict:
    calls.set_budget("s", "jev", Decimal("1"))
    with calls.use_run(budget_scope="s"), pytest.raises(type(exc)):
        calls.invoke(run_id=run_id, step_id="a", provider="jev", model="m", max_cost_usd=MAX, budget_scope="s",
                     fn=_failing(exc), retried_inside=retried_inside)
    return _row(run_id)


def test_a_single_attempt_never_sent_still_costs_nothing(isolated) -> None:  # noqa: F811
    row = _invoke("r1", httpx.ConnectError("no connection"), retried_inside=False)
    assert (row["status"], row["cost_known"], Decimal(row["cost_usd"])) == ("failed", 1, Decimal(0))


def test_a_call_retried_inside_keeps_its_maximum(isolated) -> None:  # noqa: F811
    row = _invoke("r2", httpx.ConnectError("no connection on the last attempt"), retried_inside=True)
    assert (row["status"], row["cost_known"]) == ("failed", 0)
    assert calls.left("s", "jev") == Decimal("1") - MAX


class _CannotConnect:
    def system_one(self, *, state, questions, model):
        try:
            raise httpx.ConnectError("no connection on the last attempt")
        except httpx.ConnectError as exc:
            raise TypeSafeAPIConnectionError("the request could not reach the server") from exc


def test_the_jev_adapter_says_its_sdk_retries(isolated) -> None:  # noqa: F811
    assert int(JEV_RETRY.get("max_retries", 0)) > 0  # the SDK repeats a failed connection by itself
    calls.set_budget("s", "jev", Decimal("1"))
    adapter = JevAdapter(client=_CannotConnect(), model="jev-1.14.0")
    adapter.write_cache = False
    with calls.use_run(budget_scope="s"), pytest.raises(JevUnavailableError):
        adapter.ask("t", {"text": "x"}, {"q": Noul(instructions="Is the text an invoice?")}, run_id="r3", use_cache=False)
    with store.connect() as c:
        row = c.execute("SELECT status, cost_known FROM invocations WHERE run_id='r3'").fetchone()
    assert (row["status"], row["cost_known"]) == ("failed", 0)  # the maximum stays committed
