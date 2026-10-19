"""153 (review C8): the downloads' formula guard covers the header row and a formula after leading spaces, and the named
copies' manifest does not name the machine's folders.

Not exploitable today (the headers come from the configuration and the schemas), but a header or a value like " =1+1"
was written as is, and the manifest that travels in a ZIP carried each original's full local path. Synthetic values.
"""

from openpyxl import Workbook

from jav import export, naming
from jav.outputs import xlsx


def test_the_csv_guards_its_header_and_a_formula_after_spaces():
    text = export.csv_bytes(["=SUM(A1)", "ok"], [[" =1+1", "\n+2", "-12.50", "plain"]]).decode("utf-8-sig")
    head, row = text.split("\r\n")[:2]
    assert head == "'=SUM(A1);ok"
    assert row.split(";")[:3] == ["' =1+1", "\"'\n+2\"", "-12.50"]  # a number stays a number


def test_the_workbook_writes_its_header_as_text():
    wb = Workbook()
    xlsx.write_table(wb.active, ["=1+1", "Name"], [["=2+2", "x"]])
    assert [c.data_type for c in wb.active[1]] == ["s", "s"] and [c.data_type for c in wb.active[2]] == ["s", "s"]


def test_the_manifest_names_each_original_below_the_shared_folder():
    paths = ["C:\\Users\\someone\\invoices\\2026\\a.pdf", "C:\\Users\\someone\\invoices\\2026\\may\\b.pdf"]
    assert naming._shared_folder_paths(paths) == {paths[0]: "a.pdf", paths[1]: "may\\b.pdf"}
    assert naming._shared_folder_paths(["C:\\x\\a.pdf", "D:\\y\\b.pdf"]) == {"C:\\x\\a.pdf": "a.pdf", "D:\\y\\b.pdf": "b.pdf"}
