"""Every registration the application makes, in one explicit call (173, plan 170 E2).

Plain-language summary: some modules add a rule to the shared code: a package kind's rule that the worker asks after
each item, a check that runs when a package is deleted, and a reference that keeps a party from being deleted while
something names it. Until now a module added these when it was first imported, so a process that happened not to
import it (a command-line command, say) ran without them. Now `load_all()` adds every one of them, and the command
line, the local service and the before/after replay call it when they start; the worker starts through the command
line.

What a module registers is its own `register()` function; a repeated call adds nothing. The tables a module needs are
still registered on import (`store.register_schema`), because a module's tables only matter where the module is used.
176 (plan 170 L3): the statement package and the reconciliation package register as logic packs
(`jav/app/logic_packs.py`), with their rule and their delete guard; a workflow's delete guard is asked for every package.
177 (plan 170 E5): the email domain registers its rule run after every item (an attachment of a suspicious email) and
the mailbox package's part of its page (`jav/app/item_kinds.py`).
180 (plan 170 E7): a domain's registrations are in its domain module (`jav/domains/`): the finance domain's checks,
logic packs, party references and download parts, the email domain's item rule and page part. The check registry and
the output parts registry call `load_all` themselves the first time they are read, so they are complete whichever
module asks first.
181 (plan 170 L5): the workflow step kinds (`jav/app/workflow_steps.py`): the workflows register the documents step, the
finance domain the statements and reconciliation steps, the email domain the emails step. The package scopes
(`jav/app/package_scope.py`): the finance domain registers the package roles, the workflows a step's package's scope, the
package scopes themselves their party reference and the removal of a deleted package's scope.
218 (plan P3 P3b): the modules that register machine decision points on import (`jav.core.trace`) are imported, so the
registry of points is complete in every process.
"""

from __future__ import annotations

import importlib
from typing import Any, Callable

_loaded = False
_loading = False
# 218 (P3b): the modules that register decision points on import (the workflows' are imported by `order`)
DECISION_POINT_MODULES = ("jav.flows.flow_detect", "jav.ai.policy", "jav.documents.ocr", "jav.domains.email.flow_email")


def order(domains: list[Any]) -> list[Callable[[], None]]:
    """The register calls in their order (191: any number of domains): the first domain's, the shared ones (the
    workflows, the package scopes), then each further domain's in `DOMAINS` order. The registries keep the order they
    were given (party references, step kinds, logic packs), and this is the finance-workflows-email order of 180."""
    from jav.app import package_scope, workflows

    first, *others = domains
    return [first.register, workflows.register, package_scope.register, *(domain.register for domain in others)]


def load_all() -> None:
    """Every registration: the finance domain's (its cross-document checks, the statement package and the
    reconciliation package as logic packs with their party references, its parts of the downloads), the workflows'
    delete guard and party reference, then the email domain's item rule and page part, then (191) the quotes
    domain's. Once per process; a repeated or nested call does nothing."""
    global _loaded, _loading
    if _loaded or _loading:
        return
    _loading = True
    try:
        from jav.domains import DOMAINS

        for register in order([importlib.import_module(name) for name in DOMAINS]):
            register()
        for name in DECISION_POINT_MODULES:
            importlib.import_module(name)
        _loaded = True
    finally:
        _loading = False


__all__ = ["DECISION_POINT_MODULES", "load_all", "order"]
