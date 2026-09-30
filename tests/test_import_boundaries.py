"""Dependency direction (CLAUDE.md §4): runtime code does not import experimental code (040, K0)."""

import ast
from pathlib import Path

JAV = Path(__file__).resolve().parents[1] / "jav"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):  # imports inside functions (deferred) are checked too
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_runtime_modules_do_not_import_experiments():
    runtime = [p for p in JAV.rglob("*.py") if "experiments" not in p.relative_to(JAV).parts]
    offenders = {p.relative_to(JAV).as_posix(): sorted(i for i in _imports(p) if i.startswith("jav.experiments"))
                 for p in runtime}
    assert {k: v for k, v in offenders.items() if v} == {}
