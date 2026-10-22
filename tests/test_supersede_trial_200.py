"""200 (Q-visszavont-teendok, decision of 2026-10-22): superseding an older trial run too.

The K3 trial of 199 left a trial run's to-dos open after a later run of the same documents had gone another way (the
type pack withdrawn): a run closes only its own step's reasons when that step runs again. The owner's decision: the
same manual, confirmed superseding as for an older live run (151), for a trial run too; no run closes another run's
reasons by itself. A trial run is superseded by any later finished run of the same documents (a trial result is only
viewed), and only while it has open to-dos (closing them is all superseding does for a trial). A later trial never
supersedes a live run. Synthetic data, no paid calls.
"""

import pytest

from jav import store, work, work_runs, work_views
from tests.test_supersede_runs_151 import _finish, _open, runs  # noqa: F401 - the shared fixture and helpers


@pytest.fixture()
def trials(runs):  # noqa: F811
    """After the fixture's two live runs: a trial run with open to-dos, then a later trial rerun of it."""
    older = work_runs.start_run(runs["wp"], mode="shadow", **runs["start"])["run_id"]
    _finish(older)
    for item, reason in zip(runs["items"], ("jev:unsupported:event_datetime", "pick:seller_name")):
        store.review_enqueue(subject_kind="document", subject_id=item, run_id=work_runs.flow_run_id(older, item),
                             reasons=[reason], producer="m2")
    newer = work_runs.start_run(runs["wp"], mode="shadow", rerun_of=older, **runs["start"])["run_id"]
    _finish(newer)
    return {**runs, "trial": older, "later_trial": newer}


def test_an_older_trial_run_with_open_to_dos_offers_superseding(trials):
    assert work_runs.supersede_info(trials["trial"]) == {"by": trials["later_trial"], "open_reasons": 2,
                                                    "resolved_reasons": 0, "corrected_items": 0}
    assert work_runs.supersede_info(trials["later_trial"]) is None  # nothing later covers the latest run


def test_superseding_a_trial_closes_only_its_own_reasons(trials):
    out = work_runs.supersede_run(trials["trial"], actor="teszt.elek")
    assert out == {"run_id": trials["trial"], "superseded_by": trials["later_trial"], "reasons_closed": 2}
    assert work_runs.get_run(trials["trial"])["status"] == "cancelled"
    assert _open(trials["trial"]) == []
    assert _open(trials["newer"]) == ["pick:seller_name"]  # a live run's reasons stay open
    assert work_views.run_view(trials["trial"])["superseded"]["by"] == trials["later_trial"]


def test_a_trial_without_open_to_dos_is_not_offered(trials):
    work_runs.supersede_run(trials["trial"], actor="teszt.elek")
    third = work_runs.start_run(trials["wp"], mode="shadow", rerun_of=trials["later_trial"], **trials["start"])["run_id"]
    _finish(third)
    assert work_runs.supersede_info(trials["later_trial"]) is None  # covered, but nothing to close
    with pytest.raises(work.NotReady):
        work_runs.supersede_run(trials["later_trial"], actor="t")


def test_a_later_trial_does_not_supersede_a_live_run(trials):
    assert work_runs.supersede_info(trials["newer"]) is None  # the latest live run; only trials came after it


def test_a_later_live_run_supersedes_an_older_trial(runs):  # noqa: F811
    trial = work_runs.start_run(runs["wp"], mode="shadow", **runs["start"])["run_id"]
    _finish(trial)
    store.review_enqueue(subject_kind="document", subject_id=runs["items"][0], run_id=work_runs.flow_run_id(trial, runs["items"][0]),
                         reasons=["pick:seller_name"], producer="m2")
    live = work_runs.start_run(runs["wp"], mode="apply", rerun_of=runs["newer"], **runs["start"])["run_id"]
    _finish(live)
    assert work_runs.supersede_info(trial)["by"] == live


def test_the_package_lists_the_older_trial_with_its_mode(trials):
    rows = work_runs.supersedable_runs(trials["wp"])
    assert [(r["run_id"], r["mode"]) for r in rows] == [(trials["older"], "apply"), (trials["trial"], "shadow")]
    assert rows[1]["open_reasons"] == 2
