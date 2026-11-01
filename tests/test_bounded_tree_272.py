"""272 (K5, the rest of TOOL-11): a check past its time limit is stopped with every process it started.

265 (TOOL-11) gave the start-up check's long steps a time limit, but a run past it stopped only the direct child:
the interface checks run through `.cmd` wrappers on Windows, whose node process kept the output pipe open, so the
check still waited for it to end. Now the whole process tree is stopped and the run returns at once. A Python child
that starts a sleeping grandchild holding the pipe; no network.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from jav.devtools import preflight

PARENT = ("import subprocess, sys, time; "
          "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(25)']); "
          "print('started', flush=True); time.sleep(25)")


def test_a_run_past_its_limit_is_stopped_with_its_children(tmp_path: Path) -> None:
    t0 = time.monotonic()
    r = preflight._bounded([sys.executable, "-c", PARENT], timeout=3, cwd=tmp_path)
    took = time.monotonic() - t0
    assert r.returncode == preflight.TIMED_OUT and "started" in r.stdout
    assert took < 15, f"the run waited {took:.0f} s for a child it should have stopped"


def test_a_run_within_its_limit_answers_as_before(tmp_path: Path) -> None:
    r = preflight._bounded([sys.executable, "-c", "print('ok')"], timeout=30, cwd=tmp_path)
    assert (r.returncode, r.stdout.strip()) == (0, "ok")
