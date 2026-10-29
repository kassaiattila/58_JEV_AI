"""231 (DECISIONS 231): every process may only use the general capabilities; today's exceptions are a frozen list.

The owner's decision of 2026-10-24 ("at once, fully strict"): a process is a process pack built from registered
capabilities, with no code and no screen of its own. Until stages A–C move today's processes onto process packs, their
process-specific parts are listed here. The list may only shrink: a new entry fails (a new process-specific part was
added), and so does an entry that is gone (the list is updated in the same change, so the progress shows in review).

What counts as process-specific: a logic pack, a workflow step kind or an item part registered by a domain; a domain
in the fixed domain list; a UI folder, file, registry key or create form of one process; a comparison with a process's
name in shared code.

231 (C3e): the interface has the service's domains too (`ui/src/domains/<domain>/`, the last part of each name in
`FROZEN_DOMAINS`). A domain's screens live in its folder and register themselves with the shared registries when the
interface loads; nothing outside the folder imports a domain's module but the interface's start (`main.tsx`, and the
tests' setup), no domain imports another, and a registration of an entry is a domain's.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from jav.app import item_kinds, logic_packs, registrations, workflow_steps

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui" / "src"
# 261: the names of the logic packs and workflow steps before 231, and every process pack's (`configs/processes/`), so
# a new pack is watched too; `documents` is also the name of a store table and a step kind, so it is no process's mark
_GENERAL_WORDS = {"documents"}
PROCESS_NAMES = tuple(sorted({"reconcile", "statements", "email_routing", "routing", "quote", "mailbox"}
                             | {p.stem for p in (ROOT / "configs" / "processes").glob("*.json")} - _GENERAL_WORDS))
UI_PROCESS_DIRS: set[str] = set()  # C1c: routing went; C3e: the quotes' and the reconciliation's moved to their domains' folders
UI_SHARED_DIRS = {"settings", "workflows"}

FROZEN_LOGIC_PACKS: set[str] = set()  # A3d: the quote package went; C1c: the email routing; C3a-2: the reconciliation; C3b5a: the statements
FROZEN_STEP_KINDS: set[str] = set()  # C3d: the emails (the mailbox pack's); C3c: the quote (its pack's); C1c: the routing; C3a-2: the reconciliation; C3b5b: the documents, the statements (their packs')
FROZEN_ITEM_PARTS: set[tuple[str, str]] = set()  # 231 (C1a): the quote request under its email became the general intake
FROZEN_DOMAINS = ("jav.domains.finance", "jav.domains.email", "jav.domains.quotes")
FROZEN_UI_FILES: set[str] = set()  # C3e: every domain's screen moved to its domain's folder
UI_DOMAINS = UI / "domains"  # C3e
UI_DOMAIN_NAMES = {d.rsplit(".", 1)[1] for d in FROZEN_DOMAINS}
UI_DOMAIN_ENTRIES = {"ui/src/main.tsx", "ui/src/test-setup.ts"}  # the interface's start (and the tests') loads the domains
FROZEN_UI_LOGIC_KEYS: set[str] = set()  # A3d: the quote package's went; C1c: the routing's; C3a-2: the reconciliation's; C3b5a: the statements'
FROZEN_UI_PACKAGE_PARTS: set[str] = set()  # C3e: the finance domain registers the statements rule's part
FROZEN_UI_FORMS: set[str] = set()  # C3d: the emails' (the mailbox pack's); C3c: the quote's (its pack's); C1c: the routing's; C2d: the reconciliation's; C3b5a: the documents' and the statements' (their packs')
FROZEN_UI_NAME_COMPARISONS: set[tuple[str, str]] = set()  # C3b5a: the statements' add went to the rule; C3d: the wizard's mailbox
FROZEN_UI_SOURCE_CHOOSERS: set[str] = set()  # C3e: the email domain registers the mailbox's
FROZEN_PY_NAME_COMPARISONS: set[tuple[str, str]] = set()

# C3e: the own parties are the application's (`jav/app/parties.py`, the shared scope part `party`), so a shared module of
# them (`ui/src/api/parties.ts`) is not process-specific; the finance domain's party screens live in its folder
_FILE_NAME = re.compile(r"(reconcil|quote|routing|statement|mail|utility|bankfile|bank_file|pricelist|price_list|finance)", re.I)
_NAMES = "|".join(PROCESS_NAMES)
# 261: a switch's branch names a process as a comparison does
_UI_COMPARISON = re.compile(
    rf"""(?:===?|!==?)\s*["']({_NAMES})["']|["']({_NAMES})["']\s*(?:===?|!==?)|\bcase\s+["']({_NAMES})["']\s*:""")
_IMPORT = re.compile(r"""(?:\bfrom\s+|\bimport\s*\(?\s*)["'](\.[^"']*)["']""")
_REGISTRATION = re.compile(r"(?<!function )(?<![\w.])register[A-Z]\w*(?:<[^>]*>)?\(")  # a call, not a definition or a method
_PY_COMPARISON = re.compile(rf"""(?:==|!=|\bin\b|\bcase)\s*\(?["']({_NAMES})["']""")
_SHARED_PY = ("app", "core", "service", "runtime", "flows", "ai", "documents")


def _same(found: set, frozen: set, what: str) -> None:
    new, gone = sorted(found - frozen), sorted(frozen - found)
    assert not new and not gone, (
        f"{what}: the strict principle (DECISIONS 231) allows no new process-specific part, and the frozen list "
        f"shrinks with every one that goes. New: {new}. Gone (remove from the list): {gone}.")


def _ui_files():
    return (p for p in UI.rglob("*.ts*") if ".test." not in p.name)


def _domain_of(path: Path) -> str | None:
    """The domain whose folder holds the path (None: the shared code, and the domain list `ui/src/domains/index.ts`)."""
    parts = path.relative_to(UI_DOMAINS).parts if path.is_relative_to(UI_DOMAINS) else ()
    return parts[0] if len(parts) > 1 or (parts and (UI_DOMAINS / parts[0]).is_dir()) else None


def _shared(path: Path) -> bool:
    return _domain_of(path) is None and path.parent.name not in UI_PROCESS_DIRS


def _imports(path: Path):
    """The UI modules a file imports by a relative path (statically or on first use), resolved."""
    for m in _IMPORT.finditer(path.read_text(encoding="utf-8")):
        yield (path.parent / m.group(1)).resolve()


@pytest.fixture(scope="module", autouse=True)
def _registered() -> None:
    registrations.load_all()


def test_no_new_logic_pack_step_kind_or_item_part() -> None:
    _same(set(logic_packs._PACKS), FROZEN_LOGIC_PACKS, "logic packs")
    # 231 (C1c): the process packs' own step kind (a case of the pack a step names) is the general one, not an exception
    _same({k.kind for k in workflow_steps.kinds() if k.module != "jav.app.process_runtime"}, FROZEN_STEP_KINDS,
          "workflow step kinds")
    _same(set(item_kinds._ITEM_PARTS), FROZEN_ITEM_PARTS, "item parts")


def test_the_domain_list_does_not_grow() -> None:
    from jav import domains

    assert tuple(domains.DOMAINS) == FROZEN_DOMAINS, "a new domain is a new process-specific module (DECISIONS 231)"


def test_no_new_process_specific_ui_folder_or_file() -> None:
    dirs = {p.name for p in (UI / "views").iterdir() if p.is_dir()}
    assert dirs <= UI_PROCESS_DIRS | UI_SHARED_DIRS, f"a new view folder must be shared or a listed exception: {sorted(dirs)}"
    _same({p.name for p in (UI / "views").iterdir() if p.is_dir() and p.name in UI_PROCESS_DIRS}, UI_PROCESS_DIRS,
          "process-specific view folders")
    found = {p.relative_to(ROOT).as_posix() for p in _ui_files() if _FILE_NAME.search(p.name) and _shared(p)}
    _same(found, FROZEN_UI_FILES, "process-specific UI files outside the domains' and the process folders")


def test_the_ui_domains_are_the_services() -> None:
    """231 (C3e): a folder under `ui/src/domains/` is one of the service's domains (the list does not grow)."""
    dirs = {p.name for p in UI_DOMAINS.iterdir() if p.is_dir()}
    assert dirs <= UI_DOMAIN_NAMES, f"a UI domain folder must be one of the service's domains: {sorted(dirs - UI_DOMAIN_NAMES)}"


def test_shared_ui_code_imports_no_domain_and_no_domain_another() -> None:
    """231 (C3e): the shared code reaches a domain's screens only through the registries the domain fills, so it imports
    no module of a domain's folder (but the interface's start loads the domain list); a domain imports no other."""
    shared = {(p.relative_to(ROOT).as_posix(), i.relative_to(ROOT).as_posix()) for p in UI.rglob("*.ts*")
              if not p.is_relative_to(UI_DOMAINS) and ".test." not in p.name for i in _imports(p) if i.is_relative_to(UI_DOMAINS)}
    assert shared <= {(e, "ui/src/domains") for e in UI_DOMAIN_ENTRIES}, (
        f"shared UI code importing a domain's module (register it from the domain instead): {sorted(shared)}")
    across = sorted((p.relative_to(ROOT).as_posix(), i.relative_to(ROOT).as_posix()) for p in UI_DOMAINS.rglob("*.ts*")
                    if _domain_of(p) for i in _imports(p) if _domain_of(i) not in (None, _domain_of(p)))
    assert not across, f"a UI domain importing another domain: {across}"


def test_shared_ui_code_calls_no_domains_call() -> None:
    """231 (C3e): a domain adds its calls to the shared client (`registerCalls`), typed by declaration merging, so the
    shared code could call one without importing the domain; it calls none (a domain's screen does)."""
    calls = {c for p in UI_DOMAINS.glob("*/api.ts") for block in re.findall(r"^export const \w+Api = \{(.*?)^\};",
             p.read_text(encoding="utf-8"), re.M | re.S) for c in re.findall(r"^  (\w+):", block, re.M)}
    found = sorted((p.relative_to(ROOT).as_posix(), m.group(1)) for p in _ui_files() if _shared(p)
                   for m in re.finditer(r"\bapi\.(\w+)\b", p.read_text(encoding="utf-8")) if m.group(1) in calls)
    assert not found, f"shared UI code calling a domain's call: {found}"


def test_only_a_domain_registers_with_the_shared_registries() -> None:
    """231 (C3e): a registry's entries are the domains' (the shared code defines the registries and keeps its own
    entries in them, but calls no registration)."""
    found = sorted(p.relative_to(ROOT).as_posix() for p in _ui_files() if _shared(p)
                   if _REGISTRATION.search(p.read_text(encoding="utf-8")))
    assert not found, f"shared UI code registering an entry (a domain registers its own): {found}"


def test_no_new_ui_registry_key_or_create_form() -> None:
    registry = (UI / "logic" / "registry.tsx").read_text(encoding="utf-8")
    _same(set(re.findall(r"^\s{2}([a-z_]+): \{", registry, re.M)), FROZEN_UI_LOGIC_KEYS, "UI logic registry keys")
    parts = (UI / "logic" / "packageParts.tsx").read_text(encoding="utf-8")  # C3b5a
    _same(set(re.findall(r"^\s{2}([a-z_]+): \{", parts, re.M)), FROZEN_UI_PACKAGE_PARTS, "UI package parts")
    steps_file = UI / "logic" / "steps.tsx"  # U2c: gone with the new work wizard
    steps = steps_file.read_text(encoding="utf-8") if steps_file.exists() else ""
    forms = set()
    if "const FORMS" in steps:  # C3d: gone, every one-step template is a process pack's case
        block = steps[steps.index("const FORMS"):steps.index("};", steps.index("const FORMS"))]
        forms = set(re.findall(r"^\s{2}([a-z_]+): \(", block, re.M))
    _same(forms, FROZEN_UI_FORMS, "UI create forms")
    choosers = (UI / "elements" / "sourceChoosers.tsx").read_text(encoding="utf-8")
    _same(set(re.findall(r"^\s{2}([a-z_]+): \{", choosers, re.M)), FROZEN_UI_SOURCE_CHOOSERS, "UI source choosers")


def test_shared_code_compares_with_no_new_process_name() -> None:
    ui = {(p.relative_to(ROOT).as_posix(), m.group(1) or m.group(2) or m.group(3)) for p in _ui_files() if _shared(p)
          for m in _UI_COMPARISON.finditer(p.read_text(encoding="utf-8"))}
    _same(ui, FROZEN_UI_NAME_COMPARISONS, "shared UI code comparing with a process name")
    py = {(p.relative_to(ROOT).as_posix(), m.group(1)) for d in _SHARED_PY for p in (ROOT / "jav" / d).rglob("*.py")
          for m in _PY_COMPARISON.finditer(p.read_text(encoding="utf-8"))}
    _same(py, FROZEN_PY_NAME_COMPARISONS, "shared Python code comparing with a process name")


def test_a_domains_capability_has_its_element_from_the_domain() -> None:
    """261: the special screen element of a capability a domain registers is that domain's screen, so the domain
    registers it (`registerElement` in `ui/src/domains/<domain>/`), and the shared registry does not hold it."""
    import json

    from jav.app import capabilities

    elements = json.loads((ROOT / "configs" / "screen_elements.json").read_text(encoding="utf-8"))["elements"]
    shared = (UI / "elements" / "registry.tsx").read_text(encoding="utf-8")
    shared = shared[shared.index("export const ELEMENTS"):shared.index("\n};", shared.index("export const ELEMENTS"))]
    owned = {c.name: c.module.split(".")[2] for c in capabilities.catalogue() if c.module.startswith("jav.domains.")}
    wrong = []
    for key, spec in elements.items():
        if (domain := owned.get(spec.get("capability", ""))) is None:
            continue
        registered = any(f'registerElement("{key}"' in p.read_text(encoding="utf-8") for p in (UI_DOMAINS / domain).rglob("*.ts*"))
        if re.search(rf"^\s*{key}:", shared, re.M) or not registered:
            wrong.append((key, domain))
    assert not wrong, f"a domain capability's element not registered by its domain's folder: {wrong}"


_ROUTE = re.compile(r"""@app\.(get|post|patch|put|delete)\(\s*r\s*\+\s*["']([^"']+)["']""")
_CALL = re.compile(r"""request<[^(]*?>\(\s*["'](GET|POST|PATCH|PUT|DELETE)["']\s*,\s*(`[^`]*`|"[^"]*"|'[^']*')""", re.S)


def test_shared_ui_code_calls_no_domains_address() -> None:
    """261: the shared interface reaches no address a domain of the service serves (`jav/domains/*`, compared by method
    and path), so a domain's calls live in its folder (`ui/src/domains/<domain>/api.ts`) and come through its screens."""
    routes = [(m.group(1).upper(), re.compile(re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(m.group(2))) + "$"), m.group(2))
              for p in (ROOT / "jav" / "domains").rglob("*.py") for m in _ROUTE.finditer(p.read_text(encoding="utf-8"))]
    assert routes, "the domains' addresses were not found (the pattern no longer fits the service's code)"
    found = sorted((p.relative_to(ROOT).as_posix(), path) for p in _ui_files() if _shared(p)
                   for m in _CALL.finditer(p.read_text(encoding="utf-8"))
                   for path in [re.sub(r"\$\{[^}]*\}", "x", m.group(2)[1:-1]).split("?", 1)[0]]
                   if any(method == m.group(1) and rx.match(path) for method, rx, _ in routes))
    assert not found, f"shared UI code calling a domain's address: {found}"
