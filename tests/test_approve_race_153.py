"""153 (review A5): a run superseded or stopped while it is being approved is not approved.

The approval checked the run's status before its transaction (for documents without a native result), so a person
superseding the run in between left it both cancelled and approved. The status, the items and the open reasons are now
checked again under the approval's write lock, and the approval is recorded only on a finished run. Synthetic data, no
paid calls. 160 (review R-3): a finished run can no longer be stopped at all (`tests/test_run_stop_160.py`), so only
superseding is left to race the approval.
"""

import pytest

from jav import work, work_runs
from jav.core import store
from tests.test_supersede_runs_151 import runs  # noqa: F401 - the shared fixture: one package, an older and a newer live run


def _close_reasons(run_id: str) -> None:
    with store.connect() as c:
        c.execute("UPDATE review_reasons SET status='resolved' WHERE substr(run_id, 1, ?) = ?", (len(run_id) + 1, run_id + ":"))


@pytest.mark.parametrize("meanwhile", ["supersede"])
def test_a_run_changed_during_its_approval_is_not_approved(runs, monkeypatch, meanwhile):  # noqa: F811
    with store.use_store(runs["db"]):
        _close_reasons(runs["older"])
        real = work_runs.refresh_run_status

        def racing(run_id):
            status = real(run_id)
            if run_id == runs["older"]:  # another person acts between the check and the approval's transaction
                if meanwhile == "supersede":
                    work_runs.supersede_run(runs["older"], actor="other.person")
                else:
                    work_runs.cancel_run(runs["older"], actor="other.person")
            return status

        monkeypatch.setattr(work_runs, "refresh_run_status", racing)
        with pytest.raises(work.NotReady):
            work_runs.approve_run(runs["older"], actor="teszt.elek")
        run = work_runs.get_run(runs["older"])
        assert run["status"] == "cancelled" and run["approval"] is None


def test_a_finished_run_without_to_dos_is_still_approved(runs):  # noqa: F811
    with store.use_store(runs["db"]):
        _close_reasons(runs["newer"])
        assert work_runs.approve_run(runs["newer"], actor="teszt.elek")["approval"] == "approved"
