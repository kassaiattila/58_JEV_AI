"""160 (review R-5): a step whose package was deleted is failed with the reason, so it can be started again.

An open workflow's step package cannot be deleted (153), but an archived workflow lets it go. After restoring the
workflow, the step still said "waits for a budget" or "started" without a package: it could not be started or linked,
and the chain stood still for good. Deleting the package now fails the step with the reason ("its package was
deleted"), and a person can start it again. Synthetic documents; nothing is processed."""

from jav import parties, work, workflows as wf
from tests.test_workflow_references_153 import _make
from tests.test_workflows_146 import _steps, db  # noqa: F401 - the fixture is used by name


def test_a_step_whose_package_was_deleted_fails_with_the_reason_and_can_start_again(db):  # noqa: F811
    made = _make(db, parties.create("Example D Kft.", identities=[], actor="t")["id"])
    wf_id, step = made["workflow"]["id"], _steps(made)["invoices"]
    assert step["state"] == "needs_budget"
    wf.update(wf_id, actor="t", archived=True)
    deleted = step["package"]["id"]
    work.delete_workpackage(deleted, actor="someone")
    wf.update(wf_id, actor="t", archived=False)
    step = _steps(wf.view(wf_id))["invoices"]
    assert step["state"] == "failed" and step["note"] == wf.PACKAGE_DELETED and not step.get("package")
    restarted = _steps(wf.start_step(wf_id, "invoices", actor="t"))["invoices"]
    assert restarted["state"] == "needs_budget" and restarted["package"]["id"] != deleted
