"""231 (stage D, D-a; the reassessment after D0 of 2026-10-26, F03, P02, T02): a step reads the step its pack names.

A step reference may be left out where the pack has one step it can read (the IT quote's composition reads its only
match). Where the pack has several (two matches), a left-out reference made the step read the first one while its
approval's basis named the one it waits for. The pack check now refuses it by name before a case starts, as it refuses
a reference to a step of another kind: the source a step reads, the step it waits for and its approval's basis are the
same step. Synthetic data: the IT quote's pack and the invented twin pack of D0.
"""

from __future__ import annotations

import copy

import pytest

from jav.app import capabilities, process_packs
from jav.core import cfg
from tests.test_quote_twin_231 import _pack


def _problems(data: dict) -> list[str]:
    return process_packs._problems(process_packs.ProcessPack.model_validate(data))


def _step(data: dict, step_id: str) -> dict:
    return next(s for s in data["steps"] if s["id"] == step_id)


def _twin() -> dict:
    return _pack("newest_active", "newest_active") | {"resources": {}}  # no store: the lists are not looked up


def test_the_twin_pack_naming_each_source_passes_and_the_it_quote_needs_none() -> None:
    assert _problems(_twin()) == []
    assert _problems(copy.deepcopy(cfg.load("process:it_quote"))) == []  # one match, one composition: nothing to name
    assert capabilities.step_ref_of(capabilities.of("line_draft@1").params, "from_step") == "catalogue_match"
    assert capabilities.step_ref_of(capabilities.of("letter_draft@1").params, "from_step") == "line_draft"


def test_a_left_out_source_among_several_is_refused_by_name() -> None:
    data = _twin()
    del _step(data, "compose_b")["params"]["from_step"]  # it waits for match_b, and would read match_a
    problems = _problems(data)
    assert ("step 'compose_b': from_step names no step, and the pack has several catalogue_match steps"
            " (match_a, match_b): name the one it reads") in problems, problems


def test_a_source_of_another_kind_is_refused() -> None:
    data = _twin()
    _step(data, "compose_a")["params"]["from_step"] = "request"
    problems = _problems(data)
    assert "step 'compose_a': from_step names step 'request', a record_assembly step, not a catalogue_match step" in problems, problems


def test_the_only_source_left_out_is_one_the_step_waits_for() -> None:
    data = copy.deepcopy(cfg.load("process:it_quote"))
    _step(data, "compose")["after"] = []  # it no longer waits for the match it would read
    problems = _problems(data)
    assert "step 'compose': from_step names no step, and the step does not wait for the only catalogue_match step 'match'" in problems, problems


@pytest.mark.parametrize("letters", [1, 2])
def test_a_letter_names_its_composition_where_there_are_several(letters) -> None:
    data = _twin()
    for n in range(letters):
        data["steps"].append({"id": f"letter_{n}", "uses": "letter_draft@1", "gates": ["compose_a", "compose_b"], "start": "person",
                              "params": {"frame": "letter", "callsite": "quote_letter"}})
    problems = _problems(data)
    assert any("from_step names no step, and the pack has several line_draft steps (compose_a, compose_b)" in p for p in problems), problems
