"""The kinds of a package's items and of a package's source, in one registry (177, plan 170 E5).

Plain-language summary: a work package holds items of three kinds: a document (a file whose type is recognised from
its content), an email (a received message; its attachments are documents of the same package) and a statement read
from a bank's tabular export (one account's lines, read by code). A package that only processes its items comes from
a source of its own kind: a folder, a watched folder, files chosen by hand, an upload or a mailbox (a package that
runs a logic pack has the logic pack's kind instead, `jav/app/logic_packs.py`). What each kind means to the shared code
is written here once, and the shared code asks this registry instead of naming the kind:
- of an item: whether it is copied when added, whether its result is a document record (data points, a unified name,
  the documents export, the duplicate search), whether its type is recognised from its content (the document flow,
  native reading, the general facts), whether its result is shown on its file's pages, whether its attachments are
  items of the same run, whose to-dos its to-dos are, and under which key the pre-start overview counts it;
- of a source: whether the package was read from a folder, and what the package's page adds for it.

Code that handles an email itself (its view, the correction of its intent, its export sheet, its title, the mailbox)
belongs to the email domain and names the kind by `EMAIL`.

A domain may add a rule that runs after every item of a run (`ItemRule`), and a part of a package's page for a source
kind (`register_page`); both through its domain module's `register()`, called by `registrations.load_all`. A kind a
domain owns (`owned`) is claimed by that domain's module (`claim`, `claim_source`; 229, plan structure stage 1, MD1:
until then the kind named the module), and only the claimant registers its rules and page part: the email domain's rule
that marks the attachments of a suspicious email, and the mailbox package's missing attachments (180:
`jav/domains/email/__init__.py`; the work itself in `jav/domains/email/mailbox.py`). Asking for them before that module
claimed the kind and registered them is an error (`NotRegistered`), so a process that missed `load_all` stops instead of
skipping a safety rule.

185 (plan G-full-move T1e): a kind whose result is not a document record is shown and corrected by its claimant's
handler (`ItemHandler`: the email domain's message, intent and tasks); a domain may add a part to a record item's result
(`RecordPart`: the finance domain's duplicate pairs and statement replacements), so the shared review code names
neither.

An item or a source of a kind the registry does not know is refused (`UnknownItemKind`, `UnknownSourceKind`).

Layer: business module (the registry; no rule of its own). It imports no application module.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jav.documents import native_results

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
    - `subject(item)`: the subject of its to-dos (`work_runs.review_subject`).
    - `plan_key`: the key the pre-start overview counts it under (`work_readiness.run_plan`); `plan_always`: the key is there
      even at 0 (a statement table is counted only when there is one).
    - `owned`: 229 (plan structure stage 1, MD1): a domain owns the kind (`claim`): the module that claims it registers
      the rules run after its items (`ItemRule`) and how one of its items is shown and corrected (`ItemHandler`, 185);
      until 229 the kind named that module (`rules_from`, `handler_from`).
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
    owned: bool = False


@dataclass(frozen=True)
class SourceKind:
    """One kind of source of a package that only processes its items (`workpackages.source_kind`).

    - `folder`: the package's source reference is the folder it was read from (its subfolders title the items).
    - `owned`: 229 (MD1): a domain owns the source (`claim_source`): the module that claims it registers the source's
      part of the package's page (`register_page`); until 229 the source named that module (`page_from`).
    """

    name: str
    what: str
    folder: bool = False
    owned: bool = False


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
    *, fields, expected_revision, actor, note, sources, confirm)`: a person's correction, returning the new one;
    `titles(items)`: the list's titles of its items and of their attachments (by item id); `parent_labels(items)`: the
    label of each of its items an attachment came from, for the documents' source column (by item id).

    209 (plan G-process-core R2c): what another domain reads of an item's stored result, so that it names none of the
    kind's tables. `reading(flow_run_id, c)`: what the item was read as (`read_as`: an email's intent), its `title`,
    `sender` and `received_at` (None before the run saved it); `found_as(value, c)`: (package, item) of every item a
    run read as `value`."""

    kind: str
    module: str
    result: Callable[..., dict[str, Any]]
    correct: Callable[..., dict[str, Any]]
    titles: Callable[[list[dict[str, Any]]], dict[str, str]]
    parent_labels: Callable[[list[dict[str, Any]]], dict[str, str]]
    reading: Callable[[str, Any], dict[str, Any] | None]
    found_as: Callable[[str, Any], list[tuple[str, str]]]


@dataclass(frozen=True)
class RecordPart:
    """185 (plan G-full-move T1e): a part a domain adds to a record item's result, after the shared ones, in the order
    registered: `build(item_id, reasons)` with the item's open to-dos (this run's, then the earlier runs')."""

    name: str
    module: str
    build: Callable[[str, list[dict[str, Any]]], Any]


@dataclass(frozen=True)
class ItemPart:
    """192 (plan F-quote-package B6a): a part a domain adds to the result of another kind's item (the quotes domain's
    request under an email): `build(run, item)` returns it, or None when the item has none; the parts present go under
    the result's `parts`, by name. The item's own domain names no other domain this way."""

    name: str
    module: str
    kind: str
    build: Callable[[dict[str, Any], dict[str, Any]], Any]


@dataclass(frozen=True)
class ItemExtra:
    """192 (plan F-quote-package B6c): units of a parameter-bound budget extra an item of a kind carries, as its domain
    counts them (`count(item)`: an email's table attachments, each one extraction of a quote request's part). The
    recipe's `param_item_usd` row of the extra kind `extra` prices one unit; the run's plan names their sum `plan_key`
    while there are any."""

    kind: str
    extra: str
    plan_key: str
    module: str
    count: Callable[[dict[str, Any]], int]


ITEM_KINDS: tuple[ItemKind, ...] = (
    ItemKind(DOCUMENT, "a file whose type is recognised from its content", copied=True, record=True, detected=True,
             page_image=True, attachments=False, subject=_document_subject, plan_key="documents"),
    ItemKind(EMAIL, "a received message; its attachments are documents of the same package", copied=False,
             record=False, detected=False, page_image=False, attachments=True, subject=_email_subject,
             plan_key="emails", owned=True),
    ItemKind(STATEMENT_TABLE, "one account's statement read from a bank's tabular export, by code (136)", copied=True,
             record=True, detected=False, page_image=False, attachments=False, subject=_document_subject,
             plan_key="statement_tables", plan_always=False, by_code=True),
)

SOURCE_KINDS: tuple[SourceKind, ...] = (
    SourceKind("folder", "the documents of a folder", folder=True),
    SourceKind("upload", "uploaded files"),
    SourceKind("mailbox", "the messages of a mailbox download, with their PDF attachments", owned=True),
    SourceKind("manual", "files chosen by hand, or the accounts of a bank's tabular export"),
    SourceKind("watch", "the new documents of a watched folder", folder=True),
)

_ITEMS = {k.name: k for k in ITEM_KINDS}
# 229 (MD1): the native result asks whether an item is read as a document through this registry's answer
native_results.set_document_check(lambda item: of(item).detected)
_SOURCES = {s.name: s for s in SOURCE_KINDS}
_RULES: dict[str, ItemRule] = {}
_PAGES: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {}
_HANDLERS: dict[str, ItemHandler] = {}
_ITEM_PARTS: dict[tuple[str, str], ItemPart] = {}
_ITEM_EXTRAS: dict[tuple[str, str], ItemExtra] = {}
_RECORD_PARTS: dict[str, RecordPart] = {}
_REGISTERED: set[str] = set()
_CLAIMS: dict[str, str] = {}  # 229: an owned item kind -> the module that claimed it
_SOURCE_CLAIMS: dict[str, str] = {}  # 229: an owned source kind -> the module that claimed it


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


def claim(kind: str, module: str) -> None:
    """229 (MD1): the domain module that owns an item kind (`owned`) claims it, before it registers the kind's rules and
    handler; the same claim again changes nothing, a kind not owned or claimed by another module is an error."""
    _claim(_CLAIMS, kind, module, owned=of(kind).owned, what="item kind")


def claim_source(kind: str, module: str) -> None:
    """229 (MD1): the domain module that owns a source kind (`owned`) claims it, before it registers its page part."""
    _claim(_SOURCE_CLAIMS, kind, module, owned=source(kind).owned, what="source kind")


def _claim(claims: dict[str, str], kind: str, module: str, *, owned: bool, what: str) -> None:
    if not owned:
        raise ValueError(f"the {kind} {what} is the shared code's; no module claims it")
    if claims.get(kind, module) != module:
        raise ValueError(f"the {kind} {what} is claimed already by {claims[kind]}")
    claims[kind] = module


def claimed_by(kind: str) -> str | None:
    """229: the module that claimed an owned item kind (None: none yet, or a kind the shared code keeps)."""
    return _CLAIMS.get(kind)


def source_claimed_by(kind: str) -> str | None:
    """229: the module that claimed an owned source kind."""
    return _SOURCE_CLAIMS.get(kind)


def _owner(claims: dict[str, str], kind: str, owned: bool) -> str | None:
    """The module that owes an owned kind's registrations: its claimant (`?` before anyone claimed it)."""
    return claims.get(kind, "?") if owned else None


def _owed(owner: str | None, what: str) -> None:
    if owner is not None and owner not in _REGISTERED:
        who = "no module has claimed it" if owner == "?" else f"{owner} has not registered it"
        raise NotRegistered(f"the {what}: {who} (was registrations.load_all called?)")


def register_rule(rule: ItemRule) -> None:
    """Registers a rule run after every item; the same one again adds nothing, another of the same name is an
    error."""
    owner = _owner(_CLAIMS, rule.kind, of(rule.kind).owned)
    if owner != rule.module:
        raise ValueError(f"item rule {rule.name!r}: the {rule.kind} kind's rules come from {owner}")
    known = _RULES.get(rule.name)
    if known is not None and known != rule:
        raise ValueError(f"item rule {rule.name!r} is registered already by {known.module}")
    _RULES[rule.name] = rule
    _REGISTERED.add(rule.module)


def rules() -> list[ItemRule]:
    """Every rule run after an item, in the order registered. `NotRegistered` while a kind's module owes its rules."""
    for kind in ITEM_KINDS:
        _owed(_owner(_CLAIMS, kind.name, kind.owned), f"{kind.name} item rules")
    return list(_RULES.values())


def register_page(kind: str, module: str, page: Callable[[Mapping[str, Any]], dict[str, Any]]) -> None:
    """Registers a source kind's part of a package's page: `page(wp)` returns the parts it adds."""
    owner = _owner(_SOURCE_CLAIMS, kind, source(kind).owned)
    if owner != module:
        raise ValueError(f"the {kind} source's page part comes from {owner}")
    known = _PAGES.get(kind)
    if known is not None and known != page:
        raise ValueError(f"the {kind} source's page part is registered already")
    _PAGES[kind] = page
    _REGISTERED.add(module)


def page(wp: Mapping[str, Any]) -> dict[str, Any]:
    """A package's parts of its page that its source kind adds (a mailbox package: its missing attachments); empty for
    a source that adds none. `NotRegistered` while the source's module owes its part."""
    kind = source(wp["source_kind"])
    _owed(_owner(_SOURCE_CLAIMS, kind.name, kind.owned), f"{kind.name} page part")
    part = _PAGES.get(kind.name)
    return part(wp) if part is not None else {}


def register_handler(handler: ItemHandler) -> None:
    """185: registers how an item of a kind is shown and corrected; only the module the kind names may."""
    owner = _owner(_CLAIMS, handler.kind, of(handler.kind).owned)
    if owner != handler.module:
        raise ValueError(f"the {handler.kind} kind's handler comes from {owner}")
    known = _HANDLERS.get(handler.kind)
    if known is not None and known != handler:
        raise ValueError(f"the {handler.kind} kind's handler is registered already")
    _HANDLERS[handler.kind] = handler
    _REGISTERED.add(handler.module)


def handler(item: Mapping[str, Any] | str) -> ItemHandler | None:
    """185: how an item of a kind whose result is not a document record is shown and corrected; None for a record kind.
    `NotRegistered` while the kind's module owes it."""
    kind = of(item)
    if not kind.owned:
        return None
    _owed(_owner(_CLAIMS, kind.name, kind.owned), f"{kind.name} item handler")
    return _HANDLERS[kind.name]


def handlers() -> list[ItemHandler]:
    """185: every kind's handler, for each kind that names one (`NotRegistered` while its module owes it)."""
    return [h for kind in ITEM_KINDS if (h := handler(kind.name)) is not None]


def register_record_part(part: RecordPart) -> None:
    """185: a domain's part of a record item's result; the same one again adds nothing, another of the same name is an
    error."""
    known = _RECORD_PARTS.get(part.name)
    if known is not None and known != part:
        raise ValueError(f"record part {part.name!r} is registered already by {known.module}")
    _RECORD_PARTS[part.name] = part


def register_item_part(part: ItemPart) -> None:
    """192: a domain's part of an item kind's result; the same one again adds nothing, another of the same name for the
    same kind is an error."""
    known = _ITEM_PARTS.get((part.kind, part.name))
    if known is not None and known != part:
        raise ValueError(f"item part {part.name!r} of {part.kind!r} items is registered already by {known.module}")
    _ITEM_PARTS[(part.kind, part.name)] = part


def register_item_extra(extra: ItemExtra) -> None:
    """192: a domain's budget extra counted on an item kind; the same one again adds nothing, another of the same extra
    kind for the same item kind is an error."""
    known = _ITEM_EXTRAS.get((extra.kind, extra.extra))
    if known is not None and known != extra:
        raise ValueError(f"item extra {extra.extra!r} of {extra.kind!r} items is registered already by {known.module}")
    _ITEM_EXTRAS[(extra.kind, extra.extra)] = extra


def item_extras(kind: str) -> list[ItemExtra]:
    """192: the budget extras counted on an item kind, in the order registered (`registrations.load_all` first)."""
    from jav.app import registrations

    registrations.load_all()
    return [e for (k, _name), e in _ITEM_EXTRAS.items() if k == kind]


def item_parts(kind: str) -> list[ItemPart]:
    """192: the domains' parts of an item kind's result, in the order registered (`registrations.load_all` first)."""
    from jav.app import registrations

    registrations.load_all()
    return [p for (k, _name), p in _ITEM_PARTS.items() if k == kind]


def record_parts() -> list[RecordPart]:
    """185: the domains' parts of a record item's result, in the order registered; the registry completes itself the
    first time it is read (`registrations.load_all`)."""
    from jav.app import registrations

    registrations.load_all()
    return list(_RECORD_PARTS.values())


__all__ = ["DOCUMENT", "EMAIL", "ITEM_KINDS", "ItemExtra", "ItemHandler", "ItemKind", "ItemPart", "ItemRule", "NotRegistered",
           "RecordPart",
           "SOURCE_KINDS", "STATEMENT_TABLE", "SourceKind", "UnknownItemKind", "UnknownSourceKind", "check", "claim",
           "claim_source", "claimed_by", "handler", "handlers", "names", "of", "page", "record_parts", "register_handler",
           "register_page", "register_record_part", "register_rule", "rules", "source", "source_claimed_by", "source_names"]
