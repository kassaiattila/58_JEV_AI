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
(`jav/logic_packs.py`), with their rule and their delete guard; a workflow's delete guard is asked for every package.
177 (plan 170 E5): the email domain registers its rule run after every item (an attachment of a suspicious email) and
the mailbox package's part of its page (`jav/item_kinds.py`).
180 (plan 170 E7): a domain's registrations are in its domain module (`jav/domains/`): the finance domain's checks,
logic packs, party references and download parts, the email domain's item rule and page part. The check registry and
the output parts registry call `load_all` themselves the first time they are read, so they are complete whichever
module asks first.
181 (plan 170 L5): the workflow step kinds (`jav/workflow_steps.py`): the workflows register the documents step, the
finance domain the statements and reconciliation steps, the email domain the emails step.
"""

from __future__ import annotations

import importlib

_loaded = False
_loading = False


def load_all() -> None:
    """Every registration: the finance domain's (its cross-document checks, the statement package and the
    reconciliation package as logic packs with their party references, its parts of the downloads), the workflows'
    delete guard and party reference, then the email domain's item rule and page part. Once per process; a repeated
    or nested call does nothing."""
    global _loaded, _loading
    if _loaded or _loading:
        return
    _loading = True
    try:
        from jav import workflows
        from jav.domains import DOMAINS

        finance, email = (importlib.import_module(name) for name in DOMAINS)
        for register in (finance.register, workflows.register, email.register):
            register()
        _loaded = True
    finally:
        _loading = False


__all__ = ["load_all"]
