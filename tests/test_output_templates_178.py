"""178 (plan 170 L4, DECISIONS 178): own output templates - the markers, the check at upload, the filling, the store.

The owner's decisions of 2026-10-19: the template keeps its look and the system writes the data into its markers (the
output contract's English names); a table's row is repeated with its formatting; no formula in a template (totals and
counts are markers); a template is chosen per package. The templates here are made-up workbooks built in the test;
the data is synthetic. No AI call, no network.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Font, PatternFill

from jav import export, work
from jav.core import store
from jav.domains.finance import report_utility
from jav.domains.finance import reconcile_statement as rs
from jav.outputs import contract, fill, markers, samples, templates
from tests import test_characterisation_178 as c178


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "t178.sqlite"):
        yield


def _bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _statement_template() -> bytes:
    """A heading with a value in a text, the invoices' row with an amount formatted in forints, a total and a count
    below with a merged label, and the lines' row further down."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Statement"
    ws["A1"] = "Reconciliation of {{package}} ({{period}})"
    ws["A3"], ws["B3"], ws["C3"] = "Number", "Amount", "Result"
    ws["A4"], ws["B4"], ws["C4"] = "{{invoices.number}}", "{{invoices.amount}}", "{{invoices.result}}"
    ws["A4"].font = Font(italic=True)
    ws["B4"].number_format = '#,##0.00 "Ft"'
    ws["A6"] = "Total"
    ws.merge_cells("A6:B6")
    ws["C6"] = "{{invoices.amount:sum}}"
    ws["D6"] = "{{invoices:count}} invoices"
    ws["A8"], ws["B8"] = "{{lines.booking_date}}", "{{lines.amount}}"
    return _bytes(wb)


# --- the markers ----------------------------------------------------------------------------------------------------


def test_a_marker_names_a_value_a_column_a_total_a_count_or_the_months():
    assert markers.resolve("reconcile_statement", "package").kind == "value"
    row = markers.resolve("reconcile_statement", "invoices.amount")
    assert (row.kind, row.table, row.column) == ("row", "invoices", "amount")
    assert markers.resolve("reconcile_statement", "invoices.amount:sum").kind == "sum"
    assert markers.resolve("reconcile_statement", "lines:count").kind == "count"
    per_type = markers.resolve("package_result", "invoice_hu.gross_total")
    assert (per_type.table, per_type.part, per_type.column) == ("documents", "invoice_hu", "gross_total")
    assert markers.resolve("utility_cost", "utility_cost.months").kind == "months"
    assert markers.resolve("utility_cost", "utility_cost.months:names").kind == "month_names"
    for wrong, why in (("owner", "no value owner"), ("invoices.secret", "no column secret"), ("invoices.result:sum", "not a number"),
                       ("payments.amount", "no table payments"), ("invoice_hu.consumption_kwh", "no column consumption_kwh"),
                       ("package:sum", "no :sum for a value"), ("Invoice amount", "not a marker name")):
        with pytest.raises(markers.MarkerError, match=why):
            markers.resolve("package_result" if "invoice_hu" in wrong else "reconcile_statement", wrong)


# --- the check ------------------------------------------------------------------------------------------------------


def test_a_sound_template_passes_with_what_it_uses():
    check = fill.check("reconcile_statement", _statement_template())
    assert check.ok, check.problems
    assert check.values == ["package", "period"]
    assert check.tables == {"invoices": ["number", "amount", "result"], "lines": ["booking_date", "amount"]}


def _one_sheet(**cells) -> bytes:
    wb = Workbook()
    for coord, value in cells.items():
        wb.active[coord] = value
    return wb


@pytest.mark.parametrize(("cells", "code"), [
    ({"A1": "=SUM(1,2)", "A2": "{{package}}"}, "formula"),
    ({"A1": "{{owner}}"}, "unknown_marker"),
    ({"A1": "{{invoices.number}}", "B1": "{{lines.amount}}"}, "row_mixes_tables"),
    ({"A1": "{{invoices.number}}", "A3": "{{invoices.amount}}"}, "table_in_two_rows"),
    ({"A1": "{{invoices.number}}", "B1": "{{package}}"}, "value_in_row"),
    ({"A1": "plain text"}, "no_marker"),
])
def test_the_check_refuses_what_would_not_fill_safely(cells, code):
    check = fill.check("reconcile_statement", _bytes(_one_sheet(**cells)))
    assert not check.ok and code in [p["code"] for p in check.problems]


def test_the_months_must_end_their_row_and_a_tables_row_holds_no_merged_cell():
    wb = _one_sheet(A1="{{utility_cost.months}}", B1="{{utility_cost.total}}")
    assert [p["code"] for p in fill.check("utility_cost", _bytes(wb)).problems] == ["months_not_last"]
    wb = _one_sheet(A1="{{utility_cost.address}}", C1="{{utility_cost.total}}")
    wb.active.merge_cells("A1:B1")
    assert [p["code"] for p in fill.check("utility_cost", _bytes(wb)).problems] == ["merged_row"]


def test_the_check_refuses_other_files_and_warns_about_formatting_that_does_not_spread(monkeypatch):
    assert [p["code"] for p in fill.check("reconcile_statement", b"not a workbook").problems] == ["not_xlsx"]
    wb = _one_sheet(A1="{{invoices.amount}}")
    wb.active.conditional_formatting.add("A1", CellIsRule(operator="lessThan", formula=["0"], fill=PatternFill("solid", fgColor="FF0000")))
    check = fill.check("reconcile_statement", _bytes(wb))
    assert check.ok and [w["code"] for w in check.warnings] == ["conditional_formatting"]
    monkeypatch.setattr(contract, "templates", lambda: {"max_bytes": 10, "sample_rows": 3})
    assert [p["code"] for p in fill.check("reconcile_statement", _bytes(wb)).problems] == ["too_large"]


def test_the_check_refuses_a_link_to_another_file_and_macros():
    import zipfile

    data = _bytes(_one_sheet(A1="{{package}}"))
    for extra, code in (("xl/externalLinks/externalLink1.xml", "external_link"), ("xl/connections.xml", "data_connection"),
                        ("xl/vbaProject.bin", "unsafe_content")):
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(buf, "w") as dst:
            for item in src.infolist():
                dst.writestr(item, src.read(item.filename))
            dst.writestr(extra, b"<x/>")
        assert code in [p["code"] for p in fill.check("reconcile_statement", buf.getvalue()).problems], code


# --- the filling ----------------------------------------------------------------------------------------------------


def test_the_statement_fills_its_values_rows_total_and_count_keeping_the_look(db):
    wp_id, _inv, _ids = c178._world()
    data = rs.statement_data(rs.current(wp_id)["statement"], "draft")
    ws = load_workbook(io.BytesIO(fill.fill(data, _statement_template())))["Statement"]
    invoices = data.tables[0].rows
    assert ws["A1"].value == "Reconciliation of April (2026-04-01 – 2026-04-30)" and ws["A1"].data_type == "s"
    n = len(invoices)
    assert [ws.cell(4 + i, 1).value for i in range(n)] == [r[0] for r in invoices]
    assert all(ws.cell(4 + i, 1).font.i for i in range(n)) and ws.cell(4 + n - 1, 2).number_format == '#,##0.00 "Ft"'
    amounts = [Decimal(r[6]) for r in invoices if r[6] is not None]
    total_row = 6 + n - 1
    assert ws.cell(total_row, 1).value == "Total" and f"A{total_row}:B{total_row}" in [str(r) for r in ws.merged_cells.ranges]
    assert ws.cell(total_row, 3).value == sum(amounts) and ws.cell(total_row, 4).value == f"{n} invoices"
    lines = data.tables[1].rows
    assert [ws.cell(8 + n - 1 + i, 2).value for i in range(len(lines))] == [Decimal(r[4]) for r in lines]


def test_a_value_is_text_never_a_formula_and_never_read_as_a_marker(db):
    wp_id, _inv, _ids = c178._world()
    st = rs.current(wp_id)["statement"]
    st["package"]["name"] = "=HYPERLINK(\"x\") {{period}}"
    st["invoices"][0]["number"] = "{{package}}"
    out = load_workbook(io.BytesIO(fill.fill(rs.statement_data(st, "draft"), _statement_template())))["Statement"]
    assert out["A1"].value.startswith("Reconciliation of =HYPERLINK") and "{{period}}" in out["A1"].value
    assert out["A4"].value == "{{package}}" and out["A4"].data_type == "s"


def test_an_empty_table_takes_its_row_away_and_the_rows_below_move_up(db):
    wb = _one_sheet(A1="{{invoices.number}}", A2="after", A3="{{lines.memo}}")
    wb.active.merge_cells("B2:C2")
    data = contract.OutputData("reconcile_statement", (), (
        contract.Table(key="invoices", title="i", columns=("number",), head=("n",), kinds=(None,), rows=[]),
        contract.Table(key="lines", title="l", columns=("memo",), head=("m",), kinds=(None,), rows=[["one"], ["two"]])))
    ws = load_workbook(io.BytesIO(fill.fill(data, _bytes(wb)))).active
    assert [ws.cell(r, 1).value for r in range(1, 4)] == ["after", "one", "two"]
    assert [str(r) for r in ws.merged_cells.ranges] == ["B1:C1"]


def test_the_months_spread_to_the_right_with_their_names(db):
    wb = _one_sheet(A1="Place", B1="{{utility_cost.months:names}}", A2="{{utility_cost.address}}", B2="{{utility_cost.months}}",
                    A4="Grand total", B4="{{grand_total}}")
    data = report_utility.output_data(c178._records(), export.package_values({"name": "April"}))  # 180: moved from export
    ws = load_workbook(io.BytesIO(fill.fill(data, _bytes(wb)))).active
    assert [ws.cell(1, c).value for c in range(2, 6)] == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert ws.cell(2, 1).value == "1111 Budapest, Minta utca 11" and ws.cell(2, 2).value == Decimal("10000.00")
    assert ws.cell(2, 3).value == report_utility.STATUS_TEXT["missing"]  # a missing month says so, as in the built-in template
    assert ws.cell(4, 2).value == Decimal("31000.00") and ws.cell(4, 2).number_format == "#,##0.00"


def test_a_table_per_document_type_is_named_by_the_type(db):
    wb = _one_sheet(A1="{{invoice_hu.invoice_number}}", B1="{{invoice_hu.gross_total}}", A3="{{invoice_hu:count}}")
    data = export.result_data(c178._records(), {}, [])
    ws = load_workbook(io.BytesIO(fill.fill(data, _bytes(wb)))).active
    assert [ws.cell(r, 2).value for r in (1, 2)] == [Decimal("1270.00"), Decimal("1270")]
    assert ws["A4"].value == 2


def test_a_preview_uses_made_up_data_only(db):
    data = samples.data("package_result", ("invoice_hu",))
    contract.check(data)
    assert {t.part or t.key for t in data.tables} >= {"invoice_hu", "datapoints", "utility_cost"}
    labels = samples.labels("reconcile_statement")
    assert labels["tables"]["invoices"]["columns"]["amount"] and labels["values"]["package"]


# --- the store and the choice ---------------------------------------------------------------------------------------


def _plain_package(tmp_path) -> str:
    source = tmp_path / "a.txt"
    source.write_text("synthetic", encoding="utf-8")
    return work.create_from_files([source], name="Synthetic")["id"]


def test_a_template_goes_from_draft_to_active_to_retired_and_a_package_chooses_it(db, tmp_path):
    with pytest.raises(templates.TemplateRefused) as refused:
        templates.add("reconcile_statement", "Ours", "ours.xlsx", _bytes(_one_sheet(A1="=1+1")), actor="Reviewer")
    assert [(p["code"], p["where"]) for p in refused.value.check["problems"]] == [("formula", "Sheet!A1")]
    assert templates.listing() == []  # a refused file is not stored
    v1 = templates.add("reconcile_statement", "Ours", "ours.xlsx", _statement_template(), actor="Reviewer")
    assert (v1["version"], v1["state"]) == (1, "draft")
    shown = load_workbook(io.BytesIO(templates.preview(v1["template"], 1)[0]))["Statement"]
    assert shown["A1"].value.startswith("Reconciliation of ") and shown["A4"].value.endswith(" 1")
    assert (shown["C8"].value, shown["D8"].value) == (Decimal("7501.50"), "3 invoices")  # three made-up rows: 1250.50 + 2500.50 + 3750.50
    wp_id, _inv, _ids = c178._world()
    with pytest.raises(templates.TemplateStateError):
        templates.choose(wp_id, "reconcile_statement", v1["template"], actor="Reviewer")  # a draft is not chosen
    templates.activate(v1["template"], 1, actor="Reviewer")
    with pytest.raises(templates.TemplateStateError):
        templates.choose(wp_id, "package_result", v1["template"], actor="Reviewer")  # a reconciliation has no such output
    chosen = templates.choose(wp_id, "reconcile_statement", v1["template"], actor="Reviewer")
    assert chosen["outputs"]["reconcile_statement"]["chosen"]["version"] == 1
    data = rs.statement_data(rs.current(wp_id)["statement"], "draft")
    made, meta = templates.render(data, wp_id)
    assert meta == {"template": v1["template"], "template_version": "1"}
    assert load_workbook(io.BytesIO(made))["Statement"]["A1"].value.startswith("Reconciliation of April")
    v2 = templates.add("reconcile_statement", "Ours", "ours-2.xlsx", _statement_template(), actor="Reviewer", template=v1["template"])
    templates.activate(v2["template"], 2, actor="Reviewer")
    assert templates.get(v1["template"], 1)["state"] == "superseded" and templates.render(data, wp_id)[1]["template_version"] == "2"
    templates.retire(v1["template"], actor="Reviewer")
    assert templates.render(data, wp_id)[1] == {"template": "builtin", "template_version": "1.1.0"}
    assert templates.choices(wp_id)["outputs"]["reconcile_statement"]["chosen"]["active"] is False
    other = _plain_package(tmp_path)
    assert list(templates.choices(other)["outputs"]) == ["package_result", "utility_cost"]
    with pytest.raises(templates.TemplateStateError):
        templates.add("package_result", "Other", "o.xlsx", _bytes(_one_sheet(A1="{{package}}")), actor="R", template=v1["template"])
