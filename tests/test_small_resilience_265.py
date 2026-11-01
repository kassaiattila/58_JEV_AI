"""265 (code review CORE-14, X-09, TOOL-17, TOOL-19): four small gaps.

- CORE-14: the flow-state store switched to WAL without the main store's retry on a busy file (`store.ensure_wal`).
- X-09: the native progress read the flow-state store through a connection it never closed.
- TOOL-17: the dependency audit's status went into the program folder, not the data folder.
- TOOL-19: the language guard skipped a text file that is not UTF-8, so Hungarian text could pass in another encoding.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from jav.core import store
from jav.core.config import RUNS_DIR
from jav.devtools import lang_guard
from jav.documents import native_results
from jav.flows import persistence
from jav.runtime import deps_audit

ROOT = Path(__file__).resolve().parents[1]


def test_the_flow_state_store_switches_to_wal_with_the_retry() -> None:
    assert "store.ensure_wal(connection)" in inspect.getsource(persistence)
    assert callable(store.ensure_wal)


def test_the_native_progress_closes_its_flow_state_connection() -> None:
    assert "contextlib.closing(sqlite3.connect(" in inspect.getsource(native_results)


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
