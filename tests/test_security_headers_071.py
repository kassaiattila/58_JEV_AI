"""071 S-fejlécek (070 plan 2.1, audit A07): browser protection headers on every response of the local service.

- Every response: embedding forbidden (`X-Frame-Options: DENY`, `frame-ancestors 'none'`), content-type sniffing
  forbidden (`nosniff`), no referrer passed on, the response can only be loaded from its own origin (COOP / CORP).
- The UI's HTML: a content security policy that allows only its own files (the embedded font and the favicon as
  `data:`, the download as `blob:`).
- The `/api/` responses (document data, page image, source document, download): the browser must not store them
  (`no-store`).
- Decision of 2026-09-30: the clickable endpoint list (`/api/docs`) is switched off, the machine-readable list
  (`/api/openapi.json`) stays.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav import api
from tests.test_api import BASE, _ready_wp, env  # noqa: F401  (the pytest fixture comes from here too)

COMMON = {
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
}
UI_CSP = {
    "default-src": "'self'", "script-src": "'self'", "style-src": "'self'", "img-src": "'self' data: blob:",
    "font-src": "'self' data:", "connect-src": "'self'", "object-src": "'none'", "base-uri": "'none'",
    "form-action": "'self'", "frame-ancestors": "'none'",
}


def _csp(headers) -> dict[str, str]:
    raw = headers.get("content-security-policy", "")
    return {p.split(" ", 1)[0]: p.split(" ", 1)[1] if " " in p else "" for p in (x.strip() for x in raw.split(";")) if p}


def _assert_common(r) -> None:
    for name, value in COMMON.items():
        assert r.headers.get(name) == value, (name, r.headers.get(name), r.request.url)
    assert _csp(r.headers).get("frame-ancestors") == "'none'", r.request.url


@pytest.fixture()
def ui_client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>JAV</title><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(api, "UI_DIST", dist)
    return TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url=BASE)


def test_ui_html_gets_the_strict_content_security_policy(ui_client):
    r = ui_client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    _assert_common(r)
    assert _csp(r.headers) == UI_CSP
    assert r.headers["cache-control"] == "no-cache"  # a new build shows up immediately (K3)


def test_hashed_static_asset_keeps_its_cacheability(ui_client):
    r = ui_client.get("/assets/index-abc123.js")
    assert r.status_code == 200
    _assert_common(r)
    assert "no-store" not in r.headers.get("cache-control", "")


def test_api_json_is_not_stored_and_has_a_closed_policy(ui_client):
    r = ui_client.get("/api/health")
    assert r.status_code == 200
    _assert_common(r)
    assert r.headers["cache-control"] == "no-store"
    assert _csp(r.headers) == {"default-src": "'none'", "frame-ancestors": "'none'"}


def test_rejected_request_carries_the_headers_too(ui_client):
    r = ui_client.get("/api/health", headers={"Host": "evil.example"})
    assert r.status_code == 403
    _assert_common(r)
    assert r.headers["cache-control"] == "no-store"


def test_unknown_api_path_and_error_carry_the_headers(ui_client):
    r = ui_client.get("/api/nincs-ilyen")
    assert r.status_code == 404
    _assert_common(r)


def test_interactive_docs_are_off_machine_list_stays(ui_client):
    """Decision of 2026-09-30: /api/docs would load program code from an external host into the local address."""
    assert ui_client.get("/api/docs").status_code == 404
    r = ui_client.get("/api/openapi.json")
    assert r.status_code == 200 and "/api/health" in r.json()["paths"]
    _assert_common(r)


def test_page_image_and_source_document_are_not_stored(env):  # noqa: F811
    c = env["client"]
    wp = _ready_wp(c, env["folder"])
    item = wp["items"][0]
    img = c.get(f"/api/workpackages/{wp['id']}/items/{item['item_id']}/pages/1.png?dpi=72")
    assert img.status_code == 200 and img.headers["cache-control"] == "no-store"
    _assert_common(img)
    src = c.get(f"/api/workpackages/{wp['id']}/items/{item['item_id']}/source")
    assert src.status_code == 200 and src.headers["cache-control"] == "no-store"
    _assert_common(src)
    # the source document opens in a new tab in the browser's built-in PDF viewer: `default-src` / `object-src`
    # could block that
    assert _csp(src.headers) == {"frame-ancestors": "'none'"}


def test_export_download_is_not_stored(env):  # noqa: F811
    c = env["client"]
    r = c.post("/api/datasets/activity/export", json={"scope": {"actor": "Teszt Elek"}, "format": "csv", "rows": "all"})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    _assert_common(r)
