"""121 (Q-szerepcsere): how a pair of parties stood on the earlier documents of the same type.

A model that swaps the supplier's and the buyer's tax numbers leaves two well-formed values that pass every field
check. Within one document nothing shows the swap; across documents it does: the same two companies usually stand in
the same roles. This module counts the earlier documents of the same type on which the pair stood the other way
round, and on which it stood alike; `jav/validators.py` turns a clear majority the other way into a to-do.

A position-based rule (the tax number below the other party's name or heading) was measured first on the stored
results and dropped: it flagged every invoice of some suppliers, including ones the owner had confirmed as correct.

The store is read only inside a worker run: measurements and the command line keep giving results that do not depend
on what the store holds (175: the check registry's gate, `jav/checks.py`, in front of the `party_orientation` check). Each earlier document counts once, by
its counted result when that is of the same type (174, plan 170 L2: the package's current result across every package,
`package_result.counted_documents`; before, its latest result of that type); the current document never counts.
"""

from __future__ import annotations

from jav import fact_checks, package_result
from jav.core import store


def orientation(doc_id: str | None, doc_type: str | None, fields: tuple[str, str], values: tuple[object, object]) -> tuple[int, int] | None:
    """(the other way, alike): the earlier documents of `doc_type` naming the same two parties in `fields`, by the
    tax-number key (`fact_checks.tax_party_key`). None without a type or when a value has no key. It reads the store:
    the check registry calls it in a worker run only."""
    if not doc_type:
        return None
    keys = tuple(fact_checks.tax_party_key(v) for v in values)
    if None in keys or keys[0] == keys[1]:
        return None
    first, second = fields
    with store.connect() as c:
        counted = package_result.counted_documents(c)
        counted.pop(doc_id or "", None)
        rows = package_result.result_rows(c, counted, "json_extract(datapoints, '$.' || ?) AS a,"
                                          " json_extract(datapoints, '$.' || ?) AS b", (first, second), types=[doc_type])
    latest = {r["doc_id"]: (fact_checks.tax_party_key(r["a"]), fact_checks.tax_party_key(r["b"])) for r in rows}
    other = sum(1 for pair in latest.values() if pair == (keys[1], keys[0]))
    alike = sum(1 for pair in latest.values() if pair == keys)
    return other, alike
