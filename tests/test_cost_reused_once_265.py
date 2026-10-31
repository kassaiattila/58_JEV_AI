"""265 (code review APPW-11, X-15): a reused GPT answer is counted once, as a reused answer.

An earlier GPT answer reused (090) is written to the call log (free, noted with its origin) and to the ledger as a
cached answer. The run's cost view counted it twice, as a paid call and as a reused answer, while the case page counted
it only as reused. Both now use one test (`calls.is_reused`). Synthetic rows, no AI.
"""

from __future__ import annotations

from decimal import Decimal

from jav.app import costs, work_runs
from jav.core import calls, store
from tests import test_api
from tests.test_cost_view_082 import _call, _queued_run

env = test_api.env


def test_a_reused_answer_is_not_a_paid_call(env) -> None:
    wp, run_id, a, b = _queued_run(env["client"], env["folder"])
    _call(run_id, a, "openai", "gpt-4.1-mini", cost="0.001000")
    flow = work_runs.flow_run_id(run_id, a)
    with store.connect() as c:
        c.execute("INSERT INTO invocations(run_id, step_id, attempt, provider, model_requested, model_actual, budget_scope,"
                  " status, max_cost_usd, cost_usd, cost_known, note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (flow, "extract", 1, "openai", "gpt-4.1-mini", "gpt-4.1-mini", run_id, "succeeded", "0", "0", 1,
                   f"{calls.REUSED_NOTE}:1", "2026-10-31T00:00:00+00:00"))
    store.ledger_add(run_id=flow, step="extract", provider="openai", model="gpt-4.1-mini", input_tokens=None,
                     output_tokens=None, cost_usd=0.0, seconds=0.0, cached=True)

    line = {(x.provider, x.model): x for x in costs.run_costs(run_id).items[a].lines}[("openai", "gpt-4.1-mini")]
    assert (line.calls, line.reused, line.usd) == (1, 1, Decimal("0.001"))
    assert calls.scope_calls(run_id) == {"live": 1, "live_cost_usd": Decimal("0.001"), "reused": 1}


def test_the_reused_mark() -> None:
    assert calls.is_reused(f"{calls.REUSED_NOTE}:42")
    assert not calls.is_reused(None) and not calls.is_reused("lean_bound")
