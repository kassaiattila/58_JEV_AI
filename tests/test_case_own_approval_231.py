"""231 (plan stage C, C3a-1; DECISIONS 231): a case whose process approves its result as its own version waits for that
approval like the reconciliation package did.

A process pack's case whose step is done with the case's own approved version (`Capability.own_version`, the
reconciliation's pairing) waits for that approval in a person's "Waiting for me" list, under the label its capability
gives ("Reconciliation statement"), from the moment it starts or is taken over; the approval decides the task. In a
workflow, such a case's approval counts as an own version: when an earlier step is approved again with another result,
the chain reopens the case's approved statement with a reason (rule 218), as it reopened the package's. Synthetic data,
a temporary store, no paid calls.
"""

from __future__ import annotations

import pytest

from jav.app import human_tasks, parties, process_runtime, waiting, work_runs, workflows as wf
from jav.app import package_release
from jav.core import store
from jav.core.process import tasks
from jav.domains.finance import reconcile
from tests import legacy_reconcile
from tests import test_reconcile_ai_134 as ai134
from tests import test_reconcile_k2_129 as k2
from tests.test_workflow_core_steps_214 import _core
from tests.test_workflow_reopen_chain_218 import PERSON, _approved_chain, _rerun, _turns
from tests.test_workflow_tasks_215 import _finish
from tests.test_workflows_146 import db  # noqa: F401 - the fixture is used by name


@pytest.fixture
def own(tmp_path):
    with store.use_store(tmp_path / "own.sqlite"):
        yield


def _inputs() -> str:
    k2._save_statement("stmt", *ai134.LINES)
    k2._save("tel", ai134.TELECOM)
    return parties.create("Example Home", identities=[("account", reconcile.account_key(k2.OWN), k2.OWN)], actor="t")["id"]


def _waiting_for(wp_id: str) -> list[str]:
    return [r["what"] for r in waiting.rows(PERSON, every_origin=True) if r["_wp"] == wp_id and r["kind"] == "own_approval"]


def test_a_reconciliation_case_waits_for_its_statement_s_approval(own):
    party = _inputs()
    case = process_runtime.start_case("reconciliation", {"party": party, "period": ["2026-04-01", "2026-04-30"]},
                                      name="April", actor=PERSON)
    assert _waiting_for(case) == ["Reconciliation statement"]
    with store.connect() as c:  # the approval as the statement's own version records it (its documents are synthetic)
        store.begin_immediate(c)
        package_release.record_own(c, case, content={"invented": True}, fingerprint="f" * 16, locks=[], actor=PERSON)
    assert tasks.get(tasks.task_id("own_approval", case)).status == "decided" and _waiting_for(case) == []


def test_a_case_whose_approval_task_went_missing_gets_it_back_at_the_repair(own):
    party = _inputs()
    case = process_runtime.start_case("reconciliation", {"party": party, "period": ["2026-04-01", "2026-04-30"]},
                                      name="April", actor=PERSON)
    with store.connect() as c:  # as in a store written before cases opened it
        c.execute("DELETE FROM process_tasks WHERE task_id = ?", (tasks.task_id("own_approval", case),))
    assert _waiting_for(case) == []
    with store.connect() as c:
        store.begin_immediate(c)
        human_tasks.adopt_missing(c)
    assert _waiting_for(case) == ["Reconciliation statement"]


def test_a_mail_routing_case_has_no_approval_of_its_own(own):
    assert process_runtime.owns_approval("wp-000000000000") is False  # no case: nothing to approve


def test_a_reconciliation_package_taken_over_still_waits_under_its_own_label(own):
    party = _inputs()
    wp = legacy_reconcile.old_package(name="April", accounts=[reconcile.account_key(k2.OWN)], period_start="2026-04-01",
                                      period_end="2026-04-30", actor=PERSON, party_id=party)
    assert _waiting_for(wp) == ["Approval"]  # its retired kind is unknown until the release takes it over
    process_runtime.adopt_all(actor="tester", write=True)
    assert _waiting_for(wp) == ["Reconciliation statement"]
    assert process_runtime.owns_approval(wp) is True


def test_the_chain_reopens_a_reconciliation_case_when_the_invoices_are_approved_again(db):  # noqa: F811
    wf_id, run_id, rec = _approved_chain(db)  # since C3a-2 the monthly template's reconciliation step is the pack's case
    assert process_runtime.pack_of(rec)[0] == "reconciliation"
    rerun = _rerun(run_id)
    _finish(rerun)
    work_runs.approve_run(rerun, actor=PERSON)
    _turns()
    _turns()
    assert _core(wf_id)["reconcile"] == "running:approval"
    approval = package_release.own_approval(rec)
    assert approval["active"] is None
    earlier = approval["versions"][0]
    assert (earlier["version"], earlier["reopened_by"], earlier["reopen_note"]) == (1, "tester (auto)", wf.REAPPROVE_NOTE)
    assert tasks.get(tasks.task_id("own_approval", rec)).status == "open"  # it waits for a person again
