"""The markers of an own output template (178, plan 170 L4, DECISIONS 178): what a `{{...}}` in a cell stands for.

Plain-language summary: a person writes markers into their own Excel file, and the system fills them in. The names are
the output contract's English keys (`configs/outputs.json`, the owner's decision of 2026-10-19); the settings page lists
them with their labels in the interface's language. Five kinds:
- `{{package}}` - one value of the output;
- `{{invoices.amount}}` - a column of a table, written once per row: the row holding it is repeated for every row of
  the table, with that row's formatting; a table per document type is named by the type (`{{invoice_hu.gross_total}}`);
- `{{invoices.amount:sum}}` - the total of a money, number or count column, written once;
- `{{invoices:count}}` - how many rows the table has;
- `{{utility_cost.months}}` and `{{utility_cost.months:names}}` - one column per month (its amounts in a table's row,
  its names in a header row), spreading to the right.

A template holds no formula (the owner's decision of 2026-10-19): totals are markers, computed by the system.

Layer: business module (configuration read; no file access).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from jav.ai import typepack
from jav.app.outputs import contract

ANY = re.compile(r"\{\{(.*?)\}\}", re.S)
SHAPE = re.compile(r"^\s*([a-z][a-z0-9_]*)(?:\.([a-z][a-z0-9_]*))?(?::([a-z]+))?\s*$")
SUMMABLE = ("money", "number", "count")
MONTHS = "months"


@dataclass(frozen=True)
class Marker:
    """One resolved marker: `kind` (value, row, sum, count, months, month_names), `name` the value or the table as
    written (a document type for a table per type), `table` the contract's table, `part` its document type, `column`."""

    text: str
    kind: str
    name: str
    table: str | None = None
    part: str | None = None
    column: str | None = None

    @property
    def in_row(self) -> bool:
        """Repeated with a table's rows (a column or the months of a row)."""
        return self.kind in ("row", "months")


class MarkerError(ValueError):
    """A marker the output does not have."""


def _table_of(out: dict[str, Any], name: str) -> tuple[str, str | None]:
    """(contract table, document type) of a table name as written; MarkerError if the output has none."""
    if name in out["tables"] and "per" not in out["tables"][name]:
        return name, None
    per = [key for key, t in out["tables"].items() if t.get("per") == "doc_type"]
    if per and name in typepack.keys():
        return per[0], name
    raise MarkerError(f"no table {name}")


def column_kind(output: str, table: str, part: str | None, column: str) -> str:
    """A column's kind: the contract's, a type pack field's (money, number, date; anything else text), a list column's
    or a month's."""
    spec = contract.spec(output)["tables"][table]
    if column in spec["columns"]:
        return spec["columns"][column]
    if spec.get("fields") == "type_pack" and part is not None:
        kind = typepack.get(part).kind(column)
        return kind if kind in ("money", "number", "date") else "text"
    if spec.get("fields") == "type_pack_lists":
        for key in typepack.keys():
            for lf in typepack.get(key).list_fields.values():
                if column in lf:
                    return lf[column] if lf[column] in ("money", "number") else "text"
    if "months" in spec and contract.MONTH.match(column):
        return spec["months"]
    return "text"


def _has_column(out: dict[str, Any], table: str, part: str | None, column: str) -> bool:
    spec = out["tables"][table]
    if column in spec["columns"]:
        return True
    if spec.get("fields") == "type_pack":
        return part is not None and column in typepack.get(part).fields and typepack.get(part).kind(column) != "list"
    if spec.get("fields") == "type_pack_lists":
        return column in contract._list_columns()
    return False


def resolve(output: str, text: str) -> Marker:
    """The marker `{{text}}` of the output; MarkerError naming what is wrong."""
    out = contract.spec(output)
    shape = SHAPE.match(text)
    if not shape:
        raise MarkerError("not a marker name")
    first, column, op = shape.groups()
    raw = "{{" + text + "}}"
    if column is None:
        if op is None:
            if first not in out["values"]:
                raise MarkerError(f"no value {first}")
            return Marker(raw, "value", first)
        if op != "count":
            raise MarkerError(f"no :{op} for a value")
        table, part = _table_of(out, first)
        return Marker(raw, "count", first, table, part)
    table, part = _table_of(out, first)
    if column == MONTHS:
        if "months" not in out["tables"][table]:
            raise MarkerError(f"table {first} has no months")
        if op not in (None, "names"):
            raise MarkerError(f"no :{op} for the months")
        return Marker(raw, "months" if op is None else "month_names", first, table, part, column)
    if not _has_column(out, table, part, column):
        raise MarkerError(f"table {first} has no column {column}")
    if op is None:
        return Marker(raw, "row", first, table, part, column)
    if op != "sum":
        raise MarkerError(f"no :{op} for a column")
    if column_kind(output, table, part, column) not in SUMMABLE:
        raise MarkerError(f"column {first}.{column} is not a number")
    return Marker(raw, "sum", first, table, part, column)


def find(output: str, text: str) -> tuple[list[Marker], list[str]]:
    """The markers of a cell's text and the problems of those that do not resolve (`{{x}}: why`)."""
    found, problems = [], []
    for m in ANY.finditer(text):
        try:
            found.append(resolve(output, m.group(1)))
        except MarkerError as e:
            problems.append(f"{m.group(0)}: {e}")
    return found, problems
