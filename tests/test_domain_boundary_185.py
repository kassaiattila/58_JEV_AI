"""The boundary between the shared code and the domains (185, plan G-full-move T1).

Plain-language summary: the framework is general; what it knows about invoices, bank statements, the reconciliation,
the utility cost, emails and mailboxes belongs to a domain (`jav/domains/`). These tests list which shared module
still imports a domain's module. Each step of the move takes entries off the temporary list, and the test fails both
when a new import appears and when a listed one has gone, so the list can only shrink. At the end only the lasting
exceptions stay, each with its reason.

No AI call, no store: the modules are read as syntax trees.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from jav.config import PROJECT_ROOT
from jav.domains import DOMAINS

JAV = PROJECT_ROOT / "jav"

# the modules each domain is made of; 191 (plan F-quote-package B1): as its domain module names them (`MODULES`)
MODULES = {name: importlib.import_module(name).MODULES for name in DOMAINS}
DOMAIN = frozenset().union(*MODULES.values())

# shared modules that may import a domain's modules for good: each names every domain at once by its nature
LASTING = {
    "cli": "the command line: one command per operation, a domain's commands among them",
    "docsgen": "writes the generated documents of every flow",
    "evals": "a measurement: the golden runs of every flow",
    "evals_detect": "a measurement: the golden runs of every flow",
    "evals_email": "a measurement: the golden runs of every flow",
    "evals_quotes": "a measurement: the quote request's golden runs (the email flow, the detection and the extraction)",
    "eval_report": "a measurement: the report of every golden run",
    "before_after": "a measurement: the before/after snapshot reads every view",
    "before_after_replay": "a measurement: the replay processes every kind of item",
    "policy": "the routing rules of every flow are one module with their thresholds (CLAUDE.md §6)",
}

# 185: what the move (T1) still had to take away; an entry left this list with its step (empty since T1e)
TEMPORARY: set[tuple[str, str]] = set()


def _module(path: Path) -> str:
    return ".".join(path.relative_to(JAV).with_suffix("").parts)


def _imports(path: Path) -> set[str]:
    """Every `jav` module the file imports, at its top or inside a function."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "jav":
                found |= {a.name for a in node.names}
            elif node.module.startswith("jav."):
                found.add(node.module.removeprefix("jav."))
        elif isinstance(node, ast.Import):
            found |= {a.name.removeprefix("jav.") for a in node.names if a.name.startswith("jav.")}
    return found


def _edges() -> set[tuple[str, str]]:
    edges = set()
    for path in sorted(JAV.rglob("*.py")):
        name = _module(path)
        if "__pycache__" in path.parts or name in DOMAIN or name.startswith("experiments.") or name in LASTING:
            continue
        edges |= {(name, target) for target in _imports(path) if target in DOMAIN}
    return edges


def test_a_shared_module_imports_a_domain_only_where_the_move_has_not_reached_yet() -> None:
    edges = _edges()
    assert edges - TEMPORARY == set(), "a shared module imports a domain's module (register it from the domain instead)"
    assert TEMPORARY - edges == set(), "the move took these away: take them off the temporary list"


def test_every_listed_module_exists() -> None:
    for name in DOMAIN | set(LASTING):
        assert (JAV / (name.replace(".", "/") + ".py")).is_file(), name


def test_each_domain_names_its_own_module_and_no_module_is_in_two_domains() -> None:
    for name, modules in MODULES.items():
        assert name.removeprefix("jav.") in modules, name
    assert sum(len(modules) for modules in MODULES.values()) == len(DOMAIN)
    assert not DOMAIN & set(LASTING)
