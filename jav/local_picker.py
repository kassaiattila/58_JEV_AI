"""The operating system's own folder and file pickers for the local UI (081, F-mappa-tallózás).

The local service and the browser run on the same machine (the service listens on the loopback address only), so the
service can open the system's picker and hand the chosen path back to the UI; a path can still be typed instead.

- The dialog runs in a separate Python process (`jav/picker_dialog.py`): the window toolkit needs its own main thread,
  and a dialog nobody closes must not hold the service.
- One dialog is open at a time; a second request gets `PickerBusy`.
- A dialog left open longer than `picker.timeout_s` (`configs/service.json`) is closed and counts as cancelled.
- Where no dialog can open (no window toolkit, no desktop session), `PickerUnavailable` names it, and the UI asks for
  the path to be typed.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path

from jav import cfg
from jav.config import PROJECT_ROOT

log = logging.getLogger("jav.local_picker")

_LOCK = threading.Lock()
_run = subprocess.run  # the dialog process; replaced by a fake runner in the tests


class PickerBusy(RuntimeError):
    """Another picker dialog is already open."""


class PickerUnavailable(RuntimeError):
    """The picker cannot open on this machine (no window toolkit or no desktop session)."""


def pick_folder(*, title: str, initial: str | None = None) -> str | None:
    """The folder chosen in the system's folder picker, or None when cancelled."""
    chosen = _ask("folder", title, initial)
    return chosen[0] if chosen else None


def pick_files(*, title: str, initial: str | None = None) -> list[str]:
    """The files chosen in the system's file picker (PDFs offered first; several can be chosen); empty when cancelled."""
    return _ask("files", title, initial)


def _start_folder(initial: str | None) -> str | None:
    """Where the dialog opens: the given folder, or the folder of a given file; nothing for a missing path."""
    if not initial or not initial.strip():
        return None
    p = Path(initial.strip().strip('"'))
    try:
        if p.is_dir():
            return str(p)
        if p.is_file():
            return str(p.parent)
    except OSError:
        pass
    return None


def _timeout() -> float:
    return float(cfg.load("service").get("picker", {}).get("timeout_s", 600))


def _ask(kind: str, title: str, initial: str | None) -> list[str]:
    if not _LOCK.acquire(blocking=False):
        raise PickerBusy("a picker dialog is already open")
    try:
        request = {"kind": kind, "title": title, "initial": _start_folder(initial)}
        args = [sys.executable, "-X", "utf8", "-m", "jav.picker_dialog", json.dumps(request, ensure_ascii=False)]
        extra = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
        try:
            done = _run(args, capture_output=True, text=True, encoding="utf-8", timeout=_timeout(), cwd=PROJECT_ROOT,
                        **extra)
        except subprocess.TimeoutExpired:
            log.warning("the %s picker was left open past the time limit; counted as cancelled", kind)
            return []
        if done.returncode != 0:
            tail = (done.stderr or "").strip().splitlines()[-1:] or ["no message"]
            raise PickerUnavailable(f"the {kind} picker cannot open on this machine: {tail[0][:300]}")
        lines = [line for line in (done.stdout or "").splitlines() if line.strip()]
        try:
            chosen = json.loads(lines[-1]) if lines else []
        except ValueError as exc:
            raise PickerUnavailable(f"the {kind} picker gave no readable answer") from exc
        return [str(Path(c)) for c in chosen if isinstance(c, str) and c]
    finally:
        _LOCK.release()


__all__ = ["PickerBusy", "PickerUnavailable", "pick_files", "pick_folder"]
