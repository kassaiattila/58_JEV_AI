"""160 (review R-6): the daily scheduled backups and the manual ones are kept in separate counts.

The latest 14 backups were kept whatever made them, so a day's manual backups (one before every risky step) pushed out
every daily one: on 2026-10-16 all 14 local backups were of that day, and yesterday's state was gone. A backup now
records its kind; the daily ones keep their own count (14: about two weeks), and a manual backup prunes only manual
ones (the same count, the decision of 066). A backup from before this change counts as scheduled when it was made at
the scheduled time. Temporary store and folders."""

import json
from pathlib import Path

import pytest

from jav import backup
from jav.app import work
from jav.core import store


@pytest.fixture()
def db(tmp_path: Path):
    with store.use_store(tmp_path / "s.sqlite"):
        work.create_workpackage(name="Backed up", source_kind="manual", source_ref=None)
        yield tmp_path


def _made(root: Path, name: str, kind: str | None) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"ok": True, **({"kind": kind} if kind else {})}), encoding="utf-8")


def _left(root: Path) -> set[str]:
    return {p.name for p in root.iterdir() if p.is_dir() and p.name != "sources"}


def test_manual_backups_never_push_out_the_daily_ones(db):
    local = db / "local"
    for day in ("20261013", "20261014", "20261015"):
        _made(local, f"{day}-120001", "scheduled")
    made = [Path(backup.backup(out_root=local, keep=2)["dir"]).name for _ in range(3)]
    assert _left(local) == {"20261013-120001", "20261014-120001", "20261015-120001", *made[1:]}
    assert json.loads((local / made[-1] / "manifest.json").read_text(encoding="utf-8"))["kind"] == "manual"


def test_a_scheduled_backup_prunes_only_scheduled_ones(db):
    local = backup.default_root()  # the scheduled backup's own folder
    for n in range(3):
        _made(local, f"20261015-09000{n}", "manual")
    _made(local, "20261014-120001", "scheduled")
    _made(local, "20261015-120002", None)  # from before the kinds: made at the scheduled time, so a daily one
    m = backup.scheduled(config={"keep": 2, "copy_to": None, "with_burr": False, "with_docs": False, "schedule": "12:00"})
    assert m["kind"] == "scheduled" and m["removed"] == ["20261014-120001"]
    assert _left(local) == {"20261015-090000", "20261015-090001", "20261015-090002", "20261015-120002",
                            Path(m["dir"]).name}


def test_a_persons_back_up_now_counts_with_the_manual_backups(db, monkeypatch):
    seen = {}
    monkeypatch.setattr(backup, "backup", lambda **kw: seen.update(kw) or {"ok": True, "copy": None, "files": [], "dir": "x"})
    from fastapi.testclient import TestClient

    from jav import api

    client = TestClient(api.create_app(store_path=db / "s.sqlite"), base_url="http://127.0.0.1:8930")
    assert client.post("/api/system/backup", headers={"X-Actor": "someone"}, json={}).status_code == 200
    assert seen["kind"] == "manual"
