"""231 (plan stage A, A6; DECISIONS 231): a process pack's case on the local service.

A case starts from the record it belongs to; its page is data: its pack's tabs, each element with what its step's
capability shows (the quote's elements show the quote view the quote package's page had); a paid step waits for a
person's start, which the service records and the worker carries on. An unknown case is 404, a step that does not wait
for a start is refused.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from jav.core.process import engine
from jav.service.api import create_app
from tests import test_document_result_174 as rows
from tests.test_quote_path_231 import _drain, golden  # noqa: F401 - the fixture

HUMAN = {"X-Actor": "anna"}


def test_a_case_starts_from_its_record_and_its_page_is_its_packs_tabs(golden, tmp_path) -> None:  # noqa: F811 - the shared fixture
    from jav.core import store

    cases, _seen = golden
    case = cases[0]
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        made = c.post("/api/cases", headers=HUMAN, json={"pack": "it_quote", "name": f"Quote {case.id}",
                                                          "record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}})
        assert made.status_code == 201, made.text
        case_id = made.json()["case_id"]
        engine.turn(case_id, wake=True)  # the worker: the request is put together, the match waits for its start
        page = c.get(f"/api/cases/{case_id}").json()
        assert page["case"] == {"id": case_id, "pack": "it_quote", "version": "1.5.0", "title": "IT quote",
                                "name": f"Quote {case.id}", "status": "open", "due": False}  # U-A8: the match waits for a person
        assert [t["id"] for t in page["tabs"]] == ["request", "quote", "approval", "sent", "follow_up", "history"]
        assert [e["type"] for e in page["tabs"][1]["elements"]] == ["match_proposal", "line_editor"]
        assert page["tabs"][0]["elements"][0]["data"]["quote"]["request"]["fields"]["customer_name"]
        assert page["steps"]["request"]["state"] == "done" and page["steps"]["match"]["awaiting_start"]
        started = c.post(f"/api/cases/{case_id}/steps/match/start", headers=HUMAN, json={})
        assert started.status_code == 200, started.text
        engine.turn(case_id, wake=True)
        _drain()
        engine.turn(case_id, wake=True)
        page = c.get(f"/api/cases/{case_id}").json()
        assert page["steps"]["match"]["state"] == "done"
        assert page["tabs"][1]["elements"][0]["data"]["quote"]["proposal"]["requested_by"] == "anna"
        again = c.post(f"/api/cases/{case_id}/steps/match/start", headers=HUMAN, json={})
        assert again.status_code == 422
        assert c.get("/api/cases/wp-000000000000").status_code == 404
        # the case's container is a work package like any: the list, its page (which names the case) and its output
        # template choice answer (a store with a case once broke the package list)
        assert c.get("/api/workpackages").status_code == 200
        wp = c.get(f"/api/workpackages/{case_id}").json()
        assert wp["case"] == {"id": case_id, "pack": "it_quote", "version": "1.5.0"}
        # the container's next step is its case page's: the quote's own wording (as the quote package's was)
        assert wp["next"]["code"] == "quote_approve"
        assert c.get(f"/api/cases/{case_id}").json()["next"] | {"label": None} == {
            "code": "quote_approve", "label": None, "stage": "result", "tab": "approval"}
        assert list(c.get(f"/api/workpackages/{case_id}/output-templates").json()["outputs"]) == ["quote"]
