"""The engine matrix check (160, plan F-csak-gpt, Sz0): every JEV call site has a counterpart without JEV.

`configs/engine_matrix.json` lists each JEV call site: the call-site config it uses (`call_site`, if any), the modules
that ask it, and either its counterpart without JEV (`gpt`: the module and function that do the step, GPT or the code)
or an exception of an allowed kind (`exception`: `kind` from `exception_kinds`, and a `reason`), and the tests that
cover it (`tests/<file>.py::<test>`). `routing` names the modules that only route JEV questions or handle their
failures. `problems()` checks four rules, and the preflight reports them:

1. coverage: every `configs/callsites/*.json` is some site's `call_site`, and every module under `jav/` (outside the
   adapter itself and the stand-alone measurement tools) that imports the JEV adapter or asks an adapter (`jev.ask(`, `adapter.ask(`,
   `get_adapter().ask(`) is some site's module or a routing module;
2. a counterpart or an exception: exactly one of the two, the counterpart's module existing, the exception's kind
   allowed and its reason given;
3. tests: at least one, each naming an existing test function;
4. nothing stale: a listed call-site config, module or routing module exists, and a routing module still asks JEV.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from jav.core.config import PROJECT_ROOT

MATRIX_PATH = PROJECT_ROOT / "configs" / "engine_matrix.json"
_ADAPTER_NAMES = {"jev", "adapter"}


def load(path: Path = MATRIX_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _asks_jev(tree: ast.AST) -> bool:
    """The module imports the JEV adapter, or asks an adapter (`jev.ask(`, `adapter.ask(`, `self.adapter.ask(`,
    `get_adapter().ask(`)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module == "jav.ai.jev"
                                                 or (node.module == "jav.ai" and any(a.name == "jev" for a in node.names))):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "ask":
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id in _ADAPTER_NAMES:
                return True
            if isinstance(owner, ast.Attribute) and owner.attr in _ADAPTER_NAMES:
                return True
            if isinstance(owner, ast.Call) and isinstance(owner.func, ast.Name) and owner.func.id == "get_adapter":
                return True
    return False


def jev_modules(root: Path = PROJECT_ROOT) -> set[str]:
    """The modules under `jav/` that ask JEV (rule 1), as repository paths."""
    from jav.runtime.preload import EXCLUDED

    # the JEV adapter itself and the stand-alone measurement tools (208: until then jav/adapters/, jav/experiments/)
    skipped = {"jav/ai/jev.py", *(m.replace(".", "/") + ".py" for m in EXCLUDED)}
    found = set()
    for path in (root / "jav").rglob("*.py"):
        rel = path.relative_to(root)
        if rel.as_posix() in skipped:
            continue
        if _asks_jev(ast.parse(path.read_text(encoding="utf-8"))):
            found.add(rel.as_posix())
    return found


def _test_exists(root: Path, ref: str) -> bool:
    file, _, name = ref.partition("::")
    path = root / file
    return bool(name) and path.is_file() and f"def {name}(" in path.read_text(encoding="utf-8")


def problems(matrix: dict[str, Any] | None = None, root: Path = PROJECT_ROOT) -> list[str]:
    """Every rule broken, as a sentence each; an empty list when the matrix holds."""
    matrix = load() if matrix is None else matrix
    sites: dict[str, dict[str, Any]] = matrix.get("sites") or {}
    routing: dict[str, str] = matrix.get("routing") or {}
    kinds = set(matrix.get("exception_kinds") or {})
    out: list[str] = []

    # 1. coverage
    listed_sites = {s.get("call_site") for s in sites.values()}
    for config in sorted((root / "configs" / "callsites").glob("*.json")):
        if config.stem not in listed_sites:
            out.append(f"call site {config.stem} (configs/callsites/{config.name}) is not in the engine matrix")
    listed_modules = {m for s in sites.values() for m in s.get("modules") or ()} | set(routing)
    asking = jev_modules(root)
    out += [f"{m} asks JEV but is in no site or routing entry of the engine matrix" for m in sorted(asking - listed_modules)]

    for key, site in sorted(sites.items()):
        # 2. a counterpart or an exception
        gpt, exception = site.get("gpt"), site.get("exception")
        if (gpt is None) == (exception is None):
            out.append(f"site {key}: give exactly one of a counterpart without JEV (gpt) and an exception")
        if gpt is not None and not (root / gpt.get("module", "")).is_file():
            out.append(f"site {key}: its counterpart {gpt.get('module')} does not exist")
        if exception is not None:
            if exception.get("kind") not in kinds:
                out.append(f"site {key}: exception kind {exception.get('kind')!r} is not one of {sorted(kinds)}")
            if not (exception.get("reason") or "").strip():
                out.append(f"site {key}: the exception gives no reason")
        # 3. tests
        tests = site.get("tests") or []
        if not tests:
            out.append(f"site {key}: names no covering tests")
        out += [f"site {key}: test {ref} does not exist" for ref in tests if not _test_exists(root, ref)]
        # 4. nothing stale
        call_site = site.get("call_site")
        if call_site and not (root / "configs" / "callsites" / f"{call_site}.json").is_file():
            out.append(f"site {key}: call site {call_site} has no config (configs/callsites/{call_site}.json)")
        out += [f"site {key}: module {m} does not exist" for m in site.get("modules") or () if not (root / m).is_file()]
    for module in sorted(routing):
        if not (root / module).is_file() or module not in asking:
            out.append(f"routing {module} does not exist or no longer asks JEV")
    return out


def status() -> tuple[bool, str]:
    """For the preflight: whether the matrix holds, and a one-line summary."""
    try:
        found = problems()
    except (OSError, ValueError) as exc:
        return False, f"cannot check ({exc})"
    sites = load()["sites"]
    summary = (f"{len(sites)} sites, {sum('gpt' in s for s in sites.values())} with a counterpart without JEV, "
               f"{sum('exception' in s for s in sites.values())} stated exceptions")
    return not found, summary + ("" if not found else "; " + "; ".join(found[:3]) + (" …" if len(found) > 3 else ""))
