"""The direction of the dependencies between the code's layers (208, plan G-process-core R2).

Plain-language summary: the code is in one folder per layer: the shared core, document reading, the AI questions, the
flows, the application (work packages, runs, results, outputs, workflows), the worker, the domains, the local service
and the command line, with the measurement, the developer tools and the port of the legacy project beside them. A
layer may use the layers below it, never the ones above, and a domain never uses another domain. This test reads every
module's imports, inside functions too, and fails on a new import against the direction and on a module outside the
layers' folders. `KNOWN` lists the imports against the direction that exist today, each to go with a later step; it
can only shrink: the test also fails when a listed entry has gone. (Until the move was finished, a list named the
layer of each module not yet in its folder.)

This replaces the earlier boundary tests: the shared code imports no domain (185), no domain imports another (204,
R1j) and nothing imports the measurement tools (040, K0).

No AI call, no store: the modules are read as syntax trees.
"""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

JAV = Path(__file__).resolve().parents[1] / "jav"

# the stack, lowest first: a layer may import its own and the ones before it
LAYERS = ("core", "documents", "ai", "flows", "app", "runtime", "domains", "service", "cli")
# beside the stack: a measurement reads anything but the command line; the developer tools read the measurements too;
# the legacy port uses only the core, the documents and the AI layer. Only the command line imports them (and a
# domain's golden sets, the measurement's part of a domain).
BESIDE = {
    "evals": (*LAYERS[:-1], "evals", "legacy"),
    "devtools": (*LAYERS[:-1], "evals", "devtools", "legacy"),
    "legacy": ("core", "documents", "ai", "legacy"),
}
ALLOWED = {layer: (*LAYERS[: i + 1], *(("evals", "devtools", "legacy") if layer == "cli" else ())) for i, layer in
           enumerate(LAYERS)} | BESIDE

# imports against the direction today, each with the step that takes it away. 229 (plan structure stage 1, MD1): none
# left: the value checks and the source instances are the documents layer's, the JEV check of the native facts the AI
# layer's, and the shared registries, the native result and the role-swap check get what the application knows through
# what it hands over when it is loaded (`jav.core.completion`, `native_results.set_document_check`,
# `party_history.set_results`).
KNOWN: set[tuple[str, str]] = set()
# imports against the direction for good, each with its reason (224: the shared decision rules no longer import the
# email domain; its routes are the domain's own, `jav/domains/email/email_rules.py`)
LASTING: dict[tuple[str, str], str] = {}


def _modules() -> dict[str, Path]:
    """Every module under jav, by its dotted name relative to jav (a package by its own name)."""
    found = {}
    for path in JAV.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts = path.relative_to(JAV).with_suffix("").parts
        found[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = path
    return found


MODULES = _modules()


def domain_modules(domain: str) -> frozenset[str]:
    """The modules a domain (`jav.domains.<name>`) is made of, relative to jav: its package and the modules in its folder
    (208; until then its domain module named them, `MODULES`)."""
    name = domain.removeprefix("jav.")
    return frozenset(m for m in MODULES if m == name or m.startswith(name + "."))


def _resolve(dotted: str) -> str | None:
    """The longest module that a dotted name relative to jav starts with."""
    parts = dotted.split(".")
    for i in range(len(parts), 0, -1):
        if ".".join(parts[:i]) in MODULES:
            return ".".join(parts[:i])
    return None


@functools.cache
def _imports(name: str) -> frozenset[str]:
    """Every jav module the module imports, at its top or inside a function."""
    path = MODULES[name]
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")[: len(package.split(".")) - node.level + 1] if package else []
                module = ".".join([*base, *([node.module] if node.module else [])])
            elif node.module == "jav" or (node.module or "").startswith("jav."):
                module = node.module[4:]
            else:
                continue
            for alias in node.names:
                target = _resolve(f"{module}.{alias.name}" if module else alias.name) or _resolve(module)
                if target:
                    found.add(target)
        elif isinstance(node, ast.Import):
            found |= {t for a in node.names if a.name.startswith("jav.") and (t := _resolve(a.name[4:]))}
    return frozenset(found - {name, ""})


def _place(name: str) -> tuple[str, str | None]:
    """A module's layer and its domain (None outside the domains). A domain's addresses of the local service
    (`api_*`), its commands (`*_cli`) and its golden sets (`*golden`, `*goldens`) follow the rules of the service, the
    command line and the measurement layer; the package of the domains itself is only their list."""
    parts = name.split(".")
    if name == "domains":
        return "core", None
    if parts[0] not in ALLOWED or len(parts) == 1 and not MODULES[name].name == "__init__.py":
        raise AssertionError(f"{MODULES[name].relative_to(JAV.parent).as_posix()} is in no layer's folder")
    if parts[0] != "domains":
        return parts[0], None
    leaf = name.rsplit(".", 1)[-1]
    role = ("service" if leaf.startswith("api_") else "cli" if leaf.endswith("_cli")
            else "evals" if leaf.endswith(("golden", "goldens")) else "domains")
    return role, parts[1]


@functools.cache
def _against() -> frozenset[tuple[str, str]]:
    edges = set()
    for name in MODULES:
        if not name:
            continue
        layer, domain = _place(name)
        for target in _imports(name):
            other_layer, other_domain = _place(target)
            crossing = domain and other_domain and domain != other_domain
            if crossing or other_layer not in ALLOWED[layer]:
                edges.add((f"jav.{name}", f"jav.{target}"))
    return frozenset(edges)


def test_every_module_is_in_a_layers_folder():
    for name in MODULES:
        if name:
            _place(name)
    assert sorted(p.name for p in JAV.glob("*.py")) == ["__init__.py"]


def test_no_import_against_the_direction_beyond_the_known_ones():
    against = _against()
    assert against - KNOWN - set(LASTING) == set(), "an import against the direction (use a registry or move the code)"
    assert (KNOWN | set(LASTING)) - against == set(), "these are gone: take them off KNOWN or LASTING"


def test_no_domain_imports_another_domain():
    crossings = {(a, b) for a, b in _against() if _place(a[4:])[1] and _place(b[4:])[1]
                 and _place(a[4:])[1] != _place(b[4:])[1]}
    assert crossings == set()


# --- the tables (209, plan G-process-core R2c) ------------------------------------------------------------------------

_SQL_TABLE = re.compile(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+(\w+)")
_CREATED = re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+(\w+)")


@functools.cache
def _tables() -> dict[str, str]:
    """Every table by the module that creates it."""
    owners: dict[str, list[str]] = {}
    for name, path in MODULES.items():
        for table in _CREATED.findall(path.read_text(encoding="utf-8")):
            owners.setdefault(table, []).append(name)
    assert {t: m for t, m in owners.items() if len(m) > 1} == {}, "a table is created in one module only"
    return {table: modules[0] for table, modules in owners.items()}


def test_a_domains_tables_are_named_by_its_own_modules_and_the_measurement_only():
    """A shared module or another domain reaches a domain's tables through the domain's registrations, never by naming
    them in its SQL (the measurement, the developer tools and the command line may read any table)."""
    found = set()
    for name, path in MODULES.items():
        layer, domain = _place(name) if name else ("core", None)
        if layer in ("evals", "devtools", "cli", "legacy"):
            continue
        for table in set(_SQL_TABLE.findall(path.read_text(encoding="utf-8"))) & set(_tables()):
            owner = _place(_tables()[table])[1]
            if owner and owner != domain:
                found.add((f"jav.{name}", table))
    assert found == set()


def test_the_email_tables_belong_to_the_email_domain():
    """209 (R2c): until then the shared store created them."""
    assert {t: _tables()[t] for t in ("emails", "email_results", "email_task_decisions")} == dict.fromkeys(
        ("emails", "email_results", "email_task_decisions"), "domains.email.email_store")


# --- 229 (MD1): a lower layer names no module of a higher layer as text --------------------------------------------

_DOTTED = re.compile(r"(?<!-m )\bjav\.([a-z_]+)(?:\.[a-z_]+)*")


def _strings(tree: ast.Module) -> list[tuple[int, str]]:
    """The module's strings that are not docstrings (a module named in a description is no reference)."""
    docs = {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body
            and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs]


def test_a_lower_layer_names_no_module_of_a_higher_layer_as_text():
    """An import by name (`importlib.import_module("jav.domains....")`, a registry entry naming the module that owes it)
    is a dependency the import test cannot see; the layer above registers itself instead. A command line in a message
    (`python -m jav.cli ...`) names no module to import."""
    wrong = []
    for name, path in sorted(MODULES.items()):
        layer = name.split(".")[0]
        if layer not in LAYERS:
            continue
        for line, text in _strings(ast.parse(path.read_text(encoding="utf-8"))):
            for m in _DOTTED.finditer(text):
                target = m.group(1)
                if target in LAYERS and LAYERS.index(target) > LAYERS.index(layer) and target not in ALLOWED[layer]:
                    wrong.append(f"{name}:{line}: {m.group(0)}")
    assert wrong == []
