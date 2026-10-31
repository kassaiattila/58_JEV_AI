"""264 (plan E, F5; the owner's decision of 2026-10-31): Settings › Defaults lists the decision points under one name -
the list, its download's sheet and the table say "Decision points" (until now "Rules" beside "Decision points") - and
groups them by their area for real (until now the interface blanked an area's repeated name)."""
from __future__ import annotations

from jav.app import datasets


def test_the_decision_points_are_named_so_and_grouped_by_their_area():
    ds = datasets.get("rules")
    assert ds.label == "Decision points"
    cols, rows = ds.build({})
    area = next(c for c in cols if c.key == "area")
    assert area.extra.get("group") is True
    assert rows and all(r.get("area") for r in rows)
