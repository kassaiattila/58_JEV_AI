"""The built-in layout of an output (178, plan 170 L4): the workbook every download had until 178.

Each table of the output's data (`jav/outputs/contract.py`) on its own sheet, in order, named by the table's title and
written by the shared writer (`jav/outputs/xlsx.py`); with `heading`, the output's values stand as a block above every
table; a marked cell gets its mark's fill. The layout's settings are data (`configs/outputs.json`, `builtin`).

Layer: adapter (file format), called by the builders' modules.
"""

from __future__ import annotations

import io

from jav.outputs import contract, xlsx


def render(data: contract.OutputData) -> bytes:
    """The output's workbook in the built-in layout. `contract.ContractError` when the data disagrees with the contract."""
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill

    contract.check(data)
    layout = contract.spec(data.output)["builtin"]
    heading = tuple((v.label, v.value) for v in data.values) if layout["heading"] else ()
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()
    for t in data.tables:
        ws = wb.create_sheet(xlsx.safe_sheet(t.title, used))
        top = xlsx.write_table(ws, t.head, [*t.rows, *t.footer], t.kinds, heading=heading, min_width=layout["min_width"])
        for (r, c), mark in t.marks.items():
            ws.cell(row=top + 1 + r, column=c + 1).fill = PatternFill("solid", fgColor=layout["marks"][mark])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
