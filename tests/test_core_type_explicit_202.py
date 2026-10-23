"""The shared core takes the document type explicitly (202, plan G-core-generalisation M1a).

Plain-language summary: the Hungarian invoice was the first reference flow, and the shared code used to fall back on it
whenever a caller named no type. These tests keep that from coming back: no function of the shared code has a type pack
as its default, the type pack loader needs a key, and the JEV call sites have no module-level Hungarian invoice site.
Old data saved before the type was recorded is read through one named constant (`LEGACY_DOC_TYPE`), never as a
processing default. The command line keeps the reference flow as its `--type` default, named in one place
(`cli_options.REFERENCE_TYPE`).

No AI call, no store: the modules are read as syntax trees.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from jav.ai import jev_select, jev_verify, policy, typepack
from jav.core.config import PROJECT_ROOT

JAV = PROJECT_ROOT / "jav"

# experiments are not runtime code
SKIP_DIRS = {"experiments", "__pycache__"}


def _shared_files() -> list[Path]:
    return [p for p in sorted(JAV.rglob("*.py")) if not SKIP_DIRS & set(p.relative_to(JAV).parts)]


def _type_defaults(path: Path, keys: set[str]) -> list[str]:
    """The function parameters of the file whose default is a type pack key or a name standing for one."""
    found: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        args = node.args
        positional = args.posonlyargs + args.args
        pairs = list(zip(positional[len(positional) - len(args.defaults):], args.defaults))
        pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None]
        for arg, default in pairs:
            literal = isinstance(default, ast.Constant) and default.value in keys
            named = isinstance(default, (ast.Name, ast.Attribute)) and ast.unparse(default).split(".")[-1] in {"DEFAULT_KEY", "LEGACY_DOC_TYPE"}
            if literal or named:
                found.append(f"{path.relative_to(JAV)}:{default.lineno} {arg.arg}={ast.unparse(default)}")
    return found


def test_no_shared_function_defaults_to_a_type_pack():
    keys = set(typepack.keys())
    found = [hit for path in _shared_files() for hit in _type_defaults(path, keys)]
    assert found == []


def test_the_type_pack_loader_needs_a_key():
    assert not hasattr(typepack, "DEFAULT_KEY")
    assert inspect.signature(typepack.get).parameters["key"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        typepack.get()  # type: ignore[call-arg]


def test_old_data_names_its_type_through_one_constant():
    assert typepack.LEGACY_DOC_TYPE == "invoice_hu"
    assert typepack.LEGACY_DOC_TYPE in typepack.keys()


@pytest.mark.parametrize("module", [jev_select, jev_verify])
def test_the_jev_call_sites_have_no_module_level_invoice_site(module):
    names = {"_DEFAULT", "CONFIG_HASH", "GLOSSARY", "FIELD_SPECS", "PRESENCE_WHAT", "INSTRUCTIONS", "REQUEST_FIELDS"}
    assert names.isdisjoint(vars(module))
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    module_calls = [ast.unparse(n.value) for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign)) and isinstance(n.value, ast.Call)]
    assert not [c for c in module_calls if c.startswith("site_for(")]


def test_the_policy_reads_the_pack_of_the_named_type():
    assert not hasattr(policy, "HIGH_STAKES") and not hasattr(policy, "REQUIRED")
    assert policy.high_stakes_for("invoice_foreign") == frozenset(typepack.get("invoice_foreign").high_stakes)
