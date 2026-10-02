"""091 (the version banner): the health endpoint also names the UI build the service hands out now.

A browser tab left open for a long time keeps the interface it loaded. The UI compares the service's state at page
load with the state it polls later; the commit is fixed at start-up (071), the UI build is read on every request,
because a new build is served at once, even without a restart.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from jav import api, version


def test_ui_build_is_a_short_fingerprint_of_the_entry_page(tmp_path):
    (tmp_path / "index.html").write_text('<script src="/assets/index-aaa.js"></script>', encoding="utf-8")
    first = version.ui_build(tmp_path)
    assert first is not None and len(first) == 12
    assert version.ui_build(tmp_path) == first  # deterministic
    (tmp_path / "index.html").write_text('<script src="/assets/index-bbb.js"></script>', encoding="utf-8")
    assert version.ui_build(tmp_path) != first  # a new build names new hashed asset files


def test_ui_build_without_a_build_is_unknown(tmp_path):
    assert version.ui_build(tmp_path / "missing") is None
    assert version.ui_build(tmp_path) is None  # a folder without an entry page


def test_health_reports_the_current_ui_build_not_the_one_at_start(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("old", encoding="utf-8")
    monkeypatch.setattr(api, "UI_DIST", dist)
    c = TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url="http://127.0.0.1:8930")
    before = c.get("/api/health").json()["ui_build"]
    assert before == version.ui_build(dist)
    (dist / "index.html").write_text("new", encoding="utf-8")
    after = c.get("/api/health").json()["ui_build"]
    assert after == version.ui_build(dist) and after != before
