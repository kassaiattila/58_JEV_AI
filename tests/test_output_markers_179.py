"""179 (plan 170 L4, round 2's interface, DECISIONS 178/179): the list of markers the settings page shows.

The owner's decision of 2026-10-19: a template's markers are the system's English names, and the settings page lists
them with their labels, to copy. The list comes from the service, so every marker in it must be one the check accepts
and the filling understands: each listed marker resolves to the kind the list says, and the list covers every value
and every column the output contract names, the document types' own fields and the months. Configuration only; no
store, no AI call.
"""

from __future__ import annotations

from jav.ai import typepack
from jav.app.outputs import contract, markers, samples


def _inner(marker: str) -> str:
    assert marker.startswith("{{") and marker.endswith("}}"), marker
    return marker[2:-2]


def _listed(output: str) -> list[tuple[str, str]]:
    """(marker, the kind it should resolve to) of every marker in the output's list."""
    out = []
    for group in samples.markers(output):
        for row in group["rows"]:
            out.append((row["marker"], "value" if group["table"] is None else "row"))
            if row["sum"]:
                out.append((row["sum"], "sum"))
        if group["count"]:
            out.append((group["count"], "count"))
        if group["months"]:
            out += [(group["months"]["row"], "months"), (group["months"]["names"], "month_names")]
    return out


def test_every_listed_marker_resolves_to_its_kind_in_every_output():
    for output in contract.outputs():
        listed = _listed(output)
        assert listed, output
        assert len({m for m, _ in listed}) == len(listed), f"{output}: a marker listed twice"
        for marker, kind in listed:
            assert markers.resolve(output, _inner(marker)).kind == kind, marker


def test_the_list_covers_every_value_and_fixed_column_of_the_contract():
    for output, spec in contract.outputs().items():
        listed = {m for m, _ in _listed(output)}
        assert {"{{" + v + "}}" for v in spec["values"]} <= listed
        for key, table in spec["tables"].items():
            names = [key] if "per" not in table else typepack.keys()
            for name in names:
                assert {"{{" + f"{name}.{c}" + "}}" for c in table["columns"]} <= listed, f"{output}.{name}"
                assert "{{" + name + ":count}}" in listed


def test_a_sum_is_offered_only_for_a_number_column():
    for output in contract.outputs():
        for group in samples.markers(output):
            for row in group["rows"]:
                assert bool(row["sum"]) == (group["table"] is not None and row["kind"] in markers.SUMMABLE), row["marker"]


def test_a_table_per_document_type_lists_each_type_with_its_label_and_its_own_fields():
    groups = [g for g in samples.markers("package_result") if g["table"] == "documents"]
    assert [g["part"] for g in groups] == typepack.keys()
    hu = next(g for g in groups if g["part"] == "invoice_hu")
    assert hu["label"] == samples.doc_type_label("invoice_hu") and hu["label"] != "invoice_hu"
    rows = {r["marker"]: r for r in hu["rows"]}
    gross = rows["{{invoice_hu.gross_total}}"]
    assert gross["kind"] == "money" and gross["sum"] == "{{invoice_hu.gross_total:sum}}"
    assert gross["label"] == samples.field_label("gross_total")
    # a list field is not a column of the documents' table (its rows are the line items')
    pack = typepack.get("invoice_hu")
    assert [f for f in pack.fields if pack.kind(f) == "list"]
    assert not [m for m in rows if pack.fields.get(_inner(m).split(".")[1]) == "list"]


def test_the_line_items_list_the_columns_of_every_type_packs_lists_and_the_utility_cost_its_months():
    groups = {g["table"]: g for g in samples.markers("package_result")}
    line_columns = {_inner(r["marker"]).split(".")[1] for r in groups["line_items"]["rows"]}
    # a plain list's items (`*`) are written in the `value` column, which is listed
    assert contract._list_columns() - {"*"} <= line_columns and "value" in line_columns
    for output in ("package_result", "utility_cost"):
        cost = next(g for g in samples.markers(output) if g["table"] == "utility_cost")
        assert cost["months"] == {"row": "{{utility_cost.months}}", "names": "{{utility_cost.months:names}}"}
    assert all(g["months"] is None for g in samples.markers("reconcile_statement"))


def test_an_unknown_markers_reason_has_one_of_the_forms_the_settings_page_puts_in_words():
    """The settings page translates the check's reasons by their form (`MARKER_REASONS` in
    `ui/src/views/settings/OutputTemplatesPanel.tsx`); a new wording here needs its form there too."""
    import re

    forms = [r"^not a marker name$", r"^no value (\w+)$", r"^no table (\w+)$", r"^table (\w+) has no column (\w+)$",
             r"^table (\w+) has no months$", r"^column (\S+) is not a number$", r"^no :(\w+) for (a value|the months|a column)$"]
    bad = {"package_result": ["Package", "nothing", "package:sum", "nothing.amount", "invoice_hu.nothing",
                              "emails.months", "utility_cost.months:sum", "invoice_hu.file:sum", "emails.subject:avg"],
           "reconcile_statement": ["invoices.amount:avg"]}
    for output, texts in bad.items():
        for text in texts:
            try:
                markers.resolve(output, text)
            except markers.MarkerError as e:
                assert any(re.match(f, str(e)) for f in forms), f"{text}: {e}"
            else:
                raise AssertionError(f"{text} resolved")


def test_the_service_lists_the_markers_with_each_output(tmp_path):
    from fastapi.testclient import TestClient

    from jav.service.api import create_app

    with TestClient(create_app(store_path=tmp_path / "t179.sqlite"), base_url="http://127.0.0.1:8930") as c:
        outputs = c.get("/api/output-templates").json()["outputs"]
    assert set(outputs) == set(contract.outputs())
    for output, body in outputs.items():
        assert body["markers"] == samples.markers(output)
