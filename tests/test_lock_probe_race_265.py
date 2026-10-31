"""265 (code review CORE-09): a lock probe does not stop a worker that is just starting.

A starting worker creates its lock file and then locks it. Another worker's clean-up probes every lock file by taking
its lock for a moment, so a lock taken right then failed and the start stopped as if another worker held it; the
clean-up could also remove the file before its worker locked it. A lock is now tried again a few times, and a young
lock file is never removed. Temporary files only.
"""

from __future__ import annotations

import os
import time

from jav.core import lock
from jav.runtime import pdf_status


def test_a_lock_taken_during_a_probe_is_tried_again(tmp_path, monkeypatch) -> None:
    answers = iter([False, True])  # the first attempt meets another process's probe
    monkeypatch.setattr(lock, "_try_lock", lambda f: next(answers))
    monkeypatch.setattr(lock, "_unlock", lambda f: None)
    monkeypatch.setattr(lock, "TAKE_RETRY_S", 0)
    held = lock.hold(tmp_path / "w.lock")
    lock.release(held)


def test_a_young_lock_file_is_kept_and_an_old_one_removed(tmp_path) -> None:
    young, old = tmp_path / "young.lock", tmp_path / "old.lock"
    young.write_bytes(b"")
    old.write_bytes(b"")
    hour_ago = time.time() - 3600
    os.utime(old, (hour_ago, hour_ago))
    pdf_status._remove_ended_instances(tmp_path)
    assert young.exists() and not old.exists()
