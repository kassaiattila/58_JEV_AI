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
"""

from __future__ import annotations

_loaded = False


def load_all() -> None:
    """Every module's registrations: the statement package and the reconciliation package as logic packs, the
    workflows' delete guard, the party references of all three, and the email domain's item rule and page part. Once
    per process; a repeated call does nothing."""
    global _loaded
    if _loaded:
        return
    from jav import mailbox, reconcile_package, statement_package, workflows

    for module in (statement_package, reconcile_package, workflows, mailbox):
        module.register()
    _loaded = True


__all__ = ["load_all"]
