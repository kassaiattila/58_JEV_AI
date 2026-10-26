"""231 (plan stage C, C3a-1; DECISIONS 231): a workflow's process step speaks as the step it replaces.

A workflow step that starts a process pack's case (`kind: process`) needs the parts of the workflow's scope its pack
needs (the reconciliation: the party and the period; the email routing: neither), so the wizard asks for them as it
asked for the reconciliation step's; and its package's next step means for the workflow what its capabilities say (the
pairing: "pairing" while lines are open, "approved" once the statement is), as the reconciliation step's statuses did.
No store needed beyond the registrations.
"""

from __future__ import annotations

from jav.app import registrations, workflow_steps, workflows as wf
from jav.app import workflow_records

registrations.load_all()

RECONCILIATION = {"id": "reconcile", "kind": "process", "pack": "reconciliation"}
ROUTING = {"id": "routing", "kind": "process", "pack": "mail_routing"}


def test_a_process_step_needs_what_its_pack_takes_from_the_workflow():
    assert wf.template_needs({"steps": [RECONCILIATION]}) == ["party", "period"]
    assert wf.template_needs({"steps": [ROUTING]}) == []


def test_a_process_step_s_statuses_are_its_capabilities():
    statuses = workflow_steps.of("process").statuses_of(RECONCILIATION)
    assert statuses["reconcile_pair"] == "pairing" and statuses["reconcile_approved"] == "approved"
    assert workflow_steps.of("process").statuses_of(ROUTING) == {}


def test_the_workflow_page_says_pairing_for_a_reconciliation_case(monkeypatch):
    monkeypatch.setattr(workflow_records, "_package_state", lambda wp_id: (False, {"code": "reconcile_pair", "params": {}}))
    status, nxt = workflow_records._status(RECONCILIATION, {"phase": "started", "workpackage_id": "wp-1"}, {})
    assert (status, nxt["code"]) == ("pairing", "reconcile_pair")
    monkeypatch.setattr(workflow_records, "_package_state", lambda wp_id: (False, {"code": "case_open", "params": {}}))
    assert workflow_records._status(ROUTING, {"phase": "started", "workpackage_id": "wp-2"}, {})[0] == "review"
