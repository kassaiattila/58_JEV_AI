"""231 (stage D, D-c6): the product registry through the local service, as the Settings screens use it.

The invented insurer's set installed as drafts lists every product, document, rule and tariff with its versions; a
draft carries what keeps it from being made active, each problem a sentence with its template for the interface's
language and where it applies. Making the product active by its maker is refused (409), by another person while its
rules are drafts too (422, with every problem); in order, by another person, it is made active and the listing says so.
Retiring keeps the version readable. Invented data; no paid call.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import product_sets
from jav.core import store
from jav.service.api import create_app

ANNA, BELA = {"X-Actor": "anna"}, {"X-Actor": "bela"}
PRODUCT = "/api/product-registry/product/inv_business_property"


@pytest.fixture()
def client(tmp_path):
    path = tmp_path / "registry.sqlite"
    with store.use_store(path):
        product_sets.install(product_sets.load(), maker="anna")
    with TestClient(create_app(store_path=path), base_url="http://127.0.0.1:8930") as c:
        yield c


def _thing(view: dict, key: str, ident: str) -> dict:
    return next(t for t in view[key] if t["ident"] == ident)


def test_the_registry_lists_every_thing_with_a_drafts_problems(client) -> None:
    view = client.get("/api/product-registry").json()
    assert (len(view["products"]), len(view["documents"]), len(view["rules"]), len(view["tariffs"])) == (1, 5, 16, 1)
    assert set(view["catalogues"]) == {"property"} and "sum_insured" in view["catalogues"]["property"]["facts"]
    draft = _thing(view, "products", "inv_business_property")["versions"][0]
    assert draft["state"] == "draft" and draft["made_by"] == "anna"
    first = draft["problems"][0]
    assert first["template"] == "still a draft" and first["within"]["template"] == "document {{ref}}"
    assert first["text"] == "document inv_general_conditions@1: still a draft"
    rule = _thing(view, "rules", "inv_class_cash")["versions"][0]
    assert rule["problems"] == [] and rule["content"]["source"]["clause"] == "1"


def test_the_maker_cannot_make_the_product_active_and_a_draft_rule_blocks_it(client) -> None:
    refused = client.post(f"{PRODUCT}/versions/1/activate", json={}, headers=ANNA)
    assert refused.status_code == 409 and refused.json()["error"] == "second_person_needed"
    assert refused.json()["template"] == "a product version is made active by another person than its maker"
    blocked = client.post(f"{PRODUCT}/versions/1/activate", json={}, headers=BELA)
    assert blocked.status_code == 422 and blocked.json()["error"] == "manifest_refused"
    assert {"text": "rule inv_flood_high@1: still a draft"} == {"text": next(
        p["text"] for p in blocked.json()["problems"] if p["text"].startswith("rule inv_flood_high@1"))}


def test_in_order_by_another_person_the_product_is_made_active_and_can_be_retired(client) -> None:
    view = client.get("/api/product-registry").json()
    for key, kind in (("documents", "document"), ("rules", "rule"), ("tariffs", "tariff")):
        for thing in view[key]:
            r = client.post(f"/api/product-registry/{kind}/{thing['ident']}/versions/1/activate", json={}, headers=BELA)
            assert r.status_code == 200, r.json()
    made = client.post(f"{PRODUCT}/versions/1/activate", json={}, headers=BELA)
    assert made.status_code == 200 and made.json()["state"] == "active" and made.json()["activated_by"] == "bela"
    product = _thing(client.get("/api/product-registry").json(), "products", "inv_business_property")
    assert product["active"] == 1 and "problems" not in product["versions"][0]
    retired = client.post(f"{PRODUCT}/retire", json={}, headers=BELA)
    assert retired.status_code == 200 and retired.json()["state"] == "retired"
    assert client.post(f"{PRODUCT}/retire", json={}, headers=BELA).status_code == 409


def test_a_wrong_kind_or_a_missing_person_is_refused(client) -> None:
    assert client.post("/api/product-registry/quote/x/retire", json={}, headers=BELA).status_code == 422
    assert client.post(f"{PRODUCT}/versions/1/activate", json={}).status_code == 422
    assert client.post("/api/product-registry/rule/nothing_like_it/versions/1/activate", json={}, headers=BELA).status_code == 404
