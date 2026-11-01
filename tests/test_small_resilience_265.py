"""265 (code review CORE-14, X-09, TOOL-17, TOOL-19): four small gaps.

- CORE-14: the flow-state store switched to WAL without the main store's retry on a busy file (`store.ensure_wal`).
- X-09: the native progress read the flow-state store through a connection it never closed.
- TOOL-17: the dependency audit's status went into the program folder, not the data folder.
- TOOL-19: the language guard skipped a text file that is not UTF-8, so Hungarian text could pass in another encoding.
272 (K5): the first two are checked by what the code does, not by its source text; UTF-16 is read too.
"""

from __future__ import annotations

from pathlib import Path

from jav.core import store
from jav.core.config import RUNS_DIR
from jav.devtools import lang_guard
from jav.documents import native_results
from jav.flows import persistence
from jav.runtime import deps_audit

ROOT = Path(__file__).resolve().parents[1]


def test_the_flow_state_store_switches_to_wal_with_the_retry(tmp_path, monkeypatch) -> None:
    """272 (K5): by what the store does, not by its source text."""
    asked: list[object] = []
    real = store.ensure_wal
    monkeypatch.setattr(store, "ensure_wal", lambda c: asked.append(c) or real(c))
    persister = persistence.ClosingSQLitePersister(str(tmp_path / "burr_state.sqlite"))
    try:
        assert len(asked) == 1
        assert persister.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        persister.connection.close()


def test_the_native_progress_closes_its_flow_state_connection(tmp_path, monkeypatch) -> None:
    """272 (K5): the connection to the flow-state store is closed once read (a source-text check before)."""
    import sqlite3
    from types import SimpleNamespace

    opened: list[object] = []

    class _Tracked:
        def __init__(self, conn) -> None:
            self.conn, self.closed = conn, False
            opened.append(self)

        def execute(self, *a):
            return self.conn.execute(*a)

        def close(self) -> None:
            self.closed = True
            self.conn.close()

    with store.use_store(tmp_path / "jav.sqlite"):
        burr = sqlite3.connect(tmp_path / "burr_state.sqlite")
        burr.execute("CREATE TABLE burr_state (partition_key TEXT, app_id TEXT, sequence_id INTEGER, state TEXT)")
        burr.commit()
        burr.close()
        monkeypatch.setattr(native_results, "sqlite3", SimpleNamespace(connect=lambda *a, **k: _Tracked(sqlite3.connect(*a, **k))))
        native_results.unpublished_state("run-x", "item-x")
    assert len(opened) == 1 and opened[0].closed


def test_the_audit_status_is_in_the_data_folder() -> None:
    assert deps_audit.STATUS_PATH == RUNS_DIR / "deps-audit.json"


def test_a_text_file_in_another_encoding_is_counted(tmp_path, monkeypatch) -> None:
    (tmp_path / "notes.txt").write_bytes(b"sz\xe1ml\xe1t \xe9s \xfcgyfelet\n")  # accented letters in Windows-1250
    monkeypatch.setattr(lang_guard, "tracked_files", lambda root: ["notes.txt"])
    assert lang_guard.scan(tmp_path, lang_guard.load_guard(ROOT)).get("notes.txt", 0) == 1


def test_a_utf16_text_file_is_counted_not_taken_for_binary(tmp_path, monkeypatch) -> None:
    """272 (K5, the rest of TOOL-19): a UTF-16 text file (Windows PowerShell 5.1 writes one by default) has zero bytes
    in it and was skipped as binary, so its Hungarian text passed the guard."""
    (tmp_path / "out.txt").write_text("sz\u00e1ml\u00e1t \u00e9s \u00fcgyfelet\n", encoding="utf-16")  # with its byte order mark
    (tmp_path / "be.txt").write_bytes("sz\u00e1ml\u00e1t \u00e9s \u00fcgyfelet\n".encode("utf-16-be"))  # without one
    (tmp_path / "image.bin").write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR")
    monkeypatch.setattr(lang_guard, "tracked_files", lambda root: ["out.txt", "be.txt", "image.bin"])
    counts = lang_guard.scan(tmp_path, lang_guard.load_guard(ROOT))
    assert counts.get("out.txt") == 1 and counts.get("be.txt") == 1 and "image.bin" not in counts
