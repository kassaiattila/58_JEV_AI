"""The parts a domain adds to the shared outputs (180, plan 170 E7).

Plain-language summary: a package's downloads are built by shared code: its documents, data points, line items, emails
and native facts. Some of their columns and sheets belong to the finance domain: the duplicate mark of a document,
an invoice's direction, the utility cost's two sheets and its own workbook. Until now the shared code named the finance
modules that make them. Now the finance domain registers them here (`jav/domains/finance/__init__.py`), and the shared code
asks this registry, so a download looks exactly as before and the shared code knows nothing of invoices.

Four kinds of part, each listed in the order it was registered (the order the downloads show them):
- `RecordMark`: a mark the domain sets on every document record of a run's result before any table is built (the
  duplicate mark, `duplicate`);
- `DocumentColumns`: columns of the documents table after its general ones (the duplicate mark, the direction), each
  with its built-in header and its kind in the data view; the data view shows a part's columns only when a row has
  a value in the first of them;
- `ResultPart`: tables and values added to the package's result (the utility cost's sheets and its grand total), and
  a section of the result's JSON; the labels of its tables' columns and of its values for a template's marker list;
- `OwnOutput`: an output of a processing package besides its result (the utility cost's workbook); a release stores
  its file only when `stored` says so, with its first table's rows as its row count;
- `ItemPart` (185): an item kind's part of a result, before the documents (the emails and their tasks): its rows of a
  run, its tables, its section of the result's JSON and the result views of the interface it adds;
- `OutputLabels` (185): the built-in headers and value labels of an output a logic pack makes on its own (the
  reconciliation statement), for a template's marker list and preview;
- `VersionDocument` (231, stage D0, D0-c): how an approved own version of a case's step becomes an output's data (the
  quote's Word document), for the general priced document capability (`jav/app/approved_document.py`).

Every part names the output contract's keys (`configs/outputs.json`); `jav/app/outputs/contract.py` still checks the built
data. The registry completes itself the first time it is read (`registrations.load_all`), as the check registry does.

Layer: business module (a registry; no rule of its own).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from jav.app.outputs import contract

Records = list[dict[str, Any]]


@dataclass(frozen=True)
class RecordMark:
    name: str
    module: str
    mark: Callable[[Records], None]


@dataclass(frozen=True)
class Column:
    """A column a domain adds to the documents table: its contract key, its built-in header (the data view's label
    too), its kind in the data view and, for an enumerated value, the data view's label set."""

    key: str
    head: str
    kind: str = "text"
    labels: str | None = None


@dataclass(frozen=True)
class DocumentColumns:
    name: str
    module: str
    columns: tuple[Column, ...]
    values: Callable[[Records], list[tuple[Any, ...]]]  # one tuple per record, in the records' order


@dataclass(frozen=True)
class ResultPart:
    name: str
    module: str
    data: Callable[[Records], tuple[tuple[contract.Table, ...], tuple[contract.Value, ...]]]
    json_key: str
    json: Callable[[Records], Any]
    heads: Mapping[str, Mapping[str, str]] = field(default_factory=dict)  # table -> column -> built-in header
    value_labels: Mapping[str, str] = field(default_factory=dict)
    view: str | None = None  # 185: the result view of the interface it adds when `shown(records)` (the utility cost)
    shown: Callable[[Records], bool] | None = None


@dataclass(frozen=True)
class ItemPart:
    """185 (plan G-full-move T1e): an item kind's part of a result, written before the documents. `kind`: the item
    kind; `read(run_id)`: its rows of a run, each with its `item_id`; `data(rows)`: its tables; `json_key`: its section
    of the result's JSON (the rows); `views(rows)`: the result views of the interface it adds; `heads`: its tables'
    built-in headers."""

    name: str
    module: str
    kind: str
    read: Callable[[str], Records]
    data: Callable[[Records], tuple[contract.Table, ...]]
    json_key: str
    views: Callable[[Records], list[str]]
    heads: Mapping[str, Mapping[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class OutputLabels:
    """185 (plan G-full-move T1e): the built-in headers (`heads()`: table -> column -> header) and value labels
    (`values()`) of an output a logic pack makes on its own."""

    output: str
    module: str
    heads: Callable[[], Mapping[str, Mapping[str, str]]]
    values: Callable[[], Mapping[str, str]]


@dataclass(frozen=True)
class OwnOutput:
    output: str
    module: str
    file: str  # the file a release stores
    slug: str  # the downloaded file's name part
    data: Callable[[Records, tuple[contract.Value, ...]], contract.OutputData]
    stored: Callable[[contract.OutputData], bool]
    heads: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    value_labels: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class VersionDocument:
    """D0-c: the output an approved own version is printed into: `data(content, package=, version=, approved_by=,
    approved_at=, output=)` builds the output's data from the version's content as it was approved."""

    output: str
    module: str
    data: Callable[..., contract.OutputData]


class UnknownOutput(KeyError):
    """No domain registered the output."""


_MARKS: dict[str, RecordMark] = {}
_COLUMNS: dict[str, DocumentColumns] = {}
_RESULT: dict[str, ResultPart] = {}
_OWN: dict[str, OwnOutput] = {}
_ITEMS: dict[str, ItemPart] = {}
_LABELS: dict[str, OutputLabels] = {}
_VERSIONS: dict[str, VersionDocument] = {}


def _add(table: dict[str, Any], name: str, part: Any) -> None:
    known = table.get(name)
    if known is not None and known != part:
        raise ValueError(f"output part {name!r} is registered already by {known.module}")
    table[name] = part


def register_record_mark(part: RecordMark) -> None:
    _add(_MARKS, part.name, part)


def register_document_columns(part: DocumentColumns) -> None:
    keys = [c.key for p in _COLUMNS.values() if p.name != part.name for c in p.columns]
    if any(c.key in keys for c in part.columns):
        raise ValueError(f"output part {part.name!r}: a column another part adds already")
    _add(_COLUMNS, part.name, part)


def register_result_part(part: ResultPart) -> None:
    _add(_RESULT, part.name, part)


def register_own_output(part: OwnOutput) -> None:
    _add(_OWN, part.output, part)


def register_item_part(part: ItemPart) -> None:
    _add(_ITEMS, part.name, part)


def register_output_labels(part: OutputLabels) -> None:
    _add(_LABELS, part.output, part)


def register_version_document(part: VersionDocument) -> None:
    """D0-c: an output an approved own version is printed into (one domain per output)."""
    _add(_VERSIONS, part.output, part)


_SAMPLE_TYPES: list[str] = []


def register_sample_type(doc_type: str) -> None:
    """229 (plan structure stage 1, MD2): a domain's document type whose made-up rows a template's preview shows when the
    template names no type's table of its own (the finance domain's: the Hungarian invoice; until 229 the preview's
    own default). The first registered is used; the same one again adds nothing."""
    if doc_type not in _SAMPLE_TYPES:
        _SAMPLE_TYPES.append(doc_type)


def sample_types() -> tuple[str, ...]:
    """The registered preview type, first registered first (empty: none registered)."""
    _load()
    return tuple(_SAMPLE_TYPES[:1])


def _load() -> None:
    from jav.app import registrations

    registrations.load_all()


def record_marks() -> list[RecordMark]:
    _load()
    return list(_MARKS.values())


def document_columns() -> list[DocumentColumns]:
    _load()
    return list(_COLUMNS.values())


def result_parts() -> list[ResultPart]:
    _load()
    return list(_RESULT.values())


def own_outputs() -> list[OwnOutput]:
    _load()
    return list(_OWN.values())


def item_parts() -> list[ItemPart]:
    _load()
    return list(_ITEMS.values())


def output_labels(output: str) -> OutputLabels | None:
    _load()
    return _LABELS.get(output)


def version_document(output: str) -> VersionDocument:
    """D0-c: the builder of an output an approved own version is printed into; `UnknownOutput` when no domain
    registered one."""
    _load()
    try:
        return _VERSIONS[output]
    except KeyError:
        raise UnknownOutput(f"no domain prints an approved version into the output {output!r}") from None


def own_output(output: str) -> OwnOutput:
    _load()
    try:
        return _OWN[output]
    except KeyError:
        raise UnknownOutput(f"no domain registered the output {output!r}") from None


__all__ = ["Column", "DocumentColumns", "ItemPart", "OutputLabels", "OwnOutput", "RecordMark", "ResultPart", "UnknownOutput",
           "VersionDocument", "document_columns", "item_parts", "output_labels", "own_output", "own_outputs",
           "record_marks", "register_document_columns", "register_item_part", "register_output_labels",
           "register_own_output", "register_record_mark", "register_result_part", "register_sample_type",
           "register_version_document", "result_parts", "sample_types", "version_document"]
