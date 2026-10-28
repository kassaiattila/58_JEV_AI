"""231 (stage D0, D0-b; the reassessment of 2026-10-26, F04, P02): a capability's state belongs to its step.

The same capability may stand twice in one case (two price lists matched, two premium calculations): each step then
keeps its own proposal, draft, approval, task and budget, and reopening one leaves the other alone. A capability says
what its state belongs to: the step (the rule), or the case as a whole, which a pack may then use only once. The quote's
capabilities kept theirs per case until D0-b. Synthetic data; no paid call.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import capabilities, process_packs
from jav.core import cfg
from jav.core.process import kinds


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _cap(**changes) -> capabilities.Capability:
    base = dict(name="invented_state", version=1, module="tests.synthetic", kind="machine", summary="Invented.",
                params=_Params, run=lambda ctx, params: kinds.DONE, state="step", output=capabilities.Result)
    return capabilities.Capability(**{**base, **changes})


@pytest.fixture()
def isolated(monkeypatch):
    monkeypatch.setattr(capabilities, "_CAPS", {})
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))


def test_a_capability_that_can_run_says_what_its_state_belongs_to(isolated) -> None:
    capabilities.register(_cap())
    capabilities.register(_cap(name="invented_case", state="case"))
    capabilities.register(_cap(name="invented_described", run=None, state=None))  # described only: nothing to keep
    with pytest.raises(capabilities.CapabilityError, match="says whether its state belongs to the case or to its step"):
        capabilities.register(_cap(name="invented_silent", state=None))


def test_every_registered_capability_that_can_run_names_its_state() -> None:
    states = {c.key: c.state for c in capabilities.catalogue() if c.invocable}
    assert states == {
        "record_assembly@1": "step", "catalogue_match@1": "step", "line_draft@1": "step", "priced_document@1": "step",
        "letter_draft@1": "step", "send@1": "step", "wait_reply@1": "step", "process_documents@1": "step",
        "pairing_proposal@1": "step", "pairing@1": "case", "file_placement@1": "case",
        "field_check@1": "step",  # D-d2
        "rule_evaluation@1": "step", "rating@1": "step",  # D-d3
        "decision@1": "step",  # D-d4
        "lookup@1": "step",  # D-d5
        "missing_info@1": "step",  # D-d6
        "fact_claims@1": "step",  # D-f1
        "letter@1": "step",  # D-f8
        "run_case@1": "step"}  # U2c


def test_a_capability_whose_state_belongs_to_the_case_stands_once_in_a_pack() -> None:
    data = copy.deepcopy(cfg.load("process:reconciliation"))
    twin = copy.deepcopy(next(s for s in data["steps"] if s["id"] == "pair"))
    data["steps"].append({**twin, "id": "pair_again", "after": ["pair"]})
    problems = process_packs._problems(process_packs.ProcessPack.model_validate(data))
    assert any("pairing@1 keeps its state for the whole case: a pack uses it once" in p for p in problems), problems
