"""204 (plan G-process-core R1h): a domain's golden sets are described beside its business modules, not inside them.

Plain-language summary: a golden set is a list of cases whose right answer is known in advance, and the shared
measurement command (`measure`) measures every one of them. Until 204 the reconciliation and the quote package described
their golden sets in their own modules, so the code that does the work imported the measurement code, and through it
the measurement runners. Now each domain names separate measurement modules (`GOLDENS` in its domain module), and the
shared command imports them by name, the way the local service adds a domain's service modules. These tests check that
no business module of a domain imports the measurement registry, that the modules a domain names are its own, and that
the command lists the same golden sets, in the same order, as before the move.

No AI call, no store: the modules are read as syntax trees, one import runs in a separate process, and the golden sets
are only listed.
"""

from __future__ import annotations

import ast
import importlib
import json
import subprocess
import sys

from jav.evals import goldens
from jav.core.config import PROJECT_ROOT
from jav.domains import DOMAINS
from tests.test_dependency_direction import domain_modules

JAV = PROJECT_ROOT / "jav"
MODULES = {name: domain_modules(name) for name in DOMAINS}
MEASUREMENT = {name: getattr(importlib.import_module(name), "GOLDENS", ()) for name in DOMAINS}
# every module of the domains but their measurement modules
BUSINESS = sorted(frozenset().union(*MODULES.values())
                  - {m.removeprefix("jav.") for names in MEASUREMENT.values() for m in names})

# the keys `measure --list` printed before the move (commit 1dbf395, with the legacy golden set in place), in its order;
# a golden set added later is added here on purpose
BEFORE = [
    "datapoints:altalanos_szerzodesi_feltetelek:G", "datapoints:belepo_jegy:G", "datapoints:csatorna_szamla:S",
    "datapoints:csatorna_szamla:G", "datapoints:foldgaz_szamla:S", "datapoints:foldgaz_szamla:G",
    "datapoints:invoice_foreign:S", "datapoints:invoice_foreign:G", "datapoints:invoice_foreign:S:synthetic",
    "datapoints:invoice_foreign:G:synthetic", "datapoints:invoice_hu:S", "datapoints:invoice_hu:G",
    "datapoints:invoice_hu:S:synthetic", "datapoints:invoice_hu:G:synthetic", "datapoints:invoice_out:S:synthetic",
    "datapoints:invoice_out:G:synthetic", "datapoints:mohu_szamla:S", "datapoints:mohu_szamla:G",
    "datapoints:villamos_energia_szamla:S", "datapoints:villamos_energia_szamla:G", "datapoints:viz_szamla:S",
    "datapoints:viz_szamla:G", "datapoints:vizmuvek_szamla:S", "datapoints:vizmuvek_szamla:G", "quotes:requests",
    "facts:belepo_jegy", "taught:belepo_jegy_taught:development", "taught:belepo_jegy_taught:evaluation", "types",
    "intents", "quotes:intents", "reconcile:pairs", "reconcile:credit_kinds", "quote:lines", "quote:matches",
    "quote:letters",
]
LOGIC_PACKS = ["reconcile:pairs", "reconcile:credit_kinds", "quote:lines", "quote:matches", "quote:letters"]


def _legacy_only(key: str) -> bool:
    """A golden set that exists only where the legacy golden set is in place (its manifest and documents)."""
    return (key.startswith("datapoints:") and not key.endswith(":synthetic")) or key.startswith(("facts:", "taught:"))


def _imports_goldens(name: str) -> bool:
    """Whether the module imports the measurement registry, at its top or inside a function."""
    path = JAV / (name.replace(".", "/") + ".py")
    path = path if path.is_file() else path.with_suffix("") / "__init__.py"  # 208: a domain's package
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module == "jav.evals" and any(a.name == "goldens" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "jav.evals.goldens":
            return True
        if isinstance(node, ast.Import) and any(a.name == "jav.evals.goldens" for a in node.names):
            return True
    return False


def test_no_business_module_of_a_domain_imports_the_measurement_registry() -> None:
    assert {"quote_package", "quote_pricing", "reconcile_package"} <= {n.rsplit(".", 1)[-1] for n in BUSINESS}
    assert [name for name in BUSINESS if _imports_goldens(name)] == []


def test_the_business_modules_load_without_the_measurement_layer() -> None:
    """Importing the reconciliation and the quote package, and every domain's registrations, loads no measurement code
    (until 204 they loaded the registry, which loads the runners where they measure)."""
    code = ("import json, sys, jav.domains.quotes.quote_package, jav.domains.finance.reconcile_package\n"
            "from jav.app import registrations\n"
            "registrations.load_all()\n"
            "print(json.dumps(sorted(m for m in ('jav.evals.goldens', 'jav.domains.quotes.goldens', 'jav.domains.finance.goldens') "
            "if m in sys.modules)))")
    out = subprocess.run([sys.executable, "-c", code], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
                         encoding="utf-8")
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []


def test_each_domain_names_its_own_measurement_modules() -> None:
    assert MEASUREMENT == {"jav.domains.finance": ("jav.domains.finance.goldens",), "jav.domains.email": (),  # names none
                           "jav.domains.quotes": ("jav.domains.quotes.goldens",)}
    for domain, names in MEASUREMENT.items():
        for name in names:
            assert name.removeprefix("jav.") in MODULES[domain], name
            assert _imports_goldens(name.removeprefix("jav.")), name  # a measurement module is the one that does
    assert goldens.measurement_modules() == ["jav.domains.finance.goldens", "jav.domains.quotes.goldens"]


def test_the_logic_packs_golden_sets_come_from_the_measurement_modules() -> None:
    found = goldens.logic_pack_goldens()
    assert [g.key for g in found] == LOGIC_PACKS
    owner = {"reconcile": "jav.domains.finance.goldens", "quote": "jav.domains.quotes.goldens"}  # 208: each domain's goldens.py
    assert {g.key: g.module for g in found} == {key: owner[key.split(":")[0]] for key in LOGIC_PACKS}
    # 231 (A3d): the quote's are the IT quote process pack's, which names them, under their keys of before
    assert {(g.layer, g.owner) for g in found} == {("logic_pack", "reconcile"), ("process_pack", "it_quote")}


def test_the_registry_lists_the_same_golden_sets_as_before_the_move() -> None:
    keys = [g.key for g in goldens.sets()]
    assert [k for k in keys if not _legacy_only(k)] == [k for k in BEFORE if not _legacy_only(k)]
    assert keys == [k for k in BEFORE if k in set(keys)]  # nothing new, in the same order
    assert keys[-len(LOGIC_PACKS):] == LOGIC_PACKS
