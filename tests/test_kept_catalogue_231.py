"""231 (stage D, D-d1): the plumbing the case steps of stage D need.

A step whose parameters name a fact catalogue keeps that catalogue as the case started: a catalogue changed later
reaches only the cases started after it. A step reference marked optional, left out, names no step, so a pack with two
steps of that kind passes the pack check. The assessed units read inside a transaction are those read outside it. An
approval task can go to anyone (a decision another person than the first one makes). Invented data; no paid call.
"""

from __future__ import annotations

import json
import shutil
from unittest import mock

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import assessed_units, capabilities, facts, human_tasks, process_packs, process_runtime
from jav.core import cfg, store
from jav.core.process import kinds, tasks

PACK = "invented_kept_catalogue"
ANNA = "Minta Anna"


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalogue: str
    after: str | None = capabilities.step_ref(None, of="invented_reading", optional=True)


@pytest.fixture()
def configs(monkeypatch, tmp_path):
    copy = tmp_path / "configs"
    shutil.copytree(cfg.CONFIG_DIR, copy)
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    capabilities.register(capabilities.Capability(
        name="invented_reading", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Params,
        run=lambda ctx, p: kinds.DONE, state="step", output=capabilities.Result,
        reads=lambda params: (f"facts_{params['catalogue']}",)))
    data = {"meta": {"name": f"process:{PACK}", "version": "1.0.0"}, "id": PACK, "title": "Invented reading",
            "intake": [{"on": "manual", "starts": "manual"}], "resources": {"catalogue": "property"},
            "steps": [{"id": "first", "uses": "invented_reading@1", "params": {"catalogue": "@catalogue"}},
                      {"id": "second", "uses": "invented_reading@1", "params": {"catalogue": "property"}, "after": ["first"]}],
            "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}}
    with mock.patch.multiple(cfg, CONFIG_DIR=copy, CALLSITE_DIR=copy / "callsites", TYPES_DIR=copy / "types",
                             PROCESSES_DIR=copy / "processes"):
        cfg.reload()
        real = cfg.load
        monkeypatch.setattr(cfg, "load", lambda name: data if name == f"process:{PACK}" else real(name))
        with store.use_store(tmp_path / "kept.sqlite"):
            yield copy, data
    cfg.reload()


def _retitle(copy, title: str) -> None:
    path = copy / "facts_property.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    major, minor, _ = data["meta"]["version"].split(".")
    data["meta"]["version"] = f"{major}.{int(minor) + 1}.0"
    data["facts"]["floor_area"]["title"] = title
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    cfg.reload()


def test_a_catalogue_a_step_names_is_kept_as_the_case_started(configs) -> None:
    copy, _data = configs
    title = facts.catalogue("property").facts["floor_area"].title
    old = process_runtime.start_case(PACK, {}, name="Before", actor=ANNA)
    _retitle(copy, "Floor area, as changed")
    new = process_runtime.start_case(PACK, {}, name="After", actor=ANNA)
    with capabilities.case_rules(old):
        assert facts.catalogue("property").facts["floor_area"].title == title
    with capabilities.case_rules(new):
        assert facts.catalogue("property").facts["floor_area"].title == "Floor area, as changed"
    assert [r["file"] for r in process_runtime.kept_of(old)["rules"]] == ["facts_property"]


def test_an_optional_reference_left_out_names_no_step(configs) -> None:
    _copy, data = configs
    assert capabilities.step_ref_optional(_Params, "after")
    assert process_packs._problems(process_packs.ProcessPack.model_validate(data)) == []


def test_the_units_read_inside_a_transaction_are_those_read_outside() -> None:
    import tempfile
    from pathlib import Path

    with store.use_store(Path(tempfile.mkdtemp()) / "units.sqlite"):
        assessed_units.add("wp-0000000000d1", "check", "property", level="holder", parent_id=None,
                           facts={"activity_code": "4719"}, actor=ANNA)
        with store.connect() as c:
            assert assessed_units.units_in(c, "wp-0000000000d1", "check") == assessed_units.units("wp-0000000000d1", "check")
            assert assessed_units.state_in(c, "wp-0000000000d1", "check") == assessed_units.state("wp-0000000000d1", "check")


def test_an_approval_task_can_go_to_anyone(configs) -> None:
    case = process_runtime.start_case(PACK, {}, name="Anyone", actor=ANNA)
    with store.connect() as c:
        store.begin_immediate(c)
        human_tasks.own_approval_waits(c, case, "second", assignee=None)
        task = tasks.task_in(c, tasks.task_id(human_tasks.OWN_APPROVAL, human_tasks.own_subject(case, "second")))
    assert task is not None and task.assignee is None
