"""203 (speed-up by measurement): the theme modules' routes are built once per process and shared by every service.

FastAPI analyses every endpoint's signature when it is added, about 4 ms each for some 170 endpoints; the service builds
its app once, but the test suite built one per test, about 450 times (0.76 s each). The shared routes must behave as
before: the same addresses in the same order, each service with its own store, the theme modules' error answers on
every service, and the application's JSON answer.
"""

from __future__ import annotations

import ast
import importlib

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from jav import api
from jav.domains.quotes import price_lists
from tests.pdfgen import INVOICE_LINES, write_text_pdf

BASE = "http://127.0.0.1:8930"
HUMAN = {"X-Actor": "teszt.elek"}


def _api_routes(app) -> list[APIRoute]:
    return [r for r in app.routes if isinstance(r, APIRoute)]


def test_a_second_service_shares_the_theme_routes_in_the_same_order(tmp_path):
    first = api.create_app(store_path=tmp_path / "a.sqlite")
    second = api.create_app(store_path=tmp_path / "b.sqlite")
    a, b = _api_routes(first), _api_routes(second)
    assert [(r.path, sorted(r.methods)) for r in a] == [(r.path, sorted(r.methods)) for r in b]
    shared = [r for r in a if r.path.startswith("/api/workpackages")]
    assert shared and all(any(r is s for s in b) for r in shared)  # the same objects, not built again
    health = [r for r in a if r.path == "/api/health"]
    assert health and not any(r is health[0] for r in b)  # the start-up state stays each service's own


def test_each_service_answers_from_its_own_store(tmp_path, monkeypatch):
    root = tmp_path / "root"
    folder = root / "incoming"
    folder.mkdir(parents=True)
    write_text_pdf(folder / "invoice_1.pdf", INVOICE_LINES)
    monkeypatch.setenv("JAV_API_ROOTS", str(root))
    first = TestClient(api.create_app(store_path=tmp_path / "a.sqlite"), base_url=BASE)
    second = TestClient(api.create_app(store_path=tmp_path / "b.sqlite"), base_url=BASE)
    r = first.post("/api/workpackages", headers=HUMAN, json={"folder": str(folder), "name": "First store"})
    assert r.status_code == 201, r.text
    assert [wp["name"] for wp in first.get("/api/workpackages?brief=true").json()["workpackages"]] == ["First store"]
    assert second.get("/api/workpackages?brief=true").json()["workpackages"] == []


def test_the_theme_modules_error_answers_are_on_every_service(tmp_path):
    for name in ("a", "b"):
        app = api.create_app(store_path=tmp_path / f"{name}.sqlite")
        assert price_lists.PriceListRefused in app.exception_handlers
        assert price_lists.PriceListStateError in app.exception_handlers


def test_the_shared_routes_answer_with_the_applications_json(tmp_path):
    api.create_app(store_path=tmp_path / "a.sqlite")
    app = api.create_app(store_path=tmp_path / "b.sqlite")
    for route in _api_routes(app):
        assert getattr(route.response_class, "value", route.response_class) is api.JavJSONResponse, route.path


def test_a_changed_module_list_builds_its_own_routes(tmp_path, monkeypatch):
    full = {r.path for r in _api_routes(api.create_app(store_path=tmp_path / "a.sqlite"))}
    monkeypatch.setattr(api, "route_modules", lambda: [m for m in api.SHARED_BEFORE + api.SHARED_AFTER])
    fewer = {r.path for r in _api_routes(api.create_app(store_path=tmp_path / "b.sqlite"))}
    assert fewer < full
    assert not any(p.startswith("/api/price-lists") for p in fewer)


def test_no_endpoint_uses_the_service_object():
    """The precondition of sharing: an endpoint's body never refers to the app it was added to (only its decorator)."""
    found = []
    for name in api.route_modules():
        module = importlib.import_module(name)
        tree = ast.parse(open(module.__file__, encoding="utf-8").read())
        for node in tree.body:
            if not (isinstance(node, ast.FunctionDef) and node.name == "routes"):
                continue
            app_name = node.args.args[0].arg
            for inner in node.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for statement in inner.body:
                        found += [f"{name}.{inner.name}" for n in ast.walk(statement)
                                  if isinstance(n, ast.Name) and n.id == app_name]
    assert found == []
