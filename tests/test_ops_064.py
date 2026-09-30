"""064: napi mentés második helyre és a folyamatállapot-tár ritkítása (döntés 2026-09-29).

A ritkítás után minden folyamatnak csak az utolsó mentett állapota marad; a feldolgozó visszaolvasáskor is csak ezt
használja (Burr `load`: a legnagyobb sorszámú sor), ezért a folytatás változatlan. A mentés a helyi másolat után a
második helyre (NAS) is másol; ha az nem sikerül, a helyi mentés érvényes marad, a hiba az állapotfájlban látszik.
Mesterséges adat, hamis JEV, fizetős hívás nélkül.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from burr.core import State
from fastapi.testclient import TestClient

from jav import api, backup, store, work
from jav.runtime import lock, persistence, worker
from tests.test_stability_063 import _start, wp_env  # noqa: F401 - a közös csomag-előkészítő


def _persister(path: Path) -> worker.StatePersister:
    p = worker.StatePersister(str(path))
    p.initialize()
    return p


def _rows(path: Path) -> dict[str, list[int]]:
    import sqlite3

    with sqlite3.connect(path) as c:
        out: dict[str, list[int]] = {}
        for app_id, seq in c.execute("SELECT app_id, sequence_id FROM burr_state ORDER BY app_id, sequence_id"):
            out.setdefault(app_id, []).append(seq)
    return out


# --- a folyamatállapot-tár ritkítása ---------------------------------------------------------------------------------


def test_prune_keeps_only_the_last_state_and_loading_is_unchanged(tmp_path):
    db = tmp_path / "burr_state.sqlite"
    p = _persister(db)
    for app, n in (("run-kesz:aaaaaaaaaaaaaaaa", 3), ("run-kesz:bbbbbbbbbbbbbbbb", 2), ("run-fut:cccccccccccccccc", 2)):
        for seq in range(n):
            p.save("invoice", app, seq, f"lepes{seq}", State({"x": seq}), "completed")
    before = p.load("invoice", "run-kesz:aaaaaaaaaaaaaaaa")
    p.cleanup()
    out = persistence.prune_to_last(db, skip_prefixes=("run-fut:",))
    assert out["deleted"] == 3
    assert _rows(db) == {"run-kesz:aaaaaaaaaaaaaaaa": [2], "run-kesz:bbbbbbbbbbbbbbbb": [1], "run-fut:cccccccccccccccc": [0, 1]}
    q = _persister(db)
    after = q.load("invoice", "run-kesz:aaaaaaaaaaaaaaaa")
    q.cleanup()
    assert (after["sequence_id"], after["position"], after["state"]["x"]) == (before["sequence_id"], before["position"], 2)


def test_prune_of_one_item_touches_only_its_own_stages(tmp_path):
    db = tmp_path / "burr_state.sqlite"
    p = _persister(db)
    for app in ("run-1:aaaaaaaaaaaaaaaa", "run-1:aaaaaaaaaaaaaaaa-doc_detect", "run-1:aaaaaaaaaaaaaaab"):
        for seq in range(2):
            p.save("invoice", app, seq, "lepes", State({"x": seq}), "completed")
    p.cleanup()
    assert persistence.prune_to_last(db, app_id="run-1:aaaaaaaaaaaaaaaa")["deleted"] == 2
    assert _rows(db) == {"run-1:aaaaaaaaaaaaaaaa": [1], "run-1:aaaaaaaaaaaaaaaa-doc_detect": [1], "run-1:aaaaaaaaaaaaaaab": [0, 1]}


def test_worker_prunes_the_state_of_finished_items(wp_env):  # noqa: F811
    _start(wp_env["wp"]["id"])
    worker.run_worker(once=True)
    rows = _rows(worker.persister_path())
    assert len(rows) == 2 and all(len(seqs) == 1 for seqs in rows.values())  # tételenként csak az utolsó állapot


def test_vacuum_shrinks_the_file_and_waits_for_a_stopped_worker(tmp_path, monkeypatch):
    db = tmp_path / "burr_state.sqlite"
    p = _persister(db)
    for seq in range(40):
        p.save("invoice", "run-k:dddddddddddddddd", seq, "lepes", State({"szoveg": "x" * 20000}), "completed")
    p.cleanup()
    big = db.stat().st_size
    persistence.prune_to_last(db)
    out = persistence.vacuum(db)
    assert out["bytes_after"] < big / 5 and db.stat().st_size == out["bytes_after"]


def test_cli_prune_refuses_to_compact_while_the_worker_runs(wp_env, capsys):  # noqa: F811
    from jav import cli

    p = _persister(worker.persister_path())
    for seq in range(3):
        p.save("invoice", "run-k:eeeeeeeeeeeeeeee", seq, "lepes", State({"x": seq}), "completed")
    p.cleanup()
    with lock.single_instance(worker.lock_path()):
        code = cli.main(["burr-prune"])
    out = capsys.readouterr().out
    assert code == 0 and "2 köztes állapotsor törölve" in out  # ritkít futó feldolgozó mellett is
    assert "feldolgozó fut" in out  # de tömöríteni csak leállított feldolgozóval
    assert _rows(worker.persister_path()) == {"run-k:eeeeeeeeeeeeeeee": [2]}


# --- mentés a második helyre, állapotfájl --------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path):
    with store.use_store(tmp_path / "s.sqlite"):
        work.create_workpackage(name="Mentendő", source_kind="manual", source_ref=None)
        yield tmp_path


def test_backup_is_copied_to_the_second_place_and_both_keep_the_latest(db):
    local, nas = db / "helyi", db / "nas"
    for n in range(3):
        (nas / f"20260101-00000{n}").mkdir(parents=True)
    m = backup.backup(out_root=local, keep=2, copy_to=nas)
    assert m["ok"] and m["copy"]["ok"] and m["copy"]["verified"]
    copied = Path(m["copy"]["dir"])
    assert (copied / "s.sqlite").read_bytes() == (Path(m["dir"]) / "s.sqlite").read_bytes()
    assert sorted(p.name for p in nas.iterdir()) == sorted(["20260101-000002", copied.name])
    status = backup.status(local)
    assert status["ok"] and status["copy"]["ok"] and status["dir"] == m["dir"]


def test_failed_copy_keeps_the_local_backup_and_is_reported(db):
    local = db / "helyi"
    blocked = db / "nem-mappa"
    blocked.write_text("ez egy fájl, nem mappa", encoding="utf-8")
    m = backup.backup(out_root=local, keep=2, copy_to=blocked)
    assert m["ok"] and not m["copy"]["ok"] and m["copy"]["error"]
    assert backup.status(local)["copy"]["ok"] is False


def test_failed_backup_is_recorded_in_the_status_file(tmp_path):
    with store.use_store(tmp_path / "nincs" / "s.sqlite"):
        with pytest.raises(ValueError):
            backup.backup(out_root=tmp_path / "helyi")
    status = backup.status(tmp_path / "helyi")
    assert status["ok"] is False and "no store" in status["error"]


def test_scheduled_backup_follows_the_configuration(db, monkeypatch):
    seen = {}
    monkeypatch.setattr(backup, "backup", lambda **kw: seen.update(kw) or {"ok": True, "copy": None, "files": [], "dir": "x"})
    backup.scheduled(config={"keep": 14, "copy_to": str(db / "nas"), "with_burr": False})
    assert seen == {"keep": 14, "copy_to": db / "nas", "with_burr": False, "with_docs": False}  # 070: with_docs alapból ki


def test_service_shows_backup_status_and_can_back_up_now(db, monkeypatch):
    local = db / "helyi"
    monkeypatch.setattr(backup, "scheduled", lambda **kw: backup.backup(out_root=local, keep=14))
    monkeypatch.setattr(backup, "default_root", lambda: local)
    c = TestClient(api.create_app(store_path=db / "s.sqlite"), base_url="http://127.0.0.1:8930")
    assert c.get("/api/system/backup").json()["status"] is None  # még nem volt mentés
    r = c.post("/api/system/backup", headers={"X-Actor": "teszt.elek"}, json={})
    assert r.status_code == 200 and r.json()["ok"]
    body = c.get("/api/system/backup").json()
    assert body["status"]["ok"] and body["config"]["keep"] == 14 and body["config"]["max_age_hours"] > 0
    assert json.loads((local / "backup-status.json").read_text(encoding="utf-8"))["ok"]


# --- 066 Á09, Á29: sérült mentés után nincs ritkítás és másolás; a kézi mentés a napi megőrzést követi -------------------


def _old_backup(root: Path, name: str, ok: bool = True) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"ok": ok}), encoding="utf-8")
    return d


def test_failed_integrity_check_neither_prunes_nor_copies(db, monkeypatch):
    local, nas = db / "helyi", db / "nas"
    for n in range(3):
        _old_backup(local, f"20260101-00000{n}")
    monkeypatch.setattr(backup, "_integrity", lambda conn: "*** in database main *** Page 2 is never used")
    m = backup.backup(out_root=local, keep=2, copy_to=nas)
    assert m["ok"] is False and m["removed"] == []
    assert {"20260101-000000", "20260101-000001", "20260101-000002"} <= {p.name for p in local.iterdir()}
    assert m["copy"]["ok"] is False and m["copy"].get("skipped") and not nas.exists()


def test_failed_backups_do_not_count_towards_keep(db):
    local = db / "helyi"
    _old_backup(local, "20260101-000000")
    _old_backup(local, "20260101-000001")
    _old_backup(local, "20260101-000002", ok=False)
    m = backup.backup(out_root=local, keep=2)
    assert m["ok"] and m["removed"] == ["20260101-000000"]
    assert {p.name for p in local.iterdir() if p.is_dir()} == {"20260101-000001", "20260101-000002", Path(m["dir"]).name}


def test_backup_that_raises_leaves_no_half_written_folder(db, monkeypatch):
    local = db / "helyi"

    def boom(conn):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(backup, "_integrity", boom)
    with pytest.raises(sqlite3.OperationalError):
        backup.backup(out_root=local, keep=2)
    assert not [p for p in local.iterdir() if p.is_dir()]


def test_manual_backup_keeps_as_many_as_the_daily_one(db, monkeypatch):
    local = db / "helyi"
    for n in range(4):
        _old_backup(local, f"20260101-00000{n}")
    monkeypatch.setattr(backup, "configured_keep", lambda: 3)
    m = backup.backup(out_root=local)
    assert len(m["removed"]) == 2 and len([p for p in local.iterdir() if p.is_dir()]) == 3
