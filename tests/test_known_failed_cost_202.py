"""A failed call whose cost is certain is settled at that cost (202, backlog Q-elutasitott-hivas-foglalas).

Plain-language summary: the call log reserves a call's maximum cost before it is sent. A failed call used to keep that
maximum committed in the run's budget, as if its outcome were unknown, even when it was certain. Two such cases held
back money in the 200 measurements: JEV refused a request as too large without processing it (0.019 USD held back),
and a GPT answer stopped at its output cap, whose tokens were known (0.193 USD held back). The owner decided
(2026-10-22) that such a call is settled at its certain cost: the refusal at 0, the cut-off answer at what it used.
A call whose outcome is really unknown (a timeout, a broken connection) keeps its maximum reserved, as before.

Offline: a fake JEV client and a local stand-in of the OpenAI endpoint; no paid call.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from typesafe_sdk import Noul

from jav.ai import extract_llm
from jav.core import store
from jav.ai.jev import JevAdapter, JevUnavailableError
from jav.core.config import OPENAI_MODEL, OPENAI_USD_PER_MTOK
from jav.core import calls
from jav.ai.typepack import get as get_pack
from tests.test_no_jev_085 import GOOD
from tests.test_oversize_memory_200 import SizeLimitedClient

PACK = get_pack("invoice_hu")
MAX = Decimal("0.5")


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "t.sqlite"):
        yield tmp_path


def _row(run_id: str) -> dict:
    with store.connect() as c:
        return dict(c.execute("SELECT status, cost_usd, cost_known, max_cost_usd FROM invocations WHERE run_id=?",
                              (run_id,)).fetchone())


def _committed(scope: str, provider: str) -> Decimal:
    return calls.budget_usage(scope)["providers"][provider]["committed_usd"]


def _failing(exc: BaseException):
    def fn() -> calls.Outcome:
        raise exc
    return fn


def _with_known_cost(exc: BaseException, cost: str) -> BaseException:
    exc.known_outcome = calls.Outcome(response=None, model="m", input_tokens=10, output_tokens=0, cost_usd=Decimal(cost))
    return exc


def test_a_failed_call_with_a_certain_cost_is_settled_at_that_cost(isolated):
    calls.set_budget("s", "jev", Decimal("1"))
    with calls.use_run(budget_scope="s"), pytest.raises(RuntimeError):
        calls.invoke(run_id="r1", step_id="a", provider="jev", model="m", max_cost_usd=MAX, budget_scope="s",
                     fn=_failing(_with_known_cost(RuntimeError("refused"), "0")))
    row = _row("r1")
    assert (row["status"], row["cost_known"], Decimal(row["cost_usd"])) == ("failed", 1, Decimal("0"))
    assert _committed("s", "jev") == Decimal("0")


def test_a_failed_call_without_a_certain_cost_keeps_its_maximum(isolated):
    calls.set_budget("s", "jev", Decimal("1"))
    with calls.use_run(budget_scope="s"), pytest.raises(ValueError):
        calls.invoke(run_id="r2", step_id="a", provider="jev", model="m", max_cost_usd=MAX, budget_scope="s",
                     fn=_failing(ValueError("bad answer")))
    assert (_row("r2")["status"], _row("r2")["cost_known"]) == ("failed", 0)
    assert _committed("s", "jev") == MAX


def test_an_uncertain_call_keeps_its_maximum_even_with_a_cost(isolated):
    """A timeout after sending may still have been processed: a cost the caller attached cannot be certain."""
    calls.set_budget("s", "jev", Decimal("1"))
    with calls.use_run(budget_scope="s"), pytest.raises(TimeoutError):
        calls.invoke(run_id="r3", step_id="a", provider="jev", model="m", max_cost_usd=MAX, budget_scope="s",
                     fn=_failing(_with_known_cost(TimeoutError("read timed out"), "0")))
    assert (_row("r3")["status"], _row("r3")["cost_known"]) == ("uncertain", 0)
    assert _committed("s", "jev") == MAX


def test_jev_refusing_a_request_as_too_large_costs_nothing(isolated):
    calls.set_budget("s", "jev", Decimal("1"))
    jev = JevAdapter(client=SizeLimitedClient(limit=0), cache_dir=isolated / "cache", model="jev-1.14.0")
    with calls.use_run(budget_scope="s"), pytest.raises(JevUnavailableError) as caught:
        jev.ask("probe_large", {"lines": ["L01: a line"]}, {"flag": Noul(instructions="is it?")}, run_id="r4")
    assert "max_tokens_exceeded" in caught.value.reason
    row = _row("r4")
    assert (row["status"], row["cost_known"], Decimal(row["cost_usd"])) == ("failed", 1, Decimal("0"))
    assert _committed("s", "jev") == Decimal("0")


class _Transport:
    """The OpenAI chat endpoint as a local stand-in: each answer in turn, `stop` (with `content`) or `length`."""

    def __init__(self, *answers: tuple[str, str | None]):
        self.answers = list(answers)
        self.requests = 0

    def __call__(self, request):
        finish, content = self.answers[min(self.requests, len(self.answers) - 1)]
        self.requests += 1
        full = json.dumps(PACK.llm_model().model_validate(GOOD).model_dump(mode="json"), ensure_ascii=False)
        content = content if content is not None else full[: len(full) // 2]
        return httpx.Response(200, json={
            "id": f"synthetic-{self.requests}", "object": "chat.completion", "created": 1700000000, "model": OPENAI_MODEL,
            "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 4000 if finish == "length" else 200, "total_tokens": 5200}})


def _extract(transport: _Transport, run_id: str):
    client = AsyncOpenAI(api_key="synthetic-not-a-real-key", max_retries=0,
                         http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)))
    agent = extract_llm.build_agent(PACK, OpenAIChatModel(OPENAI_MODEL, provider=OpenAIProvider(openai_client=client)))
    try:
        with extract_llm.use_agent_factory(lambda p: agent), calls.use_run(budget_scope="g"):
            return extract_llm.extract_scored("Invoice number: MINTA-1", pack=PACK, run_id=run_id)
    finally:
        asyncio.run(client.close())


def _usd(input_tokens: int, output_tokens: int) -> Decimal:
    price_in, price_out = (Decimal(str(p)) for p in OPENAI_USD_PER_MTOK[OPENAI_MODEL])
    return ((input_tokens * price_in + output_tokens * price_out) / Decimal(1_000_000)).quantize(Decimal("0.000001"))


def test_a_cut_off_gpt_answer_is_settled_at_what_it_used(isolated):
    calls.set_budget("g", "openai", Decimal("1"))
    with pytest.raises(extract_llm.OutputTruncated):
        _extract(_Transport(("length", None)), "r5")
    row = _row("r5")
    assert (row["status"], row["cost_known"], Decimal(row["cost_usd"])) == ("failed", 1, _usd(1000, 4000))
    assert _committed("g", "openai") == _usd(1000, 4000) < Decimal(row["max_cost_usd"])


def test_a_cut_off_answer_after_a_validation_retry_counts_both_requests(isolated):
    """The first answer is not valid JSON (Pydantic AI asks again), the second is cut off: both were paid."""
    calls.set_budget("g", "openai", Decimal("1"))
    with pytest.raises(extract_llm.OutputTruncated):
        _extract(_Transport(("stop", "not json"), ("length", None)), "r6")
    row = _row("r6")
    assert (row["status"], row["cost_known"]) == ("failed", 1)
    assert Decimal(row["cost_usd"]) == _usd(1000, 200) + _usd(1000, 4000)
