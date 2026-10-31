"""265 (code review SEC-02, TOOL-03, TOOL-04): a paid call is made only in a run or under a command's budget.

The JEV adapter called the provider straight away when no run context was set: the email receiver's `--run`, the
injection probe's `--live` without a budget and any other command outside `calls.measurement` spent with a ledger row
but no budget and no call-log row (the Azure branch did the same, `test_azure_budget_075`). Now the client the adapter
makes from the environment's key is called only under a run's or a command's budget; outside one only earlier answers
count (`jev_unavailable:no_budget`). A client handed over (a test's or a tool's fake) stays the caller's. No paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from jav.ai import jev as jev_mod
from jav.ai.jev import JevAdapter, JevUnavailableError
from jav.core import calls, store
from tests.test_jev_adapter_v2 import QS, FakeClient


@pytest.fixture
def isolated(tmp_path):
    with store.use_store(tmp_path / "paid.sqlite"):
        yield tmp_path


def test_the_environment_s_client_is_not_called_outside_a_budget(isolated, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(jev_mod, "make_client", lambda: fake)
    adapter = JevAdapter(cache_dir=isolated / "cache", model="jev-1.13.0")
    with pytest.raises(JevUnavailableError) as err:
        adapter.ask("t", {"x": 1}, QS, run_id="adhoc", use_cache=False)
    assert err.value.reason == "no_budget" and fake.calls == 0
    with calls.measurement("cli-test", {"jev": Decimal("0.05")}):
        adapter.ask("t", {"x": 1}, QS, run_id="adhoc", use_cache=False)
    assert fake.calls == 1


def test_a_client_handed_over_is_the_caller_s(isolated):
    fake = FakeClient()
    JevAdapter(client=fake, cache_dir=isolated / "cache", model="jev-1.13.0").ask("t", {"x": 1}, QS, run_id="adhoc",
                                                                                   use_cache=False)
    assert fake.calls == 1


def test_the_email_receiver_takes_a_budget_and_its_flows_run_under_it(isolated, monkeypatch) -> None:
    import argparse

    from jav.domains.email import email_cli, ingest_server

    parser = argparse.ArgumentParser()
    email_cli.register(parser.add_subparsers())
    args = parser.parse_args(["email-ingest-server", "--run", "--jev-budget-usd", "0.10"])
    seen: list[object] = []
    monkeypatch.setattr(ingest_server, "serve", lambda **kw: seen.append(calls.current()))
    email_cli.cmd_email_ingest_server(args)
    assert seen and seen[0] is not None and seen[0].budget_scope  # served inside the command's budget
    server = ingest_server.make_server(0, run_flow=True, flow_context=None)
    assert server.RequestHandlerClass.flow_context is None
    server.server_close()


def test_the_injection_probe_s_live_run_needs_a_hard_limit(capsys) -> None:
    from jav.evals import document_injection_probe

    assert document_injection_probe.main(["--live"]) == 2
    assert "needs a hard limit" in capsys.readouterr().out


def test_the_smoke_test_names_the_key_by_its_length_and_sends_nothing_without_a_budget(monkeypatch, capsys) -> None:
    """265 (code review TOOL-14): it printed ten of the key's characters and called the client past the ledger."""
    import smoke_test

    monkeypatch.setattr(smoke_test, "get_api_key", lambda: "abcdef-not-a-real-key-wxyz")
    monkeypatch.setattr(jev_mod.JevAdapter, "ask", lambda *a, **k: pytest.fail("a live call without a budget"))
    assert smoke_test.main([]) == 0
    out = capsys.readouterr().out
    assert "present (26 characters)" in out and "abcdef" not in out and "wxyz" not in out
