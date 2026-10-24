"""Every operation of the local service asks the authorisation check (229, plan structure stage 1, SZ2b).

Plain-language summary: each address of the local service names its operation (its theme and its function, e.g.
`workpackages.approve_run`) and goes through one shared entrance that knows who acts (the person the request names,
or nobody for a read without a name) and asks the authorisation check whether that person may do it. Today the check
allows everything, so nothing changes for the user; a company's rules will answer here later, and no address can be
left out by mistake. A temporary store, no AI call.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from jav.core import access
from jav.service import api, service_shared

BASE = "http://127.0.0.1:8930"


@pytest.fixture()
def app(tmp_path: Path):
    return api.create_app(store_path=tmp_path / "w.sqlite")


def _calls(dependant) -> set:
    out = set()
    for dep in dependant.dependencies:
        out.add(dep.call)
        out |= _calls(dep)
    return out


def test_every_address_of_the_service_goes_through_the_shared_entrance(app) -> None:
    routes = [r for r in app.routes if isinstance(r, APIRoute)]
    assert len(routes) > 150  # the service's own and every domain's
    assert [r.path for r in routes if service_shared.access_guard not in _calls(r.dependant)] == []


def test_each_operation_has_one_name_and_each_name_one_operation(app) -> None:
    endpoints = defaultdict(set)
    for route in (r for r in app.routes if isinstance(r, APIRoute)):
        action = service_shared.action_of(route)
        assert action.count(".") >= 1 and action == action.lower(), action
        endpoints[action].add(id(route.endpoint))
    assert {a: len(e) for a, e in endpoints.items() if len(e) > 1} == {}


def test_the_check_hears_who_acts_and_its_no_is_a_refusal(app) -> None:
    seen: list[tuple[str, str, str | None]] = []

    def rule(actor, action, subject) -> bool:
        seen.append((actor.id, action, subject))
        return not (actor.name == "Visitor" and action == "service.health")

    client = TestClient(app, base_url=BASE)
    access.set_authorizer(rule)
    try:
        assert client.get("/api/health", headers={"X-Actor": "Visitor"}).status_code == 403
        assert client.get("/api/health", headers={"X-Actor": "Minta%20Anna"}).status_code == 200
        assert client.get("/api/health").status_code == 200
    finally:
        access.set_authorizer(None)
    assert seen == [("local:Visitor", "service.health", None), ("local:Minta Anna", "service.health", None),
                    ("anonymous:request", "service.health", None)]
