"""Prove request counts at the actual SDK boundary using synthetic transport."""

import asyncio
from dataclasses import replace
from decimal import Decimal

import httpx2
import pytest
from typesafe_sdk import Noul, TypeSafeError

from jav import store
from jav.config import build_retry_policy, make_async_client, make_client
from jav.runtime import calls


@pytest.mark.parametrize("error_type", [httpx2.ReadTimeout, httpx2.WriteTimeout, httpx2.ReadError,
                                       httpx2.WriteError, httpx2.RemoteProtocolError])
def test_jev_does_not_resend_after_a_possible_send(tmp_path, monkeypatch, error_type):
    monkeypatch.setattr("jav.config.get_api_key", lambda: "synthetic-offline-key")
    requests = []

    def lost_response(request):
        requests.append(request)
        raise error_type("synthetic response loss", request=request)

    policy = replace(build_retry_policy(), backoff_initial=0, backoff_max=0, backoff_jitter=0)
    with store.use_store(tmp_path / "jav.sqlite"), make_client(
        api_key="synthetic-offline-key", transport=httpx2.MockTransport(lost_response), retry=policy
    ) as client:
        calls.set_budget("synthetic-budget", "jev", Decimal("1"))

        def invoke():
            return calls.invoke(
                run_id="synthetic-run", step_id="synthetic-step", provider="jev", model="jev-1.13.0",
                max_cost_usd=Decimal("0.1"), budget_scope="synthetic-budget",
                fn=lambda: client.system_one(state="Synthetic text",
                                             questions={"present": Noul(instructions="Is text present?")},
                                             model="jev-1.13.0"),
            )

        with pytest.raises(TypeSafeError):
            invoke()
        with pytest.raises(calls.UncertainAttempt):
            invoke()
        assert [entry["status"] for entry in calls.journal("synthetic-run")] == ["uncertain"]
        assert calls.budget_usage("synthetic-budget")["committed_usd"] == Decimal("0.1")
    assert len(requests) == 1


def test_jev_can_retry_when_the_connection_was_never_established(monkeypatch):
    monkeypatch.setattr("jav.config.get_api_key", lambda: "synthetic-offline-key")
    requests = []

    def connection_failed(request):
        requests.append(request)
        raise httpx2.ConnectError("synthetic connection refusal", request=request)

    policy = replace(build_retry_policy(), backoff_initial=0, backoff_max=0, backoff_jitter=0)
    with make_client(api_key="synthetic-offline-key", transport=httpx2.MockTransport(connection_failed), retry=policy) as client:
        with pytest.raises(TypeSafeError):
            client.system_one(state="Synthetic text", questions={"present": Noul(instructions="Is text present?")}, model="jev-1.13.0")
    assert len(requests) == policy.max_retries + 1


def test_async_jev_does_not_resend_a_lost_response(monkeypatch):
    monkeypatch.setattr("jav.config.get_api_key", lambda: "synthetic-offline-key")
    requests = []

    def response_lost(request):
        requests.append(request)
        raise httpx2.ReadTimeout("synthetic lost response", request=request)

    async def run():
        async with make_async_client(api_key="synthetic-offline-key", transport=httpx2.MockTransport(response_lost)) as client:
            with pytest.raises(TypeSafeError):
                await client.system_one(state="Synthetic text", questions={"present": Noul(instructions="Is text present?")},
                                        model="jev-1.13.0")

    asyncio.run(run())
    assert len(requests) == 1
