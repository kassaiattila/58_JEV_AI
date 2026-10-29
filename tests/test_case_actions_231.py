"""231 (stage D, D-f2): a person's actions with values, through the case step's action endpoint.

The field check's freeze, reopen and unit edits and the decision take values, which their form checks; each carries
the state of the page it was made on, and an older one is refused (409), as values that do not fit are (422). The page
marks these actions as taking values, so its generic buttons leave them to the step's own element. The case's path is
the decision test's invented one; no paid call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import assessed_units, case_decisions, case_views, field_check, process_runtime
from jav.core import decisions
from jav.service import api
from tests.test_case_decisions_231 import ANNA, BELA, _turn, packs  # noqa: F401 - the fixture is used by name


@pytest.fixture()
def client(packs, tmp_path):  # noqa: F811
    with TestClient(api.create_app(store_path=tmp_path / "decisions.sqlite"), base_url="http://127.0.0.1:8930",
                    headers={"X-Actor": ANNA}) as c:
        yield c


def _started() -> str:
    case_id = process_runtime.start_case("invented_decide_reference", {}, name="Invented actions", actor=ANNA)
    _turn(case_id)
    return case_id


def _actions(case_id: str, step: str) -> dict[str, dict]:
    return {a["name"]: a for a in case_views.view(case_id)["steps"][step]["actions"]}


def test_the_field_check_is_frozen_through_its_action_and_a_stale_page_is_refused(packs, client) -> None:  # noqa: F811
    case_id = _started()
    forms = {n: a.get("form") for n, a in _actions(case_id, "check").items()}
    state = field_check.view(case_id, "check")["state"]
    # 261 (B1g): the freeze's form is described for the shared form (the day a person gives, its first value, the
    # units' state the page shows); the others are the field review's own
    assert forms.pop("freeze") == {"fields": [{"name": "cover_start", "label": "Cover starts", "kind": "date", "required": True}],
                                   "values": {"cover_start": None, "expected_state": state}, "blocked": None}
    assert forms == {"unit_add": True, "unit_save": True, "unit_remove": True, "keep_value": True}
    url = f"/api/cases/{case_id}/steps/check/actions/"
    holder = next(u for u in assessed_units.units(case_id, "check") if u["level"] == "holder")
    saved = client.post(url + "unit_save", json={"values": {"unit_id": holder["unit_id"], "facts": {**holder["facts"],
                                                                                                   "activity_code": "4711"},
                                                          "expected_state": holder["state"], "note": "the register"}})
    assert saved.status_code == 200
    stale = client.post(url + "freeze", json={"values": {"cover_start": "2027-01-01", "expected_state": state}})
    assert stale.status_code == 409  # the units changed since the page showed them
    assert client.post(url + "freeze", json={"values": {"cover_start": "a day", "expected_state": 0}}).status_code == 422
    assert client.post(url + "freeze", json={"note": "no values"}).status_code == 422
    fresh = field_check.view(case_id, "check")["state"]
    assert client.post(url + "freeze", json={"values": {"cover_start": "2027-01-01", "expected_state": fresh}}).status_code == 200
    _turn(case_id)
    assert set(_actions(case_id, "check")) == {"reopen"}
    assert client.post(url + "reopen", json={}).status_code == 422  # a reason is needed
    assert client.post(url + "reopen", json={"note": "a fact is wrong"}).status_code == 200


def test_a_decision_is_made_through_its_action_with_the_page_it_was_made_on(packs, client) -> None:  # noqa: F811
    case_id = _started()
    field_check.freeze(case_id, "check", cover_start="2027-01-01", expected_state=None, actor=ANNA)
    _turn(case_id)
    assert _actions(case_id, "risk") == {"decide": {"name": "decide", "label": "Decide", "form": True}}
    basis = case_decisions.view(case_id, "risk")["basis"]
    url = f"/api/cases/{case_id}/steps/risk/actions/decide"
    old = client.post(url, json={"values": {"choice": "accept", "expected_basis": {k: v - 1 for k, v in basis.items()}}})
    assert old.status_code == 409
    assert client.post(url, json={"values": {"choice": "maybe", "expected_basis": basis}}).status_code == 422
    with pytest.raises(decisions.RevisionConflict):
        case_views.act(case_id, "risk", "decide", ANNA, values={"choice": "accept", "expected_basis": {}})
    assert client.post(url, json={"values": {"choice": "accept", "expected_basis": basis}}).status_code == 200
    _turn(case_id)
    assert case_views.view(case_id)["steps"]["risk"]["state"] == "done"
    assert BELA  # the premium's second person is the decision test's
