"""231 (an incident of 2026-10-25): a long-running process reads the configs it started with, whatever the folder holds
later.

The live service ran from the development folder: it loaded its code at start-up (091), and every config file then
(218), but it listed the config files anew on every request, so a process pack that appeared in the folder later (the
development branch's) was read by the released code, which refused its format: Settings › Processes showed the error.
A cleared cache read every file from the folder again too. Now the service and the worker freeze the configs at
start-up (`cfg.freeze`, called by `preload.preload`): the list and every file's content are the ones of that moment;
a later change on disk, a new file or a cleared cache changes nothing in the process, and `cfg.drift()` names what
the folder holds differently. Synthetic config folders only.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from jav.core import cfg
from jav.core.config import PROJECT_ROOT


@pytest.fixture
def folder(tmp_path, monkeypatch):
    """A copy of the configs in a folder of its own, read by this test's cfg (and frozen only here)."""
    configs = tmp_path / "configs"
    shutil.copytree(PROJECT_ROOT / "configs", configs)
    monkeypatch.setattr(cfg, "CONFIG_DIR", configs)
    monkeypatch.setattr(cfg, "CALLSITE_DIR", configs / "callsites")
    monkeypatch.setattr(cfg, "TYPES_DIR", configs / "types")
    monkeypatch.setattr(cfg, "PROCESSES_DIR", configs / "processes")
    cfg.reload()
    yield configs
    cfg.unfreeze()
    cfg.reload()


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def test_a_process_pack_that_appears_later_is_not_listed(folder):
    names = cfg.freeze()
    assert "process:it_quote" in names and cfg.frozen()
    _write(folder / "processes" / "later.json", {"meta": {"name": "process:later", "version": "1.0.0"}, "id": "later"})
    assert "process:later" not in cfg.all_names()
    with pytest.raises(FileNotFoundError, match="not among the configs this process started with"):
        cfg.load("process:later")


def test_a_base_type_pack_in_its_subfolder_is_frozen_too(folder):
    """231 (found on 2026-10-26): the utility bills' type packs extend the base pack in `configs/types/_base/`; the
    freeze listed the type packs' folder only, so a frozen service failed on every page that loads a utility type pack
    (Settings › Rules, the output templates, the bank files) and a frozen worker would have failed on a utility bill."""
    from jav.ai import typepack

    assert "type:_base/utility_bill_hu" in cfg.freeze()
    typepack.reload()
    assert typepack.get("villamos_energia_szamla").extends == "utility_bill_hu"
    assert "villamos_energia_szamla" in typepack.keys() and not any(k.startswith("_base/") for k in typepack.keys())


def test_a_changed_file_and_a_cleared_cache_change_nothing_in_the_process(folder):
    before = cfg.load("workflows")["meta"]["version"]
    cfg.freeze()
    data = json.loads((folder / "workflows.json").read_text(encoding="utf-8"))
    data["meta"]["version"] = "99.0.0"
    _write(folder / "workflows.json", data)
    cfg.reload()  # a cleared cache reads the frozen configs, not the folder
    assert cfg.load("workflows")["meta"]["version"] == before
    assert cfg.drift() == {"changed": ["workflows"], "new": [], "gone": []}


def test_drift_names_new_and_gone_files(folder):
    cfg.freeze()
    _write(folder / "processes" / "later.json", {"meta": {"name": "process:later", "version": "1.0.0"}, "id": "later"})
    (folder / "send.json").unlink()
    assert cfg.drift() == {"changed": [], "new": ["process:later"], "gone": ["send"]}


def test_without_freezing_the_folder_is_read_as_before(folder):
    assert not cfg.frozen() and cfg.drift() is None
    _write(folder / "processes" / "later.json", {"meta": {"name": "process:later", "version": "1.0.0"}, "id": "later"})
    assert "process:later" in cfg.all_names()  # a command, a test: they read the folder as it is


def test_the_preload_of_the_service_and_the_worker_freezes_the_configs(monkeypatch):
    from jav.runtime import preload

    seen = []
    monkeypatch.setattr(cfg, "freeze", lambda: seen.append("frozen") or [])
    monkeypatch.setattr(preload, "_import_all", lambda: [])
    preload.preload()
    assert seen == ["frozen"]


def test_the_service_s_health_names_the_drift(folder, tmp_path):
    from fastapi.testclient import TestClient

    from jav.service import api

    client = TestClient(api.create_app(store_path=tmp_path / "s.sqlite"), base_url="http://127.0.0.1:8930")
    assert client.get("/api/health").json()["config_drift"] is None  # a test's service froze nothing
    cfg.freeze()
    _write(folder / "processes" / "later.json", {"meta": {"name": "process:later", "version": "1.0.0"}, "id": "later"})
    fresh = TestClient(api.create_app(store_path=tmp_path / "s.sqlite"), base_url="http://127.0.0.1:8930")
    assert fresh.get("/api/health").json()["config_drift"] == {"changed": [], "new": ["process:later"], "gone": []}
