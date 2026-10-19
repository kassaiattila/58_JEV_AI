"""The parts a domain adds to the shared outputs (180, plan 170 E7).

Plain-language summary: a package's downloads are built by shared code: its documents, data points, line items, emails
and native facts. Some of their columns and sheets belong to the finance domain: the duplicate mark of a document,
an invoice's direction, the utility cost's two sheets and its own workbook. Until now the shared code named the finance
modules that make them. Now the finance domain registers them here (`jav/domains/finance.py`), and the shared code
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
  its file only when `stored` says so, with its first table's rows as its row count.

Every part names the output contract's keys (`configs/outputs.json`); `jav/outputs/contract.py` still checks the built
data. The registry completes itself the first time it is read (`registrations.load_all`), as the check registry does.

Layer: business module (a registry; no rule of its own).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from jav.outputs import contract

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


class UnknownOutput(KeyError):
    """No domain registered the output."""


_MARKS: dict[str, RecordMark] = {}
_COLUMNS: dict[str, DocumentColumns] = {}
_RESULT: dict[str, ResultPart] = {}
_OWN: dict[str, OwnOutput] = {}


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


def _load() -> None:
    from jav import registrations

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


def own_output(output: str) -> OwnOutput:
    _load()
    try:
        return _OWN[output]
    except KeyError:
        raise UnknownOutput(f"no domain registered the output {output!r}") from None


__all__ = ["Column", "DocumentColumns", "OwnOutput", "RecordMark", "ResultPart", "UnknownOutput", "document_columns",
           "own_output", "own_outputs", "record_marks", "register_document_columns", "register_own_output",
           "register_record_mark", "register_result_part", "result_parts"]
