"""272 (K3, the rest of UI-08): a download keeps the list's grouping whatever rows it takes.

265 (UI-08) made the download panel send the list's grouping, but the service kept it only for the filtered rows:
"every row" (the default) and "the selected rows" were rebuilt without it, so the file came in the plain sort order.
All three now keep the group, as the list shows it: a group's rows together, the groups in their captions' order,
the empty group last. Synthetic rows, offline.
"""

from __future__ import annotations

import pytest

from jav.app import datasets
from jav.app.tablequery import Column, Query, Sort

COLS = [Column("id", "Id"), Column("name", "Name"), Column("partner", "Partner")]
ROWS = [{"_key": "1", "id": "1", "name": "d", "partner": "Beta"}, {"_key": "2", "id": "2", "name": "a", "partner": "Alfa"},
        {"_key": "3", "id": "3", "name": "c", "partner": None}, {"_key": "4", "id": "4", "name": "b", "partner": "Beta"}]


@pytest.mark.parametrize("mode", ["all", "filtered", "selected"])
def test_every_download_keeps_the_grouping(monkeypatch, mode) -> None:
    monkeypatch.setattr(datasets, "rows", lambda name, scope: (COLS, ROWS))
    q = Query(sort=[Sort(col="name")], group="partner", keys=["1", "2", "3", "4"] if mode == "selected" else None)
    _cols, picked = datasets.export_rows("invented", {}, q, mode)
    assert [r["id"] for r in picked] == ["2", "4", "1", "3"]  # Alfa; Beta by name; the empty group last


def test_the_selected_rows_keep_only_the_selection(monkeypatch) -> None:
    monkeypatch.setattr(datasets, "rows", lambda name, scope: (COLS, ROWS))
    q = Query(q="nothing matches this", sort=[Sort(col="name")], group="partner", keys=["1", "3"])
    _cols, picked = datasets.export_rows("invented", {}, q, "selected")
    assert [r["id"] for r in picked] == ["1", "3"]  # the search is not applied; the group order is
