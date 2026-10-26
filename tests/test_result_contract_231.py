"""231 (stage D0, D0-c; the reassessment of 2026-10-26, F05, P03): what a step gives and what another reads is a
contract.

A capability names the form of its result (`Capability.output`, a model with its version); a step parameter that names
another step says which fields of that step's result it reads (`step_ref(reads=...)`) and, when it matters, which
versions of the form it takes. The pack check refuses a reference to a field the other step's capability does not give,
or to a version it does not take, before a case starts; a step's result is checked against its capability's form before
it is kept, and a result another step reads is checked before it is used, so a mismatch stops the step before any
effect. Synthetic capabilities and the IT quote's pack; no paid call.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import capabilities, process_packs
from jav.core import cfg, identity
from jav.core.process import kinds
from jav.core.process.definition import ProcessDef, StepDef
from jav.core.process.engine import StepContext


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Given(capabilities.Result):
    version: int


def _cap(**changes) -> capabilities.Capability:
    base = dict(name="invented_contract", version=1, module="tests.synthetic", kind="machine", summary="Invented.",
                params=_Params, run=lambda ctx, params: kinds.Done({"version": 3}), state="step", output=_Given)
    return capabilities.Capability(**{**base, **changes})


@pytest.fixture()
def isolated(monkeypatch):
    monkeypatch.setattr(capabilities, "_CAPS", {})
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))


def _ctx(kind: str, results: dict[str, tuple[int, object]] | None = None, params: dict | None = None) -> StepContext:
    giver = StepDef(id="giver", kind="cap.invented_contract.v1")
    step = StepDef(id="reader", kind=kind, after=("giver",), params=params or {})
    definition = ProcessDef(id="synthetic", version="1", title="Synthetic", steps=(giver, step))
    ctx = StepContext(case_id="case-1", step=step, definition=definition, data={}, actor=identity.machine("test"))
    if results is not None:
        object.__setattr__(ctx, "result_of", lambda step_id: results[step_id])
    return ctx


def test_a_capability_that_can_run_names_the_form_of_its_result(isolated) -> None:
    capabilities.register(_cap())
    capabilities.register(_cap(name="invented_described", run=None, output=None))  # described only: it gives nothing
    with pytest.raises(capabilities.CapabilityError, match="names the form of its result"):
        capabilities.register(_cap(name="invented_formless", output=None))


def test_every_registered_capability_that_can_run_names_its_result() -> None:
    formless = [c.key for c in capabilities.catalogue() if c.invocable and c.output is None]
    assert formless == []


def test_a_result_that_does_not_fit_its_form_stops_the_step_before_it_is_kept(isolated) -> None:
    capabilities.register(_cap(run=lambda ctx, params: kinds.Done({"version": "three"})))
    outcome = kinds.of("cap.invented_contract.v1").run(_ctx("cap.invented_contract.v1"))
    assert isinstance(outcome, kinds.Fail) and "does not fit the form invented_contract@1 gives: version" in outcome.note


def test_a_result_another_step_reads_is_checked_before_it_is_used(isolated) -> None:
    capabilities.register(_cap())
    seen: list = []

    class _Reads(BaseModel):
        model_config = ConfigDict(extra="forbid")
        from_step: str = capabilities.step_ref(reads=("version",))

    def read(ctx, params):
        seen.append(capabilities.read_result(ctx, params, "from_step"))
        return kinds.Done({"version": 1})

    capabilities.register(_cap(name="invented_reader", run=read, params=_Reads))
    run = kinds.of("cap.invented_reader.v1").run
    good = _ctx("cap.invented_reader.v1", {"giver": (1, {"version": 7})}, {"from_step": "giver"})
    assert run(good) == kinds.Done({"version": 1}) and seen == [{"version": 7}]
    bad = _ctx("cap.invented_reader.v1", {"giver": (1, {"lines": 2})}, {"from_step": "giver"})
    outcome = run(bad)
    assert isinstance(outcome, kinds.Fail) and "the result of step 'giver' does not fit" in outcome.note
    assert seen == [{"version": 7}]  # the reader never ran with it


def _it_quote() -> dict:
    return copy.deepcopy(cfg.load("process:it_quote"))


def _problems(data: dict) -> list[str]:
    return process_packs._problems(process_packs.ProcessPack.model_validate(data))


def test_a_step_reading_a_field_the_other_step_does_not_give_is_refused() -> None:
    data = _it_quote()
    next(s for s in data["steps"] if s["id"] == "document")["params"]["from_step"] = "match"  # a proposal has no version
    problems = _problems(data)
    assert any("step 'document': from_step reads 'version', which catalogue_match@1 does not give" in p
               for p in problems), problems


def test_the_it_quote_pack_reads_what_its_steps_give() -> None:
    assert _problems(_it_quote()) == []
    assert capabilities.step_reads(capabilities.of("priced_document@1").params, "from_step") == (("version",), None)


def test_a_step_taking_another_version_of_the_form_is_refused(isolated, monkeypatch) -> None:
    capabilities.register(_cap())

    class _Takes2(BaseModel):
        model_config = ConfigDict(extra="forbid")
        from_step: str = capabilities.step_ref(reads=("version",), versions=(2,))

    reader = _cap(name="invented_reader", params=_Takes2)
    capabilities.register(reader)
    problem = capabilities.reference_problem(reader, "from_step", capabilities.of("invented_contract@1"))
    assert problem == "from_step takes the form of version 2 of invented_contract@1's result, not version 1"
