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
logic packs, party references and download parts, the email domain's item rule and page part. The registries call
`load_all` themselves the first time they are read, so they are complete whichever module asks first: the
application's own ones directly, the shared core's and the AI layer's through the call this module hands over on
import (229, plan structure stage 1, MD1: `jav.core.completion`), so they name no module above them.
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

from jav.core import completion

_loaded = False
_loading = False
# 218 (P3b): the shared modules that register decision points on import (the workflows' are imported by `order`; 229: a
# domain's by its own `register()`)
DECISION_POINT_MODULES = ("jav.flows.flow_detect", "jav.ai.policy", "jav.documents.ocr")
# 229 (MD1): the application modules that register log events, sources of the day's work and decision kinds on import;
# loaded first, so a domain's entry finds the shared one it is placed by (until 229 the activity registry named them)
ACTIVITY_MODULES = ("jav.app.work", "jav.app.package_release", "jav.app.workflows", "jav.app.activity", "jav.app.corrections")


def order(domains: list[Any]) -> list[Callable[[], None]]:
    """The register calls in their order (191: any number of domains): the first domain's, the shared ones (the
    workflows, the package scopes), then each further domain's in `DOMAINS` order. The registries keep the order they
    were given (party references, step kinds, logic packs), and this is the finance-workflows-email order of 180."""
    from jav.app import (approved_document, assessed_units, case_decisions, case_lists, document_processing, evaluation_steps,
                         fact_claims, field_check, letters, lookups, missing_info, package_scope, process_runtime,
                         product_sets, rated_offer, replies, sending, workflows)

    first, *others = domains
    # 231 (A6): the process packs' case container among the shared ones; (A7c, A7d) the general send and reply
    # capabilities; (A7e) the case lists; (C3b2) the document processing capability; (C3b5b) last, the workflow step
    # kinds of the packs that serve one, once every domain registered its package makers
    # D0-c: the priced document of an approved version, general since then
    return [first.register, workflows.register, package_scope.register, process_runtime.register, sending.register,
            replies.register, document_processing.register, approved_document.register, case_lists.register,
            assessed_units.register,  # D-b4: the units a case's step assesses, as a pageable list
            field_check.register,  # D-d2: a person's check of the units, frozen as the checked input
            evaluation_steps.register,  # D-d3: the frozen input's rules evaluated, and its premium computed
            case_decisions.register,  # D-d4: a person's decision on another step's result, a second person above a limit
            lookups.register,  # D-d5: a question to an outside register, its answers offered as facts
            missing_info.register,  # D-d6: waiting for the facts the rules miss, with a task that expires
            fact_claims.register,  # D-f1: the facts a case's processed documents hold, offered to its field check
            rated_offer.register,  # D-f7: a rated offer as a Word document, from an accepted premium
            letters.register,  # D-f8: a letter that goes with a printed document, and its message for the send step
            product_sets.register,  # 231 (U0): a product set installed as a process's example material
            *(domain.register for domain in others), document_processing.register_workflow_steps]


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

        for name in ACTIVITY_MODULES:
            importlib.import_module(name)
        for register in order([importlib.import_module(name) for name in DOMAINS]):
            register()
        for name in DECISION_POINT_MODULES:
            importlib.import_module(name)
        _loaded = True
    finally:
        _loading = False


completion.set_completer(load_all)  # 229 (MD1): the shared registries complete themselves through it


__all__ = ["ACTIVITY_MODULES", "DECISION_POINT_MODULES", "load_all", "order"]
