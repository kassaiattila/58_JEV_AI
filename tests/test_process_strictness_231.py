"""231 (DECISIONS 231): every process may only use the general capabilities; today's exceptions are a frozen list.

The owner's decision of 2026-10-24 ("at once, fully strict"): a process is a process pack built from registered
capabilities, with no code and no screen of its own. Until stages A–C move today's processes onto process packs, their
process-specific parts are listed here. The list may only shrink: a new entry fails (a new process-specific part was
added), and so does an entry that is gone (the list is updated in the same change, so the progress shows in review).

What counts as process-specific: a logic pack, a workflow step kind or an item part registered by a domain; a domain
in the fixed domain list; a UI folder, file, registry key or create form of one process; a comparison with a process's
name in shared code.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from jav.app import item_kinds, logic_packs, registrations, workflow_steps

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui" / "src"
PROCESS_NAMES = ("reconcile", "statements", "email_routing", "routing", "quote", "mailbox")
UI_PROCESS_DIRS = {"quotes", "reconcile", "routing"}
UI_SHARED_DIRS = {"settings", "workflows"}

FROZEN_LOGIC_PACKS = {"email_routing", "quote", "reconcile", "statements"}
FROZEN_STEP_KINDS = {"documents", "emails", "quote", "reconcile", "routing", "statements"}
FROZEN_ITEM_PARTS = {("email", "quote_request")}
FROZEN_DOMAINS = ("jav.domains.finance", "jav.domains.email", "jav.domains.quotes")
FROZEN_UI_FILES = {
    "ui/src/api/finance.ts", "ui/src/api/quotes.ts", "ui/src/review/StatementPanel.tsx", "ui/src/views/BankFiles.tsx",
    "ui/src/views/Mailbox.tsx", "ui/src/views/StatementPackageCreate.tsx", "ui/src/views/StatementPackagePanel.tsx",
    "ui/src/views/UtilityReport.tsx", "ui/src/views/settings/PartiesPanel.tsx", "ui/src/views/settings/PriceListsPanel.tsx",
}
FROZEN_UI_LOGIC_KEYS = {"email_routing", "quote", "reconcile", "statements"}
FROZEN_UI_FORMS = {"documents", "emails", "quote", "reconcile", "routing", "statements"}
FROZEN_UI_NAME_COMPARISONS = {("ui/src/views/PackageItems.tsx", "statements"), ("ui/src/views/WorkpackageActions.tsx", "statements"),
                              ("ui/src/views/workflows/NewWork.tsx", "mailbox")}
FROZEN_PY_NAME_COMPARISONS: set[tuple[str, str]] = set()

_FILE_NAME = re.compile(r"(reconcil|quote|routing|statement|mailbox|utility|bankfile|bank_file|parties|pricelist|price_list|finance)", re.I)
_NAMES = "|".join(PROCESS_NAMES)
_UI_COMPARISON = re.compile(rf"""(?:===?|!==?)\s*["']({_NAMES})["']|["']({_NAMES})["']\s*(?:===?|!==?)""")
_PY_COMPARISON = re.compile(rf"""(?:==|!=|\bin\b)\s*\(?["']({_NAMES})["']""")
_SHARED_PY = ("app", "core", "service", "runtime", "flows", "ai", "documents")


def _same(found: set, frozen: set, what: str) -> None:
    new, gone = sorted(found - frozen), sorted(frozen - found)
    assert not new and not gone, (
        f"{what}: the strict principle (DECISIONS 231) allows no new process-specific part, and the frozen list "
        f"shrinks with every one that goes. New: {new}. Gone (remove from the list): {gone}.")


def _ui_files():
    return (p for p in UI.rglob("*.ts*") if ".test." not in p.name)


@pytest.fixture(scope="module", autouse=True)
def _registered() -> None:
    registrations.load_all()


def test_no_new_logic_pack_step_kind_or_item_part() -> None:
    _same(set(logic_packs._PACKS), FROZEN_LOGIC_PACKS, "logic packs")
    _same({k.kind for k in workflow_steps.kinds()}, FROZEN_STEP_KINDS, "workflow step kinds")
    _same(set(item_kinds._ITEM_PARTS), FROZEN_ITEM_PARTS, "item parts")


def test_the_domain_list_does_not_grow() -> None:
    from jav import domains

    assert tuple(domains.DOMAINS) == FROZEN_DOMAINS, "a new domain is a new process-specific module (DECISIONS 231)"


def test_no_new_process_specific_ui_folder_or_file() -> None:
    dirs = {p.name for p in (UI / "views").iterdir() if p.is_dir()}
    assert dirs <= UI_PROCESS_DIRS | UI_SHARED_DIRS, f"a new view folder must be shared or a listed exception: {sorted(dirs)}"
    _same({p.name for p in (UI / "views").iterdir() if p.is_dir() and p.name in UI_PROCESS_DIRS}, UI_PROCESS_DIRS,
          "process-specific view folders")
    found = {p.relative_to(ROOT).as_posix() for p in _ui_files()
             if _FILE_NAME.search(p.name) and p.parent.name not in UI_PROCESS_DIRS}
    _same(found, FROZEN_UI_FILES, "process-specific UI files outside the process folders")


def test_no_new_ui_registry_key_or_create_form() -> None:
    registry = (UI / "logic" / "registry.tsx").read_text(encoding="utf-8")
    _same(set(re.findall(r"^\s{2}([a-z_]+): \{", registry, re.M)), FROZEN_UI_LOGIC_KEYS, "UI logic registry keys")
    steps = (UI / "logic" / "steps.tsx").read_text(encoding="utf-8")
    block = steps[steps.index("FORMS"):steps.index("};", steps.index("FORMS"))]
    _same(set(re.findall(r"^\s{2}([a-z_]+): \(", block, re.M)), FROZEN_UI_FORMS, "UI create forms")


def test_shared_code_compares_with_no_new_process_name() -> None:
    ui = {(p.relative_to(ROOT).as_posix(), m.group(1) or m.group(2)) for p in _ui_files() if p.parent.name not in UI_PROCESS_DIRS
          for m in _UI_COMPARISON.finditer(p.read_text(encoding="utf-8"))}
    _same(ui, FROZEN_UI_NAME_COMPARISONS, "shared UI code comparing with a process name")
    py = {(p.relative_to(ROOT).as_posix(), m.group(1)) for d in _SHARED_PY for p in (ROOT / "jav" / d).rglob("*.py")
          for m in _PY_COMPARISON.finditer(p.read_text(encoding="utf-8"))}
    _same(py, FROZEN_PY_NAME_COMPARISONS, "shared Python code comparing with a process name")
