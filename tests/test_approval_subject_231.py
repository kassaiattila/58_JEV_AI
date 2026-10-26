"""231 (stage D0, D0-d; the reassessment of 2026-10-26, F03, P14): an approval names what it approved and what that was
built on.

An approved version records its basis, the result versions of the steps its step builds on. When one of them changes
(a match redone with a newer price list), the step's approval is out of date: the step reopens it by itself, with that
reason, and waits for a person to approve again; the other step's approval in the same case stays. Until D0-d the step
went on at once with its old approval. A person may also return a step's result instead of approving it, with a reason;
the step still waits, and the return shows until the next approval. The approval's state of a step - missing, approved,
out of date or returned - is one view. The invented twin pack of the quote path; no paid call.
"""

from __future__ import annotations

import json

import pytest

from jav.app import package_release, process_runtime
from jav.core import cfg, identity, store
from jav.core.process import cases, engine, tasks
from jav.domains.quotes import price_lists, quote_draft
from tests.test_quote_path_231 import ACTOR, FIXTURE, _drain, golden  # noqa: F401 - the fixture
from tests.test_quote_twin_231 import PACK, _approve, _move, _pack, _second_list, _start, _task

PERSON = identity.who(ACTOR)


@pytest.fixture()
def twin(golden, tmp_path, monkeypatch):  # noqa: F811
    cases_, _seen = golden
    data = _pack(price_lists.chosen().price_list, _second_list(tmp_path))
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data if name == f"process:{PACK}" else real(name))
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case_id = _start(next(c for c in cases_ if "letter" in record[c.id]))
    _move(case_id)
    return case_id


def _state(case_id: str, step: str) -> dict:
    return package_release.approval_state(case_id, step=step)


def test_an_approval_records_what_its_step_built_on(twin) -> None:
    assert _state(twin, "compose_a")["state"] == "missing"
    _approve(twin, "compose_a")
    active = _state(twin, "compose_a")["active"]
    assert active["basis"] == process_runtime.basis_of(twin, "compose_a") == {"request": 1, "match_a": 1}
    assert _state(twin, "compose_a")["state"] == "approved" and process_runtime.outdated(twin, "compose_a") is None


def test_a_changed_earlier_step_puts_the_approval_out_of_date_and_a_person_approves_again(twin) -> None:
    _approve(twin, "compose_a")
    _approve(twin, "compose_b")
    engine.turn(twin, wake=True)
    cases.reopen(twin, "match_a", PERSON, reason="match it again")  # the proposal is redone: a new result version
    for _ in range(6):
        engine.turn(twin, wake=True)
        _drain()
    state = _state(twin, "compose_a")
    assert state["state"] == "outdated" and state["outdated"] == "an earlier step it builds on changed: match_a"
    steps = engine.state(twin)["steps"]
    assert steps["compose_a"]["state"] == "running"  # it waits for the approval again, instead of going on with the old
    assert _task(twin, "compose_a") == "open"
    assert _state(twin, "compose_b")["state"] == "approved"  # the other step's approval stays
    assert _approve(twin, "compose_a") == 3
    assert _state(twin, "compose_a")["active"]["basis"] == {"request": 1, "match_a": 2}
    engine.turn(twin, wake=True)
    assert engine.state(twin)["steps"]["compose_a"]["state"] == "done"


def test_a_person_returns_a_result_with_a_reason_and_the_step_waits_on(twin) -> None:
    with store.connect() as c:
        store.begin_immediate(c)
        with pytest.raises(ValueError, match="returning needs a reason"):
            package_release.reject_own(c, twin, step="compose_b", reason=" ", actor=ACTOR)
        package_release.reject_own(c, twin, step="compose_b", reason="The customer asked for fewer lines", actor=ACTOR)
    state = _state(twin, "compose_b")
    assert state["state"] == "returned" and state["returned"]["reason"] == "The customer asked for fewer lines"
    assert _task(twin, "compose_b") == "open" and _state(twin, "compose_a")["state"] == "missing"
    _approve(twin, "compose_b")
    assert _state(twin, "compose_b")["state"] == "approved" and _state(twin, "compose_b")["returned"] is None
    with store.connect() as c:
        store.begin_immediate(c)
        with pytest.raises(package_release.NothingToReturn):
            package_release.reject_own(c, twin, step="compose_b", reason="too late", actor=ACTOR)
    assert tasks.get(tasks.task_id("own_approval", f"{twin}:compose_b")).status == "decided"
    assert quote_draft.view(twin, step="compose_b")["approval"]["active"]["version"] == 1


def test_the_service_shows_the_approval_s_state_and_takes_a_return(twin) -> None:
    from fastapi.testclient import TestClient

    from jav.service.api import create_app

    human = {"X-Actor": "anna"}
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        assert c.get(f"/api/cases/{twin}/steps/compose_a/approval").json()["state"] == "missing"
        returned = c.post(f"/api/cases/{twin}/steps/compose_a/approval/return", headers=human,
                          json={"reason": "Two lines are missing"})
        assert returned.status_code == 200 and returned.json()["returned"]["reason"] == "Two lines are missing"
        assert c.post(f"/api/cases/{twin}/steps/match_a/approval/return", headers=human,
                      json={"reason": "no"}).status_code == 422  # a step that approves nothing
        page = c.get(f"/api/cases/{twin}").json()
        approval = next(e for tab in page["tabs"] for e in tab["elements"] if e["type"] == "approval" and e["step"] == "compose_a")
        assert approval["data"]["quote"]["draft"]["approval_state"]["state"] == "returned"  # the quote's own view says it
