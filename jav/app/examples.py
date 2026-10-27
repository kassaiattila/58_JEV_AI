"""A process's invented example material (231, stage U, U0; the owner's decisions of 2026-10-27).

Plain-language summary: a person trying a process needs something to try it on. A process pack names its example
material as data (`examples` in `configs/processes/<id>.json`): the sets of versioned things a case of it needs (the
invented product set: its condition documents, rules, tariff and product), and a file of invented documents in packets,
each a few documents a case can start on (`configs/examples_<name>.json`: every document's printed pages, made from a
golden set by `python -m jav.cli examples --write`). From the interface a person installs the material: the machine
makes each thing, so every thing it made reads as an example, and the person makes it active (the four eyes a product
needs); the same material again changes nothing. The material goes in one go while no case keeps any of it; while one
does, the removal is refused, naming the cases. A thing a person made is never removed as an example. A packet's
documents are written as PDFs in a folder beside the store, and a case starts on those files.

- `register(kind, ExampleKind)`: a module that keeps versioned things says how a set of them is shown, installed and
  removed (`jav/app/product_sets.py` registers `product_set`).
- `of(pack_id)`: the material: each set with its state (`installed`, `partial`, `missing`) and whether the machine made
  all of it (`example`), and the packets (id, title, the number of documents).
- `install(pack_id, actor)`, `remove(pack_id, actor)`: the material put in or taken out (`ExampleRefused`; a set a case
  keeps: `ExampleInUse`).
- `packet_files(pack_id, packet_id)`: the packet's documents as PDFs; their paths (`UnknownPacket`).

Layer: application, the shared library; it names no process and no business: what an example holds is the pack's data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jav.app import process_packs
from jav.core import cfg, identity, store
from jav.core.user_messages import explained
from jav.documents.synthetic_pdf import write_unicode_pdf_pages

__all__ = ["DOCUMENTS_PREFIX", "FOLDER", "INSTALLED", "MACHINE", "MISSING", "PARTIAL", "ExampleInUse", "ExampleKind",
           "ExampleRefused", "UnknownPacket", "install", "is_example", "of", "packet_files", "register", "remove"]

DOCUMENTS_PREFIX = process_packs.EXAMPLE_DOCUMENTS
FOLDER = "examples"  # beside the store: <store folder>/examples/<pack>/<packet>/<file>
MACHINE = identity.machine("examples")
INSTALLED, PARTIAL, MISSING = "installed", "partial", "missing"


class ExampleRefused(ValueError):
    """The material cannot be put in or taken out (a set of things a person made, a kind no module registered)."""


class ExampleInUse(ExampleRefused):
    """A case keeps a thing of the material: it stays."""


class UnknownPacket(KeyError):
    """The process has no example packet of this id."""


@dataclass(frozen=True)
class ExampleKind:
    """How a set of one kind of versioned things is shown (`state(name)`: {state, example, title}), installed
    (`install(name, maker, approver)`) and removed (`remove(name, maker_id)`, refusing what a case keeps)."""

    state: Callable[[str], dict[str, Any]]
    install: Callable[[str, identity.Who, identity.Who], None]
    remove: Callable[[str, str], None]


_KINDS: dict[str, ExampleKind] = {}


def register(kind: str, how: ExampleKind) -> None:
    _KINDS[kind] = how


def is_example(made_by_id: str | None) -> bool:
    """Whether a version was made by the examples' machine."""
    return made_by_id == MACHINE.id


def _kind(kind: str) -> ExampleKind:
    from jav.app import registrations

    registrations.load_all()
    if kind not in _KINDS:
        raise explained(ExampleRefused, "no module installs example sets of the kind {{kind}}", kind=kind)
    return _KINDS[kind]


def _examples(pack_id: str) -> process_packs.Examples:
    return process_packs.load(pack_id).examples or process_packs.Examples()


def _packets(examples: process_packs.Examples) -> list[dict[str, Any]]:
    return list(cfg.load(DOCUMENTS_PREFIX + examples.documents)["packets"]) if examples.documents else []


def of(pack_id: str) -> dict[str, Any]:
    """The pack's example material: its sets, each with its state, and its packets of invented documents."""
    examples = _examples(pack_id)
    return {"sets": [{"kind": s.kind, "name": s.name, **_kind(s.kind).state(s.name)} for s in examples.sets],
            "packets": [{"id": p["id"], "title": p["title"], "documents": len(p["documents"])} for p in _packets(examples)]}


def install(pack_id: str, actor: identity.Who) -> dict[str, Any]:
    """Every set of the material made by the machine and made active by `actor`; a set already there is kept."""
    for s in _examples(pack_id).sets:
        _kind(s.kind).install(s.name, MACHINE, actor)
    return of(pack_id)


def remove(pack_id: str, actor: identity.Who) -> dict[str, Any]:
    """Every set of the material taken out, once nothing refuses it (each set checks before it removes anything: a
    case that keeps one of its things, a thing a person made)."""
    del actor  # anyone who may install the examples may take them out; the store keeps no trace of either
    for s in _examples(pack_id).sets:
        _kind(s.kind).remove(s.name, MACHINE.id)
    return of(pack_id)


def packet_files(pack_id: str, packet_id: str) -> list[str]:
    """The packet's documents written as PDFs in `<store folder>/examples/<pack>/<packet>/`; their paths."""
    packet = next((p for p in _packets(_examples(pack_id)) if p["id"] == packet_id), None)
    if packet is None:
        raise UnknownPacket(packet_id)
    folder = Path(store.current_path()).parent / FOLDER / pack_id / packet_id
    folder.mkdir(parents=True, exist_ok=True)
    return [str(write_unicode_pdf_pages(folder / d["file"], d["pages"])) for d in packet["documents"]]
