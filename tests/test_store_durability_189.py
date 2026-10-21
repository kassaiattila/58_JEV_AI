"""The disk wait after a write (189): off in the tests, SQLite's own setting in the application.

Plain-language summary: the test suite's stores are temporary files, so the suite tells SQLite not to wait for the disk
after each write (`store.SYNCHRONOUS`, set in tests/conftest.py); the application leaves SQLite's own, safer setting.
These tests show both: a fresh process has no setting of its own, the store's and the process state's connections
follow the setting, and without one they keep SQLite's default.
"""

from __future__ import annotations

import subprocess
import sys

from jav import store
from jav.config import PROJECT_ROOT
from jav.runtime.persistence import ClosingSQLitePersister

FULL, OFF = 2, 0  # `PRAGMA synchronous` values


def _synchronous(conn) -> int:
    return conn.execute("PRAGMA synchronous").fetchone()[0]


def test_the_application_keeps_sqlites_own_setting() -> None:
    code = "import jav.store as s; print(s.SYNCHRONOUS)"
    out = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "None"


def test_the_test_suite_turns_the_wait_off_for_the_store_and_the_process_state(tmp_path) -> None:
    assert store.SYNCHRONOUS == "OFF"
    with store.connect(tmp_path / "jav.sqlite") as c:
        assert _synchronous(c) == OFF
    persister = ClosingSQLitePersister(str(tmp_path / "burr_state.sqlite"))
    try:
        assert _synchronous(persister.connection) == OFF
    finally:
        persister.cleanup()


def test_without_a_setting_a_connection_keeps_the_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "SYNCHRONOUS", None)
    with store.connect(tmp_path / "jav.sqlite") as c:
        assert _synchronous(c) == FULL
    persister = ClosingSQLitePersister(str(tmp_path / "burr_state.sqlite"))
    try:
        assert _synchronous(persister.connection) == FULL
    finally:
        persister.cleanup()
