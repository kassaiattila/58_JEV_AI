"""Who acts (213, P1a; rule 8 of plan 212 P0): the identity plug-in point.

Plain-language summary: every change records who made it as one small record: a stable id, the name shown, whether a
person or the machine acted, the organisation and the request it came with; a machine acting for a person names that
person too. Today the id comes from the local user name (`local:<name>`); with the company sign-in it will be the
organisation's and the person's stable ids. An email address or a shown name is never the id.

229 (plan structure stage 1, SZ2a): moved from the process core to the shared core, because every layer acts through
it (the service's operations, the human tasks, the decisions), not only the cases.
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

    def __str__(self) -> str:
        """229 (SZ2c-3): printed (a log line, a note), an actor is the name shown; its record is `repr`."""
        return self.name

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


def anonymous() -> Actor:
    """229 (SZ2b): a request that names nobody (a read without a name): who acts is not known; the check decides."""
    return Actor(id="anonymous:request", name="anonymous", kind=HUMAN)


def machine(name: str = "process-core", *, on_behalf_of: Actor | None = None) -> Actor:
    """The machine, acting for itself or for the person who set the work going."""
    return Actor(id=f"machine:{name}", name=name, kind=MACHINE,
                 on_behalf_of=on_behalf_of.id if on_behalf_of is not None else None)


def acting_for(machine_name: str, shown: str, person_: Actor) -> Actor:
    """229 (SZ2c-3): the machine acting for a person (a workflow's automatic step, a scheduled download): the machine's
    id, the name the lists and logs have always shown for it, and the id of the person it acts for."""
    return Actor(id=f"machine:{machine_name}", name=shown, kind=MACHINE, on_behalf_of=person_.id)


# 229 (SZ2c): what a business operation takes as who acts. The service passes the actor its shared entrance knows; a
# bare name (the command line, a test, an internal caller) is a local person of that name.
Who = Actor | str


def who(actor: Who) -> Actor:
    """229 (SZ2c): the actor an operation records beside the name. A name is taken as given, so the id of a row
    written now and of one filled from its name later (`store.add_actor_ids`) are the same: `local:<name>`."""
    if isinstance(actor, Actor):
        return actor
    return Actor(id=f"{LOCAL}:{actor}", name=actor, kind=HUMAN)


def id_of(actor: Who | None) -> str | None:
    """The stable id to store beside the name (None stays None: nobody acted yet)."""
    return None if actor is None else who(actor).id


def name_of(actor: Who | None) -> str | None:
    """The name to store and show (None stays None)."""
    return None if actor is None else who(actor).name


def recorded(name: str, actor_id: str | None) -> Actor:
    """229 (SZ2c): the actor a row recorded (its name and stable id), when code records something again as them (a
    version backfilled with the approver of its runs, a workflow's packages owned by its maker). A row without an id
    is the local person of its name; an id from the machine is the machine's."""
    if actor_id is None:
        return who(name)
    return Actor(id=actor_id, name=name, kind=MACHINE if actor_id.startswith("machine:") else HUMAN)
