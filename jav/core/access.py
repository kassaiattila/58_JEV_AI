"""The authorisation check (213, P1a; rule 9 and the plug-in points of plan 212 P0).

Plain-language summary: every operation asks one function whether the actor may do it, naming the operation and,
where there is one, what it acts on. Today there is one local user and the answer is always yes; a company's rules
will answer here later, at the moment of the operation.

229 (plan structure stage 1, SZ2a): moved from the process core to the shared core, so the service's operations ask it
too; what an operation acts on is named generally (`subject`), a case by its id.
"""

from __future__ import annotations

from collections.abc import Callable

from jav.core.identity import Actor

Authorizer = Callable[[Actor, str, str | None], bool]


class NotAuthorised(PermissionError):
    """The actor may not do this operation on this subject."""


_authorizer: Authorizer | None = None


def set_authorizer(fn: Authorizer | None) -> None:
    """Installs the authorisation rule (None: everything is allowed, the local default)."""
    global _authorizer
    _authorizer = fn


def authorize(actor: Actor, action: str, subject: str | None = None) -> None:
    """Raises `NotAuthorised` when the installed rule says no."""
    if _authorizer is not None and not _authorizer(actor, action, subject):
        raise NotAuthorised(f"{actor.id} may not {action}" + (f" on {subject}" if subject else ""))
