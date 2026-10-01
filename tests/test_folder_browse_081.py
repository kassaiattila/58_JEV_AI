"""081 F-mappa-tallózás (the owner's trial of 2026-10-01): a package from a folder can take the subfolders too, and every
path field can be filled from the operating system's own folder or file picker.

Synthetic PDFs, no model calls; the picker's dialog process is replaced by a fake runner.
"""

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav import api, app_settings, local_picker, store, work, work_views
from tests.pdfgen import INVOICE_LINES, write_text_pdf

BASE = "http://127.0.0.1:8930"
HUMAN = {"X-Actor": "teszt.elek"}


def _pdf(path: Path, number: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_pdf(path, [line.replace("MINTA-2026-001", number) for line in INVOICE_LINES])
    return path


@pytest.fixture()
def tree(tmp_path: Path):
    root = tmp_path / "szamlak"
    _pdf(root / "a.pdf", "MINTA-2026-001")
    _pdf(root / "2026-08" / "b.pdf", "MINTA-2026-002")
    _pdf(root / "2026-09" / "deep" / "c.pdf", "MINTA-2026-003")
    (root / "2026-09" / "notes.txt").write_text("not a document\n", encoding="utf-8")
    with store.use_store(tmp_path / "w.sqlite"):
        yield root


def _names(wp: dict) -> list[str]:
    return sorted(Path(i["source_path"]).name for i in wp["items"])


def test_folder_without_subfolders_stays_the_default(tree):
    wp = work.create_from_folder(tree)
    assert _names(wp) == ["a.pdf"]


def test_folder_with_subfolders_takes_every_pdf_below_it(tree):
    wp = work.create_from_folder(tree, recursive=True)
    assert _names(wp) == ["a.pdf", "b.pdf", "c.pdf"]
    assert wp["source_ref"] == str(tree.resolve())


def test_an_excluded_folder_inside_is_skipped(tree):
    out = tree / "atnevezett"
    _pdf(out / "copy.pdf", "MINTA-2026-009")
    wp = work.create_from_folder(tree, recursive=True, exclude=[out])
    assert _names(wp) == ["a.pdf", "b.pdf", "c.pdf"]


def test_titles_show_the_subfolder_of_a_file_below_the_package_folder(tree):
    wp = work.create_from_folder(tree, recursive=True)
    titles = work_views.item_titles(wp["items"], root=wp["source_ref"])
    by_name = {Path(i["source_path"]).name: titles.get(i["item_id"]) for i in wp["items"]}
    assert by_name == {"a.pdf": None, "b.pdf": "2026-08/b.pdf", "c.pdf": "2026-09/deep/c.pdf"}


def test_the_package_view_and_the_item_list_use_the_subfolder_titles(tree):
    wp = work.create_from_folder(tree, recursive=True)
    view = work_views.workpackage_view(wp["id"])
    assert sorted(view["titles"].values()) == ["2026-08/b.pdf", "2026-09/deep/c.pdf"]


# --- the local service ---------------------------------------------------------------------------------------------


@pytest.fixture()
def client(tree, tmp_path: Path):
    yield TestClient(api.create_app(store_path=tmp_path / "w.sqlite"), base_url=BASE)


def test_create_from_folder_over_http_takes_subfolders_only_when_asked(client, tree):
    r = client.post("/api/workpackages", headers=HUMAN, json={"folder": str(tree)})
    assert r.status_code == 201, r.text
    assert len(r.json()["workpackage"]["items"]) == 1
    r = client.post("/api/workpackages", headers=HUMAN, json={"folder": str(tree), "name": "Mind", "recursive": True})
    assert r.status_code == 201, r.text
    assert len(r.json()["workpackage"]["items"]) == 3


def test_create_from_folder_over_http_skips_the_output_folder(client, tree, monkeypatch):
    out = tree / "atnevezett"
    _pdf(out / "copy.pdf", "MINTA-2026-009")
    monkeypatch.setattr(app_settings, "output_folder", lambda: str(out))
    r = client.post("/api/workpackages", headers=HUMAN, json={"folder": str(tree), "recursive": True})
    assert r.status_code == 201, r.text
    assert len(r.json()["workpackage"]["items"]) == 3


class _FakeRunner:
    """Stands in for the dialog process: records the request and answers with the given paths."""

    def __init__(self, answer: list[str] | None = None, *, returncode: int = 0, timeout: bool = False):
        self.answer, self.returncode, self.timeout, self.requests = answer or [], returncode, timeout, []

    def __call__(self, args, **kwargs):
        self.requests.append(json.loads(args[-1]))
        if self.timeout:
            raise subprocess.TimeoutExpired(args, kwargs.get("timeout"))
        return subprocess.CompletedProcess(args, self.returncode, stdout=json.dumps(self.answer), stderr="no display")


def test_pick_folder_returns_the_chosen_folder_in_windows_form(monkeypatch, tmp_path):
    runner = _FakeRunner([tmp_path.as_posix()])
    monkeypatch.setattr(local_picker, "_run", runner)
    assert local_picker.pick_folder(title="Mappa", initial=str(tmp_path)) == str(tmp_path)
    assert runner.requests == [{"kind": "folder", "title": "Mappa", "initial": str(tmp_path)}]


def test_pick_folder_cancelled_is_none_and_a_missing_start_folder_is_dropped(monkeypatch, tmp_path):
    runner = _FakeRunner([])
    monkeypatch.setattr(local_picker, "_run", runner)
    assert local_picker.pick_folder(title="Mappa", initial=str(tmp_path / "nincs")) is None
    assert runner.requests[0]["initial"] is None


def test_pick_files_starts_in_the_folder_of_a_given_file(monkeypatch, tmp_path):
    f = _pdf(tmp_path / "x" / "a.pdf", "MINTA-2026-001")
    runner = _FakeRunner([f.as_posix()])
    monkeypatch.setattr(local_picker, "_run", runner)
    assert local_picker.pick_files(title="Fájlok", initial=str(f)) == [str(f)]
    assert runner.requests[0] == {"kind": "files", "title": "Fájlok", "initial": str(f.parent)}


def test_a_dialog_that_cannot_open_is_named(monkeypatch):
    monkeypatch.setattr(local_picker, "_run", _FakeRunner(returncode=1))
    with pytest.raises(local_picker.PickerUnavailable):
        local_picker.pick_folder(title="Mappa")


def test_a_dialog_left_open_past_the_time_limit_counts_as_cancelled(monkeypatch):
    monkeypatch.setattr(local_picker, "_run", _FakeRunner(timeout=True))
    assert local_picker.pick_folder(title="Mappa") is None


def test_only_one_dialog_is_open_at_a_time(monkeypatch):
    monkeypatch.setattr(local_picker, "_run", _FakeRunner([]))
    assert local_picker._LOCK.acquire(blocking=False)
    try:
        with pytest.raises(local_picker.PickerBusy):
            local_picker.pick_folder(title="Mappa")
    finally:
        local_picker._LOCK.release()


def test_pick_endpoints_return_the_chosen_paths(client, tree, monkeypatch):
    monkeypatch.setattr(local_picker, "_run", _FakeRunner([tree.as_posix()]))
    r = client.post("/api/local/pick-folder", json={"title": "Mappa kiválasztása"})
    assert r.status_code == 200, r.text
    assert r.json() == {"path": str(tree)}
    f = tree / "a.pdf"
    monkeypatch.setattr(local_picker, "_run", _FakeRunner([f.as_posix()]))
    r = client.post("/api/local/pick-files", json={"title": "Fájlok", "initial": str(tree)})
    assert r.status_code == 200, r.text
    assert r.json() == {"paths": [str(f)]}


def test_pick_endpoint_cancel_busy_and_unavailable(client, monkeypatch):
    monkeypatch.setattr(local_picker, "_run", _FakeRunner([]))
    assert client.post("/api/local/pick-folder", json={}).json() == {"path": None}
    monkeypatch.setattr(local_picker, "_run", _FakeRunner(returncode=1))
    r = client.post("/api/local/pick-folder", json={})
    assert r.status_code == 503 and r.json()["error"] == "picker_unavailable"
    assert local_picker._LOCK.acquire(blocking=False)
    try:
        r = client.post("/api/local/pick-files", json={})
        assert r.status_code == 409 and r.json()["error"] == "picker_busy"
    finally:
        local_picker._LOCK.release()


def test_a_picked_folder_outside_the_allowed_roots_is_refused_when_restricted(client, tree, tmp_path, monkeypatch):
    elsewhere = tmp_path / "mashol"
    elsewhere.mkdir()
    monkeypatch.setattr(api, "paths_restricted", lambda: True)
    monkeypatch.setattr(api, "allowed_roots", lambda: [tree.resolve()])
    monkeypatch.setattr(local_picker, "_run", _FakeRunner([elsewhere.as_posix()]))
    r = client.post("/api/local/pick-folder", json={})
    assert r.status_code == 403 and r.json()["error"] == "forbidden_path"


def test_pick_endpoints_refuse_a_foreign_origin(client, monkeypatch):
    monkeypatch.setattr(local_picker, "_run", _FakeRunner([]))
    r = client.post("/api/local/pick-folder", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
