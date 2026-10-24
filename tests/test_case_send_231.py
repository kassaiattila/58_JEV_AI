"""231 (plan stage A, A7e; DECISIONS 231): the IT quote's case after its letter, on the local service.

Pack 1.1.0: once the letter is accepted, the case's next step is the send, which a person starts from the Sent tab; the
letter goes into the output folder, and the case waits for the reply on the Follow-up tab, where the person records it.
The person's actions are the steps' own (a failed step's retry, whether a message arrived, the reply). The case list
shows where each case stands, the handovers to check list the failed or unknown ones, and the "Waiting for me" list
opens the case's page for its tasks. The History tab shows the case's events and what its steps spent. Invented quote
requests with stand-in models; no paid call.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from jav.app import app_settings, capabilities, case_views, sending
from jav.core import calls, store
from jav.core.process import engine
from jav.service.api import create_app
from tests import test_document_result_174 as rows
from tests.test_quote_case_231 import _drive, out  # noqa: F401 - the fixture
from tests.test_quote_path_231 import golden  # noqa: F401 - the fixture

HUMAN = {"X-Actor": "anna"}


@pytest.fixture()
def service(golden, out):  # noqa: F811 - the shared fixtures
    cases, _seen = golden
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        yield c, cases[0]


def _start(c: TestClient, case) -> str:
    made = c.post("/api/cases", headers=HUMAN, json={"pack": "it_quote", "name": f"Quote {case.id}",
                                                      "record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}})
    assert made.status_code == 201, made.text
    case_id = made.json()["case_id"]
    _drive(case_id, send=False)  # up to the accepted letter: the send waits for a person
    return case_id


def _rows(c: TestClient, name: str, **scope: str) -> list[dict]:
    answer = c.post(f"/api/datasets/{name}/query", headers=HUMAN, json={"scope": scope})
    assert answer.status_code == 200, answer.text
    return answer.json()["rows"]


def _element(page: dict, kind: str) -> dict:
    return next(e for tab in page["tabs"] for e in tab["elements"] if e["type"] == kind)["data"]


def test_a_person_sends_the_accepted_letter_and_records_the_reply(service, out) -> None:  # noqa: F811
    c, case = service
    case_id = _start(c, case)
    page = c.get(f"/api/cases/{case_id}").json()
    assert page["next"]["code"] == "case_send" and page["next"]["tab"] == "sent"
    assert page["steps"]["send"]["awaiting_start"] and page["steps"]["send"]["actions"] == []
    sent = _element(page, "handover_view")
    assert (sent["mode"], sent["output_folder"], sent["attempts"]) == ("output_folder", str(out), [])
    [listed] = _rows(c, "cases")
    assert (listed["name"], listed["step"], listed["waits_for"], listed["status"]) == (f"Quote {case.id}", "Send",
                                                                                      "person_start", "open")
    waiting = [r for r in _rows(c, "waiting", actor="anna") if r["kind"] == "step_start"]
    assert [(r["what"], r["workpackage_name"]) for r in waiting] == [("Send", f"Quote {case.id}")]

    assert c.post(f"/api/cases/{case_id}/steps/send/start", headers=HUMAN, json={}).status_code == 200
    engine.turn(case_id, wake=True)
    page = c.get(f"/api/cases/{case_id}").json()
    [attempt] = _element(page, "handover_view")["attempts"]
    assert attempt["status"] == "acknowledged" and attempt["receipt"]["path"].startswith(str(out))
    assert page["steps"]["send"]["state"] == "done" and page["next"]["code"] == "case_reply_wait"
    assert page["next"]["tab"] == "follow_up"
    wait = _element(page, "reply_wait")
    assert wait["state"] == "running" and wait["since"] and wait["remind_at"] > wait["since"] and wait["reply"] is None
    assert [a["name"] for a in page["steps"]["follow_up"]["actions"]] == ["replied", "not_needed"]
    assert c.post(f"/api/cases/{case_id}/steps/follow_up/actions/keep_waiting", headers=HUMAN, json={}).status_code == 422
    assert _rows(c, "cases")[0]["waits_for"] == "reply"

    done = c.post(f"/api/cases/{case_id}/steps/follow_up/actions/replied", headers=HUMAN, json={"note": "accepted"})
    assert done.status_code == 200, done.text
    engine.turn(case_id, wake=True)
    page = c.get(f"/api/cases/{case_id}").json()
    assert page["case"]["status"] == "closed"
    assert (_element(page, "reply_wait")["reply"], _element(page, "reply_wait")["by"]) == ("replied", "anna")
    events = _element(page, "timeline")["events"]
    assert events[0]["kind"] == "started" and events[-1]["kind"] == "closed"
    assert any(e["kind"] == "step_done" and e["step"] == "send" for e in events)
    assert all(e["kind"] not in ("waiting", "wait_ended") for e in events)
    assert _rows(c, "cases") == [] and _rows(c, "cases", include_closed="1")[0]["status"] == "closed"


def test_a_failed_send_is_listed_and_a_retry_sends_it(service, out, monkeypatch) -> None:  # noqa: F811
    c, case = service
    monkeypatch.setattr(app_settings, "output_folder", lambda: None)
    case_id = _start(c, case)
    c.post(f"/api/cases/{case_id}/steps/send/start", headers=HUMAN, json={})
    engine.turn(case_id, wake=True)
    page = c.get(f"/api/cases/{case_id}").json()
    assert page["steps"]["send"]["state"] == "failed" and page["next"]["code"] == "case_send_failed"
    assert page["steps"]["send"]["actions"] == [{"name": "retry", "label": "Try again"}]
    [listed] = _rows(c, "handovers")
    assert (listed["status"], listed["attempt"], listed["step"], listed["mode"]) == ("failed", 1, "Send", "output_folder")
    assert "no output folder" in listed["error"] and _rows(c, "cases")[0]["waits_for"] == "failed"
    monkeypatch.setattr(app_settings, "output_folder", lambda: str(out))
    assert c.post(f"/api/cases/{case_id}/steps/send/actions/retry", headers=HUMAN, json={}).status_code == 200
    engine.turn(case_id, wake=True)
    page = c.get(f"/api/cases/{case_id}").json()
    assert [a["status"] for a in _element(page, "handover_view")["attempts"]] == ["failed", "acknowledged"]
    assert _rows(c, "handovers") == []


def test_an_uncertain_send_waits_for_the_person_who_says_it_arrived(service, monkeypatch) -> None:
    c, case = service

    def lost(_handover_id, _payload):
        raise OSError("the network share stopped answering")

    monkeypatch.setitem(sending._SENDERS, sending.OUTPUT_FOLDER, sending.Sender(sending.OUTPUT_FOLDER, __name__, lost))
    case_id = _start(c, case)
    c.post(f"/api/cases/{case_id}/steps/send/start", headers=HUMAN, json={})
    engine.turn(case_id, wake=True)
    page = c.get(f"/api/cases/{case_id}").json()
    assert page["next"]["code"] == "case_send_settle" and _rows(c, "handovers")[0]["status"] == "uncertain"
    assert [a["name"] for a in page["steps"]["send"]["actions"]] == ["delivered", "not_delivered"]
    waiting = [r for r in _rows(c, "waiting", actor="anna") if r["kind"] == sending.SETTLE_TASK]
    assert [(r["what"], r["workpackage_name"]) for r in waiting] == [("Send", f"Quote {case.id}")]
    assert c.post(f"/api/cases/{case_id}/steps/send/actions/delivered", headers=HUMAN, json={}).status_code == 200
    engine.turn(case_id, wake=True)
    page = c.get(f"/api/cases/{case_id}").json()
    assert page["steps"]["send"]["state"] == "done" and page["next"]["code"] == "case_reply_wait"
    assert _rows(c, "handovers") == []


def test_the_history_tab_shows_what_each_step_spent(service) -> None:
    c, case = service
    case_id = _start(c, case)
    with capabilities.step_budget(case_id, "send", 1, {"openai": Decimal("0.05")}) as scope:
        calls.invoke(run_id=scope, step_id="invented", provider="openai", model="m", max_cost_usd=Decimal("0.01"),
                     fn=lambda: calls.Outcome("ok", "m", 10, 5, Decimal("0.002")), budget_scope=scope)
    cost = case_views.view(case_id)["tabs"][-1]["elements"][1]["data"]
    assert cost == {"lines": [{"step": "send", "step_title": "Send", "provider": "openai", "calls": 1, "reused": 0,
                               "cost_usd": "0.002", "open_usd": "0"}], "total_usd": "0.002"}


def test_the_package_list_is_built_again_when_a_case_moves(service) -> None:
    """231 (A3d): a case's row in the package list reads its steps and its quote; the list's cache mark follows them."""
    from jav.app import datasets

    c, case = service
    case_id = _start(c, case)
    datasets._workpackages_fingerprint({})  # the first look registers the tables the list reads in this new store
    marks = [datasets._workpackages_fingerprint({})]
    assert datasets._workpackages_fingerprint({}) == marks[0]  # nothing moved: the list is not built again
    c.post(f"/api/cases/{case_id}/steps/send/start", headers=HUMAN, json={})  # a person's task decided
    marks.append(datasets._workpackages_fingerprint({}))
    engine.turn(case_id, wake=True)  # the step ran
    marks.append(datasets._workpackages_fingerprint({}))
    assert len(set(marks)) == 3
