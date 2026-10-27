"""231 (stage D, D-b2; the reassessment after D0 of 2026-10-26, F02, P05, T03): a step reads what it expects, typed.

A step reference said which fields of the other step's result it reads and which versions of its form it takes; a
field of the same name but another type passed the pack check and stopped the step later. A reference may now name the
form it expects (`step_ref(expects=)`): the pack check refuses, before a case starts, a field the giver does not give,
one of another type (a text where a number is expected, a bare number where money is), and one the giver may leave
empty where the reader needs a value; a subclass fits (a per-thousand rate where a rate is expected). At run time the
result read is checked against the expected form before any effect. Invented capabilities; no paid call.
"""

from __future__ import annotations

import copy
from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import capabilities, process_packs
from jav.core import cfg
from jav.core.measures import Money, PerMille, Rate
from jav.core.process import kinds
from tests.test_quote_twin_231 import _pack


class _None(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GivesText(capabilities.Result):
    version: str


class GivesMaybe(capabilities.Result):
    version: int | None = None


class GivesNumber(capabilities.Result):
    version: int
    total: Decimal
    rate: PerMille


class Expected(capabilities.Result):
    version: int


class ExpectsMoney(capabilities.Result):
    total: Money


class ExpectsRate(capabilities.Result):
    rate: Rate


def _reader(expects: type[capabilities.Result]) -> type[BaseModel]:
    class Reads(BaseModel):
        model_config = ConfigDict(extra="forbid")
        from_step: str = capabilities.step_ref(min_length=1, expects=expects)

    return Reads


def _cap(name: str, params: type[BaseModel], output: type[capabilities.Result]) -> capabilities.Capability:
    return capabilities.Capability(name=name, version=1, module="tests.synthetic", kind="machine", summary="Invented.",
                                   params=params, run=lambda ctx, p: kinds.DONE, state="step", output=output)


@pytest.fixture()
def isolated(monkeypatch):
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))


def _pack_of(giver: type[capabilities.Result], expects: type[capabilities.Result]) -> list[str]:
    capabilities.register(_cap("invented_giver", _None, giver))
    capabilities.register(_cap("invented_reader", _reader(expects), capabilities.Result))
    data = {"meta": {"name": "process:invented_types", "version": "1.0.0"}, "id": "invented_types", "title": "Invented",
            "intake": [{"on": "manual", "starts": "manual"}],
            "steps": [{"id": "give", "uses": "invented_giver@1", "params": {}},
                      {"id": "read", "uses": "invented_reader@1", "after": ["give"], "params": {"from_step": "give"}}],
            "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}}
    return process_packs._problems(process_packs.ProcessPack.model_validate(data))


def test_a_field_of_the_expected_type_fits(isolated) -> None:
    assert _pack_of(GivesNumber, Expected) == []
    assert _pack_of(GivesNumber, ExpectsRate) == []  # a per-thousand rate is a rate


@pytest.mark.parametrize(("giver", "expects", "problem"), [
    (GivesText, Expected, "from_step reads 'version' as int, and invented_giver@1 gives str"),
    (GivesMaybe, Expected, "from_step reads 'version' as int, and invented_giver@1 may leave it empty"),
    (GivesNumber, ExpectsMoney, "from_step reads 'total' as Money, and invented_giver@1 gives Decimal"),
    (GivesText, ExpectsMoney, "from_step reads 'total', which invented_giver@1 does not give"),
])
def test_a_field_of_another_type_is_refused_before_a_case_starts(isolated, giver, expects, problem) -> None:
    problems = _pack_of(giver, expects)
    assert any(problem in p for p in problems), problems


def test_a_result_read_at_run_time_is_checked_against_the_expected_form() -> None:
    reads = _reader(Expected)
    assert capabilities.expected_result(reads, "from_step", {"version": 3, "other": "kept"}).version == 3
    with pytest.raises(capabilities.ResultMismatch, match="does not fit the form the step expects: version"):
        capabilities.expected_result(reads, "from_step", {"version": "active"})


def test_the_packs_in_use_still_pass() -> None:
    assert process_packs._problems(process_packs.ProcessPack.model_validate(copy.deepcopy(cfg.load("process:it_quote")))) == []
    twin = _pack("newest_active", "newest_active") | {"resources": {}}
    assert process_packs._problems(process_packs.ProcessPack.model_validate(twin)) == []
