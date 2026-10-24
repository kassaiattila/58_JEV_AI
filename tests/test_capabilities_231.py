"""231 (plan stage A, A2; DECISIONS 231): the capability registry, the general building blocks of every process pack.

A capability describes what a process sets for it (a model that forbids other fields), whether it may call a paid
service and what effect it has; one that can run gets its own step kind in the process core, which checks the step's
parameters first. A paid step outside a work run spends from its own budget scope per case, step and round, as
business work (not a measurement). The process core makes the application's registrations before it calls a step kind
unknown, since the capabilities register there. Synthetic capabilities; no paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import capabilities, registrations
from jav.core import calls, completion, identity, store
from jav.core.process import kinds
from jav.core.process.definition import ProcessDef, StepDef
from jav.core.process.engine import StepContext

PROCESS_NAMES = ("reconcile", "statements", "email_routing", "routing", "quote", "mailbox", "it_quote", "insurance_quote")


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int


class Loose(BaseModel):
    days: int


@pytest.fixture()
def isolated(monkeypatch):
    monkeypatch.setattr(capabilities, "_CAPS", {})
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))


def _cap(**changes) -> capabilities.Capability:
    seen: list = []

    def run(ctx, params):
        seen.append(params)
        return kinds.Done({"days": params.days})

    base = dict(name="wait_reply", version=1, module="tests.synthetic", kind="wait", summary="Waits for a reply.",
                params=Params, run=run)
    cap = capabilities.Capability(**{**base, **changes})
    object.__setattr__(cap, "described", {"seen": seen})
    return cap


def _ctx(params: dict) -> StepContext:
    step = StepDef(id="follow_up", kind="cap.wait_reply.v1", params=params)
    definition = ProcessDef(id="synthetic", version="1", title="Synthetic", steps=(step,))
    return StepContext(case_id="case-1", step=step, definition=definition, data={}, actor=identity.machine("test"))


def test_a_capability_that_can_run_gets_its_step_kind_which_checks_the_parameters_first(isolated) -> None:
    cap = _cap()
    capabilities.register(cap)
    assert capabilities.of("wait_reply@1") is cap and cap.step_kind == "cap.wait_reply.v1"
    kind = kinds.of("cap.wait_reply.v1")
    assert kind.owner == "tests.synthetic" and kind.described["capability"] == "wait_reply@1"
    assert kind.run(_ctx({"days": 5})) == kinds.Done({"days": 5})
    bad = kind.run(_ctx({"days": "five", "extra": 1}))
    assert isinstance(bad, kinds.Fail) and "days" in bad.note and "extra" in bad.note


def test_a_capability_only_described_has_no_step_kind(isolated) -> None:
    capabilities.register(_cap(name="document_processing", run=None))
    assert not capabilities.of("document_processing@1").invocable
    assert not kinds.known("cap.document_processing.v1")


@pytest.mark.parametrize("changes", [{"name": "Wait-Reply"}, {"version": 0}, {"params": Loose},
                                     {"providers": ("somewhere",)}, {"summary": " "}, {"effects": "magic"}])
def test_a_capability_that_breaks_a_rule_is_refused(isolated, changes) -> None:
    with pytest.raises(capabilities.CapabilityError):
        capabilities.register(_cap(**changes))


def test_another_module_cannot_take_a_registered_capability(isolated) -> None:
    capabilities.register(_cap())
    capabilities.register(_cap())  # its owner again: a module loaded twice
    with pytest.raises(capabilities.CapabilityError):
        capabilities.register(_cap(module="tests.other"))
    with pytest.raises(capabilities.CapabilityError):
        capabilities.of("wait_reply@2")


def test_a_paid_step_spends_from_its_own_budget_per_case_step_and_round(tmp_path) -> None:
    with store.use_store(tmp_path / "budget.sqlite"):
        with capabilities.step_budget("case-1", "match", 1, {"jev": Decimal("0.05")}) as scope:
            ctx = calls.current()
            assert scope == "case:case-1:match:1"
            assert (ctx.budget_scope, ctx.reuse, ctx.measurement) == (scope, True, False)
        with capabilities.step_budget("case-1", "match", 1, {"jev": Decimal("9")}):
            pass  # the same round again keeps its cap
        assert calls.budget_usage("case:case-1:match:1")["providers"]["jev"]["limit_usd"] == Decimal("0.05")
        assert calls.current() is None


def test_the_core_makes_the_registrations_before_it_calls_a_step_kind_unknown(monkeypatch) -> None:
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    step = StepDef(id="s", kind="cap.late.v1")
    definition = ProcessDef(id="late", version="1", title="Late", steps=(step,))

    def complete() -> None:
        kinds.register(kinds.StepKind(name="cap.late.v1", owner="tests.late", run=lambda ctx: kinds.DONE))

    monkeypatch.setattr(completion, "_completer", complete)
    assert kinds.unknown(definition) == []
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    monkeypatch.setattr(completion, "_completer", None)
    step2 = StepDef(id="s", kind="cap.never.v1")
    assert kinds.unknown(ProcessDef(id="never", version="1", title="Never", steps=(step2,))) == ["cap.never.v1"]


def test_every_registered_capability_fits_the_rules() -> None:
    registrations.load_all()
    for cap in capabilities.catalogue():
        assert cap.name not in PROCESS_NAMES, f"{cap.key}: a capability is general, never named after a process"
        assert not cap.invocable or kinds.known(cap.step_kind), cap.key
        if cap.providers:
            assert cap.rule_files, f"{cap.key}: a paid capability names the rule files it reads"
