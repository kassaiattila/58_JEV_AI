"""Who acts (213, P1a; rule 8 of plan 212 P0): the identity plug-in point.

Plain-language summary: every change to a case records who made it as one small record: a stable id, the name shown,
whether a person or the machine acted, the organisation and the request it came with; a machine acting for a person
names that person too. Today the id comes from the local user name (`local:<name>`); with the company sign-in it will
be the organisation's and the person's stable ids. An email address or a shown name is never the id.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

HUMAN, MACHINE = "human", "machine"
LOCAL = "local"


@dataclass(frozen=True)
class Actor:
    """`id` is stable (`local:<name>` today); `name` is only shown; `on_behalf_of` is the person a machine acts for."""

    id: str
    name: str
    kind: Literal["human", "machine"]
    org: str = LOCAL
    request_id: str | None = None
    on_behalf_of: str | None = None

    def __post_init__(self) -> None:
        if not self.id or ":" not in self.id:
            raise ValueError(f"an actor id is '<namespace>:<id>', not {self.id!r}")
        if self.kind not in (HUMAN, MACHINE):
            raise ValueError(f"an actor is a human or a machine, not {self.kind!r}")

    def as_json(self) -> str:
        return json.dumps({k: v for k, v in asdict(self).items() if v is not None}, sort_keys=True, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> Actor:
        data: dict[str, Any] = json.loads(text)
        return cls(**data)


def person(name: str, *, request_id: str | None = None) -> Actor:
    """A local person by the user name the caller has already put in its canonical form."""
    name = name.strip()
    if not name:
        raise ValueError("a person needs a name")
    return Actor(id=f"{LOCAL}:{name}", name=name, kind=HUMAN, request_id=request_id)


def machine(name: str = "process-core", *, on_behalf_of: Actor | None = None) -> Actor:
    """The machine, acting for itself or for the person who set the work going."""
    return Actor(id=f"machine:{name}", name=name, kind=MACHINE,
                 on_behalf_of=on_behalf_of.id if on_behalf_of is not None else None)
