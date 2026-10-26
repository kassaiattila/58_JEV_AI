"""231 (stage D, D-d6): waiting for the facts the rules miss, with a person's task that expires.

The reference cases of the invented product set run as cases up to the evaluation. Where nothing is missing, the step
is done at once and opens no task. Where facts are missing (the accounting method, the site's protection class), a task
opens with them and a deadline of the days the pack sets; once a person enters them in the field check and freezes it
again, the evaluation misses nothing, the task is withdrawn and the step is done. If the deadline passes, or a person
says - with a reason - that the facts will not come, the case closes with the pack's outcome. Invented data; no paid
call.
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import assessed_units, capabilities, field_check, missing_info, process_runtime, product_sets
from jav.core import cfg, store
from jav.core.process import cases, engine, kinds, tasks
from tests.test_evaluation_steps_231 import CASES, _claims

ANNA = "Minta Anna"
DAYS = 10


class _Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[dict]


def _pack(pid: str, claims: list[dict]) -> dict:
    return {"meta": {"name": f"process:{pid}", "version": "1.0.0"}, "id": pid, "title": "Invented missing facts",
            "intake": [{"on": "manual", "starts": "manual"}], "resources": {"product": "inv_business_property"},
            "needs_at_start": ["product"],
            "steps": [{"id": "read", "uses": "invented_offer@1", "params": {"claims": claims}},
                      {"id": "check", "uses": "field_check@1", "params": {"catalogue": "property", "product": "@product"},
                       "after": ["read"]},
                      {"id": "evaluate", "uses": "rule_evaluation@1", "params": {"from_step": "check"}, "after": ["check"]},
                      {"id": "missing", "uses": "missing_info@1",
                       "params": {"from_step": "evaluate", "days": DAYS, "closes": "expired"}, "after": ["evaluate"]}],
            "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}}


@pytest.fixture()
def packs(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    capabilities.register(capabilities.Capability(
        name="invented_offer", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Offer,
        run=lambda ctx, p: kinds.Done({"claims": p.claims}), state="step", output=capabilities.Result))
    data = {f"process:invented_missing_{cid}": _pack(f"invented_missing_{cid}", _claims(CASES[cid]))
            for cid in ("reference", "missing_facts")}
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data[name] if name in data else real(name))
    with store.use_store(tmp_path / "missing.sqlite"):
        product_sets.install(product_sets.load(), maker=ANNA, approver="Minta Bela")
        yield


_CLOCK = [time.time()]


def _turn(case_id: str, at: float | None = None) -> None:
    _CLOCK[0] = max(_CLOCK[0], time.time(), at or 0) + 10  # never behind the real time the steps' timers are set from
    engine.turn(case_id, now=_CLOCK[0])


def _started(cid: str) -> str:
    case_id = process_runtime.start_case(f"invented_missing_{cid}", {}, name="Invented missing facts", actor=ANNA)
    _turn(case_id)
    field_check.freeze(case_id, "check", cover_start="2027-01-01", expected_state=None, actor=ANNA)
    _turn(case_id)
    return case_id


def _task(case_id: str) -> tasks.Task | None:
    return tasks.get(tasks.task_id(missing_info.TASK, f"{case_id}:missing"))


def _closed(case_id: str) -> tuple[str, str | None]:
    with store.connect() as c:
        row = cases.find_case_in(c, case_id)
    return row["status"], row["outcome"]


def test_nothing_missing_is_done_at_once_without_a_task(packs) -> None:
    case_id = _started("reference")
    step = engine.state(case_id)["steps"]["missing"]
    assert step["state"] == "done" and step["result"]["requested"] is False and step["result"]["missing"] == []
    assert _task(case_id) is None


def test_the_missing_facts_open_a_task_that_their_arrival_withdraws(packs) -> None:
    case_id = _started("missing_facts")
    task = _task(case_id)
    assert task is not None and task.status == tasks.OPEN and task.case_id == case_id
    assert sorted({m["fact"] for m in task.detail["missing"]}) == ["accounting_method", "protection_class_in_place"]
    assert task.due_at == pytest.approx(time.time() + DAYS * missing_info.DAY_S, abs=600)
    assert engine.state(case_id)["steps"]["missing"]["state"] == "running"
    field_check.reopen(case_id, "check", note="the client sent the missing facts", actor=ANNA)
    _turn(case_id)
    units = {u["level"]: u for u in assessed_units.units(case_id, "check")}
    for level, fact, value in (("holder", "accounting_method", "gross_profit"), ("site", "protection_class_in_place", 3)):
        unit = assessed_units.unit(case_id, "check", units[level]["unit_id"])
        assessed_units.save(case_id, "check", "property", unit["unit_id"], facts={**unit["facts"], fact: value},
                            actor=ANNA, expected_state=unit["state"], note="from the client")
    field_check.freeze(case_id, "check", cover_start="2027-01-01", expected_state=None, actor=ANNA)
    _turn(case_id)
    _turn(case_id)
    step = engine.state(case_id)["steps"]["missing"]
    assert step["state"] == "done" and step["result"]["requested"] is True and step["result"]["missing"] == []
    assert _task(case_id).status == tasks.WITHDRAWN


def test_the_deadline_passing_closes_the_case_with_the_packs_outcome(packs) -> None:
    case_id = _started("missing_facts")
    _turn(case_id, at=_task(case_id).due_at + 1)
    assert _task(case_id).status == tasks.EXPIRED
    assert _closed(case_id) == (cases.CLOSED, "expired")


def test_a_person_says_with_a_reason_that_the_facts_will_not_come(packs) -> None:
    case_id = _started("missing_facts")
    with pytest.raises(missing_info.MissingInfoError, match="needs a reason"):
        missing_info.will_not_come(case_id, "missing", ANNA, note=" ")
    missing_info.will_not_come(case_id, "missing", ANNA, note="the client withdrew the request")
    _turn(case_id)
    assert _task(case_id).status == tasks.DECIDED
    assert _closed(case_id) == (cases.CLOSED, "expired")
    with pytest.raises(missing_info.MissingInfoError, match="does not wait"):
        missing_info.will_not_come(case_id, "missing", ANNA, note="again")
