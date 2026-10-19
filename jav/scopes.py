"""The scope of a workflow: what it belongs to, made of registered parts (181, plan 170 L5; DECISIONS 181).

Plain-language summary: until now a workflow always belonged to one own party and one period. Now the steps of its
template say what they need: the bank statements and the reconciliation need a party and a period, the documents and
the emails need neither. A template asks for the parts its steps need, and a workflow is made with exactly those
(a part no step needs may still be given, e.g. the period a mailbox step reads its emails by). Each part is registered
once: how a given value is checked and how it is named. Today there are two parts, the own party and the period; a
logic pack that needs another one (a client, a case) registers it, and the store keeps it without a change.

- `register(part)`, `of(name)`, `parts()`: the registry.
- `check(needs, given)`: the scope a workflow is made with: every needed part given and checked, the others kept when
  given and known; an unknown part is refused (`ScopeError`).
- `label(scope)`: the scope in words, in the parts' order (a workflow's default name).

Layer: business module. It names the two parts it registers itself (`jav/parties.py` for the party).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from jav.user_messages import explained

PARTY = "party"
PERIOD = "period"


class ScopeError(ValueError):
    """A scope that cannot be: a needed part missing, an unknown part, or a value its part refuses."""


@dataclass(frozen=True)
class Part:
    """One part of a scope: its `name`, the registering `module`, `check(value, error)` (the given value in its stored
    form; raises `error`, the caller's own error class), `label(value)` (the stored value in words) and
    `missing(error)`: the error when a workflow needs it and it was not given (each message an interface label,
    `jav/user_messages.py`)."""

    name: str
    module: str
    check: Callable[[Any, type[Exception]], Any]
    label: Callable[[Any], str]
    missing: Callable[[type[Exception]], Exception]


_PARTS: dict[str, Part] = {}


def register(part: Part) -> None:
    """Registers a part; the same one again adds nothing, another one of the same name is an error."""
    known = _PARTS.get(part.name)
    if known is not None and known != part:
        raise ValueError(f"scope part {part.name!r} is registered already by {known.module}")
    _PARTS[part.name] = part


def of(name: str, error: type[Exception] = ScopeError) -> Part:
    try:
        return _PARTS[name]
    except KeyError:
        raise explained(error, "unknown scope part {{name}}", name=repr(name)) from None


def parts() -> list[Part]:
    return list(_PARTS.values())


def check(needs: Iterable[str], given: Mapping[str, Any], *, error: type[Exception] = ScopeError) -> dict[str, Any]:
    """The scope made of `given` ({part: value}, a missing or None value is not given): every part in `needs` must be
    given; each given part is checked by its own part; the result is in the registry's order. A refusal raises `error`
    (the caller's own error class, e.g. `workflows.WorkflowError`)."""
    needed = list(dict.fromkeys(needs))
    present = {k: v for k, v in given.items() if v is not None}
    for name in [*needed, *present]:
        of(name, error)  # an unknown part is refused
    if missing := [n for n in needed if n not in present]:
        raise of(missing[0]).missing(error)
    return {p.name: p.check(present[p.name], error) for p in _PARTS.values() if p.name in present}


def label(scope: Mapping[str, Any]) -> str:
    """The scope in words, in the parts' order (empty for an empty scope)."""
    return " ".join(p.label(scope[p.name]) for p in _PARTS.values() if scope.get(p.name) is not None)


# --- the two parts registered here -----------------------------------------------------------------------------------


def _party(value: Any, error: type[Exception]) -> str:
    from jav import parties

    for p in parties.parties():
        if p["id"] == value:
            return p["id"]
    raise explained(error, "unknown own party {{party_id}}", party_id=repr(value))


def _party_name(value: str) -> str:
    from jav import parties

    return next((p["name"] for p in parties.parties() if p["id"] == value), value)


def period(start: Any, end: Any, error: type[Exception] = ScopeError) -> tuple[str, str]:
    """A period: two ISO dates, the first not after the second (until 181 `workflows._period`)."""
    try:
        a, b = date.fromisoformat(str(start)), date.fromisoformat(str(end))
    except ValueError as exc:
        raise explained(error, "a period is two dates (YYYY-MM-DD): {{exc}}", exc=exc) from exc
    if a > b:
        raise explained(error, "the period ends before it starts")
    return a.isoformat(), b.isoformat()


def _period(value: Any, error: type[Exception]) -> tuple[str, str]:
    start, end = value
    return period(start, end, error)


def _period_words(value: tuple[str, str]) -> str:
    return f"{value[0]} – {value[1]}"


def _no_party(error: type[Exception]) -> Exception:
    return explained(error, "the workflow needs an own party")


def _no_period(error: type[Exception]) -> Exception:
    return explained(error, "the workflow needs a period")


register(Part(PARTY, __name__, _party, _party_name, _no_party))
register(Part(PERIOD, __name__, _period, _period_words, _no_period))


__all__ = ["PARTY", "PERIOD", "Part", "ScopeError", "check", "label", "of", "parts", "period", "register"]
