"""The output contract (178, plan 170 L4): what each output is filled with, read from `configs/outputs.json`.

Plain-language summary: an output (a package's result, a reconciliation statement) is first built as data - its values
and its tables, each column with a key and a kind - and only then laid out as a file. The contract lists, per output,
the values, the tables and their columns a layout may use; the built-in layout (`jav/outputs/builtin.py`) writes every
table as the downloads did until 178, and a person's own template (planned, the second round of L4) will be checked
against the same list. A builder that emits a name the contract does not list fails here, so the contract stays the
truth about what an output holds.

Dynamic parts: a table `per` document type takes the type pack's fields after its listed columns (`type_pack`), the line
items take the columns of the type packs' lists (`type_pack_lists`), and the utility cost takes one column per month
(`month_<yyyy>_<mm>`).

Layer: business module (configuration read; no rule of its own). The builders: `jav/export.py` (`result_data`) and
`jav/reconcile_statement.py` (`statement_data`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from jav import cfg, typepack

KEY = re.compile(r"^[a-z][a-z0-9_]*$")
MONTH = re.compile(r"^month_\d{4}_\d{2}$")
KINDS = ("text", "date", "money", "number", "count", "probability", "flag", "json")
WRITER_KINDS = ("money", "number")  # the kinds the writer turns into a decimal number (`jav/outputs/xlsx.py`)


class ContractError(ValueError):
    """An output's data uses a name the contract does not list, or disagrees with it."""


@dataclass(frozen=True)
class Value:
    """One value of an output (the statement's package name): its contract key, the built-in layout's label, the value."""

    key: str
    label: str
    value: Any


@dataclass(frozen=True)
class Table:
    """One table of an output's data. `key`: the contract's table; `part`: the document type of a table per type;
    `title`: the built-in layout's sheet name; `columns`: the column keys; `head`: the built-in layout's header;
    `kinds`: each column's writer kind (money, number or None); `rows`: the values in column order; `marks`: marked
    cells, (row index, column index) -> mark (the utility grid's missing, overlap or partial month); `footer`: rows
    the built-in template writes below the rows (the utility cost's grand total; an own template takes the value)."""

    key: str
    title: str
    columns: tuple[str, ...]
    head: tuple[str, ...]
    kinds: tuple[str | None, ...]
    rows: Sequence[Sequence[Any]]
    part: str | None = None
    marks: Mapping[tuple[int, int], str] = field(default_factory=dict)
    footer: Sequence[Sequence[Any]] = ()


@dataclass(frozen=True)
class OutputData:
    """An output's data: which output, its values in order, its tables in order."""

    output: str
    values: tuple[Value, ...]
    tables: tuple[Table, ...]


def outputs() -> dict[str, Any]:
    return cfg.load("outputs")["outputs"]


def templates() -> dict[str, Any]:
    """The limits of an own template (its size, the made-up rows of a preview)."""
    return cfg.load("outputs")["templates"]


def spec(output: str) -> dict[str, Any]:
    try:
        return outputs()[output]
    except KeyError:
        raise ContractError(f"unknown output: {output}") from None


def writer_kind(kind: str | None) -> str | None:
    return kind if kind in WRITER_KINDS else None


@cache
def _list_columns() -> frozenset[str]:
    """Every column of every type pack's lists (the line items' dynamic columns)."""
    return frozenset(c for key in typepack.keys() for lf in typepack.get(key).list_fields.values() for c in lf)


def _dynamic(table: dict[str, Any], part: str | None, column: str) -> bool:
    if table.get("fields") == "type_pack":
        return part is not None and column in typepack.get(part).fields
    if table.get("fields") == "type_pack_lists":
        return column in _list_columns()
    return "months" in table and bool(MONTH.match(column))


def check(data: OutputData) -> None:
    """The data names only what the contract lists, and each listed column's writer kind is the contract's.
    `ContractError` names every disagreement."""
    out = spec(data.output)
    errors = [f"value {v.key}" for v in data.values if v.key not in out["values"]]
    for t in data.tables:
        table = out["tables"].get(t.key)
        if table is None:
            errors.append(f"table {t.key}")
            continue
        if ("per" in table) != (t.part is not None):
            errors.append(f"table {t.key}: part {t.part}")
        if not len(t.columns) == len(t.head) == len(t.kinds):
            errors.append(f"table {t.key}: {len(t.columns)} columns, {len(t.head)} headers, {len(t.kinds)} kinds")
        if len(set(t.columns)) != len(t.columns):
            errors.append(f"table {t.key}: a column twice")
        for column, kind in zip(t.columns, t.kinds):
            listed = table["columns"].get(column)
            if listed is not None:
                if writer_kind(listed) != kind:
                    errors.append(f"column {t.key}.{column}: kind {kind}, the contract's {listed}")
            elif not _dynamic(table, t.part, column):
                errors.append(f"column {t.key}.{column}")
    if errors:
        raise ContractError(f"{data.output}: not in the output contract: {'; '.join(errors)}")
