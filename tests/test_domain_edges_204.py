"""204 (R1j): a domain never imports another domain's module; it asks a shared registry instead.

Plain-language summary: the shared code already imports no domain (`tests/test_domain_boundary_185.py`), but two
domains still reached into each other: the reconciliation (finance) read the suspicious-attachment to-do code from the
mailbox module (email), and the email routing (email) called the statement package (finance) to add or make a
package. The to-do code now lives with the to-do kinds, and a logic pack takes files through its registry entry. This
test reads every domain module's imports, inside functions too, so a new cross-domain call fails here.

No AI call, no store.
"""

from __future__ import annotations

import ast
from pathlib import Path

from jav.domains import DOMAINS

ROOT = Path(__file__).resolve().parents[1]


def _members() -> dict[str, str]:
    """Each domain module's full name -> its domain's name."""
    import importlib

    owner = {}
    for name in DOMAINS:
        domain = importlib.import_module(name)
        for member in domain.MODULES:
            owner[f"jav.{member}"] = name
    return owner


def _imports(module: str) -> set[str]:
    tree = ast.parse((ROOT / (module.replace(".", "/") + ".py")).read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def test_no_domain_module_imports_another_domains_module():
    owner = _members()
    crossings = sorted(f"{module} -> {target}" for module, domain in owner.items()
                       for target in _imports(module) if owner.get(target, domain) != domain)
    assert crossings == []


def test_the_suspicious_attachment_code_is_a_shared_to_do_kind():
    from jav import todo_kinds

    assert todo_kinds.SUSPICIOUS_ATTACHMENT == "attachment:suspicious_email"
    assert any(k.code == todo_kinds.SUSPICIOUS_ATTACHMENT for k in todo_kinds.kinds())


def test_the_statement_package_takes_files_through_its_registry_entry():
    from jav import logic_packs, registrations

    registrations.load_all()
    pack = logic_packs.of("statements")
    assert pack is not None and pack.take_files is not None and pack.create_with_files is not None
