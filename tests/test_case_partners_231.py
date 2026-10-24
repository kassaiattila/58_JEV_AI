"""231 (plan stage B, B1; DECISIONS 231): a case's partners, from the partner links of its process pack.

The IT quote's pack (1.2.0) says its request's customer is the case's partner in the customer role, with the values
its request step's fields give. The case's page proposes them, with the partner they seem to be when the register has
one; a person records the partner (one click) and links it, and the case's scope names it. A second case from the same
request finds the recorded partner. A role the pack has no link for, and a retired partner, are refused. Invented
quote requests with stand-in models; no paid call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import package_scope, partners, process_packs, scopes
from jav.core import store
from jav.core.process import engine
from jav.service.api import create_app
from tests import test_document_result_174 as rows
from tests.test_quote_path_231 import golden  # noqa: F401 - the fixture

HUMAN = {"X-Actor": "anna"}


@pytest.fixture()
def service(golden):  # noqa: F811 - the shared fixture
    cases, _seen = golden
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        yield c, cases[0]


def _start(c: TestClient, case) -> str:
    made = c.post("/api/cases", headers=HUMAN, json={"pack": "it_quote", "name": f"Quote {case.id}",
                                                      "record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}})
    case_id = made.json()["case_id"]
    engine.turn(case_id, wake=True)  # the request is put together (its step's result holds the record's fields)
    return case_id


def _links(c: TestClient, case_id: str) -> list[dict]:
    page = c.get(f"/api/cases/{case_id}").json()
    [element] = [e for e in page["tabs"][0]["elements"] if e["type"] == "partner_link"]
    return element["data"]["links"]


def test_a_case_proposes_its_customer_and_a_person_records_and_links_it(service) -> None:
    c, case = service
    case_id = _start(c, case)
    [link] = _links(c, case_id)
    assert (link["role"], link["role_label"], link["partner"], link["match"]) == ("customer", "Customer", None, None)
    proposal = link["proposal"]
    assert proposal["name"] == case.expected.request.customer_name
    made = c.post("/api/partners", headers=HUMAN, json={**proposal, "roles": ["customer"]})
    assert made.status_code == 201, made.text
    pid = made.json()["partner_id"]
    linked = c.post(f"/api/cases/{case_id}/partners", headers=HUMAN, json={"role": "customer", "partner_id": pid})
    assert linked.status_code == 200, linked.text
    [link] = _links(c, case_id)
    assert link["partner"]["partner_id"] == pid and link["proposal"] is None
    assert package_scope.stored(case_id)["parts"][scopes.PARTNERS] == {"customer": pid}
    # a second case from the same request finds the partner recorded since
    other = _start(c, case)
    [link] = _links(c, other)
    assert link["partner"] is None and link["match"]["partner_id"] == pid


def test_a_role_without_a_link_and_a_retired_partner_are_refused(service) -> None:
    c, case = service
    case_id = _start(c, case)
    pid = partners.create(partners.PartnerIn(name="Invented Broker Kft.", roles=["broker"]), "anna")["partner_id"]
    assert c.post(f"/api/cases/{case_id}/partners", headers=HUMAN, json={"role": "broker", "partner_id": pid}).status_code == 422
    partners.retire(pid, "anna")
    assert c.post(f"/api/cases/{case_id}/partners", headers=HUMAN, json={"role": "customer", "partner_id": pid}).status_code == 422
    assert c.post(f"/api/cases/{case_id}/partners", headers=HUMAN,
                  json={"role": "customer", "partner_id": "partner-000000000000"}).status_code == 404


@pytest.mark.parametrize(("link", "expected"), [
    ({"role": "landlord", "from_step": "request", "fields": {"name": "customer_name"}}, "unknown partner role"),
    ({"role": "customer", "from_step": "nowhere", "fields": {"name": "customer_name"}}, "no step 'nowhere'"),
    ({"role": "customer", "from_step": "request", "fields": {"email": "contact_email"}}, "its fields give a name"),
])
def test_a_pack_with_a_wrong_partner_link_is_refused(link, expected) -> None:
    from jav.core import cfg

    data = dict(cfg.load("process:it_quote"))
    data["partners"] = [link]
    assert any(expected in p for p in process_packs._problems(process_packs.ProcessPack.model_validate(data)))
