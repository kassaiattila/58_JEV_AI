"""265 (code review X-12): a call whose request never reached the provider is settled at 0.

A failed call keeps its reserved maximum committed in the run's budget unless its cost is certain (202). A request
that could not even be sent (the connection could not be made) is certain: it cost nothing, yet it held its maximum.
It is now settled at 0; an error answer and a failure after sending keep the maximum, as before. Offline, no call.
"""

from __future__ import annotations

from decimal import Decimal
from urllib.error import HTTPError

import httpx2 as httpx
import pytest

from jav.core import calls
from tests.test_known_failed_cost_202 import MAX, _failing, _row, isolated  # noqa: F401 (the fixture)


def _call(run_id: str, exc: BaseException) -> dict:
    calls.set_budget("s", "openai", Decimal("1"))
    with calls.use_run(budget_scope="s"), pytest.raises(type(exc)):
        calls.invoke(run_id=run_id, step_id="a", provider="openai", model="m", max_cost_usd=MAX, budget_scope="s",
                     fn=_failing(exc))
    return _row(run_id)


def test_a_request_never_sent_costs_nothing(isolated) -> None:  # noqa: F811
    row = _call("r1", httpx.ConnectError("the connection could not be made"))
    assert (row["status"], row["cost_known"], Decimal(row["cost_usd"])) == ("failed", 1, Decimal(0))


def test_an_error_answer_keeps_its_maximum(isolated) -> None:  # noqa: F811
    row = _call("r2", HTTPError("https://invented.example", 500, "server error", None, None))
    assert (row["status"], row["cost_known"]) == ("failed", 0)
