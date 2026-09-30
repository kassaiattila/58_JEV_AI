"""Recomputes the source locations of existing runs (053): field and line-item boxes on the image, in code, no AI.

When it is needed: the source-location rule has changed (053: a value printed in several places gets its box at the
most likely place, the currency also matches the printed "Ft", and the rows of itemised lists get a location too), and
we want to see this on results that have already run. The extracted values and the to-dos do not change, only the
`datapoints.provenance` helper data.

What stays: the exact location of the chosen candidate (`pick`), the approximate line (`pick_line`) and the manual
selection (`manual`), because these came from choices made during the run and cannot be recomputed afterwards. Every
other field is searched again, keeping the estimated confidence (`confidence`).
"""

from __future__ import annotations

import json
from typing import Any

from jav import grounding, source_layer, store, typepack, work

KEEP_METHODS = ("pick", "pick_line", "manual")


def reground_provenance(layer: source_layer.SourceLayer | None, old: dict[str, dict[str, Any]], *, fields: dict[str, str],
                        values: dict[str, Any], list_kinds: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    """An item's new source locations from its old ones: in-run choices keep their place; search and rows are redone."""
    labels = grounding.Labels(layer) if layer is not None else None
    out: dict[str, dict[str, Any]] = {}
    for f, kind in fields.items():
        prev = old.get(f) or {}
        if kind == "list":
            continue
        if prev.get("method") in KEEP_METHODS and prev.get("status") in ("located", "approximate"):
            out[f] = prev
            continue
        entry = grounding.locate_value(layer, kind, values.get(f), field=f, labels=labels)
        out[f] = {"alternatives": [], **entry, "confidence": prev.get("confidence")}
    lists = {f: values.get(f) or [] for f, k in fields.items() if k == "list"}
    out.update(grounding.ground_lists(layer, lists=lists, kinds=list_kinds))
    return out


def reground_run(run_id: str) -> dict[str, int]:
    """Recomputes the source locations of all items in a run. Returns: item count, boxed fields before / after."""
    run = work.get_run(run_id)
    counts = {"items": 0, "located_before": 0, "located_after": 0, "rows": 0, "rows_located": 0}
    with store.connect() as c:  # read all rows first: loading the word layer opens its own connection (no nesting)
        rows = [(it, dict(r)) for it in run["items"] if it.get("flow_run_id")
                for r in [c.execute("SELECT doc_type, datapoints, provenance, source_layer_id FROM datapoints WHERE run_id=? AND doc_id=?",
                                    (it["flow_run_id"], it["item_id"])).fetchone()] if r is not None and r["source_layer_id"]]
    updates = []
    for it, row in rows:
        pack = typepack.get(row["doc_type"])
        layer = source_layer.load(row["source_layer_id"])
        old = json.loads(row["provenance"] or "{}")
        new = reground_provenance(layer, old, fields=dict(pack.fields), values=json.loads(row["datapoints"] or "{}"),
                                  list_kinds={f: dict(v) for f, v in pack.list_fields.items()})
        counts["items"] += 1
        counts["located_before"] += sum(1 for v in old.values() if v.get("status") == "located")
        counts["located_after"] += sum(1 for v in new.values() if v.get("status") == "located")
        for v in new.values():
            for r in v.get("rows") or []:
                counts["rows"] += 1
                counts["rows_located"] += r.get("status") in ("located", "approximate")
        updates.append((json.dumps(new, ensure_ascii=False), it["flow_run_id"], it["item_id"]))
    with store.connect() as c:
        c.executemany("UPDATE datapoints SET provenance=? WHERE run_id=? AND doc_id=?", updates)
    return counts


__all__ = ["KEEP_METHODS", "reground_provenance", "reground_run"]
