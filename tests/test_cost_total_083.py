"""The run's total cost (083).

The owner found the run's total cost hard to read: the run's page showed the budget bars first and the cost only per
provider. The planned-and-actual view now carries the run's total (actual cost, paid calls, failed calls, the reserved
amount of the calls without a known cost, and the questions answered from earlier answers), added up with `Decimal`.
Synthetic rows, no paid calls.
"""

from decimal import Decimal

from jav import costs
from tests import test_api
from tests.test_cost_view_082 import _call, _queued_run, _reused

env = test_api.env


def test_the_run_total_adds_up_every_provider(env):
    wp, run_id, a, b = _queued_run(env["client"], env["folder"])
    _call(run_id, a, "jev", "jev-1.13.0", cost="0.002000")
    _call(run_id, b, "jev", "jev-1.13.0", cost="0.000100")
    _call(run_id, a, "jev", "jev-1.13.0", status="failed", max_cost="0.010000")
    _call(run_id, a, "openai", "gpt-4.1-mini", cost="0.001000")
    _reused(run_id, a, n=3)

    total = costs.plan_vs_actual(run_id)["total"]
    assert total == {"usd": Decimal("0.0031"), "calls": 4, "failed": 1, "held_usd": Decimal("0.01"), "reused": 3}


def test_a_run_without_calls_has_a_zero_total(env):
    wp, run_id, a, b = _queued_run(env["client"], env["folder"])
    assert costs.plan_vs_actual(run_id)["total"] == {"usd": Decimal(0), "calls": 0, "failed": 0, "held_usd": Decimal(0), "reused": 0}


def test_the_run_view_carries_the_total(env):
    wp, run_id, a, b = _queued_run(env["client"], env["folder"])
    _call(run_id, a, "jev", "jev-1.13.0", cost="0.002000")
    body = env["client"].get(f"/api/runs/{run_id}").json()
    assert Decimal(body["costs"]["total"]["usd"]) == Decimal("0.002") and body["costs"]["total"]["calls"] == 1
