"""218 (plan G-process-core P3-0): the before/after comparison reads the "Waiting for me" list of every person, by
default and with every origin: the persons a task is assigned to, the people on the user list and the comparison's own
name, which sees only anyone's tasks. A changed row is reported. Synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path

from jav.app import app_settings, waiting, work
from jav.core import store
from jav.core import identity as actors
from jav.core.process import cases, tasks
from jav.evals import before_after

KIND = "synthetic_218"
MACHINE = actors.machine("tests")
tasks.register_kind(tasks.TaskKind(KIND, __name__))


def _backup(root: Path) -> Path:
    folder = root / "20261023-120000"
    folder.mkdir(parents=True)
    with store.use_store(folder / "jav.sqlite"):
        work.create_workpackage(name="Synthetic package", source_kind="manual", source_ref=None, owner="Reviewer One")
        app_settings.save_users(["Reviewer One", "Second Person"])
        with cases.transaction() as c:
            tasks.open_in(c, KIND, "mine-1", MACHINE, assignee=actors.person("Reviewer One").id)
            tasks.open_in(c, KIND, "anyone-1", MACHINE)
    return folder


def _waiting_key(scope: dict[str, str]) -> str:
    return "dataset/waiting/" + json.dumps(scope, sort_keys=True, ensure_ascii=False)


def _subjects(view: dict) -> list[str]:
    return sorted(r["what"] for r in view["body"]["rows"])


def test_every_person_s_waiting_list_is_read_by_default_and_with_every_origin(tmp_path) -> None:
    folder = _backup(tmp_path / "backup")
    out = tmp_path / "snap.jsonl"
    before_after.static_snapshot(folder, tmp_path / "work", out, items=False)
    _, views = before_after.load(out)
    for person in ("Reviewer One", "Second Person", before_after.ACTOR):
        for scope in ({"actor": person}, {"actor": person, "all": "true"}):
            assert views[_waiting_key(scope)]["status"] == 200, scope
    assert _subjects(views[_waiting_key({"actor": "Reviewer One"})]) == ["anyone-1", "mine-1"]
    assert _subjects(views[_waiting_key({"actor": "Second Person"})]) == ["anyone-1"]
    assert _subjects(views[_waiting_key({"actor": before_after.ACTOR})]) == ["anyone-1"]


def test_a_changed_row_of_a_waiting_list_is_a_difference(tmp_path, monkeypatch) -> None:
    folder = _backup(tmp_path / "backup")
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    before_after.static_snapshot(folder, tmp_path / "work", first, items=False)
    real = waiting.rows

    def planted(actor: str, *, every_origin: bool = False) -> list[dict]:
        return [{**r, "opened_at": "2000-01-01T00:00:00+00:00"} for r in real(actor, every_origin=every_origin)]

    monkeypatch.setattr(waiting, "rows", planted)
    before_after.static_snapshot(folder, tmp_path / "work", second, items=False)
    changed = {d.key for d in before_after.diff(first, second)}
    assert _waiting_key({"actor": "Reviewer One"}) in changed
    assert {before_after.kind_of(k) for k in changed} == {"dataset/waiting"}
