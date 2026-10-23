"""The kinds of to-do a processing step can raise, in one registry (177, plan 170 E6).

Plain-language summary: a to-do (a review reason) is a short code such as `pick:low_conf:invoice_number:0.62`; until
now the codes were written in many modules and only the interface's label function knew them all, so a code it did
not know showed raw. `configs/todo_kinds.json` now lists every kind once: its code (the first two parts, as the label
reads it), the whole reason's shape, the modules that raise it, what it means and an example. The interface's label
test checks that every kind's example gets a label (`ui/src/todoKinds177.test.ts`), and the test suite checks that
every to-do a step raises in a test is of a registered kind (`tests/conftest.py`); the before/after replay names the
unregistered kinds it meets. The store accepts any reason, as before (the owner's decision of 2026-10-19).

A kind's code is `<prefix>:<name>`; `<prefix>:*` is a family whose second part varies (each validator check, each JEV
error), `*:<name>` one whose first part is a field (`<field>:unparseable`).

Layer: business module (configuration read; no rule of its own).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from jav.core import cfg

# 204 (R1j): raised by the mailbox (email), read by the reconciliation (finance) and the email routing; a shared code,
# so neither domain imports the other for it
SUSPICIOUS_ATTACHMENT = "attachment:suspicious_email"  # 154 (DECISIONS 154)


@dataclass(frozen=True)
class TodoKind:
    """One kind of to-do: `code` (`<prefix>:<name>`), `shape` (the whole reason), `owners` (the modules that raise it;
    empty: only earlier runs have it), `what` (its meaning) and `example` (one reason of the kind)."""

    code: str
    shape: str
    owners: tuple[str, ...]
    what: str
    example: str


@cache
def kinds() -> tuple[TodoKind, ...]:
    """Every registered kind, in the registry's order."""
    return tuple(TodoKind(code=k["code"], shape=k["shape"], owners=tuple(k["owners"]), what=k["what"],
                          example=k["example"]) for k in cfg.load("todo_kinds")["kinds"])


@cache
def _by_code() -> dict[str, TodoKind]:
    return {k.code: k for k in kinds()}


def code_of(reason: str) -> str:
    """A reason's kind code: its first two parts (`no_invoice` -> `no_invoice:`), as the interface's label reads it."""
    parts = reason.split(":")
    return f"{parts[0]}:{parts[1] if len(parts) > 1 else ''}"


def of(reason: str) -> TodoKind | None:
    """The registered kind of a reason, or None: its own code, else its prefix's family, else its name's family."""
    code = code_of(reason)
    prefix, name = code.split(":", 1)
    by_code = _by_code()
    return by_code.get(code) or by_code.get(f"{prefix}:*") or by_code.get(f"*:{name}")


def unregistered(reasons: list[str]) -> dict[str, str]:
    """The reasons of no registered kind: kind code -> the first such reason."""
    out: dict[str, str] = {}
    for reason in reasons:
        if of(reason) is None:
            out.setdefault(code_of(reason), reason)
    return out


__all__ = ["TodoKind", "code_of", "kinds", "of", "unregistered"]
