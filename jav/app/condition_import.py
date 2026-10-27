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
_CAPITAL = "A-ZÁÉÍÓÖŐÚÜŰ"
_TITLE = rf"(?:\s*(?P<title>[{_CAPITAL}].{{0,150}}?))?\s*$"
# the numbering styles a clause heading starts its line with, each with its title starting with a capital letter (or
# nothing): a number of up to four parts ("3", "3.1.2", its closing dot or not, "8.3.2.Ellenkező" with no space), a
# Roman chapter with an optional number ("II.", "II. 2."), or a number with a letter ("1/A.")
_STYLES = {
    "number": re.compile(r"^\s*(?P<n>\d{1,2}(?:\.\d{1,2}){0,3})(?:\.|(?=\s|$))" + _TITLE),
    "roman": re.compile(r"^\s*(?P<r>[IVX]{1,5})\.(?:\s*(?P<n>\d{1,2})\.?)?" + _TITLE),
    "letter": re.compile(r"^\s*(?P<n>\d{1,2})/(?P<l>[A-Z])\.?" + _TITLE),
}
# an extension's or a clause's heading that names its own code at the line's end: "… – KIEGÉSZÍTŐ BIZTOSÍTÁS (VIL)"
_CODED = re.compile(r"(?i)(?:kieg[eé]sz[ií]t[oőö]\s+biztos[ií]t[aá]s|z[aá]rad[eé]k)\W{0,4}\((?P<code>[A-Z]{1,3}\d{0,3})\)\s*$")
_ROMAN = {"I": 1, "V": 5, "X": 10}


def _roman(text: str) -> int:
    values = [_ROMAN[ch] for ch in text]
    return sum(-v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values))


_IN_FORCE = re.compile(r"hat[aá]lyos", re.IGNORECASE)


@dataclass(frozen=True)
class Imported:
    content: ConditionDocument
    pages: page_text.DocumentPages
    problems: list[str] = field(default_factory=list)  # what could not be read (the day in force, any clause)


_LEADER = re.compile(r"\.{5,}|…{2,}")  # a table of contents' dot leaders


def _candidates(line: str) -> list[tuple[str, tuple[int, ...], str, str | None]]:
    """The ways a line may head a clause: (style, its order key, its number as named, its title)."""
    out = []
    for style, rx in _STYLES.items():
        if (m := rx.match(line)) is None:
            continue
        title = (m.group("title") or "").strip() or None
        if style == "number":
            out.append((style, tuple(int(p) for p in m.group("n").split(".")), m.group("n"), title))
        elif style == "roman":
            n = m.group("n")
            out.append((style, (_roman(m.group("r")), int(n) if n else 0), m.group("r") + (f".{n}" if n else ""), title))
        else:
            out.append((style, (int(m.group("n")), ord(m.group("l"))), f"{m.group('n')}/{m.group('l')}", title))
    return out


def _rising(found: list[tuple[tuple[int, ...], Section]]) -> list[Section]:
    """The longest run of `found` whose keys rise in the order given, the later of two equally long ones."""
    if not found:
        return []
    length = [1] * len(found)
    before: list[int | None] = [None] * len(found)
    for i in range(len(found)):
        for j in range(i):
            if found[j][0] < found[i][0] and length[j] + 1 >= length[i]:  # `>=`: the later predecessor of two
                length[i], before[i] = length[j] + 1, j
    end: int | None = max(range(len(found)), key=lambda i: (length[i], i))
    out: list[Section] = []
    while end is not None:
        out.append(found[end][1])
        end = before[end]
    return out[::-1]


def sections_of(pages: dict[int, str]) -> list[Section]:
    """The clause headings of the pages. A heading that names its own code (an extension's "… – KIEGÉSZÍTŐ BIZTOSÍTÁS
    (VIL)") starts a part whose clauses are numbered again and named with the code ("VIL 2"). In each part, of every line
    that looks like a heading (a table of contents' line, with its dot leaders, is none), the longest run of one
    numbering style (numbers, Roman chapters, a number with a letter) whose numbers rise in the order printed counts, the
    later of two equally long ones (the body over a table of contents); a numbered item in a clause's text or a number
    printed again falls out. A clause's title is the words after its number on the heading's line (a short heading's
    whole title; the first words of a clause whose text starts there)."""
    parts: list[tuple[str | None, list[tuple[str, tuple[int, ...], Section, int]]]] = [(None, [])]
    order = 0
    for page in sorted(pages):
        for line in pages[page].splitlines():
            if (coded := _CODED.search(line)) is not None:
                parts.append((coded.group("code"), []))
                continue
            if _LEADER.search(line):
                continue
            prefix, found = parts[-1]
            order += 1
            for style, key, number, title in _candidates(line):
                found.append((style, key, Section(clause=f"{prefix} {number}" if prefix else number, page=page, title=title), order))
    out: list[Section] = []
    for _prefix, found in parts:
        at = {id(s): n for _st, _key, s, n in found}
        runs = {style: _rising([(key, s) for st, key, s, _n in found if st == style]) for style in _STYLES}
        chosen = max(runs["number"], runs["roman"], key=len)
        if len(runs["letter"]) >= 2:  # the protection rules' "1/A." points stand beside its numbered annexes
            chosen = sorted(chosen + runs["letter"], key=lambda s: at[id(s)])
        out += chosen
    return out


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

