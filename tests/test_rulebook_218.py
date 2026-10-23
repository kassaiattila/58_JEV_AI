"""218 (plan G-process-core P3a): the calculation snapshot. A snapshot names the code and every config file with its
version; the same files give the same snapshot, a changed file another one; each content is stored once and restores
byte for byte; two snapshots show the files that changed between them; a subject keeps the snapshot it was linked to
last. Synthetic config folders, no AI call."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jav.core import cfg, rulebook, store


def _configs(root: Path, *, threshold: float = 0.9) -> Path:
    (root / "prompts").mkdir(parents=True, exist_ok=True)
    (root / "policy.json").write_text(json.dumps({"meta": {"name": "policy", "version": "1.0.0"},
                                                  "bands": {"sure": threshold}}), encoding="utf-8")
    (root / "prompts" / "ask.md").write_text("Answer in English.\n", encoding="utf-8")
    return root


def _take(root: Path, **kw: object) -> rulebook.Snapshot:
    return rulebook.take(root, **{"app_version": "9.9.9", "commit": "abc1234", "dirty": False, **kw})


def test_a_snapshot_names_the_code_and_every_file_with_its_version(tmp_path) -> None:
    snap = _take(_configs(tmp_path / "configs"))
    assert set(snap.files) == {"policy.json", "prompts/ask.md"}
    assert snap.files["policy.json"].version == "1.0.0" and snap.files["prompts/ask.md"].version is None
    assert snap.snapshot_id == _take(tmp_path / "configs").snapshot_id  # the same files, the same snapshot
    assert len(snap.snapshot_id) == rulebook.ID_LEN


def test_a_changed_file_or_another_commit_is_another_snapshot(tmp_path) -> None:
    first = _take(_configs(tmp_path / "a"))
    assert _take(_configs(tmp_path / "b", threshold=0.8)).snapshot_id != first.snapshot_id
    assert _take(tmp_path / "a", commit="def5678").snapshot_id != first.snapshot_id
    assert _take(tmp_path / "a", dirty=True).snapshot_id != first.snapshot_id


def test_each_content_is_stored_once_and_restores_byte_for_byte(tmp_path) -> None:
    first, second = _take(_configs(tmp_path / "a")), _take(_configs(tmp_path / "b", threshold=0.8))
    with store.use_store(tmp_path / "s.sqlite"), store.connect() as c:
        store.begin_immediate(c)
        a = rulebook.store_in(c, first)
        assert rulebook.store_in(c, first) == a  # idempotent
        b = rulebook.store_in(c, second)
        assert c.execute("SELECT COUNT(*) FROM rule_files").fetchone()[0] == 3  # the prompt is the same in both
        assert c.execute("SELECT COUNT(*) FROM calc_snapshots").fetchone()[0] == 2
        sha = first.files["policy.json"].sha256
        assert rulebook.content_in(c, sha) == (tmp_path / "a" / "policy.json").read_bytes()
        before, after = rulebook.get_in(c, a), rulebook.get_in(c, b)
    assert before is not None and after is not None
    assert before["commit"] == "abc1234" and before["dirty"] is False and before["app_version"] == "9.9.9"
    assert before["files"]["policy.json"] == {"sha256": sha, "version": "1.0.0"}
    assert [ch["path"] for ch in rulebook.changes(before, after)] == ["policy.json"]
    assert rulebook.changes(before, before) == []


def test_a_subject_keeps_the_snapshot_it_was_linked_to_last(tmp_path) -> None:
    first, second = _take(_configs(tmp_path / "a")), _take(_configs(tmp_path / "b", threshold=0.8))
    with store.use_store(tmp_path / "s.sqlite"), store.connect() as c:
        store.begin_immediate(c)
        rulebook.link_in(c, rulebook.RUN, "run-1", first)
        rulebook.link_in(c, rulebook.RUN_ITEM, rulebook.run_item_subject("run-1", "a"), first)
        rulebook.link_in(c, rulebook.RUN_ITEM, rulebook.run_item_subject("run-1", "b"), first)
        rulebook.link_in(c, rulebook.RUN_ITEM, rulebook.run_item_subject("run-1", "b"), second)  # processed again
        rulebook.link_in(c, rulebook.RUN_ITEM, rulebook.run_item_subject("run-10", "x"), second)  # another run
        assert rulebook.of_run_in(c, "run-1") == {"start": first.snapshot_id,
                                                   "items": {"a": first.snapshot_id, "b": second.snapshot_id}}
        assert rulebook.of_in(c, rulebook.CASE, "case-1") is None  # made before snapshots
        with pytest.raises(ValueError, match="unknown snapshot subject"):
            rulebook.link_in(c, "document", "d-1", first)


def test_the_process_snapshot_names_the_project_s_configs_and_follows_a_reload() -> None:
    snap = rulebook.current()
    assert rulebook.current() is snap  # taken once per process
    assert "policy.json" in snap.files and snap.files["policy.json"].version == cfg.version("policy")
    cfg.reload()
    assert rulebook.current() is not snap  # a reload takes a new one
