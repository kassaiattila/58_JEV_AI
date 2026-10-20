"""183 (backlog Q-ténytábla-magas-sorok): a column may say the most lines a cell shows; the full value stays its tooltip.

The facts table repeated a document's long file name in every row of its facts, and a narrow column broke it into five
to eight lines (64 of 129 rows taller than four lines at 1366 px, 61 of them by the file name, 6 by the source). Its
document column now shows at most 2 lines, its source 3 and its value 4; no other dataset changes.
"""

from jav import datasets
from jav.datasets import _col


def test_a_column_can_limit_its_lines():
    assert _col("source", "Label", clamp=3).spec()["clamp"] == 3
    assert "clamp" not in _col("source", "Label").spec()


def test_the_facts_table_limits_its_document_source_and_value_columns(monkeypatch):
    # the columns do not depend on the rows: an empty result, without a store
    monkeypatch.setattr(datasets, "_merged", lambda _scope, _read: ([], {}))
    monkeypatch.setattr(datasets, "_linker", lambda _scope, _run_of: lambda _item: {"_wp": None, "_run": None})
    cols, _rows = datasets._native_facts({"run_id": "run-000000000000"})
    clamp = {c.key: c.spec().get("clamp") for c in cols}
    assert {k: v for k, v in clamp.items() if v} == {"file": 2, "effective_value": 4, "source": 3}
