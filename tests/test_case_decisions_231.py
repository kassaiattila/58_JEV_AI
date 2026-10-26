"""231 (stage D, D-d4): a person's decisions on a case's risk, then its premium, with another person above a limit.

The reference cases of the invented product set run as cases: the facts are offered and frozen, the rules evaluated,
then a person decides on the risk; the premium is computed and a person decides on it. Above the invented limit of the
rule file (a premium above 300 000 HUF), the premium decision is refused to the person who decided on the risk and
made by another, and whether a second person was needed is traced and replays the same; below it, one person decides
both. A refused risk is not accepted, a decline ends the case and needs a reason, a page showing an older result is
refused, and a decision whose result changed goes out of date and is made again; a returned one is shown as returned.
Invented data; no paid call.
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import (capabilities, case_decisions, case_views, field_check, package_release, process_runtime, product_sets,
                     rating)
from jav.core import cfg, decisions, store, trace
from jav.core.process import cases, engine, kinds
from tests.test_evaluation_steps_231 import CASES, _claims

ANNA, BELA = "Minta Anna", "Minta Bela"
DECLINE = {"title": "Decline", "closes": "declined"}
RISK = {"about": "evaluate", "choices": {"accept": {"title": "Accept the risk", "allowed_when": {"verdict": ["allow", "refer"]}},
                                         "decline": DECLINE}}
PREMIUM = {"about": "rate", "choices": {"accept": {"title": "Accept the premium"}, "decline": DECLINE},
           "other_than": "risk", "limit": "inv_premium_second_person"}


class _Offer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: list[dict]


def _pack(pid: str, claims: list[dict]) -> dict:
    return {"meta": {"name": f"process:{pid}", "version": "1.0.0"}, "id": pid, "title": "Invented decisions",
            "intake": [{"on": "manual", "starts": "manual"}],
            "resources": {"product": "inv_business_property", "tariff": "inv_business_property_tariff"},
            "needs_at_start": ["product", "tariff"],
            "steps": [{"id": "read", "uses": "invented_offer@1", "params": {"claims": claims}},
                      {"id": "check", "uses": "field_check@1", "params": {"catalogue": "property", "product": "@product"},
                       "after": ["read"]},
                      {"id": "evaluate", "uses": "rule_evaluation@1", "params": {"from_step": "check"}, "after": ["check"]},
                      {"id": "risk", "uses": "decision@1", "params": RISK, "after": ["evaluate"]},
                      {"id": "rate", "uses": "rating@1", "params": {"from_step": "evaluate", "tariff": "@tariff"},
                       "after": ["risk"]},
                      {"id": "premium", "uses": "decision@1", "params": PREMIUM, "after": ["rate"]}],
            "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}}


@pytest.fixture()
def packs(monkeypatch, tmp_path):
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    capabilities.register(capabilities.Capability(
        name="invented_offer", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Offer,
        run=lambda ctx, p: kinds.Done({"claims": p.claims}), state="step", output=capabilities.Result))
    data = {f"process:invented_decide_{cid}": _pack(f"invented_decide_{cid}", _claims(case)) for cid, case in CASES.items()}
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data[name] if name in data else real(name))
    with store.use_store(tmp_path / "decisions.sqlite"):
        product_sets.install(product_sets.load(), maker=ANNA, approver=BELA)
        yield


_CLOCK = [time.time()]


def _turn(case_id: str) -> None:
    _CLOCK[0] += 10
    engine.turn(case_id, now=_CLOCK[0])


def _started(cid: str) -> str:
    case_id = process_runtime.start_case(f"invented_decide_{cid}", {}, name="Invented decisions", actor=ANNA)
    _turn(case_id)
    field_check.freeze(case_id, "check", cover_start="2027-01-01", expected_state=None, actor=ANNA)
    _turn(case_id)
    return case_id


def _decide(case_id: str, step: str, choice: str, actor: str, note: str | None = None) -> dict:
    out = case_decisions.decide(case_id, step, choice=choice, note=note,
                                expected_basis=case_decisions.view(case_id, step)["basis"], actor=actor)
    _turn(case_id)
    return out


def _steps(case_id: str) -> dict:
    return engine.state(case_id)["steps"]


def test_risk_then_premium_with_another_person_above_the_limit(packs) -> None:
    case_id = _started("reference")
    risk = case_decisions.view(case_id, "risk")
    assert risk["result"]["verdict"] == "allow" and risk["second_person"] is None
    assert {c["code"]: c["allowed"] for c in risk["choices"]} == {"accept": True, "decline": True}
    assert _steps(case_id)["rate"]["state"] != "done"  # the premium waits for the risk decision
    _decide(case_id, "risk", "accept", ANNA)
    assert _steps(case_id)["risk"]["result"]["choice"] == "accept"
    premium = case_decisions.view(case_id, "premium")
    assert premium["result"]["total"]["amount"] == "487000"
    assert premium["second_person"]["needed"] is True and premium["second_person"]["earlier_by"] == ANNA
    with pytest.raises(case_decisions.SecondPersonNeeded):
        case_decisions.decide(case_id, "premium", choice="accept", note=None, expected_basis=premium["basis"], actor=ANNA)
    _decide(case_id, "premium", "accept", BELA)
    steps = _steps(case_id)
    assert steps["premium"]["state"] == "done" and steps["premium"]["result"]["choice"] == "accept"
    assert package_release.approval_state(case_id, step="premium")["active"]["approved_by"] == BELA
    [row] = [r for r in trace.rows(case_id=case_id) if r["point"] == case_decisions.POINT]
    assert row["outcome"] == {"needed": True} and trace.replay(row) == row["outcome"]


def test_below_the_limit_one_person_decides_both(packs) -> None:
    case_id = _started("referred")
    assert case_decisions.view(case_id, "risk")["result"]["verdict"] == "refer"
    _decide(case_id, "risk", "accept", ANNA)
    premium = case_decisions.view(case_id, "premium")
    assert premium["second_person"]["needed"] is False
    _decide(case_id, "premium", "accept", ANNA)
    assert _steps(case_id)["premium"]["state"] == "done"
    [row] = [r for r in trace.rows(case_id=case_id) if r["point"] == case_decisions.POINT]
    assert row["outcome"] == {"needed": False} and trace.replay(row) == row["outcome"]


def test_a_refused_risk_is_not_accepted_and_a_decline_ends_the_case_with_a_reason(packs) -> None:
    case_id = _started("excluded_activity")
    view = case_decisions.view(case_id, "risk")
    assert view["result"]["verdict"] == "refuse"
    assert {c["code"]: c["allowed"] for c in view["choices"]} == {"accept": False, "decline": True}
    with pytest.raises(case_decisions.DecisionError, match="does not allow"):
        case_decisions.decide(case_id, "risk", choice="accept", note=None, expected_basis=view["basis"], actor=ANNA)
    with pytest.raises(case_decisions.DecisionError, match="needs a reason"):
        case_decisions.decide(case_id, "risk", choice="decline", note=" ", expected_basis=view["basis"], actor=ANNA)
    with pytest.raises(case_decisions.DecisionError, match="no choice"):
        case_decisions.decide(case_id, "risk", choice="maybe", note=None, expected_basis=view["basis"], actor=ANNA)
    _decide(case_id, "risk", "decline", ANNA, note="an excluded activity")
    with store.connect() as c:
        case = cases.find_case_in(c, case_id)
    assert (case["status"], case["outcome"]) == (cases.CLOSED, "declined")
    with pytest.raises(case_decisions.DecisionError, match="nothing to decide"):
        case_decisions.decide(case_id, "premium", choice="accept", note=None, expected_basis=None, actor=BELA)


def test_a_stale_page_is_refused_a_changed_result_puts_the_decision_out_of_date_and_a_return_shows(packs) -> None:
    case_id = _started("reference")
    view = case_decisions.view(case_id, "risk")
    stale = {k: v - 1 for k, v in view["basis"].items()}
    with pytest.raises(decisions.RevisionConflict):
        case_decisions.decide(case_id, "risk", choice="accept", note=None, expected_basis=stale, actor=ANNA)
    _decide(case_id, "risk", "accept", ANNA)
    assert package_release.approval_state(case_id, step="risk")["state"] == "approved"
    field_check.reopen(case_id, "check", note="a fact is wrong", actor=ANNA)
    _turn(case_id)
    field_check.freeze(case_id, "check", cover_start="2027-01-01", expected_state=None, actor=ANNA)
    _turn(case_id)
    _turn(case_id)
    state = package_release.approval_state(case_id, step="risk")
    assert state["state"] == "outdated" and state["outdated"]
    _decide(case_id, "risk", "accept", ANNA)
    assert _steps(case_id)["risk"]["result"]["version"] > 1
    assert rating.POINT in {r["point"] for r in trace.rows(case_id=case_id)}
    case_views.return_step(case_id, "premium", "the premium looks too high", BELA)
    assert package_release.approval_state(case_id, step="premium")["state"] == "returned"
