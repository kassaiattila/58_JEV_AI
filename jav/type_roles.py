"""The roles a document type plays, read from the lists that name them (175, plan 170 E3).

Plain-language summary: whether a document type is an incoming invoice, an outgoing invoice, a bank statement or a
utility invoice, and which checks look at it, is written in several settings files: the reconciliation's lists, the
duplicate search's families, the own-tax-number check, the utility cost report, the issuer and direction checks of
type detection, and the email flow's list. Until now each piece of code read its own list, so a new type left out of
one list silently missed that behaviour. Now the code asks here, and a test checks that the lists agree with each
other (an incoming invoice is also in the duplicate search and the own-tax check, a utility invoice is an incoming
invoice, a bank statement type is a statement, and so on). The settings files themselves do not change.

A role names the list it comes from (`ROLES`). `types(role)` keeps the list's order; `has(doc_type, role)` and
`roles(doc_type)` answer for one type. The duplicate search's families are roles of their own (`duplicate:<family>`).
"""

from __future__ import annotations

from typing import Any

from jav import cfg


class UnknownRole(KeyError):
    """No role is defined under the name."""


def _reconcile(key: str) -> list[str]:
    return list(cfg.load("reconcile")[key])


def _policy(*path: str) -> list[str]:
    node: Any = cfg.load("policy")
    for key in path:
        node = node.get(key, {})
    return list(node or [])


# role -> (where the list is, how it is read); the order is the order `roles()` reports them in
ROLES: dict[str, tuple[str, Any]] = {
    "incoming_invoice": ("reconcile.json invoice_types", lambda: _reconcile("invoice_types")),
    "outgoing_invoice": ("reconcile.json outgoing_types", lambda: _reconcile("outgoing_types")),
    "statement": ("reconcile.json statement_types", lambda: _reconcile("statement_types")),
    "own_tax_check": ("parties.json supplier_check.doc_types", lambda: list(cfg.load("parties")["supplier_check"]["doc_types"])),
    "utility": ("reports.json utility_cost.utilities", lambda: list(cfg.load("reports")["utility_cost"]["utilities"])),
    "hungarian_issuer": ("policy.json detect_issuer.hungarian_types", lambda: _policy("detect_issuer", "hungarian_types")),
    "direction:incoming": ("policy.json detect_detail.direction_sides.incoming",
                           lambda: _policy("detect_detail", "direction_sides", "incoming")),
    "direction:outgoing": ("policy.json detect_detail.direction_sides.outgoing",
                           lambda: _policy("detect_detail", "direction_sides", "outgoing")),
    "email_extraction": ("policy.json email.m2_types", lambda: _policy("email", "m2_types")),
}

DUPLICATE_PREFIX = "duplicate:"


def duplicate_families() -> dict[str, list[str]]:
    """The duplicate search's families in their order (`policy.json` `duplicates.families`): family -> its types."""
    return {name: list(types) for name, types in cfg.load("policy")["duplicates"]["families"].items()}


def names() -> list[str]:
    """Every role: the fixed ones, then one per duplicate family."""
    return [*ROLES, *(DUPLICATE_PREFIX + name for name in duplicate_families())]


def source(role: str) -> str:
    """Where a role's list is written."""
    if role.startswith(DUPLICATE_PREFIX) and role[len(DUPLICATE_PREFIX):] in duplicate_families():
        return f"policy.json duplicates.families.{role[len(DUPLICATE_PREFIX):]}"
    if role not in ROLES:
        raise UnknownRole(f"no type role is defined as {role!r}")
    return ROLES[role][0]


def types(role: str) -> tuple[str, ...]:
    """The types with the role, in the order of its list."""
    if role.startswith(DUPLICATE_PREFIX):
        families = duplicate_families()
        name = role[len(DUPLICATE_PREFIX):]
        if name not in families:
            raise UnknownRole(f"no duplicate family is defined as {name!r}")
        return tuple(families[name])
    if role not in ROLES:
        raise UnknownRole(f"no type role is defined as {role!r}")
    return tuple(ROLES[role][1]())


def has(doc_type: str | None, role: str) -> bool:
    return doc_type is not None and doc_type in types(role)


def roles(doc_type: str | None) -> tuple[str, ...]:
    """Every role of a type, in the order of `names()`."""
    return tuple(r for r in names() if has(doc_type, r))


def duplicate_family(doc_type: str | None) -> str | None:
    """The duplicate family of an invoice-like type; None for any other type."""
    return next((name for name, members in duplicate_families().items() if doc_type in members), None)


def table() -> dict[str, tuple[str, ...]]:
    """Every type named by a role, with its roles (types in the order they are first named)."""
    out: dict[str, tuple[str, ...]] = {}
    for role in names():
        for t in types(role):
            out.setdefault(t, ())
    return {t: roles(t) for t in out}


__all__ = ["DUPLICATE_PREFIX", "ROLES", "UnknownRole", "duplicate_families", "duplicate_family", "has", "names",
           "roles", "source", "table", "types"]
