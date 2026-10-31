"""263 (plan E, F3; the owner's decisions of 2026-10-30: views, groups and a period grid): the case list has a row only
for the main cases; a sub-case's step shows in its main case's row as the main case's step's own, the step a person
must act on first; the views (waiting for the person, the person's own, every open one, the closed ones) filter it and
count their cases at once. The synthetic chain of `test_sub_case_231`; nothing is processed (its runs would call AI).
"""

from __future__ import annotations

from jav.app import case_lists, datasets, process_runtime
from jav.app.tablequery import Query
from jav.core import store
from jav.core.identity import person
from jav.core.process import cases, engine
from tests.test_sub_case_231 import PERIOD, PERSON, _source, _sub, db  # noqa: F401 (the fixture)

ALL = Query(limit=1000)


def _rows(**scope: str) -> list[dict]:
    return datasets.query("cases", scope, ALL)["rows"]


def _started(db, name: str) -> str:  # noqa: F811
    chain = process_runtime.start_case("sub_chain", {"period": PERIOD, "step_sources": {
        "first": _source(db, f"{name}a"), "second": _source(db, f"{name}b")}}, name=name, actor=PERSON)
    engine.turn(chain, wake=True)
    return chain


def test_only_the_main_cases_have_a_row_and_a_sub_case_s_step_shows_in_its_main_case_s(db) -> None:  # noqa: F811
    chain = _started(db, "Invented March")
    first = _sub(chain, "first")
    engine.turn(first, wake=True)  # its step makes its batch and waits for a person's live run
    rows = _rows()
    assert [r["_key"] for r in rows] == [chain]  # the two sub-cases are its steps, not rows of their own
    row = rows[0]
    assert row["step"] == "First documents › Processing" and row["waits_for"] == case_lists.PERSON_START
    assert row["period"] == "2026-03-01 – 2026-03-31" and row["steps"] == "0/3"
    assert [t["state"] for t in row["_track"]] == ["running", "running", "waiting"]
    page = datasets.query("cases", {}, ALL)
    assert {c["key"]: c.get("group") for c in page["columns"]}["process"] is True


def test_the_views_filter_the_list_and_count_their_cases_at_once(db) -> None:  # noqa: F811
    mine = _started(db, "Invented March")
    engine.turn(_sub(mine, "first"), wake=True)
    other = process_runtime.start_case("sub_chain", {"period": PERIOD, "step_sources": {
        "first": _source(db, "ca"), "second": _source(db, "cb")}}, name="Invented April", actor="bela")
    engine.turn(other, wake=True)
    with cases.transaction() as c:
        cases.close(c, other, "done", person("bela"))
    assert [r["_key"] for r in _rows(view="mine", actor=PERSON)] == [mine]
    assert [r["_key"] for r in _rows(view="waiting", actor=PERSON)] == [mine]  # its step waits for a person's start
    assert _rows(view="waiting", actor="bela") == []  # Anna's case is not Bela's to act on
    assert [r["_key"] for r in _rows(view="closed")] == [other]
    assert {r["_key"] for r in _rows(include_closed="1")} == {mine, other}
    counts = case_lists.view_counts(PERSON)
    assert counts["views"] == {"waiting": 1, "mine": 1, "open": 1, "closed": 1}
    assert counts["processes"] == [{"pack": "sub_chain", "title": "Chain", "open": 1, "all": 2, "repeats": False}]
    with store.connect() as c:
        assert len(case_lists._case_rows(c, closed=True)) == 2
