"""231 (stage D0, D0-a; the reassessment of 2026-10-26, F05, F06, P01, P04): a pack is refused before a case starts
when a step could not run or an element could not show.

The pack check refused unknown capabilities, but took one that is described without a runner (the line pricing), a step
parameter naming another step that is not there or that the step does not wait for, and a screen element the
interface has no component for or whose data no capability gives: the case would have stopped at that step, or its
tab would have stayed empty. The catalogue now says which elements are built and which are only planned, a pack may
use the built ones only, an element shows what its step's capability (or every case) gives, and the interface's
components match the catalogue (`ui/src/elements/elementCatalogue231.test.tsx`). Synthetic data, the IT quote's pack.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import BaseModel

from jav.app import capabilities, case_views, process_packs, process_runtime
from jav.core import cfg, store


def _it_quote() -> dict:
    return copy.deepcopy(cfg.load("process:it_quote"))


def _problems(data: dict) -> list[str]:
    return process_packs._problems(process_packs.ProcessPack.model_validate(data))


def _step(data: dict, step_id: str) -> dict:
    return next(s for s in data["steps"] if s["id"] == step_id)


def _tab(data: dict, tab_id: str) -> dict:
    return next(t for t in data["screens"]["tabs"] if t["id"] == tab_id)


def test_the_it_quote_pack_still_passes() -> None:
    assert _problems(_it_quote()) == []


def test_a_capability_without_a_runner_is_refused() -> None:
    data = _it_quote()
    data["steps"].insert(2, {"id": "price", "uses": "line_pricing@1", "gates": ["match"], "params": {"catalogue": "@price_list"}})
    assert not capabilities.of("line_pricing@1").invocable
    problems = _problems(data)
    assert any("step 'price': line_pricing@1 cannot run: it is described only" in p for p in problems), problems


@pytest.mark.parametrize(("step_id", "ref", "expected"), [
    ("send", "ghost", "step 'send': from_step names no step 'ghost'"),
    ("send", "send", "step 'send': from_step names step 'send', which it does not wait for"),
    ("send", "follow_up", "step 'send': from_step names step 'follow_up', which it does not wait for"),
    ("document", "letter", "step 'document': from_step names step 'letter', which it does not wait for"),
])
def test_a_step_parameter_naming_another_step_names_one_it_waits_for(step_id, ref, expected) -> None:
    data = _it_quote()
    _step(data, step_id)["params"]["from_step"] = ref
    problems = _problems(data)
    assert any(expected in p for p in problems), problems


def test_a_step_it_waits_for_through_another_counts() -> None:
    data = _it_quote()  # send waits for letter, letter for document, document for compose
    _step(data, "send")["params"]["from_step"] = "compose"
    assert _problems(data) == []


def test_the_step_parameters_that_name_a_step_are_known_by_the_capability() -> None:
    assert capabilities.step_refs(capabilities.of("send@1").params) == ("from_step",)
    assert capabilities.step_refs(capabilities.of("priced_document@1").params) == ("from_step",)
    assert capabilities.step_refs(capabilities.of("catalogue_match@1").params) == ()

    class Plain(BaseModel):
        from_step: str | None = None  # a field of that name is no reference unless it is declared one

    assert capabilities.step_refs(Plain) == ()


def test_a_planned_element_is_refused() -> None:
    elements = cfg.load(process_packs.ELEMENTS)["elements"]
    planned = sorted(k for k, v in elements.items() if v.get("status") == "planned")
    assert planned == ["actions", "data_table", "form"]  # built: D-f4 the field review, D-f7 the document view, D-f9 the blockers
    data = _it_quote()
    _tab(data, "history")["elements"].append({"type": "data_table"})
    problems = _problems(data)
    assert any("tab 'history': screen element 'data_table' is planned, not built" in p for p in problems), problems


@pytest.mark.parametrize(("tab", "element", "expected"), [
    ("quote", {"type": "approval", "step": "match"}, "element 'approval' shows nothing for a step of catalogue_match@1"),
    ("quote", {"type": "match_proposal"}, "element 'match_proposal' shows nothing without a step"),
    ("history", {"type": "pairing", "step": "send"}, "element 'pairing' shows nothing for a step of send@1"),
])
def test_an_element_shows_only_what_its_step_s_capability_gives(tab, element, expected) -> None:
    data = _it_quote()
    _tab(data, tab)["elements"].append(element)
    problems = _problems(data)
    assert any(expected in p for p in problems), problems


def test_every_built_element_has_its_data() -> None:
    elements = cfg.load(process_packs.ELEMENTS)["elements"]
    for name, spec in elements.items():
        if spec.get("status") == "planned":
            continue
        assert case_views.gives(name, spec.get("capability")), name


def test_every_pack_uses_built_elements_only() -> None:
    elements = cfg.load(process_packs.ELEMENTS)["elements"]
    for pack in process_packs.packs():
        for tab in pack.screens.tabs:
            assert all(elements[e.type].get("status") != "planned" for e in tab.elements), (pack.id, tab.id)


def test_a_refused_pack_starts_no_case(tmp_path: Path, monkeypatch) -> None:
    data = _it_quote()
    _step(data, "send")["params"]["from_step"] = "ghost"
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data if name == "process:it_quote" else real(name))
    with store.use_store(tmp_path / "jav.sqlite"):
        with pytest.raises(process_packs.PackError, match="from_step names no step 'ghost'"):
            process_runtime.start_case("it_quote", {}, name="Refused", actor="anna")
        with store.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM workpackages").fetchone()[0] == 0
            assert c.execute("SELECT COUNT(*) FROM process_cases").fetchone()[0] == 0
