"""200 (decision of 2026-10-22): the JEV model is pinned to a concrete version; a newer one is reported, not taken.

On 2026-10-22 the provider's moving name `jev-latest` went from jev-1.13.0 to jev-1.14.0 without notice, every earlier
JEV answer lost its key, and every golden set had to be measured again. The owner's decision: `configs/models.json`
names the concrete version, the daily backup looks once where the moving name points (one tiny probe), and the start-up
check and the System page say when a newer version is out. Switching stays a decision with a measurement. Offline.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typesafe_sdk import SystemOneResponse

from jav import api, jev_version
from jav.core import config, store
from jav.adapters.jev import _CONCRETE_MODEL, MODEL_VERSIONS_FILE, JevAdapter


def _versions(cache: Path, latest: str | None, *, hours_ago: float = 1) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    data = {} if latest is None else {
        "jev-latest": {"model": latest, "resolved_at": (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")}}
    (cache / MODEL_VERSIONS_FILE).write_text(json.dumps(data), encoding="utf-8")


def test_the_configured_model_is_a_concrete_version():
    assert _CONCRETE_MODEL.match(config.JEV_MODEL), config.JEV_MODEL
    assert jev_version.WATCH_ALIAS == "jev-latest"


def test_the_moving_name_on_the_pinned_version(tmp_path: Path):
    _versions(tmp_path, "jev-1.14.0")
    st = jev_version.status(cache_dir=tmp_path, pinned="jev-1.14.0")
    assert (st["pinned"], st["latest"], st["newer"], st["stale"]) == ("jev-1.14.0", "jev-1.14.0", False, False)
    assert jev_version.verdict(st) == (True, f"jev-1.14.0 pinned; jev-latest is the same version (checked {st['checked_at'][:10]})")


def test_a_newer_version_is_reported_not_taken(tmp_path: Path):
    _versions(tmp_path, "jev-1.15.0")
    st = jev_version.status(cache_dir=tmp_path, pinned="jev-1.14.0")
    assert st["newer"] is True
    ok, line = jev_version.verdict(st)
    assert ok and "a newer JEV version is out: jev-latest is jev-1.15.0" in line and "decision and a measurement" in line
    assert JevAdapter(cache_dir=tmp_path, model="jev-1.14.0").resolved_model == "jev-1.14.0"  # the questions stay pinned


def test_a_missing_or_old_look_is_said(tmp_path: Path):
    _versions(tmp_path, None)
    st = jev_version.status(cache_dir=tmp_path, pinned="jev-1.14.0")
    assert st["latest"] is None and jev_version.verdict(st) == (True, "jev-1.14.0 pinned; jev-latest not looked up yet")
    _versions(tmp_path, "jev-1.14.0", hours_ago=24 * 4)
    st = jev_version.status(cache_dir=tmp_path, pinned="jev-1.14.0")
    assert st["stale"] is True and "not looked up for 4 days" in jev_version.verdict(st)[1]


def test_an_unpinned_model_is_said():
    assert jev_version.verdict({"pinned": "jev-latest", "latest": None, "newer": None, "stale": False,
                                "checked_at": None}) == (True, "not pinned: the model is the moving name jev-latest")


class ProbeClient:
    def __init__(self, answer: str) -> None:
        self.answer, self.models = answer, []

    def system_one(self, *, state, questions, model):
        self.models.append(model)
        return SystemOneResponse.model_validate({"model": self.answer, "usage": {"input_tokens": 100, "output_tokens": 1},
                                                 "answers": {q: {"type": "noul", "noul": 0.9} for q in questions}})


def test_the_daily_look_asks_the_moving_name_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    client = ProbeClient("jev-1.15.0")
    adapter = JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.14.0")
    st = jev_version.refresh(adapter=adapter, pinned="jev-1.14.0")
    assert client.models == ["jev-latest"] and st["latest"] == "jev-1.15.0" and st["newer"] is True
    jev_version.refresh(adapter=JevAdapter(client=client, cache_dir=tmp_path / "cache", model="jev-1.14.0"), pinned="jev-1.14.0")
    assert client.models == ["jev-latest"]  # a fresh look is not repeated within its day


def test_the_service_returns_the_look(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _versions(tmp_path / "cache", "jev-1.15.0")
    monkeypatch.setattr(jev_version, "CACHE_DIR", tmp_path / "cache")
    client = TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url="http://127.0.0.1:8930")
    body = client.get("/api/system/jev-version").json()
    assert body["latest"] == "jev-1.15.0" and body["pinned"] == config.JEV_MODEL
