"""265 (code review APPW-07): the waiting list builds no item title for a to-do it leaves out.

The "Waiting for me" count, asked every 30 seconds on every page, built the title of every to-do's item (reading the
package's items and an email's file) before it left out the trial runs' to-dos. Now a list of live work decides a
to-do's origin first; the trial's item is never read, while the full list still names it. Invented packages; no AI.
"""

from __future__ import annotations

from jav.app import waiting
from tests.test_review_tasks_215 import _pkg, _run
from tests.test_waiting_list_216 import ME, _raise_on, _rows
from tests.test_workflows_146 import db  # noqa: F401 (the fixture)


def test_a_trials_item_is_not_read_for_the_live_list(db, monkeypatch) -> None:  # noqa: F811
    trial_pkg = _pkg(db, "b", owner=ME)
    _raise_on(trial_pkg["wp"], _run(trial_pkg, mode="shadow"), "pick:supplier")
    read = []
    real = waiting._Packages.item
    monkeypatch.setattr(waiting._Packages, "item", lambda self, wp_id, subject: read.append(wp_id) or real(self, wp_id, subject))
    assert _rows() == {} and read == []
    every = _rows(all="true")
    assert [r["origin"] for r in every.values()] == ["trial"] and read == [trial_pkg["wp"]]
