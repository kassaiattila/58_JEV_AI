"""204 (R1g): the modules of addresses take the shared request handling from `jav/service_shared.py`, not the gateway.

Plain-language summary: the local service's gateway (`jav/api.py`) loads the modules of addresses by theme
(`jav/api_*.py`). Those modules used to take the shared rules (the request body's strictness, the actor check, the path
check, the error answer's shape) from the gateway itself, a hidden loop, and used its private names. The rules now live
in one shared module. These checks keep it so: no module of addresses imports the gateway, and the shared module imports
neither the gateway nor any module of addresses, not even indirectly. No AI call, no store: the modules are read as
syntax trees, and one import runs in a fresh process.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

from jav.config import PROJECT_ROOT

JAV = PROJECT_ROOT / "jav"
THEMES = sorted(JAV.glob("api_*.py"))


def _imports(path: Path) -> set[str]:
    """Every module the file imports, at its top or inside a function (`from jav import x` as `jav.x`)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            if node.module == "jav":
                found |= {f"jav.{a.name}" for a in node.names}
        elif isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
    return found


def _is_service(name: str) -> bool:
    """The gateway or one of its modules of addresses."""
    return name == "jav.api" or name.startswith(("jav.api.", "jav.api_"))


def test_there_are_modules_of_addresses_to_check():
    assert len(THEMES) >= 16
    assert all(p.stem.startswith("api_") for p in THEMES)


def test_no_module_of_addresses_imports_the_gateway():
    found = {p.name: sorted(n for n in _imports(p) if n == "jav.api" or n.startswith("jav.api."))
             for p in THEMES}
    assert {name: names for name, names in found.items() if names} == {}


def test_every_module_of_addresses_takes_the_shared_rules_from_the_shared_module():
    assert [p.name for p in THEMES if "jav.service_shared" not in _imports(p)] == []


def test_the_shared_module_imports_no_service_module():
    assert sorted(n for n in _imports(JAV / "service_shared.py") if _is_service(n)) == []


def test_importing_the_shared_module_loads_no_service_module():
    code = ("import sys, jav.service_shared; "
            "print(sorted(m for m in sys.modules if m == 'jav.api' or m.startswith(('jav.api.', 'jav.api_'))))")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=PROJECT_ROOT, check=True)
    assert done.stdout.strip() == "[]"
