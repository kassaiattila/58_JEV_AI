"""272 (check of the code review fixes, K1a): the daily look at JEV's moving name runs under its own small budget.

Since 265 (SEC-02) the JEV adapter's own client answers only from earlier answers outside a run or a budgeted
measurement. The daily backup's look ran outside both, so it was refused (`no_budget`), the adapter kept the old
resolution with a warning, and the look silently stopped. The owner's decision of 2026-11-01: the look runs under its
own daily JEV budget (`configs/service.json` `backup.jev_version_usd`), through the call log; a look that could not
run is said by the start-up check. Offline: the client is a fake held by an adapter that counts it as its own.
"""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from typesafe_sdk import SystemOneResponse

from jav.ai import jev_version
from jav.ai.jev import MODEL_VERSIONS_FILE, JevAdapter
from jav.core import calls, cfg, store


class ProbeClient:
    def __init__(self, answer: str) -> None:
        self.answer, self.models = answer, []

    def system_one(self, *, state, questions, model):
        self.models.append(model)
        return SystemOneResponse.model_validate({"model": self.answer, "usage": {"input_tokens": 100, "output_tokens": 1},
                                                 "answers": {q: {"type": "noul", "noul": 0.9} for q in questions}})


def _own(cache: Path, client: ProbeClient) -> JevAdapter:
    """An adapter whose client counts as made from the environment's key (the paid one), as in the daily backup."""
    adapter = JevAdapter(cache_dir=cache, model="jev-1.14.0")
    adapter._client = client
    return adapter


def _versions(cache: Path, latest: str, *, hours_ago: float) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    (cache / MODEL_VERSIONS_FILE).write_text(json.dumps({"jev-latest": {"model": latest, "resolved_at": at}}),
                                             encoding="utf-8")


@pytest.fixture
def where(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    monkeypatch.setattr(jev_version, "LOOK_PATH", tmp_path / "jev-version-look.json")
    return tmp_path


def test_the_daily_look_is_made_under_its_own_budget(where: Path):
    client = ProbeClient("jev-1.15.0")
    st = jev_version.refresh(adapter=_own(where / "cache", client), pinned="jev-1.14.0", budget_usd=Decimal("0.001"))
    assert client.models == ["jev-latest"] and st["latest"] == "jev-1.15.0" and st["newer"] is True
    with store.connect() as c:
        rows = c.execute("SELECT provider, budget_scope, status FROM invocations").fetchall()
    assert [(r["provider"], r["status"]) for r in rows] == [("jev", "succeeded")]
    assert rows[0]["budget_scope"].startswith("jev-version-")
    assert st["look_failed_at"] is None and "failed" not in jev_version.verdict(st)[1]


def test_the_budget_comes_from_the_service_settings():
    assert jev_version.daily_budget_usd() == Decimal(str(cfg.load("service")["backup"]["jev_version_usd"]))
    assert jev_version.daily_budget_usd() == Decimal("0.001")


def test_the_look_spends_at_most_its_daily_budget(where: Path):
    client = ProbeClient("jev-1.14.0")
    jev_version.refresh(adapter=_own(where / "cache", client), pinned="jev-1.14.0", budget_usd=Decimal("0.001"))
    _versions(where / "cache", "jev-1.14.0", hours_ago=30)  # due again on the same day: the same day's budget
    jev_version.refresh(adapter=_own(where / "cache", client), pinned="jev-1.14.0", budget_usd=Decimal("0.001"))
    with store.connect() as c:
        scopes = {r["budget_scope"] for r in c.execute("SELECT budget_scope FROM invocations")}
    assert len(scopes) == 1 and calls.left(scopes.pop(), "jev") <= Decimal("0.001")


def test_a_look_that_could_not_run_is_said(where: Path):
    _versions(where / "cache", "jev-1.14.0", hours_ago=30)  # due, and an old resolution to fall back on
    client = ProbeClient("jev-1.15.0")
    with pytest.raises(jev_version.LookFailed):
        jev_version.refresh(adapter=_own(where / "cache", client), pinned="jev-1.14.0", budget_usd=Decimal(0))
    assert client.models == []  # nothing left without a budget
    st = jev_version.status(cache_dir=where / "cache", pinned="jev-1.14.0")
    assert st["latest"] == "jev-1.14.0" and st["look_failed_at"] is not None
    assert "the last daily look failed" in jev_version.verdict(st)[1]


def test_a_fresh_resolution_is_not_asked_again(where: Path):
    _versions(where / "cache", "jev-1.14.0", hours_ago=1)
    client = ProbeClient("jev-1.15.0")
    st = jev_version.refresh(adapter=_own(where / "cache", client), pinned="jev-1.14.0", budget_usd=Decimal("0.001"))
    assert client.models == [] and st["latest"] == "jev-1.14.0" and st["look_failed_at"] is None


def test_a_later_good_look_clears_the_failure(where: Path):
    _versions(where / "cache", "jev-1.14.0", hours_ago=30)
    with pytest.raises(jev_version.LookFailed):
        jev_version.refresh(adapter=_own(where / "cache", ProbeClient("x")), pinned="jev-1.14.0", budget_usd=Decimal(0))
    st = jev_version.refresh(adapter=_own(where / "cache", ProbeClient("jev-1.14.0")), pinned="jev-1.14.0",
                             budget_usd=Decimal("0.001"))
    assert st["look_failed_at"] is None


def test_each_test_s_default_adapter_reads_its_own_cache_folder() -> None:
    """272 (K5, the rest of X-28): the conftest gives every test an empty JEV cache folder; the kept default adapter
    is made again in each test, so it never reads an earlier test's folder."""
    from jav.ai import jev

    assert jev.get_adapter().cache_dir == jev.CACHE_DIR
