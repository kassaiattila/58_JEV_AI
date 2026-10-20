"""The kinds of a package's items and of a package's source, in one registry (177, plan 170 E5).

Plain-language summary: a work package holds items of three kinds: a document (a file whose type is recognised from
its content), an email (a received message; its attachments are documents of the same package) and a statement read
from a bank's tabular export (one account's lines, read by code). A package that only processes its items comes from
a source of its own kind: a folder, a watched folder, files chosen by hand, an upload or a mailbox (a package that
runs a logic pack has the logic pack's kind instead, `jav/logic_packs.py`). What each kind means to the shared code
is written here once, and the shared code asks this registry instead of naming the kind:
- of an item: whether it is copied when added, whether its result is a document record (data points, a unified name,
  the documents export, the duplicate search), whether its type is recognised from its content (the document flow,
  native reading, the general facts), whether its result is shown on its file's pages, whether its attachments are
  items of the same run, whose to-dos its to-dos are, and under which key the pre-start overview counts it;
- of a source: whether the package was read from a folder, and what the package's page adds for it.

Code that handles an email itself (its view, the correction of its intent, its export sheet, its title, the mailbox)
belongs to the email domain and names the kind by `EMAIL`.

A domain may add a rule that runs after every item of a run (`ItemRule`), and a part of a package's page for a source
kind (`register_page`); both through its domain module's `register()`, called by `registrations.load_all`. Each kind
names the module that owes them (`rules_from`, `page_from`): the email domain's rule that marks the attachments of a
suspicious email, and the mailbox package's missing attachments (180: `jav/domains/email.py`; the work itself in
`jav/mailbox.py`). Asking for them before that module registered is an error (`NotRegistered`), so a process that
missed `load_all` stops instead of skipping a safety rule.

185 (plan G-full-move T1e): a kind whose result is not a document record names the module that shows and corrects
its items (`handler_from`, `ItemHandler`: the email domain's message, intent and tasks); a domain may add a part to a
record item's result (`RecordPart`: the finance domain's duplicate pairs and statement replacements), so the shared
review code names neither.

An item or a source of a kind the registry does not know is refused (`UnknownItemKind`, `UnknownSourceKind`).

Layer: business module (the registry; no rule of its own). It imports no application module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DOCUMENT, EMAIL, STATEMENT_TABLE = "document", "email", "statement_table"


class UnknownItemKind(ValueError):
    """An item of a kind the registry does not know."""


class UnknownSourceKind(LookupError):
    """A package source of a kind the registry does not know."""


class NotRegistered(RuntimeError):
    """A kind's rules or page part were asked for before the module that owes them registered them."""


def _document_subject(item: Mapping[str, Any]) -> tuple[str, str]:
    return "document", item["item_id"]


def _email_subject(item: Mapping[str, Any]) -> tuple[str, str]:
    """An email's to-dos are the message's: its identifier is the name of the email's folder (written by the receiver
    and used by the email flow, 048 T2)."""
    return "email", Path(item["source_path"]).parent.name


@dataclass(frozen=True)
class ItemKind:
    """One kind of item (`workpackage_items.kind`).

    - `copied`: its file is copied into the source instance store when it is added (an email is hashed in place: it is
      the system's own copy already).
    - `record`: its result is a document record: data points, a unified name, the documents export, the duplicate
      search.
    - `detected`: its type is recognised from its content: the document flow, a recipe's routing by file suffix,
      native reading and the general facts.
    - `page_image`: its result is shown on the pages of its file (a statement read from a table has none).
    - `attachments`: its attachments are items of the same run, and its flow reads them (an email's PDFs).
    - `by_code`: it is read by code alone, so its result names no AI engine (a statement read from a table, 136).
    - `subject(item)`: the subject of its to-dos (`work.review_subject`).
    - `plan_key`: the key the pre-start overview counts it under (`work.run_plan`); `plan_always`: the key is there
      even at 0 (a statement table is counted only when there is one).
    - `rules_from`: the module that registers the rules run after its items (`ItemRule`), if any.
    - `handler_from`: 185: the module that registers how one of its items is shown and corrected (`ItemHandler`), for a
      kind whose result is not a document record.
    """

    name: str
    what: str
    copied: bool
    record: bool
    detected: bool
    page_image: bool
    attachments: bool
    subject: Callable[[Mapping[str, Any]], tuple[str, str]]
    plan_key: str
    plan_always: bool = True
    by_code: bool = False
    rules_from: str | None = None
    handler_from: str | None = None


@dataclass(frozen=True)
class SourceKind:
    """One kind of source of a package that only processes its items (`workpackages.source_kind`).

    - `folder`: the package's source reference is the folder it was read from (its subfolders title the items).
    - `page_from`: the module that registers the source's part of the package's page (`register_page`), if any.
    """

    name: str
    what: str
    folder: bool = False
    page_from: str | None = None


@dataclass(frozen=True)
class ItemRule:
    """A rule run after every item of a run, in the order registered, after the package kind's own rule.
    `after_item(run, item)` returns whether it raised a to-do (the item then ends as needing review). `kind`: the item
    kind that owes the rule (its `rules_from` registers it); it runs for every item, because an email's attachment is
    a document."""

    kind: str
    name: str
    module: str
    after_item: Callable[[dict[str, Any], dict[str, Any]], bool]


@dataclass(frozen=True)
class ItemHandler:
    """185 (plan G-full-move T1e): how the review page shows and a person corrects an item of a kind whose result is
    not a document record. `result(run, item, engine)`: the item's result as the page shows it; `correct(run_id, item,
    *, fields, expected_revision, actor, note, sources, confirm)`: a person's correction, returning the new one."""

    kind: str
    module: str
    result: Callable[..., dict[str, Any]]
    correct: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class RecordPart:
    """185 (plan G-full-move T1e): a part a domain adds to a record item's result, after the shared ones, in the order
    registered: `build(item_id, reasons)` with the item's open to-dos (this run's, then the earlier runs')."""

    name: str
    module: str
    build: Callable[[str, list[dict[str, Any]]], Any]


ITEM_KINDS: tuple[ItemKind, ...] = (
    ItemKind(DOCUMENT, "a file whose type is recognised from its content", copied=True, record=True, detected=True,
             page_image=True, attachments=False, subject=_document_subject, plan_key="documents"),
    ItemKind(EMAIL, "a received message; its attachments are documents of the same package", copied=False,
             record=False, detected=False, page_image=False, attachments=True, subject=_email_subject,
             plan_key="emails", rules_from="jav.domains.email", handler_from="jav.domains.email"),
    ItemKind(STATEMENT_TABLE, "one account's statement read from a bank's tabular export, by code (136)", copied=True,
             record=True, detected=False, page_image=False, attachments=False, subject=_document_subject,
             plan_key="statement_tables", plan_always=False, by_code=True),
)

SOURCE_KINDS: tuple[SourceKind, ...] = (
    SourceKind("folder", "the documents of a folder", folder=True),
    SourceKind("upload", "uploaded files"),
    SourceKind("mailbox", "the messages of a mailbox download, with their PDF attachments", page_from="jav.domains.email"),
    SourceKind("manual", "files chosen by hand, or the accounts of a bank's tabular export"),
    SourceKind("watch", "the new documents of a watched folder", folder=True),
)

_ITEMS = {k.name: k for k in ITEM_KINDS}
_SOURCES = {s.name: s for s in SOURCE_KINDS}
_RULES: dict[str, ItemRule] = {}
_PAGES: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {}
_HANDLERS: dict[str, ItemHandler] = {}
_RECORD_PARTS: dict[str, RecordPart] = {}
_REGISTERED: set[str] = set()


def names() -> tuple[str, ...]:
    """Every item kind's name, in the registry's order."""
    return tuple(_ITEMS)


def of(item: Mapping[str, Any] | str) -> ItemKind:
    """The kind of an item (or of a kind's name); `UnknownItemKind` for a kind the registry does not know."""
    name = item if isinstance(item, str) else item.get("kind")
    try:
        return _ITEMS[name]  # type: ignore[index]
    except KeyError:
        raise UnknownItemKind(f"unknown item kind: {name}") from None


def check(kinds: list[str]) -> None:
    """Refuses item kinds the registry does not know, every one of them named (sorted)."""
    if unknown := sorted({k for k in kinds if k not in _ITEMS}):
        raise UnknownItemKind(f"unknown item kind: {', '.join(unknown)}")


def source_names() -> tuple[str, ...]:
    """Every source kind's name: the work package kinds that only process their own items."""
    return tuple(_SOURCES)


def source(kind: str) -> SourceKind:
    try:
        return _SOURCES[kind]
    except KeyError:
        raise UnknownSourceKind(f"unknown package source kind: {kind}") from None


def _owed(owner: str | None, what: str) -> None:
    if owner is not None and owner not in _REGISTERED:
        raise NotRegistered(f"{owner} has not registered its {what} (was registrations.load_all called?)")


def register_rule(rule: ItemRule) -> None:
    """Registers a rule run after every item; the same one again adds nothing, another of the same name is an
    error."""
    if of(rule.kind).rules_from != rule.module:
        raise ValueError(f"item rule {rule.name!r}: the {rule.kind} kind's rules come from {of(rule.kind).rules_from}")
    known = _RULES.get(rule.name)
    if known is not None and known != rule:
        raise ValueError(f"item rule {rule.name!r} is registered already by {known.module}")
    _RULES[rule.name] = rule
    _REGISTERED.add(rule.module)


def rules() -> list[ItemRule]:
    """Every rule run after an item, in the order registered. `NotRegistered` while a kind's module owes its rules."""
    for kind in ITEM_KINDS:
        _owed(kind.rules_from, f"{kind.name} item rules")
    return list(_RULES.values())


def register_page(kind: str, module: str, page: Callable[[Mapping[str, Any]], dict[str, Any]]) -> None:
    """Registers a source kind's part of a package's page: `page(wp)` returns the parts it adds."""
    if source(kind).page_from != module:
        raise ValueError(f"the {kind} source's page part comes from {source(kind).page_from}")
    known = _PAGES.get(kind)
    if known is not None and known != page:
        raise ValueError(f"the {kind} source's page part is registered already")
    _PAGES[kind] = page
    _REGISTERED.add(module)


def page(wp: Mapping[str, Any]) -> dict[str, Any]:
    """A package's parts of its page that its source kind adds (a mailbox package: its missing attachments); empty for
    a source that adds none. `NotRegistered` while the source's module owes its part."""
    kind = source(wp["source_kind"])
    _owed(kind.page_from, f"{kind.name} page part")
    part = _PAGES.get(kind.name)
    return part(wp) if part is not None else {}


def register_handler(handler: ItemHandler) -> None:
    """185: registers how an item of a kind is shown and corrected; only the module the kind names may."""
    if of(handler.kind).handler_from != handler.module:
        raise ValueError(f"the {handler.kind} kind's handler comes from {of(handler.kind).handler_from}")
    known = _HANDLERS.get(handler.kind)
    if known is not None and known != handler:
        raise ValueError(f"the {handler.kind} kind's handler is registered already")
    _HANDLERS[handler.kind] = handler
    _REGISTERED.add(handler.module)


def handler(item: Mapping[str, Any] | str) -> ItemHandler | None:
    """185: how an item of a kind whose result is not a document record is shown and corrected; None for a record kind.
    `NotRegistered` while the kind's module owes it."""
    kind = of(item)
    if kind.handler_from is None:
        return None
    _owed(kind.handler_from, f"{kind.name} item handler")
    return _HANDLERS[kind.name]


def register_record_part(part: RecordPart) -> None:
    """185: a domain's part of a record item's result; the same one again adds nothing, another of the same name is an
    error."""
    known = _RECORD_PARTS.get(part.name)
    if known is not None and known != part:
        raise ValueError(f"record part {part.name!r} is registered already by {known.module}")
    _RECORD_PARTS[part.name] = part


def record_parts() -> list[RecordPart]:
    """185: the domains' parts of a record item's result, in the order registered; the registry completes itself the
    first time it is read (`registrations.load_all`)."""
    from jav import registrations

    registrations.load_all()
    return list(_RECORD_PARTS.values())


__all__ = ["DOCUMENT", "EMAIL", "ITEM_KINDS", "ItemHandler", "ItemKind", "ItemRule", "NotRegistered", "RecordPart",
           "SOURCE_KINDS", "STATEMENT_TABLE", "SourceKind", "UnknownItemKind", "UnknownSourceKind", "check", "handler",
           "names", "of", "page", "record_parts", "register_handler", "register_page", "register_record_part",
           "register_rule", "rules", "source", "source_names"]
