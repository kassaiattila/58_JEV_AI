"""Meglévő futások forráshelyének újraszámolása (053): a képen a mezők és a tételsorok kerete, kódból, AI-hívás nélkül.

Mikor kell: a forráshely-szabály változott (053: a több helyen szereplő érték a legvalószínűbb helyen kap keretet, a
pénznem a „Ft” feliratra is illeszkedik, a tételes listák sorai is kapnak helyet), és a már lefutott eredményeken is
látni akarjuk. A kinyert értékek és a teendők nem változnak, csak a `datapoints.provenance` segédadat.

Mi marad: a kiválasztott jelölt pontos helye (`pick`), a közelítő sor (`pick_line`) és a kézi kijelölés (`manual`),
mert ezek a futás közbeni választásból születtek, és utólag nem számolhatók újra. Minden más mező újra keresve, a
becsült bizonyosság (`confidence`) megtartva.
"""

from __future__ import annotations

import json
from typing import Any

from jav import grounding, source_layer, store, typepack, work

KEEP_METHODS = ("pick", "pick_line", "manual")


def reground_provenance(layer: source_layer.SourceLayer | None, old: dict[str, dict[str, Any]], *, fields: dict[str, str],
                        values: dict[str, Any], list_kinds: dict[str, dict[str, str]]) -> dict[str, dict[str, Any]]:
    """Egy tétel új forráshelye a régi mellől: a futás közbeni választás helye marad, a keresés és a sorok újra."""
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
    """Egy futás minden tételének forráshelye újraszámolva. Visszaad: tételszám, a keretes mezők száma előtte / utána."""
    run = work.get_run(run_id)
    counts = {"items": 0, "located_before": 0, "located_after": 0, "rows": 0, "rows_located": 0}
    with store.connect() as c:  # előbb minden sor beolvasva: a szóréteg betöltése saját kapcsolatot nyit (nincs egymásba ágyazás)
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
