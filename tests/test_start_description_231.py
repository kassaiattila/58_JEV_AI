"""231 (stage E, E2; the owner's decisions of 2026-10-29): the start-up description and the store's installation.

Without a start-up description everything stays under the program's folder, as before. With one (`JAV_START`), the
configs, the writable data (the store, the runs, the caches, the inbox, the logs) and the keys come from the folders it
names, so two invented installations run on one machine with separate folders. The installation's store is stamped
with the installation the description names; a store of another installation stops the start, read only, and nothing
is written to it. A description that cannot be read, names an unknown key or a data folder that does not exist stops
the start too. Invented installations in temporary folders; nothing runs and no AI is asked.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jav.core import config, store
from jav.core.config import PROJECT_ROOT

PROBE = (
    "import json\n"
    "from jav.core import cfg, config, store\n"
    "from jav.core import applog\n"
    "from jav.domains.email import ingest_server\n"
    "out = {'data': str(config.DATA_ROOT), 'configs': str(cfg.CONFIG_DIR), 'store': str(config.STORE_PATH),\n"
    "       'logs': str(applog.LOG_DIR), 'inbox': str(ingest_server.INBOX_ROOT), 'installation': config.INSTALLATION_ID}\n"
    "try:\n"
    "    store.check_installation()\n"
    "    with store.connect() as c:\n"
    "        out['stamped'] = c.execute(\"SELECT value FROM meta WHERE key='installation_id'\").fetchone()[0]\n"
    "except store.ForeignStore as exc:\n"
    "    out['refused'] = str(exc)\n"
    "print(json.dumps(out))\n"
)


def _run(description: Path | None, code: str = PROBE) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != config.START_ENV}
    if description is not None:
        env[config.START_ENV] = str(description)
    env["PYTHONPATH"] = str(PROJECT_ROOT)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(PROJECT_ROOT),
                          timeout=300)


def _describe(folder: Path, **values: str) -> Path:
    path = folder / "start.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


def test_without_a_description_everything_stays_under_the_program_folder() -> None:
    assert config.DATA_ROOT == PROJECT_ROOT and config.CONFIG_ROOT == PROJECT_ROOT / "configs"
    assert config.RUNS_DIR == PROJECT_ROOT / "runs" and config.INBOX_ROOT == PROJECT_ROOT / "inbox"
    assert config.INSTALLATION_ID is None


def test_two_installations_run_on_one_machine_with_separate_folders(tmp_path) -> None:
    seen = {}
    for name in ("minta-a", "minta-b"):
        data = tmp_path / name
        data.mkdir()
        done = _run(_describe(tmp_path / name, data=".", installation=name))
        assert done.returncode == 0, done.stderr[-2000:]
        seen[name] = json.loads(done.stdout.strip().splitlines()[-1])
        out = seen[name]
        assert Path(out["data"]) == data.resolve() and Path(out["store"]) == data.resolve() / "store" / "jav.sqlite"
        assert Path(out["logs"]) == data.resolve() / "runs" / "logs" and Path(out["inbox"]) == data.resolve() / "inbox"
        assert Path(out["configs"]) == PROJECT_ROOT / "configs" and out["stamped"] == name
        assert (data / "store" / "jav.sqlite").is_file()
    assert seen["minta-a"]["store"] != seen["minta-b"]["store"]


def test_another_installation_s_store_stops_the_start_and_is_not_touched(tmp_path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    assert _run(_describe(tmp_path, data="data", installation="minta-b")).returncode == 0  # the store is minta-b's
    path = data / "store" / "jav.sqlite"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    done = _run(_describe(tmp_path, data="data", installation="minta-a"))
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert "minta-b" in out["refused"] and "stamped" not in out
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(("values", "problem"), [
    ({"data": "missing"}, "does not exist"),
    ({"data": ".", "port": 1}, "unknown keys"),
    ({"data": ".", "installation": "Not Valid!"}, "lowercase letters"),
])
def test_a_description_that_cannot_be_used_stops_the_start(tmp_path, values, problem) -> None:
    done = _run(_describe(tmp_path, **values), "import jav.core.config")
    assert done.returncode != 0 and "StartError" in done.stderr and problem in done.stderr


def test_a_store_a_command_names_is_never_stamped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "INSTALLATION_ID", "minta-a")
    with store.use_store(tmp_path / "copy.sqlite"):
        with store.connect() as c:
            assert c.execute("SELECT value FROM meta WHERE key='installation_id'").fetchone() is None
