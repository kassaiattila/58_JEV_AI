"""231 (plan stage C, C2b): the pairing of two lists as a general capability (`pairing@1`).

The step proposes by code and waits for a person; it is done when the person approves the result as the case's own
version, the same rule a workflow's reconciliation step follows, so a reconciliation package taken over as a case keeps
its state. The rules it names are checked before it runs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from jav.app import capabilities, registrations
from jav.core.process import cases, kinds
from jav.domains.finance import capabilities as finance_capabilities


@pytest.fixture(scope="module", autouse=True)
def _registered():
    registrations.load_all()


class Ctx:
    def __init__(self, container: str):
        self.data, self.waited = {"container": container}, []
        self.step = SimpleNamespace(id="pair")  # D0-b: the approval is the pairing step's

    def wait(self, what, *, timer=None, detail=None):
        self.waited.append((what, timer[0] if timer else None))
        return kinds.WAIT


def _approval(monkeypatch, active):
    monkeypatch.setattr(finance_capabilities.package_release, "own_approval",
                        lambda wp_id, c=None, step=None: {"active": active.get(wp_id), "versions": []})


def test_the_capability_is_registered_as_a_human_step_reading_the_reconciliation_rules():
    cap = capabilities.of("pairing@1")
    assert (cap.kind, cap.effects, cap.providers, cap.rule_files) == ("human", "store", (), ("reconcile", "finance"))
    assert cap.invocable and cap.adopt is not None and cap.module == "jav.domains.finance.capabilities"


@pytest.mark.parametrize("params", [{}, {"rules": "anything"}, {"rules": "invoice_statement", "extra": 1}])
def test_the_rules_are_named_and_checked(params):
    with pytest.raises(ValidationError):
        finance_capabilities.Pairing.model_validate(params)


def test_the_step_waits_for_the_approval_and_is_done_with_its_version(monkeypatch):
    params = finance_capabilities.Pairing(rules="invoice_statement")
    _approval(monkeypatch, {})
    ctx = Ctx("wp-1")
    assert finance_capabilities._pair(ctx, params) is kinds.WAIT and ctx.waited == [("pairing", "check")]
    _approval(monkeypatch, {"wp-1": {"version": 2}})
    assert finance_capabilities._pair(ctx, params) == kinds.Done({"version": 2})


def test_a_package_taken_over_keeps_its_state(monkeypatch):
    _approval(monkeypatch, {"wp-done": {"version": 1}})
    done = finance_capabilities._adopt("wp-done", {"rules": "invoice_statement"})
    waiting = finance_capabilities._adopt("wp-open", {"rules": "invoice_statement"})
    assert (done.state, done.result) == (cases.DONE, {"version": 1})
    assert (waiting.state, waiting.waiting_for, waiting.timer[0]) == (cases.RUNNING, "pairing", "check")
