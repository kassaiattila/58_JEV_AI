"""178 (plan 170 L4, DECISIONS 178): the output layer - the shared Excel writer.

Found while pinning the downloads (K20: a small visible fault found during the refactoring is fixed in its own commit):
the reconciliation statement styled the empty row below its heading block as the table's header, froze the rows above
the real header and filtered from the empty row, so the header scrolled away and the last row was outside the filter.
Synthetic values only.
"""

from __future__ import annotations

from openpyxl import Workbook

from jav.outputs import xlsx


def test_a_table_below_a_heading_block_has_its_own_header_frozen_and_filtered():
    wb = Workbook()
    ws = wb.active
    xlsx.write_table(ws, ["Number", "Amount"], [["A-1", "10.00"], ["A-2", "20.00"], ["A-3", "30.00"]], [None, "money"],
                     heading=[("Package", "April"), ("Period", "2026-04-01 – 2026-04-30")], min_width=10)
    assert [ws.cell(r, 1).value for r in range(1, 8)] == ["Package", "Period", None, "Number", "A-1", "A-2", "A-3"]
    assert ws.cell(4, 1).font.b and ws.cell(4, 1).fill.fgColor.rgb == "00EEEEF2"  # the header row
    assert not ws.cell(3, 1).fill.fill_type  # the empty row between stays plain
    assert ws.freeze_panes == "A5"  # the header stays in view
    assert ws.auto_filter.ref == "A4:B7"  # from the header to the last row


def test_a_table_without_a_heading_starts_on_the_first_row():
    wb = Workbook()
    ws = wb.active
    xlsx.write_table(ws, ["Number"], [["A-1"]])
    assert ws.cell(1, 1).font.b and ws.freeze_panes == "A2" and ws.auto_filter.ref == "A1:A2"
