"""121 (Q-szerepcsere): how a pair of parties stood on the earlier documents of the same type.

A model that swaps the supplier's and the buyer's tax numbers leaves two well-formed values that pass every field
check. Within one document nothing shows the swap; across documents it does: the same two companies usually stand in
the same roles. This module counts the earlier documents of the same type on which the pair stood the other way
round, and on which it stood alike; `jav/validators.py` turns a clear majority the other way into a to-do.

A position-based rule (the tax number below the other party's name or heading) was measured first on the stored
results and dropped: it flagged every invoice of some suppliers, including ones the owner had confirmed as correct.

The store is read only inside a worker run (`jav.runtime.calls.current()` with a budget scope): measurements and the
command line keep giving results that do not depend on what the store holds. Each earlier document counts once, by
its latest result of that type; the current document never counts.
"""

from __future__ import annotations

from jav import fact_checks, store
from jav.runtime import calls


def enabled() -> bool:
    ctx = calls.current()
    return ctx is not None and ctx.budget_scope is not None


def orientation(doc_id: str | None, doc_type: str | None, fields: tuple[str, str], values: tuple[object, object]) -> tuple[int, int] | None:
    """(the other way, alike): the earlier documents of `doc_type` naming the same two parties in `fields`, by the
    tax-number key (`fact_checks.tax_party_key`). None when the store is not read here or a value has no key."""
    if not enabled() or not doc_type:
        return None
    keys = tuple(fact_checks.tax_party_key(v) for v in values)
    if None in keys or keys[0] == keys[1]:
        return None
    first, second = fields
    with store.connect() as c:
        rows = c.execute(
            "SELECT d.doc_id, json_extract(d.datapoints, '$.' || ?), json_extract(d.datapoints, '$.' || ?) FROM datapoints d"
            " JOIN (SELECT doc_id, MAX(created_at) AS m FROM datapoints WHERE doc_type = ? GROUP BY doc_id) l"
            " ON l.doc_id = d.doc_id AND l.m = d.created_at WHERE d.doc_type = ? AND d.doc_id != ?",
            (first, second, doc_type, doc_type, doc_id or ""),
        ).fetchall()
    latest = {doc: (fact_checks.tax_party_key(a), fact_checks.tax_party_key(b)) for doc, a, b in rows}
    other = sum(1 for pair in latest.values() if pair == (keys[1], keys[0]))
    alike = sum(1 for pair in latest.values() if pair == keys)
    return other, alike
