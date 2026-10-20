"""183 (backlog N-angol-felulet-maradek): why a unified name is uncertain is given as codes too.

The warning mark beside an uncertain unified name said why in Hungarian on the English interface: the service sends
the reasons as text made from the naming configuration's Hungarian labels. A name now carries its reasons' codes as
well (`missing:<field>`, `todo:<field>`, `todo:*`, `type`, ...), and an item list's row gives them beside the text, so
that the interface writes the mark in its own language. The text stays (the downloads and the copy log use it).
Synthetic invoices and a fake model, no paid call.
"""

from jav import naming

from tests.test_unified_names_082 import _correct_first, _query, _run, env  # noqa: F401 - `env` is a fixture


def test_a_name_and_an_item_rows_carry_the_reasons_codes_beside_the_text(env):  # noqa: F811
    c = env["client"]
    wp, run_id = _run(c, env["folder"])
    first = _correct_first(c, wp, run_id)
    names = naming.run_item_names(run_id)
    assert names[first].reasons == ()
    other = next(n for k, n in names.items() if k != first)
    assert any(r.endswith(":invoice_number") for r in other.reasons)
    assert naming.reason_text(other.reasons) == other.check
    rows = {r["item_id"]: r for r in _query(c, "run_items", {"run_id": run_id, "names": "unified"})["rows"]}
    row = next(r for k, r in rows.items() if k != first)
    assert row["_name_reasons"] == list(other.reasons) and row["_name_check"] == other.check
    assert rows[first]["_name_reasons"] == []
