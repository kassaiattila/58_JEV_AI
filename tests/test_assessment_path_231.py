"""231 (stage D, D-d7): the whole path of an assessment case, from a pack of shared capabilities only (test only).

An invented reading offers a policyholder's facts, with two facts the rules need left out; the company register and
the sanctions list are asked, independently; a person freezes the facts in the field check; the rules find facts
missing and a task with a deadline opens; the person enters them and freezes again, and the rules decide; a person
accepts the risk; the premium is computed from the tariff the case kept; and the premium is accepted - by another
person when it is above the invented limit. The case is done; every decision on the way is in the decision trace and
replays the same. No step names insurance: the product, its rules, its tariff, the registers and the limit are data.
Invented data; no paid call.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import (assessed_units, capabilities, case_decisions, field_check, missing_info, process_runtime,
                     product_sets)
from jav.core import cfg, connectors, store, trace
from jav.core.process import cases, engine, kinds, tasks
from jav.devtools import invented_services
from tests.test_evaluation_steps_231 import CASES, _claims

ANNA, BELA = "Minta Anna", "Minta Bela"
PID = "invented_assessment"
REF = CASES["reference"]
LEFT_OUT = ("accounting_method", "protection_class_in_place")
SRC = {"item": "invented-document", "page": 1}


def _read() -> list[dict]:
    """The reference case's facts with two left out, and the holder's name and tax number (the register knows them)."""
    claims = [c for c in _claims(REF) if c["fact"] not in LEFT_OUT]
    holder = next(u["unit_id"] for u in REF.input["units"] if u.get("parent_id") is None)
    claims += [{"unit": holder, "level": "holder", "parent": None, "fact": fact, "value": value, "source": SRC,
                "reading": "invented_reading@1"}
               for fact, value in (("company_name", "Minta Kereskedő Kft."), ("tax_number", "12345676-2-41"))]
    return claims


DECLINE = {"title": "Decline", "closes": "declined"}
STEPS = [
    {"id": "read", "uses": "invented_offer@1", "params": {"claims": _read()}},
    {"id": "company", "uses": "lookup@1", "after": ["read"],
     "params": {"connector": "invented_company_register", "from_step": "read", "asks": {"tax_number": "tax_number"},
                "answers": {"company.status": "company_status", "company.activity_code": "activity_code"}}},
    {"id": "sanctions", "uses": "lookup@1", "after": ["read"],
     "params": {"connector": "invented_sanctions_list", "from_step": "read", "asks": {"name": "company_name"},
                "asks_if_known": {"tax_number": "tax_number"}, "answers": {"listed": "sanctions_listed"}}},
    {"id": "check", "uses": "field_check@1", "params": {"catalogue": "property", "product": "@product"},
     "after": ["read", "company", "sanctions"]},
    {"id": "evaluate", "uses": "rule_evaluation@1", "params": {"from_step": "check"}, "after": ["check"]},
    {"id": "missing", "uses": "missing_info@1", "params": {"from_step": "evaluate", "days": 14, "closes": "expired"},
     "after": ["evaluate"]},
    {"id": "risk", "uses": "decision@1", "after": ["missing"],
     "params": {"about": "evaluate", "choices": {"accept": {"title": "Accept the risk",
                                                            "allowed_when": {"verdict": ["allow", "refer"]}},
                                                 "decline": DECLINE}}},
    {"id": "rate", "uses": "rating@1", "params": {"from_step": "evaluate", "tariff": "@tariff"}, "after": ["risk"]},
    {"id": "premium", "uses": "decision@1", "after": ["rate"],
     "params": {"about": "rate", "choices": {"accept": {"title": "Accept the premium"}, "decline": DECLINE},
                "other_than": "risk", "limit": "inv_premium_second_person"}},
]


class _Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[dict]


@pytest.fixture()
def pack(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    capabilities.register(capabilities.Capability(
        name="invented_offer", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Offer,
        run=lambda ctx, p: kinds.Done({"claims": p.claims}), state="step", output=capabilities.Result))
    data = {f"process:{PID}": {
        "meta": {"name": f"process:{PID}", "version": "1.0.0"}, "id": PID, "title": "Invented assessment",
        "intake": [{"on": "manual", "starts": "manual"}],
        "resources": {"product": "inv_business_property", "tariff": "inv_business_property_tariff"},
        "needs_at_start": ["product", "tariff"], "steps": STEPS,
        "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}}}
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data[name] if name in data else real(name))
    with store.use_store(tmp_path / "path.sqlite"), connectors.use_transport(invented_services.transport()):
        product_sets.install(product_sets.load(), maker=ANNA, approver=BELA)
        yield


_CLOCK = [time.time()]


def _turn(case_id: str) -> None:
    _CLOCK[0] = max(_CLOCK[0], time.time()) + 10  # never behind the real time the steps' timers are set from
    engine.turn(case_id, now=_CLOCK[0])


def _state(case_id: str, step: str) -> str:
    return engine.state(case_id)["steps"][step]["state"]


def _decide(case_id: str, step: str, actor: str) -> None:
    view = case_decisions.view(case_id, step)
    case_decisions.decide(case_id, step, choice="accept", note=None, expected_basis=view["basis"], actor=actor)
    _turn(case_id)


def test_an_assessment_case_runs_from_the_reading_to_the_accepted_premium(pack) -> None:
    case_id = process_runtime.start_case(PID, {}, name="Invented assessment", actor=ANNA)
    _turn(case_id)
    assert [_state(case_id, s) for s in ("read", "company", "sanctions")] == ["done"] * 3
    holder = next(u for u in field_check.view(case_id, "check")["units"] if u["level"] == "holder")
    assert (holder["facts"]["company_status"], holder["facts"]["sanctions_listed"]) == ("active", False)

    field_check.freeze(case_id, "check", cover_start="2027-01-01", expected_state=None, actor=ANNA)
    _turn(case_id)
    evaluated = engine.state(case_id)["steps"]["evaluate"]["result"]
    assert evaluated["verdict"] == "unknown" and {m["fact"] for m in evaluated["missing"]} == set(LEFT_OUT)
    task = tasks.get(tasks.task_id(missing_info.TASK, f"{case_id}:missing"))
    assert task.status == tasks.OPEN and _state(case_id, "risk") != "running"

    field_check.reopen(case_id, "check", note="the client sent the missing facts", actor=ANNA)
    _turn(case_id)
    with store.connect() as c:  # each unit by the key the reading gave it
        ours = {r["unit_key"]: r["unit_id"] for r in c.execute(
            "SELECT unit_key, unit_id FROM field_check_units WHERE case_id=? AND step_id='check'", (case_id,))}
    for given in REF.input["units"]:
        if add := {f: v for f, v in given["facts"].items() if f in LEFT_OUT}:
            unit = assessed_units.unit(case_id, "check", ours[given["unit_id"]])
            assessed_units.save(case_id, "check", "property", unit["unit_id"], facts={**unit["facts"], **add}, actor=ANNA,
                                expected_state=unit["state"], note="from the client")
    field_check.freeze(case_id, "check", cover_start="2027-01-01", expected_state=None, actor=ANNA)
    _turn(case_id)
    _turn(case_id)
    assert engine.state(case_id)["steps"]["evaluate"]["result"]["verdict"] == REF.expected.verdict
    assert _state(case_id, "missing") == "done" and tasks.get(task.task_id).status == tasks.WITHDRAWN

    _decide(case_id, "risk", ANNA)
    total = engine.state(case_id)["steps"]["rate"]["result"]["total"]
    assert total == {"amount": REF.expected.total, "currency": "HUF"}
    premium = case_decisions.view(case_id, "premium")
    needed = Decimal(total["amount"]) > Decimal("300000")
    assert premium["second_person"]["needed"] is needed
    _decide(case_id, "premium", BELA if needed else ANNA)

    with store.connect() as c:
        row = cases.find_case_in(c, case_id)
    assert (row["status"], row["outcome"]) == (cases.CLOSED, "done")
    rows = trace.rows(case_id=case_id)
    points = {r["point"] for r in rows}
    assert {"claims.offered", "rules.outcome", "rating.premium", "decision.second_person"} <= points
    assert all(trace.replay(r) == r["outcome"] for r in rows)
