"""The process core's boundary (229, plan structure stage 1, SZ1b): code outside it uses only what it declares public.

Plain-language summary: each module of the process core lists what other code may use (`__all__`): the operations a
caller makes in its own transaction, the reads, the step and task kinds' registries and the four operations of the
durable workflow engine plug-in point. Code outside the core uses only these, and never names the core's tables in
SQL: it reads them through the core (the rule the domains' tables follow since 211). So the core can change inside,
and the engine behind the plug-in point can be replaced, without touching the code above it. Static checks, no store.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ("jav", "core", "process")
TABLES = re.compile(r"\bprocess_(cases|steps|history|inbox|outbox|claims|tasks|task_history|timers)\b")
SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|JOIN|CREATE TABLE|ALTER TABLE)\b")
# tools that read a store copy of any version, before and after, with their own SQL
SQL_TOOLS = {"jav/devtools/admin.py", "jav/evals/before_after.py"}


def _outside() -> list[Path]:
    return [p for p in sorted((ROOT / "jav").rglob("*.py")) if p.relative_to(ROOT).parts[:3] != CORE]


def _uses(tree: ast.Module) -> dict[str, set[str]]:
    """The names of each core module the file uses: imported from it, or read as an attribute of its alias."""
    alias: dict[str, str] = {}
    used: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "jav.core.process":
            alias |= {a.asname or a.name: a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("jav.core.process."):
            used.setdefault(node.module.rsplit(".", 1)[1], set()).update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            alias |= {a.asname: a.name.rsplit(".", 1)[1] for a in node.names
                      if a.asname and a.name.startswith("jav.core.process.")}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in alias:
            used.setdefault(alias[node.value.id], set()).add(node.attr)
    return used


def test_code_outside_the_core_uses_only_what_its_modules_declare_public() -> None:
    wrong = []
    for path in _outside():
        for module, names in _uses(ast.parse(path.read_text(encoding="utf-8"))).items():
            public = set(importlib.import_module(f"jav.core.process.{module}").__all__)
            wrong += [f"{path.relative_to(ROOT).as_posix()}: {module}.{n}" for n in sorted(names - public)]
    assert wrong == []


def test_every_public_name_of_the_core_exists() -> None:
    for path in sorted((ROOT / "jav" / "core" / "process").glob("*.py")):
        if path.stem == "__init__":
            continue
        module = importlib.import_module(f"jav.core.process.{path.stem}")
        assert [n for n in module.__all__ if not hasattr(module, n)] == [], path.stem


def _strings(tree: ast.Module) -> list[str]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            out.append("".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str)))
    return out


def test_code_outside_the_core_does_not_name_its_tables_in_sql() -> None:
    wrong = []
    for path in _outside():
        rel = path.relative_to(ROOT).as_posix()
        if rel in SQL_TOOLS:
            continue
        wrong += [f"{rel}: {m.group(0)}" for text in _strings(ast.parse(path.read_text(encoding="utf-8")))
                  if SQL.search(text) for m in TABLES.finditer(text)]
    assert wrong == []
