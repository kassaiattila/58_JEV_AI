"""The Hungarian names of the type packs' fields (`configs/field_labels.json`), for one type or for all (197, plan
197 K0).

Plain-language summary: a field's name comes from one shared dictionary, so the same field reads the same everywhere.
A type may call a shared field by its own name (`by_type`): the quote request's customer is the requester, while the
utility bills' customer is the consumer. Where a view or a download knows the document's type, it asks for that type's
name; where it shows several types together, it uses the shared one. (231) A field's enumerated values have names too
(`values`, keyed `field=value`): a table shows the name, not the code.
"""

from __future__ import annotations

from collections.abc import Iterable

from jav.core import cfg, display


def field_label(field: str, doc_type: str | None = None) -> str:
    """A field's name: the type's own one when it has one, else the shared one, else the field's key. 231 (D4): its
    English source, which the interface shows in its language; a download or a file name the service makes itself
    takes `field_name`."""
    names = cfg.load("field_labels")
    own = names.get("by_type", {}).get(doc_type or "", {}).get(field)
    return own or names["fields"].get(field) or field


def field_name(field: str, doc_type: str | None = None) -> str:
    """231 (D4): a field's name in the request's language (`jav/core/display.py`), for what the service writes itself."""
    return display.text(field_label(field, doc_type))


def type_name(doc_type: str | None) -> str:
    """231 (D4): a document type's name in the request's language; the key when the type has no name."""
    name = cfg.load("field_labels")["doc_types"].get(doc_type or "")
    return display.text(name) if name else (doc_type or "")


def value_labels(field: str) -> dict[str, str]:
    """The names of a field's enumerated values ({value: name}); empty when the field enumerates none."""
    prefix = f"{field}="
    return {k.removeprefix(prefix): v for k, v in cfg.load("field_labels").get("values", {}).items() if k.startswith(prefix)}


def shared_type(field: str, records: Iterable[dict]) -> str | None:
    """The one type of the records that carry the field (its column then reads as that type's own name), or None
    when the field belongs to several types or to none."""
    types = {r["doc_type"] for r in records if field in r["fields"]}
    return types.pop() if len(types) == 1 else None
