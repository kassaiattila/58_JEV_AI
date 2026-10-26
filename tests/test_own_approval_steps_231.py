"""231 (stage D0, D0-b2; the reassessment of 2026-10-26, F03, F04, P02, P14): an approval belongs to the step that
approves.

A case's own approved version was one per case: a second approving step could not record its version while the first
held (`OwnVersionHolds`), and its person's task was the case's one `own_approval:<case>`. Now each approving step
keeps its own versions, its own task (`own_approval:<case>:<step>`) and its own reopening: two steps of one case hold
two approved versions, and reopening one leaves the other approved. The version numbers stay one sequence per case, so
a version's files and downloads keep their names. A task written the old way is moved to its case's approving step
when the store opens, keeping when it opened, its round, its assignee and its history. Synthetic data, a temporary
store, no paid calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jav.app import human_tasks, package_release, process_runtime, waiting, work
from jav.core import store
from jav.core.process import tasks
from tests.test_case_own_approval_231 import PERSON, _inputs

OWN = human_tasks.OWN_APPROVAL


@pytest.fixture
def db(tmp_path: Path):
    with store.use_store(tmp_path / "steps.sqlite"):
        yield


def _container() -> str:
    return work.create_workpackage(name="Invented", source_kind=process_runtime.CONTAINER, source_ref="pack:invented@1",
                                   owner=PERSON)["id"]


def _record(wp: str, step: str, fingerprint: str) -> int:
    with store.connect() as c:
        store.begin_immediate(c)
        return package_release.record_own(c, wp, step=step, content={"step": step}, fingerprint=fingerprint, locks=[],
                                          actor=PERSON)


def _task(wp: str, step: str) -> tasks.Task:
    return tasks.get(tasks.task_id(OWN, f"{wp}:{step}"))


def test_two_steps_of_one_case_hold_two_approved_versions(db) -> None:
    wp = _container()
    with store.connect() as c:
        store.begin_immediate(c)
        human_tasks.own_approval_waits(c, wp, "premium")
        human_tasks.own_approval_waits(c, wp, "terms")
    assert (_record(wp, "premium", "a" * 16), _record(wp, "terms", "b" * 16)) == (1, 2)
    assert package_release.own_approval(wp, step="premium")["active"]["version"] == 1
    assert package_release.own_approval(wp, step="terms")["active"]["version"] == 2
    assert (_task(wp, "premium").status, _task(wp, "terms").status) == ("decided", "decided")
    with pytest.raises(package_release.OwnVersionHolds):
        _record(wp, "premium", "c" * 16)  # one version of a step holds at a time


def test_reopening_one_step_s_version_leaves_the_other_approved(db) -> None:
    wp = _container()
    _record(wp, "premium", "a" * 16)
    _record(wp, "terms", "b" * 16)
    with store.connect() as c:
        store.begin_immediate(c)
        assert package_release.reopen_own(c, wp, step="premium", note="a new tariff", actor=PERSON) == 1
    assert package_release.own_approval(wp, step="premium")["active"] is None
    assert package_release.own_approval(wp, step="terms")["active"]["version"] == 2
    assert _task(wp, "premium").status == "open"
    assert _record(wp, "premium", "c" * 16) == 3  # the next number of the case
    assert [v["version"] for v in package_release.own_versions(wp, step="premium")] == [3, 1]
    assert package_release.own_version(wp, 3)["content"] == {"step": "premium"}


def test_a_deleted_package_withdraws_every_step_s_approval_task(db) -> None:
    wp = _container()
    with store.connect() as c:
        store.begin_immediate(c)
        human_tasks.own_approval_waits(c, wp, "premium")
        human_tasks.own_approval_waits(c, wp, "terms")
        human_tasks.package_deleted(c, wp, PERSON)
    assert (_task(wp, "premium").status, _task(wp, "terms").status) == ("withdrawn", "withdrawn")


def test_a_reconciliation_case_waits_under_its_pairing_step(db) -> None:
    case = process_runtime.start_case("reconciliation", {"party": _inputs(), "period": ["2026-04-01", "2026-04-30"]},
                                      name="April", actor=PERSON)
    assert process_runtime.step_using(case, "pairing") == "pair"
    assert _task(case, "pair").status == "open"
    assert [r["what"] for r in waiting.rows(PERSON, every_origin=True)
            if r["_wp"] == case and r["kind"] == OWN] == ["Reconciliation statement"]


def test_a_task_written_the_old_way_moves_to_its_case_s_approving_step(db) -> None:
    case = process_runtime.start_case("reconciliation", {"party": _inputs(), "period": ["2026-04-01", "2026-04-30"]},
                                      name="April", actor=PERSON)
    with store.connect() as c:  # as a store written before D0-b keeps it: the task under the case alone
        store.begin_immediate(c)
        c.execute("DELETE FROM process_tasks WHERE task_id=?", (tasks.task_id(OWN, f"{case}:pair"),))
        c.execute("DELETE FROM process_task_history WHERE task_id=?", (tasks.task_id(OWN, f"{case}:pair"),))
        tasks.open_in(c, OWN, case, human_tasks.ADOPTION, detail={"workpackage_id": case})
    old = tasks.get(tasks.task_id(OWN, case))
    with store.connect() as c:
        assert human_tasks.own_approvals_per_step(c) == 1
        assert human_tasks.own_approvals_per_step(c) == 0  # once
        assert human_tasks.adopt_missing(c) == 0  # neither withdrawn nor opened again
    moved = _task(case, "pair")
    assert (moved.status, moved.round, moved.opened_at, moved.assignee) == ("open", old.round, old.opened_at, old.assignee)
    assert moved.detail == {"workpackage_id": case, "step_id": "pair"}
    assert tasks.get(tasks.task_id(OWN, case)) is None
    with store.connect() as c:
        kinds = [r["kind"] for r in c.execute("SELECT kind FROM process_task_history WHERE task_id=? ORDER BY id",
                                              (moved.task_id,))]
    assert kinds == ["opened"]
