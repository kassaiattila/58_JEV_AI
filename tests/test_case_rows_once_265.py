"""265 (code review APPW-10): the case list's rows are built once per change, and a run's to-do does not change them.

The case list built its rows anew for every view, person and process asked (the period grid and the views' counts
ask several), and a task anywhere in the store - a run's to-do too - invalidated them, though the rows read no task.
Now the rows are built once per change of what they read and only filtered per view. Invented process; no AI.
"""

from __future__ import annotations

from jav.app import case_lists, datasets
from jav.app.tablequery import Query
from jav.core import store
from tests.test_case_list_263 import _started
from tests.test_sub_case_231 import db  # noqa: F401 (the fixture)


def test_the_rows_are_built_once_for_every_view(db, monkeypatch) -> None:  # noqa: F811
    _started(db, "Invented March")
    built = []
    real = case_lists._case_rows
    monkeypatch.setattr(case_lists, "_case_rows", lambda c, closed: built.append(closed) or real(c, closed=closed))
    monkeypatch.setattr(case_lists, "_ROWS_KEPT", {})
    for view in ("open", "mine", "waiting"):
        datasets.query("cases", {"view": view, "actor": "Invented Person"}, Query())
    assert built == [False]


def test_a_runs_to_do_does_not_change_the_list(db) -> None:  # noqa: F811
    _started(db, "Invented April")
    before = case_lists._fingerprint({})
    store.review_enqueue(subject_kind="document", subject_id="doc-x", run_id="eval-1", reasons=["pick:x"], producer="tests")
    assert case_lists._fingerprint({}) == before
