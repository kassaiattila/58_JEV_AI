"""A condition document read from its PDF into the registry's form (231, stage U, U-A2; the owner's decisions of
2026-10-27).

Plain-language summary: an insurer publishes a product's terms as condition documents (PDFs). Before a rule can cite a
clause of one, the registry has to hold the document: its kind, title, the day it is in force and its clauses, each with
the page it stands on. This module reads that from the file by code alone: the pages as a rule proposal reads them (the
text layer, else local text recognition, whose numbers a person confirms later; every page, as nothing here goes to a
model), each numbered clause heading at the start of a line ("3.1. Kizárt tevékenységek", "3.1.") becomes a section with
its page and title, in the order printed, and a heading whose number does not come after the one before (a numbered item
in a clause's text, a number printed again in a table of contents) is left to the clause it stands in. The day it is in
force is the first date after the word "hatályos" on the first page, unless given. The machine adds the document to the
registry as a draft (the owner's decision: the system assembles the product, a person makes it active).

- `read(path, kind=, title=, valid_from=)`: the `Imported` document (its content, its pages, what could not be read).
- `sections_of(pages)`: the clause headings of pages given as text, in order.
- `install(ident, imported)`: the document as a draft of the registry, made by the machine; its reference.

Layer: application (it reads the documents layer and writes the product registry); it names no insurer and no product.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from jav.app import product_rules
from jav.app.product_rules import ConditionDocument, Section
from jav.core import dates, identity
from jav.documents import page_text

__all__ = ["MACHINE", "Imported", "install", "read", "sections_of", "valid_from_of"]

MACHINE = identity.machine("condition import")
Kind = Literal["general", "special", "supplementary", "clause"]
# a clause heading starts its line: a number of up to four parts ("3", "3.1", "3.1.2"), its closing dot or not, then
# a title starting with a capital letter, or nothing
_HEADING = re.compile(r"^\s*(?P<clause>\d{1,2}(?:\.\d{1,2}){0,3})\.?(?:\s+(?P<title>[A-ZÁÉÍÓÖŐÚÜŰ].{0,150}?))?\s*$")
_IN_FORCE = re.compile(r"hat[aá]lyos", re.IGNORECASE)


@dataclass(frozen=True)
class Imported:
    content: ConditionDocument
    pages: page_text.DocumentPages
    problems: list[str] = field(default_factory=list)  # what could not be read (the day in force, any clause)


def _key(clause: str) -> tuple[int, ...]:
    return tuple(int(p) for p in clause.split("."))


_LEADER = re.compile(r"\.{5,}|…{2,}")  # a table of contents' dot leaders


def sections_of(pages: dict[int, str]) -> list[Section]:
    """The clause headings of the pages: of every line that looks like one (a table of contents' line, with its dot
    leaders, is none), the longest run whose numbers rise in the order printed, the later of two equally long ones (the
    body over a table of contents); a numbered item in a clause's text or a number printed again falls out. A clause's
    title is the words after its number on the heading's line (a short heading's whole title; the first words of a
    clause whose text starts there)."""
    found: list[Section] = []
    for page in sorted(pages):
        for line in pages[page].splitlines():
            if not _LEADER.search(line) and (m := _HEADING.match(line)) is not None:
                found.append(Section(clause=m.group("clause"), page=page, title=(m.group("title") or "").strip() or None))
    keys = [_key(s.clause) for s in found]
    length = [1] * len(found)
    before: list[int | None] = [None] * len(found)
    for i in range(len(found)):
        for j in range(i):
            if keys[j] < keys[i] and length[j] + 1 >= length[i]:  # `>=`: the later predecessor of two
                length[i], before[i] = length[j] + 1, j
    if not found:
        return []
    end: int | None = max(range(len(found)), key=lambda i: (length[i], i))
    out: list[Section] = []
    while end is not None:
        out.append(found[end])
        end = before[end]
    return out[::-1]


def valid_from_of(first_page: str) -> date | None:
    """The first date after the word "hatályos" on a document's first page (a text recognition's misread letters
    included, as the shared date reader takes them)."""
    m = _IN_FORCE.search(first_page)
    if m is None:
        return None
    hits = dates.find_dates_in(first_page[m.end():m.end() + 120], ocr=True)
    return hits[0].value if hits else None


def read(path: str | Path, *, kind: Kind, title: str, valid_from: date | None = None) -> Imported:
    """A condition document's file read into the registry's form, by code; nothing is written."""
    pages = page_text.read_pages(path)
    problems: list[str] = []
    day = valid_from or valid_from_of(pages.pages.get(1, ""))
    if day is None:
        problems.append("the day it is in force is not printed after 'hatályos' on its first page: give it")
        day = date.min
    sections = sections_of(pages.pages)
    if not sections:
        problems.append("no numbered clause heading was found")
    return Imported(ConditionDocument(kind=kind, title=title, valid_from=day, sections=tuple(sections)), pages, problems)


def install(ident: str, imported: Imported) -> str:
    """The document as the registry's draft, made by the machine (a person makes it active); a draft or version already
    there with the same content is kept. Its reference (`<id>@<n>`)."""
    content = imported.content.model_dump(mode="json")
    latest = product_rules.latest("document", ident)
    if latest is not None and latest["content"] == content:
        return latest["ref"]
    return product_rules.add("document", ident, content, actor=MACHINE)["ref"]

