"""The scope of a workflow: what it belongs to, made of registered parts (181, plan 170 L5; DECISIONS 181).

Plain-language summary: until now a workflow always belonged to one own party and one period. Now the steps of its
template say what they need: the bank statements and the reconciliation need a party and a period, the documents and
the emails need neither. A template asks for the parts its steps need, and a workflow is made with exactly those
(a part no step needs may still be given, e.g. the period a mailbox step reads its emails by). Each part is registered
once: how a given value is checked and how it is named. Today there are two parts, the own party and the period; a
logic pack that needs another one (a client, a case) registers it, and the store keeps it without a change.

- `register(part)`, `of(name)`, `parts()`: the registry.
- `check(needs, given)`: the scope a workflow is made with: every needed part given and checked (231: or taken from
  its default), the others kept when given and known; an unknown part is refused (`ScopeError`). `asks(needs)`: the
  needed parts a person gives.
- `label(scope)`: the scope in words, in the parts' order (a workflow's default name).

Layer: business module. It names the two parts it registers itself (`jav/app/parties.py` for the party).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from jav.core.user_messages import explained

PARTY = "party"
PERIOD = "period"


class ScopeError(ValueError):
    """A scope that cannot be: a needed part missing, an unknown part, or a value its part refuses."""


@dataclass(frozen=True)
class Part:
    """One part of a scope: its `name`, the registering `module`, `check(value, error)` (the given value in its stored
    form; raises `error`, the caller's own error class), `label(value)` (the stored value in words) and
    `missing(error)`: the error when a workflow needs it and it was not given (each message an interface label,
    `jav/core/user_messages.py`). 231 (C2d): `default(scope)`: the value a needed part takes when it is not given,
    from the parts already checked (None: none for this scope); a part without one must be given."""

    name: str
    module: str
    check: Callable[[Any, type[Exception]], Any]
    label: Callable[[Any], str]
    missing: Callable[[type[Exception]], Exception]
    default: Callable[[Mapping[str, Any]], Any] | None = None


_PARTS: dict[str, Part] = {}
# 231 (C2e): how a needed part follows from the other parts given, said by the domain that knows (a part registered
# here cannot know a later domain's parts): {part: [(module, implied(scope) -> value | None)]}
_IMPLIED: dict[str, list[tuple[str, Callable[[Mapping[str, Any]], Any]]]] = {}


def imply(name: str, module: str, implied: Callable[[Mapping[str, Any]], Any]) -> None:
    """231 (C2e): `implied(scope)` gives the value of the needed part `name` when it is not given, from the parts given
    (None: they do not imply one), e.g. the own party from the accounts a scope names. The same one again adds
    nothing."""
    entries = _IMPLIED.setdefault(name, [])
    if (module, implied) not in entries:
        entries.append((module, implied))


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
    (the caller's own error class, e.g. `workflows.WorkflowError`). 231 (C2d): a needed part with a default that was
    not given takes it from the parts checked before it (in the registry's order); none for this scope is missing.
    231 (C2e): before that, a needed part not given takes the value the given parts imply (`imply`), if they do."""
    needed = list(dict.fromkeys(needs))
    present = {k: v for k, v in given.items() if v is not None}
    for name in [*needed, *present]:
        of(name, error)  # an unknown part is refused
    if missing := [n for n in needed if n not in present and of(n).default is None and n not in _IMPLIED]:
        raise of(missing[0]).missing(error)
    checked = {p.name: p.check(present[p.name], error) for p in _PARTS.values() if p.name in present}
    for p in _PARTS.values():
        if p.name in needed and p.name not in checked:
            for _module, implied in _IMPLIED.get(p.name, ()):
                if (value := implied(dict(checked))) is not None:
                    checked[p.name] = p.check(value, error)
                    break
    for p in _PARTS.values():
        if p.name in needed and p.name not in checked:
            value = p.default(checked) if p.default is not None else None
            if value is None:
                raise p.missing(error)
            checked[p.name] = p.check(value, error)
    return {p.name: checked[p.name] for p in _PARTS.values() if p.name in checked}


def asks(needs: Iterable[str]) -> list[str]:
    """231 (C2d): the needed parts a person gives (those without a default), in the registry's order."""
    needed = set(needs)
    return [p.name for p in _PARTS.values() if p.name in needed and p.default is None]


def label(scope: Mapping[str, Any]) -> str:
    """The scope in words, in the parts' order (empty for an empty scope)."""
    return " ".join(p.label(scope[p.name]) for p in _PARTS.values() if scope.get(p.name) is not None)


# --- the two parts registered here -----------------------------------------------------------------------------------


def _party(value: Any, error: type[Exception]) -> str:
    from jav.app import parties

    for p in parties.parties():
        if p["id"] == value:
            return p["id"]
    raise explained(error, "unknown own party {{party_id}}", party_id=repr(value))


def _party_name(value: str) -> str:
    from jav.app import parties

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


RECORD = "record"  # 231 (A4): the package item a case was started from, read as a record (e.g. a quote request)


def _record(value: Any, error: type[Exception]) -> dict[str, str]:
    if not (isinstance(value, Mapping) and isinstance(value.get("workpackage_id"), str) and value["workpackage_id"]
            and isinstance(value.get("item_id"), str) and value["item_id"]):
        raise explained(error, "the record is named by its work package and item")
    return {"workpackage_id": value["workpackage_id"], "item_id": value["item_id"]}


def _record_words(value: Mapping[str, str]) -> str:
    return f"{value['workpackage_id']} / {value['item_id'][:12]}"


def _no_record(error: type[Exception]) -> Exception:
    return explained(error, "the record a case starts from is missing")


register(Part(PARTY, __name__, _party, _party_name, _no_party))
register(Part(PERIOD, __name__, _period, _period_words, _no_period))


__all__ = ["PARTNERS", "PARTY", "PERIOD", "Part", "RECORD", "SOURCES", "ScopeError", "asks", "check", "imply", "label", "of",
           "parts", "period", "register"]
register(Part(RECORD, __name__, _record, _record_words, _no_record))

PARTNERS = "partners"  # 231 (B1): the partners a case is about, by role ({role: partner_id}; `jav/app/partners.py`)
SOURCES = "sources"  # 231 (C1c): the work packages a case reads its items from (the email routing's email packages)
MAX_SOURCES = 100


def _sources(value: Any, error: type[Exception]) -> list[str]:
    from jav.app import work

    if not (isinstance(value, list) and value and all(isinstance(v, str) and v for v in value)):
        raise explained(error, "the case reads at least one work package")
    chosen = list(dict.fromkeys(value))
    if len(chosen) > MAX_SOURCES:
        raise explained(error, "a case reads at most {{n}} work packages", n=MAX_SOURCES)
    for wp_id in chosen:
        try:
            work.get(wp_id)
        except KeyError as exc:
            raise explained(error, "no work package {{wp_id}}", wp_id=repr(wp_id)) from exc
    return chosen


def _sources_words(value: list[str]) -> str:
    return f"{len(value)} packages"


def _no_sources(error: type[Exception]) -> Exception:
    return explained(error, "the work packages a case reads are missing")


register(Part(SOURCES, __name__, _sources, _sources_words, _no_sources))


def _partners(value: Any, error: type[Exception]) -> dict[str, str]:
    if not (isinstance(value, Mapping) and value and all(isinstance(k, str) and k and isinstance(v, str)
                                                         and v.startswith("partner-") for k, v in value.items())):
        raise explained(error, "the partners are named by their roles")
    return {str(k): str(v) for k, v in value.items()}


def _partners_words(value: Mapping[str, str]) -> str:
    return ", ".join(f"{role}: {pid}" for role, pid in value.items())


def _no_partners(error: type[Exception]) -> Exception:
    return explained(error, "the case names no partner")


register(Part(PARTNERS, __name__, _partners, _partners_words, _no_partners))
