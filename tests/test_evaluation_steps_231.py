"""231 (stage D, D-d3): a frozen input's rules evaluated, and its premium computed, as steps of a case.

Every reference case of the invented product set runs as a case: an invented step offers the case's facts unit by
unit (with the modules it asks for on the policyholder), a person freezes them in the field check with the day cover
starts, and the evaluation and the premium steps follow. Their verdict, missing facts, total and blockers are the
ones the set expects (T14), each rule's outcome and the premium are traced and replay the same, and a premium a blocker
stops is kept with its blockers. A later turn makes nothing new; a new freeze makes a new evaluation and premium. An
input that does not say its modules is no better than unknown and is not priced. Invented data; no paid call.
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import capabilities, evaluation_steps, field_check, process_runtime, product_sets, rating, rule_evaluation
from jav.core import cfg, store, trace
from jav.core.process import engine, kinds

ANNA = "Minta Anna"
SRC = {"item": "invented-document", "page": 1}
SET = product_sets.load()
CASES = {case.id: case for case in SET.cases}


class _Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[dict]


def _claims(case: product_sets.Case, *, modules: bool = True) -> list[dict]:
    """The case's facts as claims, unit by unit (a parent before its children), keyed by the case's own unit ids."""
    out = []
    for unit in case.input["units"]:
        facts = dict(unit["facts"])
        if modules and unit.get("parent_id") is None:
            facts["requested_modules"] = list(case.modules)
        out += [{"unit": unit["unit_id"], "level": unit["level"], "parent": unit.get("parent_id"), "fact": name,
                 "value": value, "source": SRC, "reading": "invented_reading@1"} for name, value in facts.items()]
    return out


def _pack(pid: str, claims: list[dict]) -> dict:
    return {"meta": {"name": f"process:{pid}", "version": "1.0.0"}, "id": pid, "title": "Invented evaluation",
            "intake": [{"on": "manual", "starts": "manual"}],
            "resources": {"product": "inv_business_property", "tariff": "inv_business_property_tariff"},
            "needs_at_start": ["product", "tariff"],
            "steps": [{"id": "read", "uses": "invented_offer@1", "params": {"claims": claims}},
                      {"id": "check", "uses": "field_check@1", "params": {"catalogue": "property", "product": "@product"},
                       "after": ["read"]},
                      {"id": "evaluate", "uses": "rule_evaluation@1", "params": {"from_step": "check"}, "after": ["check"]},
                      {"id": "rate", "uses": "rating@1", "params": {"from_step": "evaluate", "tariff": "@tariff"},
                       "after": ["evaluate"]}],
            "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}}


@pytest.fixture()
def packs(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    capabilities.register(capabilities.Capability(
        name="invented_offer", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Offer,
        run=lambda ctx, p: kinds.Done({"claims": p.claims}), state="step", output=capabilities.Result))
    data = {f"process:invented_eval_{cid}": _pack(f"invented_eval_{cid}", _claims(case)) for cid, case in CASES.items()}
    data["process:invented_eval_unsaid"] = _pack("invented_eval_unsaid", _claims(CASES["reference"], modules=False))
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data[name] if name in data else real(name))
    with store.use_store(tmp_path / "evaluation.sqlite"):
        product_sets.install(SET, maker=ANNA, approver="Minta Bela")
        yield


def _frozen_case(pid: str, cover_start: str = "2027-01-01") -> str:
    case_id = process_runtime.start_case(pid, {}, name="Invented evaluation", actor=ANNA)
    engine.turn(case_id)
    field_check.freeze(case_id, "check", cover_start=cover_start, expected_state=None, actor=ANNA)
    engine.turn(case_id, now=time.time() + 10)
    return case_id


def _ours(case_id: str) -> dict[str, str]:
    """The case's own unit ids by the ids the field check gave them."""
    with store.connect() as c:
        return {r["unit_id"]: r["unit_key"] for r in c.execute(
            "SELECT unit_key, unit_id FROM field_check_units WHERE case_id=? AND step_id='check'", (case_id,))}


def _named(text: str, ours: dict[str, str]) -> str:
    for given, own in ours.items():
        text = text.replace(given, own)
    return text


@pytest.mark.parametrize("cid", sorted(CASES))
def test_each_reference_case_runs_to_the_verdict_and_premium_it_expects(packs, cid) -> None:
    case = CASES[cid]
    case_id = _frozen_case(f"invented_eval_{cid}", case.input["cover_start"])
    ours, want = _ours(case_id), case.expected
    steps = engine.state(case_id)["steps"]
    evaluated = steps["evaluate"]["result"]
    assert steps["evaluate"]["state"] == "done" and evaluated["verdict"] == want.verdict
    assert tuple((ours[m["unit_id"]], m["fact"]) for m in evaluated["missing"]) == want.missing
    kept = evaluation_steps.record(case_id, "rate", 1)
    assert [_named(b, ours) for b in kept["content"]["blockers"]] == list(want.blockers)
    if want.blockers:
        assert steps["rate"]["state"] == "failed" and steps["rate"]["note"].startswith("blocked: ")
        return
    assert steps["rate"]["state"] == "done"
    assert steps["rate"]["result"]["total"]["amount"] == want.total == kept["content"]["total"]["amount"]
    assert sorted((ours[x["unit_id"]], x["module"], x["amount"]["amount"]) for x in kept["content"]["lines"]) == sorted(want.lines)
    assert kept["content"]["policy_minimum_applied"] is want.policy_minimum_applied
    rows = trace.rows(case_id=case_id)
    outcomes = [r for r in rows if r["point"] == rule_evaluation.POINT]
    assert outcomes and all(trace.replay(r) == r["outcome"] for r in outcomes)
    [premium] = [r for r in rows if r["point"] == rating.POINT]
    assert trace.replay(premium) == premium["outcome"]


def test_a_later_turn_makes_nothing_new_and_a_new_freeze_a_new_evaluation(packs) -> None:
    case_id = _frozen_case("invented_eval_reference")
    engine.turn(case_id, now=time.time() + 20)
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM evaluation_records WHERE case_id=?", (case_id,)).fetchone()[0] == 2
    field_check.reopen(case_id, "check", note="a fact is wrong", actor=ANNA)
    engine.turn(case_id, now=time.time() + 30)
    field_check.freeze(case_id, "check", cover_start="2027-01-01", expected_state=None, actor=ANNA)
    engine.turn(case_id, now=time.time() + 40)
    steps = engine.state(case_id)["steps"]
    assert (steps["evaluate"]["result"]["version"], steps["evaluate"]["result"]["input_version"]) == (2, 2)
    assert steps["rate"]["state"] == "done" and steps["rate"]["result"]["version"] == 2
    assert evaluation_steps.record(case_id, "rate", 2)["input_version"] == 2
    assert steps["rate"]["result"]["total"]["amount"] == CASES["reference"].expected.total


def test_an_input_that_does_not_say_its_modules_is_unknown_and_not_priced(packs) -> None:
    case_id = _frozen_case("invented_eval_unsaid")
    steps = engine.state(case_id)["steps"]
    evaluated = steps["evaluate"]["result"]
    assert evaluated["verdict"] == rule_evaluation.UNKNOWN and evaluated["modules"] == []
    assert evaluated["missing"][0]["fact"] == "requested_modules"
    assert steps["rate"]["state"] == "failed" and "requested_modules" in steps["rate"]["note"]
