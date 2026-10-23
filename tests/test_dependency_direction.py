"""The direction of the dependencies between the code's layers (208, plan G-process-core R2).

Plain-language summary: the code is being put into one folder per layer: the shared core, document reading, the AI
questions, the flows, the application (work packages, runs, results, outputs, workflows), the worker, the domains,
the local service and the command line, with the measurement, the developer tools and the port of the legacy project
beside them. A layer may use the layers below it, never the ones above, and a domain never uses another domain. This
test reads every module's imports, inside functions too, and fails on a new import against the direction.
`KNOWN` lists the ones that exist today, each to go with a later step; `NOT_MOVED` names the layer of each module that
is not in its layer's folder yet. Both lists can only shrink: the test also fails when a listed entry has gone.

This replaces the earlier boundary tests: the shared code imports no domain (185), no domain imports another (204,
R1j) and nothing imports the measurement tools (040, K0).

No AI call, no store: the modules are read as syntax trees.
"""

from __future__ import annotations

import ast
import functools
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

# not in its layer's folder yet: module (relative to jav) -> its layer ("domains.<domain>" for a domain's module)
NOT_MOVED = {name: layer for layer, names in {
    "documents": "adapters.azure_di isolated_pdf native_contracts native_results ocr page_image pdf pdf_input readers "
        "readers.__main__ readers.chunks readers.contracts readers.external_recognition "
        "readers.interpretation readers.isolation readers.limits readers.native readers.pipeline "
        "readers.providers readers.receipts readers.visual readers.visual_ocr readers.worker source_layer "
        "synthetic_pdf text_document",
    "ai": "adapters adapters.jev candidates checks detect detect_detail detect_gpt doc_types engine extract_llm "
        "fact_checks gpt_choice grounding jev_budget jev_select jev_verify jev_version legacy_validation "
        "models native_processing party_history policy token_confidence typepack validators",
    "flows": "contract flow flow_detect flow_native runtime.flows runtime.persistence",
    "app": "activity app_settings corrections costs datasets export item_kinds logic_packs naming outputs "
        "outputs.builtin outputs.contract outputs.docx outputs.fill outputs.markers outputs.parts "
        "outputs.samples outputs.templates outputs.xlsx package_release package_result package_scope parties "
        "registrations reground scopes source_instances tablequery work work_readiness work_recipes work_runs "
        "work_views workflow_steps workflows",
    "runtime": "backup deps_audit",
    "service": "api api_items api_outputs api_results api_runs api_settings api_system api_workflows "
        "api_workpackages local_picker picker_dialog service_shared",
    "cli": "cli_options maintenance_cli measure_cli outputs_cli type_teaching_cli work_cli",
    "evals": "before_after before_after_replay eval_report evals evals_detect evals_email evals_facts evals_quotes "
        "experiments experiments.document_injection_probe experiments.extract_cases experiments.jev_estimate "
        "goldens type_teaching",
    "devtools": "admin capability_catalog data_guard docsgen engine_matrix lang_guard preflight",
    "legacy": "legacy_import legacy_packs typepack_convert",
}.items() for name in names.split()}

# imports against the direction today, each with the step that takes it away
KNOWN = {
    # the general data model's page layout moves to the documents layer when the model splits (R2)
    ("jav.ocr", "jav.models"), ("jav.pdf", "jav.models"),
    # reading asks the decision rules for its thresholds, and the native reader's interpretation the AI layer
    ("jav.ocr", "jav.policy"), ("jav.pdf_input", "jav.policy"), ("jav.text_document", "jav.typepack"),
    ("jav.readers.interpretation", "jav.fact_checks"), ("jav.readers.providers", "jav.adapters.jev"),
    # the registries load the domains' registrations themselves
    ("jav.core.activity_kinds", "jav.registrations"), ("jav.checks", "jav.registrations"),
    # the shared decision handler raises the work package's conflict error; a document's reading checks its item
    ("jav.core.decisions", "jav.work"), ("jav.native_results", "jav.item_kinds"), ("jav.ocr", "jav.source_instances"),
    ("jav.party_history", "jav.package_result"),
    # the shared views show the worker's state
    ("jav.work_views", "jav.runtime.worker"),
    # the operations log masks keys with the data guard's patterns
    ("jav.core.applog", "jav.data_guard"),
    # the quote's business modules read the invented price list of its golden set
    ("jav.domains.quotes.quote_letter", "jav.domains.quotes.invented_golden"), ("jav.domains.quotes.quote_match", "jav.domains.quotes.invented_golden"),
}
# imports against the direction for good, each with its reason
LASTING = {
    ("jav.policy", "jav.domains.email.emails"): "the routing rules of every flow are one module with their thresholds (CLAUDE.md §6)",
    ("jav.policy", "jav.domains.email.intents"): "the routing rules of every flow are one module with their thresholds (CLAUDE.md §6)",
}


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
    (208; until then its domain module named them in `MODULES`)."""
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
    if name in NOT_MOVED:
        layer, _, domain = NOT_MOVED[name].partition(".")
        if not domain:
            return layer, None
        parts = [layer, domain]
    else:
        parts = name.split(".")
        if name == "domains":
            return "core", None
        if parts[0] not in ALLOWED:
            raise AssertionError(f"jav/{name.replace('.', '/')} is in no layer's folder and not in NOT_MOVED")
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


def test_every_module_has_a_layer_and_no_listed_one_is_in_its_folder_already():
    for name in MODULES:
        if name:
            _place(name)
    for name, layer in NOT_MOVED.items():
        assert name in MODULES, f"jav.{name} is listed as not moved, but there is no such module"
        folder = MODULES[name].relative_to(JAV).parts
        assert not (len(folder) > 1 and folder[0] == layer.split(".")[0]), f"jav.{name} is in its folder: take it off NOT_MOVED"


def test_no_import_against_the_direction_beyond_the_known_ones():
    against = _against()
    assert against - KNOWN - set(LASTING) == set(), "an import against the direction (use a registry or move the code)"
    assert (KNOWN | set(LASTING)) - against == set(), "these are gone: take them off KNOWN or LASTING"


def test_no_domain_imports_another_domain():
    crossings = {(a, b) for a, b in _against() if _place(a[4:])[1] and _place(b[4:])[1]
                 and _place(a[4:])[1] != _place(b[4:])[1]}
    assert crossings == set()

