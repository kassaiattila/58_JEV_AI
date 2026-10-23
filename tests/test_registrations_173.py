"""Explicit registration (173, plan 170 E2): what the application registers happens in one call, not on import.

Guarantees tested: importing the registering modules registers nothing; `load_all` registers the two logic packs
(176: the statement package with its rule, the reconciliation package; each with its delete guard), the workflows'
delete guard and (181) the package scopes' one, the four party references (181: the package scopes'), and a second
call adds nothing; the command line, the local service and
the before/after replay call it.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys

from jav import before_after_replay, cli
from jav.app import logic_packs, parties, registrations, work
from jav.core.config import PROJECT_ROOT

_PROBE = """
import json
from jav.app import logic_packs, parties, work
import jav.domains.email.email_routing, jav.app.package_scope, jav.domains.finance.reconcile_package, jav.domains.finance.statement_package, jav.app.workflows
seen = lambda: {"packages": [p.kind for p in logic_packs.packs()], "guards": len(work._DELETE_GUARDS),
                "references": sorted(parties._REFERENCES)}
before = seen()
from jav.app import registrations
registrations.load_all()
registrations.load_all()
print(json.dumps({"before": before, "after": seen()}))
"""


def test_importing_registers_nothing_and_load_all_registers_everything_once() -> None:
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
                         encoding="utf-8")
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    assert seen["before"] == {"packages": [], "guards": 0, "references": []}
    assert seen["after"] == {"packages": ["statements", "reconcile", "email_routing", "quote"], "guards": 2,
                             "references": ["package_scopes", "workflows"]}  # 186: one for every package scope


def test_in_this_process_everything_is_registered() -> None:
    registrations.load_all()  # the test session's own call (conftest) made it already; a repeat changes nothing
    assert [p.kind for p in logic_packs.packs()] == ["statements", "reconcile", "email_routing", "quote"]  # 181, 191
    assert logic_packs.of("statements").rule is not None
    assert len(work._DELETE_GUARDS) == len(set(work._DELETE_GUARDS)) == 2  # 181: the package scopes' too
    assert {"package_scopes", "workflows"} <= set(parties._REFERENCES)  # 186: the logic packs' scopes are the shared one's
    assert not {"reconcile_package", "statement_package"} & set(parties._REFERENCES)


def test_the_entry_points_call_it() -> None:
    from jav import api

    assert "registrations.load_all()" in inspect.getsource(cli.main)
    assert "registrations.load_all()" in inspect.getsource(api.create_app)
    assert "registrations.load_all()" in inspect.getsource(before_after_replay.running_snapshot)
