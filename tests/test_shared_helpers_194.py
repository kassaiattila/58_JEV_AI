"""One clock and one name per error (194, plan G-tidy R2).

Plain-language summary: every stored time is written by one shared clock (`jav/clock.py`) in one form; the modules no
longer carry their own copy of it. These tests keep it that way: no module writes its own `_now` again (the backup
keeps its local time on purpose), and no two modules name their refusal the same.

No AI call, no store: the modules are read as syntax trees.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from jav import clock, fx, package_release, work
from jav.config import PROJECT_ROOT

JAV = PROJECT_ROOT / "jav"

# the backup names its folders and times in the machine's local time, for a person reading them beside its clock
OWN_CLOCK = {"backup.py"}


def _trees() -> list[tuple[Path, ast.Module]]:
    return [(path, ast.parse(path.read_text(encoding="utf-8"))) for path in sorted(JAV.rglob("*.py"))]


def test_a_stored_time_is_utc_to_the_second():
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", clock.utc_stamp())
    assert clock.utc_now().utcoffset().total_seconds() == 0


def test_no_module_writes_its_own_clock():
    own = [str(path.relative_to(JAV)) for path, tree in _trees() if path.name not in OWN_CLOCK
           for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_now"]
    assert own == []


def test_a_module_keeps_its_own_name_for_the_shared_clock():
    # a test can still stop the clock of one module (`monkeypatch.setattr(work, "_now", ...)`)
    assert work._now is clock.utc_stamp
    assert package_release._now is clock.utc_stamp
    assert fx._now is clock.utc_now


def test_no_two_modules_name_an_error_the_same():
    names = Counter(node.name for _path, tree in _trees() for node in tree.body
                    if isinstance(node, ast.ClassDef) and node.name.endswith("Error"))
    assert [name for name, count in names.items() if count > 1] == []
