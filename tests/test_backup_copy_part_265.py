"""265 (code review CORE-03): the copy to the second location is put in place only when it is whole and verified.

The copy started under the backup's own name; a failure (a full or lost network share) left a half-copied folder there,
which the pruning kept as a good backup. Now it is copied under `<stamp>.part`, checked, and put in place in one step;
a failure removes the part and leaves nothing under the backup's name. Synthetic folders.
"""

from __future__ import annotations

from jav.runtime import backup


def _local(tmp_path):
    src = tmp_path / "local" / "20261031-120000"
    src.mkdir(parents=True)
    (src / "jav.sqlite").write_bytes(b"store")
    (src / "manifest.json").write_text("{}", encoding="utf-8")
    return src


def test_a_verified_copy_takes_the_backup_s_name(tmp_path) -> None:
    src = _local(tmp_path)
    out = backup._copy(src, tmp_path / "nas", keep=3, prune=False)
    assert out["ok"] and (tmp_path / "nas" / src.name / "jav.sqlite").read_bytes() == b"store"
    assert not (tmp_path / "nas" / f"{src.name}.part").exists()


def test_a_failed_copy_leaves_nothing_under_the_backup_s_name(tmp_path, monkeypatch) -> None:
    src = _local(tmp_path)
    real = backup._sha256
    monkeypatch.setattr(backup, "_sha256", lambda p: "bad" if ".part" in str(p) else real(p))  # a corrupted copy
    out = backup._copy(src, tmp_path / "nas", keep=3, prune=False)
    assert not out["ok"] and "verification failed" in out["error"]
    assert not (tmp_path / "nas" / src.name).exists() and not (tmp_path / "nas" / f"{src.name}.part").exists()


def test_a_copy_left_half_way_by_a_stopped_run_is_removed_by_the_next_pruning(tmp_path) -> None:
    """272 (K5, the rest of CORE-03): a run stopped during the copy (the process killed, so no clean-up ran) left its
    `.part` folder for good; the pruning took only the backups' own names. An old one goes now; a fresh one (a copy
    that may still be running) and a folder of another name stay."""
    import os
    import time

    root = tmp_path / "nas"
    old, fresh, other = root / "20260101-000000.part", root / "20260102-000000.part", root / "notes.part"
    for folder in (old, fresh, other):
        folder.mkdir(parents=True)
    hour_ago = time.time() - 2 * 3600
    os.utime(old, (hour_ago, hour_ago))
    os.utime(other, (hour_ago, hour_ago))
    removed = backup._prune(root, keep=14)
    assert not old.exists() and fresh.exists() and other.exists()
    assert removed == ["20260101-000000.part"]
