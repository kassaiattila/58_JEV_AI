"""Explicit registration (173, plan 170 E2): what the application registers happens in one call, not on import.

Guarantees tested: importing the registering modules registers nothing; `load_all` registers the statement package's
rule, the three delete guards and the three party references, and a second call adds nothing; the command line, the
local service and the before/after replay call it.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys

from jav import before_after_replay, cli, parties, registrations, work
from jav.config import PROJECT_ROOT

_PROBE = """
import json
from jav import parties, work
import jav.reconcile_package, jav.statement_package, jav.workflows
seen = lambda: {"rules": sorted(work._PACKAGE_RULES), "guards": len(work._DELETE_GUARDS),
                "references": sorted(parties._REFERENCES)}
before = seen()
from jav import registrations
registrations.load_all()
registrations.load_all()
print(json.dumps({"before": before, "after": seen()}))
"""


def test_importing_registers_nothing_and_load_all_registers_everything_once() -> None:
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
                         encoding="utf-8")
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    assert seen["before"] == {"rules": [], "guards": 0, "references": []}
    assert seen["after"] == {"rules": ["statements"], "guards": 3,
                             "references": ["reconcile_package", "statement_package", "workflows"]}


def test_in_this_process_everything_is_registered() -> None:
    registrations.load_all()  # the test session's own call (conftest) made it already; a repeat changes nothing
    assert "statements" in work._PACKAGE_RULES and len(work._DELETE_GUARDS) == len(set(work._DELETE_GUARDS)) == 3
    assert {"reconcile_package", "statement_package", "workflows"} <= set(parties._REFERENCES)


def test_the_entry_points_call_it() -> None:
    from jav import api

    assert "registrations.load_all()" in inspect.getsource(cli.main)
    assert "registrations.load_all()" in inspect.getsource(api.create_app)
    assert "registrations.load_all()" in inspect.getsource(before_after_replay.running_snapshot)
