"""231 (stage E, E3; the owner's decisions of 2026-10-29): the store's order.

Every write lock goes through the store's shared helper, and no module writes an insert only SQLite reads (an insert
that ignores or replaces a row): a later database takes the same statements. The other SQLite-specific constructs
(PRAGMA, sqlite_master, json_extract, instr, a direct connection) stay where they are and grow nowhere: their count per
module is frozen here. The store records the newest program version that set it up; a store a newer program set up
stops this one before it writes, and an older one is raised to this program's version. Connections setting up a fresh
store at the same moment all get it (they failed with "database is locked"). Temporary stores; nothing runs.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from pathlib import Path

import pytest

from jav.core import store
from jav.core.config import PROJECT_ROOT

SKIP = ("jav/core/store.py", "jav/evals/", "jav/legacy/", "jav/devtools/")  # the store's helpers; tools beside the runtime
NEVER = {"an insert that ignores or replaces": r"INSERT OR (IGNORE|REPLACE)", "a write lock of its own": r"execute\(\s*[\"']BEGIN"}
FROZEN = {
    r"PRAGMA ": {"jav/app/package_release.py": 1, "jav/app/workflow_cases.py": 1, "jav/app/workflow_records.py": 1,
                 "jav/domains/quotes/quote_steps.py": 2, "jav/flows/persistence.py": 1, "jav/runtime/backup.py": 2},
    r"sqlite_master": {"jav/app/activity.py": 1, "jav/app/human_tasks.py": 1, "jav/app/package_release.py": 3,
                       "jav/app/package_result.py": 1, "jav/app/package_scope.py": 1, "jav/app/work.py": 1,
                       "jav/documents/native_results.py": 1, "jav/documents/source_instances.py": 1,
                       "jav/domains/email/email_store.py": 1, "jav/domains/finance/reconcile_store.py": 1,
                       "jav/domains/finance/statement_months.py": 1, "jav/domains/finance/statement_package.py": 1,
                       "jav/flows/persistence.py": 1, "jav/runtime/backup.py": 3},
    r"json_extract\(": {"jav/ai/party_history.py": 2, "jav/app/activity.py": 3, "jav/app/document_processing.py": 3,
                        "jav/app/intake.py": 1, "jav/app/work_runs.py": 1, "jav/core/process/cases.py": 4,
                        "jav/domains/email/mailbox_bridge.py": 1, "jav/domains/finance/duplicates.py": 1,
                        "jav/domains/finance/reconcile_package.py": 1, "jav/domains/finance/statement_package.py": 1,
                        "jav/domains/quotes/quote_request.py": 1},
    r"\binstr\(": {"jav/app/document_processing.py": 1, "jav/app/human_tasks.py": 1, "jav/core/trace.py": 1},
    r"sqlite3\.connect\(": {"jav/documents/native_results.py": 1, "jav/flows/persistence.py": 3, "jav/runtime/backup.py": 4},
}


def _modules() -> dict[str, str]:
    out = {}
    for path in sorted((PROJECT_ROOT / "jav").rglob("*.py")):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        if "__pycache__" not in rel and not rel.startswith(SKIP):
            out[rel] = path.read_text(encoding="utf-8")
    return out


def test_no_module_writes_an_insert_only_sqlite_reads_or_takes_its_own_write_lock() -> None:
    for what, pattern in NEVER.items():
        assert [rel for rel, text in _modules().items() if re.search(pattern, text)] == [], what


@pytest.mark.parametrize("pattern", sorted(FROZEN))
def test_the_other_sqlite_specific_constructs_grow_nowhere(pattern) -> None:
    found = {rel: n for rel, text in _modules().items() if (n := len(re.findall(pattern, text)))}
    grown = {rel: n for rel, n in found.items() if n > FROZEN[pattern].get(rel, 0)}
    assert grown == {}, f"new uses of {pattern}: move them into the store's helpers ({grown})"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_store_records_this_program_s_version_and_an_older_one_is_raised(tmp_path) -> None:
    path = tmp_path / "s.sqlite"
    with store.use_store(path), store.connect() as c:
        assert c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(store.SCHEMA_VERSION)
    with sqlite3.connect(path) as raw:
        raw.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    store._initialized.clear()
    with store.use_store(path), store.connect() as c:
        assert c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0] == str(store.SCHEMA_VERSION)


def test_a_store_a_newer_program_set_up_stops_this_one_before_it_writes(tmp_path, monkeypatch) -> None:
    path = tmp_path / "s.sqlite"
    with store.use_store(path), store.connect():
        pass
    with sqlite3.connect(path) as raw:
        raw.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(store.SCHEMA_VERSION + 1),))
    store._initialized.clear()
    before = _digest(path)
    with pytest.raises(store.SchemaTooNew, match="newer program"):
        with store.use_store(path), store.connect():
            pass
    monkeypatch.setattr(store, "STORE_PATH", path)
    with pytest.raises(store.SchemaTooNew):
        store.check_installation()
    assert _digest(path) == before


def test_connections_setting_up_a_fresh_store_at_the_same_moment_all_get_it(tmp_path) -> None:
    # before the switch to WAL waited, about half of these failed: 44 of 80 threads, 9 of 20 processes started together
    for n in range(5):
        db = tmp_path / f"s{n}.sqlite"
        gate = threading.Barrier(8)
        errors: list[Exception] = []

        def one() -> None:
            gate.wait()
            try:
                with store.connect(db) as c:
                    c.execute("SELECT count(*) FROM meta").fetchone()
            except sqlite3.OperationalError as exc:
                errors.append(exc)

        threads = [threading.Thread(target=one) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        with sqlite3.connect(db) as c:
            assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
