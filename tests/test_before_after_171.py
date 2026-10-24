"""171 (plan 170, E0): the before/after comparison tool. A snapshot of the same store copy taken twice is identical; a
changed view, a view only on one side and the places inside a view are reported; the copy carries the files kept next
to a store; personal data is never written inside the repository. Synthetic data only."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from jav.evals import before_after
from jav.app import work
from jav.core import store
from jav.core.config import PROJECT_ROOT


def _snapshot_file(path: Path, views: dict[str, object]) -> Path:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"meta": {"format": 1}}) + "\n")
        for key, value in views.items():
            f.write(json.dumps({"key": key, "value": value}) + "\n")
    return path


def test_the_kind_of_a_view_leaves_out_its_ids() -> None:
    assert before_after.kind_of("workpackages") == "workpackages"
    assert before_after.kind_of("workpackage/wp-1") == "workpackage"
    assert before_after.kind_of("workpackage/wp-1/reviews") == "workpackage/reviews"
    assert before_after.kind_of("run/run-1/export/documents.csv") == "run/export/documents.csv"
    assert before_after.kind_of("run/run-1/item/abc") == "run/item"
    assert before_after.kind_of("reconcile/wp-1/matches/line-9") == "reconcile/matches"
    assert before_after.kind_of('dataset/run_items/{"run_id": "run-1"}') == "dataset/run_items"
    # 224: a replay's views - a replayed item's by its part, a run's by its name
    assert before_after.kind_of("replay/run-1/abc/rows") == "replay/item/rows"
    assert before_after.kind_of("replay/run-1/dataset/documents") == "replay/dataset/documents"
    assert before_after.kind_of("replay/run-1/run") == "replay/run"


def test_a_diff_names_the_changed_views_and_the_places_inside(tmp_path) -> None:
    before = _snapshot_file(tmp_path / "a.jsonl", {
        "same": {"status": 200, "body": [1, 2]},
        "gone": {"status": 200, "body": {}},
        "run/run-1": {"status": 200, "body": {"status": "done", "items": [{"id": "x", "final": "auto"}], "n": 1}},
    })
    after = _snapshot_file(tmp_path / "b.jsonl", {
        "same": {"status": 200, "body": [1, 2]},
        "new": {"status": 404, "body": {"error": "not_found"}},
        "run/run-1": {"status": 200, "body": {"status": "done", "items": [{"id": "x", "final": "needs_review"}],
                                              "extra": True}},
    })
    found = {d.key: d for d in before_after.diff(before, after)}
    assert set(found) == {"gone", "new", "run/run-1"}
    assert found["gone"].kind == "only_before" and found["new"].kind == "only_after"
    assert found["run/run-1"].places == ("/body/extra: only after", '/body/items[0]/final: "auto" -> "needs_review"',
                                         "/body/n: only before")
    assert {k: dict(v) for k, v in before_after.summary(list(found.values())).items()} == {
        "gone": {"only_before": 1}, "new": {"only_after": 1}, "run": {"changed": 1}}


def test_a_list_of_another_length_is_reported(tmp_path) -> None:
    a = _snapshot_file(tmp_path / "a.jsonl", {"v": [1, 2, 3]})
    b = _snapshot_file(tmp_path / "b.jsonl", {"v": [1, 9]})
    assert before_after.diff(a, b)[0].places == (": 3 -> 2 elements", "[1]: 2 -> 9")


def test_personal_data_is_never_written_inside_the_repository(tmp_path) -> None:
    with pytest.raises(before_after.SnapshotError, match="inside the repository"):
        before_after._outside_git(PROJECT_ROOT / "docs" / "snapshot.jsonl")
    before_after._outside_git(PROJECT_ROOT / "store" / "snapshots" / "a.jsonl")  # git-ignored
    before_after._outside_git(tmp_path / "a.jsonl")


def _backup(root: Path) -> Path:
    """A backup laid out as `jav.cli backup` writes it: a timestamped folder and the shared `sources/` folder."""
    folder = root / "20261018-120000"
    folder.mkdir(parents=True)
    with store.use_store(folder / "jav.sqlite"):
        wp = work.create_workpackage(name="Synthetic package", source_kind="manual", source_ref=None, owner="Reviewer One")
    with zipfile.ZipFile(folder / "native-artifacts.zip", "w") as z:
        z.writestr("native/readings/r1/bundle.json", "{}")
    (root / "sources" / "ab").mkdir(parents=True)
    (root / "sources" / "ab" / "abc.pdf").write_bytes(b"%PDF-synthetic")
    (folder / "wp.txt").write_text(wp["id"], encoding="utf-8")
    return folder


def test_the_copy_carries_the_files_kept_next_to_a_store(tmp_path) -> None:
    folder = _backup(tmp_path / "backup")
    copy = before_after.fresh_copy(folder, tmp_path / "work")
    assert copy == (tmp_path / "work").resolve() / "jav.sqlite" and copy.is_file()
    assert (copy.parent / "native" / "readings" / "r1" / "bundle.json").is_file()
    assert (copy.parent / "sources" / "ab" / "abc.pdf").read_bytes() == b"%PDF-synthetic"
    (copy.parent / "leftover.txt").write_text("x", encoding="utf-8")
    before_after.fresh_copy(folder, tmp_path / "work")  # a new copy replaces the earlier one
    assert not (copy.parent / "leftover.txt").exists()


def test_a_snapshot_taken_twice_is_the_same_and_leaves_the_backup_alone(tmp_path) -> None:
    folder = _backup(tmp_path / "backup")
    wp_id = (folder / "wp.txt").read_text(encoding="utf-8")
    stored = (folder / "jav.sqlite").read_bytes()
    default = store.STORE_PATH
    first = tmp_path / "first.jsonl"
    counts = before_after.static_snapshot(folder, tmp_path / "work", first)
    assert store.STORE_PATH == default  # pointed back after the snapshot
    second = tmp_path / "second.jsonl"
    before_after.static_snapshot(folder, tmp_path / "work", second)
    assert before_after.diff(first, second) == []
    assert (folder / "jav.sqlite").read_bytes() == stored
    meta, views = before_after.load(first)
    assert meta["format"] == before_after.FORMAT_VERSION and meta["items"] is True
    assert views["workpackages"]["status"] == 200
    assert [w["id"] for w in views["workpackages"]["body"]["workpackages"]] == [wp_id]
    assert views[f"workpackage/{wp_id}"]["status"] == 200
    assert counts["workpackage"] >= 4 and counts["dataset"] >= 4
    with pytest.raises(before_after.SnapshotError, match="already exists"):
        before_after.static_snapshot(folder, tmp_path / "work", first)
