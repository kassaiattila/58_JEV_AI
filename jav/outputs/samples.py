"""The labels of an output's names and made-up data to preview a template with (178, plan 170 L4, DECISIONS 178).

`labels(output)`: every value and table of the output with its columns, each with the label the built-in template
shows. `markers(output)` (179): the markers a template of the output may use, ready to copy, in groups (the settings
page lists them; every one resolves, `tests/test_output_markers_179.py`). `data(output, parts)`: made-up rows for every
table of the contract - a few rows of each, the document types the template names - so a template's preview never shows
a person's real data.

Layer: business module (configuration read).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from jav import cfg, typepack
from jav.outputs import contract, markers as marker_names, parts

DEFAULT_PART = "invoice_hu"
SAMPLE_MONTHS = ("2026-01", "2026-02", "2026-03")


def _fixed_labels(output: str) -> dict[str, dict[str, str]]:
    """The built-in template's headers of the fixed columns, by table (180: a domain's own output and its result parts
    give their own, `jav/outputs/parts.py`)."""
    from jav import export
    from jav import reconcile_statement as rs

    if output == "reconcile_statement":
        lab = rs._labels()
        empty = {"invoices": [], "lines": []}
        return {"invoices": dict(zip(rs.INVOICE_COLUMNS, rs._invoice_table(empty, lab)[0])),
                "lines": dict(zip(rs.LINE_COLUMNS, rs._line_table(empty, lab)[0]))}
    if output != "package_result":
        return {t: dict(heads) for t, heads in parts.own_output(output).heads.items()}
    added = {t: dict(heads) for part in parts.result_parts() for t, heads in part.heads.items()}
    return {"native_facts": dict(zip(export.NATIVE_COLUMNS, export.NATIVE_HEAD)),
            "native_readings": dict(zip(export.NATIVE_READING_COLUMNS, export.NATIVE_READING_HEAD)),
            "emails": dict(zip(export.EMAIL_COLUMNS, export.EMAIL_HEAD)), "tasks": dict(zip(export.TASK_COLUMNS, export.TASK_HEAD)),
            "documents": dict(zip(export.document_columns(), export.document_head())),
            "datapoints": dict(zip(export.DATAPOINT_COLUMNS, export.DATAPOINT_HEAD)),
            "line_items": {**dict(zip(export.LINE_COLUMNS, export.LINE_HEAD)), "value": export.LIST_VALUE}, **added}


def _value_labels(output: str) -> dict[str, str]:
    from jav import export
    from jav import reconcile_statement as rs

    if output == "reconcile_statement":
        h = rs._labels()["heading"]
        return {k: h[k] for k in ("package", "party", "period", "accounts", "state")}
    package = {v.key: v.label for v in export.package_values({"name": ""})}
    if output != "package_result":  # a domain's own output: the package's name and its own values
        return {"package": package["package"], **parts.own_output(output).value_labels}
    return {**package, **{k: v for part in parts.result_parts() for k, v in part.value_labels.items()}}


def field_label(field: str) -> str:
    names = cfg.load("field_labels")
    return names["fields"].get(field) or names["columns"].get(field) or field


def labels(output: str) -> dict[str, Any]:
    """The output's values and tables with their labels: `{values: {key: label}, tables: {table: {per, columns: {key:
    label}, dynamic}}}` (`dynamic`: the type pack's fields, the lists' columns, or the months)."""
    spec = contract.spec(output)
    fixed = _fixed_labels(output)
    values = _value_labels(output)
    tables = {}
    for key, t in spec["tables"].items():
        tables[key] = {"per": t.get("per"), "columns": {c: fixed.get(key, {}).get(c, c) for c in t["columns"]},
                       "kinds": dict(t["columns"]), "dynamic": t.get("fields") or ("months" if "months" in t else None)}
    return {"output": output, "what": spec["what"], "values": {k: values.get(k, k) for k in spec["values"]},
            "value_kinds": dict(spec["values"]), "tables": tables}


def doc_type_label(key: str) -> str:
    return cfg.load("field_labels")["doc_types"].get(key) or key


def _row(name: str, column: str, label: str, kind: str) -> dict[str, Any]:
    marker = "{{" + f"{name}.{column}" + "}}"
    return {"marker": marker, "label": label, "kind": kind,
            "sum": marker[:-2] + ":sum}}" if kind in marker_names.SUMMABLE else None}


def markers(output: str) -> list[dict[str, Any]]:
    """179: the markers a template of the output may use, in groups - the values first, then each table in the
    contract's order (a table per document type once for every type pack, named by the type) - each group with its
    rows (the marker, its label, its kind, and the marker of its total for a money, number or count column), the
    marker of its row count, and its months' two markers. `{table: None}` is the values' group."""
    spec, names = contract.spec(output), labels(output)
    groups: list[dict[str, Any]] = [{
        "table": None, "part": None, "label": None, "count": None, "months": None,
        "rows": [{"marker": "{{" + key + "}}", "label": names["values"][key], "kind": kind, "sum": None}
                 for key, kind in spec["values"].items()]}]
    for key, table in spec["tables"].items():
        fixed = names["tables"][key]["columns"]
        for part in (typepack.keys() if table.get("per") else (None,)):
            name = part or key
            rows = [_row(name, c, fixed[c], marker_names.column_kind(output, key, part, c)) for c in table["columns"]]
            if table.get("fields") == "type_pack":
                pack = typepack.get(part)
                rows += [_row(name, f, field_label(f), marker_names.column_kind(output, key, part, f))
                         for f in pack.header_fields if f not in table["columns"]]
            elif table.get("fields") == "type_pack_lists":  # a plain list's items (`*`) are the `value` column
                rows += [_row(name, c, field_label(c), marker_names.column_kind(output, key, None, c))
                         for c in sorted(contract._list_columns()) if contract.KEY.match(c) and c not in table["columns"]]
            months = {"row": "{{" + f"{name}.{marker_names.MONTHS}" + "}}", "names": "{{" + f"{name}.{marker_names.MONTHS}:names" + "}}"}
            groups.append({"table": key, "part": part, "label": doc_type_label(part) if part else None,
                           "count": "{{" + name + ":count}}", "months": months if "months" in table else None, "rows": rows})
    return groups


def _sample(kind: str, label: str, i: int) -> Any:
    if kind in ("money", "number"):
        return Decimal(f"{(i + 1) * 1250}.50") if kind == "money" else Decimal(i + 1)
    if kind == "count":
        return i + 1
    if kind == "probability":
        return 0.95
    if kind == "date":
        return f"2026-04-{i + 1:02d}"
    if kind == "flag":
        return "igen" if i == 0 else ""
    if kind == "json":
        return "{}"
    return f"{label} {i + 1}"


def data(output: str, parts: tuple[str, ...] = (DEFAULT_PART,)) -> contract.OutputData:
    """Made-up data of every value and table of the output (the tables per document type for `parts`)."""
    spec, names = contract.spec(output), labels(output)
    n = contract.templates()["sample_rows"]
    values = tuple(contract.Value(k, names["values"][k], _sample(kind, names["values"][k], 0)) for k, kind in spec["values"].items())
    tables = []
    for key, t in spec["tables"].items():
        for part in (parts if t.get("per") else (None,)):
            columns = dict(t["columns"])
            heads = dict(names["tables"][key]["columns"])
            if t.get("fields") == "type_pack":
                pack = typepack.get(part)
                for f in pack.header_fields:
                    columns[f] = pack.kind(f) if pack.kind(f) in ("money", "number", "date") else "text"
                    heads[f] = field_label(f)
            elif t.get("fields") == "type_pack_lists":
                for p in parts:
                    for lf in typepack.get(p).list_fields.values():
                        for c, k in lf.items():
                            columns.setdefault(c, k if k in ("money", "number") else "text")
                            heads.setdefault(c, field_label(c))
            if "months" in t:
                for m in SAMPLE_MONTHS:
                    columns[f"month_{m.replace('-', '_')}"] = t["months"]
                    heads[f"month_{m.replace('-', '_')}"] = m
            keys = tuple(columns)
            rows = [[_sample(columns[c], heads[c], i) for c in keys] for i in range(n)]
            tables.append(contract.Table(key=key, title=part or key, columns=keys, head=tuple(heads[c] for c in keys),
                                         kinds=tuple(contract.writer_kind(columns[c]) for c in keys), rows=rows, part=part))
    return contract.OutputData(output, values, tuple(tables))
