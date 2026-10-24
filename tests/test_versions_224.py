"""224 (plan G-process-core P3c): the shared versions of an editable thing - draft, active, superseded, retired.

The price lists (191) and the own output templates (178) keep their versions with these steps on their own tables;
their own tests (`tests/test_price_lists_191.py`, `tests/test_output_templates_178.py`) stay as they were. Here the
steps on an invented table: the state changes, the errors, the listing.
"""

from __future__ import annotations

import sqlite3

import pytest

from jav.app.outputs import templates
from jav.core import versions
from jav.domains.quotes import price_lists


class _Missing(versions.VersionNotFound):
    pass


class _Wrong(versions.VersionStateError):
    pass


TABLE = versions.VersionTable("things", "thing", not_found=_Missing, state_error=_Wrong)


@pytest.fixture
def c():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE things (id INTEGER PRIMARY KEY, thing TEXT, name TEXT, version INTEGER, state TEXT,"
                 " activated_by TEXT, activated_by_id TEXT, activated_at TEXT, retired_by TEXT, retired_by_id TEXT,"
                 " retired_at TEXT)")
    for thing, n in (("a", 1), ("a", 2), ("a", 3), ("b", 1)):
        conn.execute("INSERT INTO things(thing, name, version, state) VALUES (?,?,?,?)", (thing, thing.upper(), n, "draft"))
    yield conn
    conn.close()


def _states(c, thing: str) -> list[str]:
    return [r["state"] for r in c.execute("SELECT state FROM things WHERE thing=? ORDER BY version", (thing,))]


def test_activating_supersedes_the_active_one_and_brings_a_retired_one_back(c):
    TABLE.activate(c, "a", 1, actor="anna")
    assert _states(c, "a") == ["active", "draft", "draft"] and TABLE.active(c, "a")["activated_by"] == "anna"
    assert TABLE.active(c, "a")["activated_by_id"] == "local:anna"  # 229 (SZ2c): the stable id beside the name
    TABLE.activate(c, "a", 2, actor="bela")
    assert _states(c, "a") == ["superseded", "active", "draft"]
    assert TABLE.retire(c, "a", actor="anna") == 2
    assert _states(c, "a") == ["superseded", "retired", "draft"] and TABLE.active(c, "a") is None
    TABLE.activate(c, "a", 1, actor="bela")  # an earlier version again: the retired one is superseded
    row = TABLE.active(c, "a")
    assert _states(c, "a") == ["active", "superseded", "draft"] and (row["retired_by"], row["retired_at"]) == (None, None)
    assert _states(c, "b") == ["draft"]  # another thing is untouched


def test_the_owners_errors_name_what_is_wrong(c):
    with pytest.raises(_Missing, match="a version 9"):
        TABLE.row(c, "a", 9)
    with pytest.raises(_Missing, match="'z'"):
        TABLE.latest(c, "z")
    assert TABLE.latest(c, "a")["version"] == 3
    with pytest.raises(_Wrong, match="a has no active version"):
        TABLE.retire(c, "a", actor="anna")
    TABLE.activate(c, "a", 3, actor="anna")
    with pytest.raises(_Wrong, match="a version 3 is already active"):
        TABLE.activate(c, "a", 3, actor="anna")


def test_the_listing_groups_the_versions_newest_first(c):
    TABLE.activate(c, "a", 2, actor="anna")
    TABLE.retire(c, "a", actor="anna")
    TABLE.activate(c, "b", 1, actor="anna")
    rows = c.execute("SELECT * FROM things ORDER BY id DESC").fetchall()
    listing = TABLE.grouped(rows, lambda r: {"thing": r["thing"], "name": r["name"]},
                            lambda r: {"version": r["version"], "state": r["state"]})
    assert listing == [
        {"thing": "b", "name": "B", "active": 1, "retired": False, "versions": [{"version": 1, "state": "active"}]},
        {"thing": "a", "name": "A", "active": None, "retired": True,
         "versions": [{"version": 3, "state": "draft"}, {"version": 2, "state": "retired"}, {"version": 1, "state": "draft"}]},
    ]


def test_the_price_lists_and_the_templates_keep_their_versions_with_these_steps():
    assert price_lists.STATES == templates.STATES == versions.STATES
    for own, shared in ((price_lists.PriceListNotFound, versions.VersionNotFound),
                        (price_lists.PriceListStateError, versions.VersionStateError),
                        (templates.TemplateNotFound, versions.VersionNotFound),
                        (templates.TemplateStateError, versions.VersionStateError)):
        assert issubclass(own, shared)
    assert (price_lists.VERSIONS.table, price_lists.VERSIONS.key) == ("price_lists", "price_list")
    assert (templates.VERSIONS.table, templates.VERSIONS.key) == ("output_templates", "template")
