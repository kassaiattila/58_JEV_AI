"""265 (code review APPW-02; a regression of 263 F3): a hidden (archived) case is not on the open lists or in their counts.

Since the case list's rows were built for the main cases (263 F3), the containers were read with the closed ones for a
sub-case's sake, and a hidden case stayed on the open lists and in the views' counts (the handovers list hid it). Now
it shows only among the closed cases. The synthetic chain of `test_sub_case_231`; nothing is processed.
"""

from __future__ import annotations

from jav.app import case_lists, work
from tests.test_case_list_263 import _rows, _started
from tests.test_sub_case_231 import PERSON, db  # noqa: F401 (the fixture)


def test_a_hidden_case_is_only_among_the_closed_ones(db) -> None:  # noqa: F811
    shown = _started(db, "Invented March")
    hidden = _started(db, "Invented April")
    work.archive_workpackage(hidden, actor=PERSON)
    assert [r["_key"] for r in _rows()] == [shown]
    assert [r["_key"] for r in _rows(view="mine", actor=PERSON)] == [shown]
    assert [r["_key"] for r in _rows(view="closed")] == [hidden]
    counts = case_lists.view_counts(PERSON)
    assert counts["views"]["open"] == 1 and counts["views"]["mine"] == 1 and counts["views"]["closed"] == 1
    assert counts["processes"][0]["open"] == 1 and counts["processes"][0]["all"] == 2


def test_a_change_within_one_second_changes_the_case_list_s_mark(db) -> None:  # noqa: F811
    """265 (code review APPW-04): the process core's mark names the history's last row, which every change writes; the
    times are to the second, so a step that changed twice within one second kept the list's old rows (the run of
    `test_document_processing_231` showed "waits for a person's start" while the run worked)."""
    from jav.core import store
    from jav.core.process import cases

    _started(db, "Invented March")
    before = cases.marks()
    with store.connect() as c:
        c.execute("INSERT INTO process_history(case_id, step_id, kind, actor, detail, pid, at)"
                  " SELECT case_id, step_id, 'waiting', actor, detail, pid, at FROM process_history ORDER BY id DESC LIMIT 1")
    assert cases.marks() != before
