"""181 (backlog J-preflight-friss-tar): the state snapshot of a fresh store.

A process that never loaded the work package module (the start-up check's state snapshot) has no runs table in a
fresh store, and the snapshot's count of open to-dos by the kind of run that raised them failed there (`no such
table: runs`). Without the runs table every open reason counts as raised without a run, and the snapshot is written.
"""

from __future__ import annotations

import json
import subprocess
import sys

from jav.core.config import PROJECT_ROOT

_PROBE = """
import json, sys
from pathlib import Path
from jav import admin
from jav.core import store
with store.use_store(Path(sys.argv[1])):
    store.review_enqueue(subject_kind="document", subject_id="d" * 64, run_id="cli-x", reasons=["needs:look"])
    counts = admin.reasons_by_run_kind()
    admin.write_state(Path(sys.argv[2]))
print(json.dumps({"counts": counts, "work_loaded": "jav.app.work" in sys.modules}))
"""


def test_a_fresh_store_without_the_runs_table_gets_its_snapshot(tmp_path) -> None:
    out = subprocess.run([sys.executable, "-c", _PROBE, str(tmp_path / "fresh.sqlite"), str(tmp_path / "STATE.md")],
                         cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr[-2000:]
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    assert seen["counts"] == {"live": 0, "trial": 0, "no_run": 1}
    assert (tmp_path / "STATE.md").is_file()
