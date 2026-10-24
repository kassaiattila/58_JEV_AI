"""153 (review D1): a workflow follows a merge of its party, keeps its party from being deleted, and keeps its steps'
packages.

A merge of duplicate parties left a workflow on the deleted party's id, so every later step failed ("no own party") and
the workflow could not be repeated; a party a workflow named could be deleted; and a step's package could be deleted,
after which every start of the step failed with the deleted package's id. Synthetic data, temporary store, no paid calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jav.app import parties, work, workflows as wf
from jav.core import store
from jav.domains.finance import statement_table as st
from tests import test_statement_erste_137 as erste

MONTH = ("2026-06-01", "2026-06-30")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_pdf_lines", lambda path: Path(path).read_text(encoding="utf-8").splitlines())
    monkeypatch.setattr(wf, "_last_tick", 0.0)
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def _make(db: Path, party: str, **kw):
    invoices = db / "inv"
    invoices.mkdir(parents=True, exist_ok=True)
    for i in range(2):
        (invoices / f"invoice-{i}.pdf").write_bytes(b"%PDF-1.4\n% synthetic invoice " + str(i).encode() + b"\n%%EOF\n")
    statements = db / "erste"
    erste._export(statements, "20260630", erste.JUNE, pdf=erste.PDF_JUNE)
    steps = {"invoices": {"source": {"kind": "folder", "folder": str(invoices)}},
             "statements": {"source": {"kind": "folder", "folder": str(statements)}},
             "reconcile": {"source": {"kind": "none"}}}
    return wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                     steps=steps, actor="tester", **kw)


def test_a_merge_moves_the_workflow_to_the_party_it_was_merged_into(db):
    a = parties.create("Example A Kft.", identities=[], actor="t")["id"]
    b = parties.create("Example B Kft.", identities=[], actor="t")["id"]
    wf_id = _make(db, a, advance_now=False)["workflow"]["id"]
    parties.merge(a, b, actor="t")
    assert wf.view(wf_id)["workflow"]["party_id"] == b
    draft = wf.repeat_draft(wf_id)  # it can be repeated for the next period
    assert draft["party_id"] == b


def test_a_party_a_workflow_names_cannot_be_deleted(db):
    a = parties.create("Example C Kft.", identities=[], actor="t")["id"]
    _make(db, a, advance_now=False)
    with pytest.raises(parties.PartyError):
        parties.delete(a, actor="t")


def test_an_open_workflows_step_package_cannot_be_deleted(db):
    a = parties.create("Example E Kft.", identities=[], actor="t")["id"]
    made = _make(db, a)  # the invoices step makes its package and waits for a budget (no runs yet)
    step = {s["id"]: s for s in made["steps"]}["invoices"]
    assert step["state"] == "needs_budget"
    with pytest.raises(work.NotReady) as refused:
        work.delete_workpackage(step["package"]["id"], actor="someone")
    assert refused.value.blockers[0]["code"] == "workflow_step"
    assert work.get(step["package"]["id"])  # still there


def test_an_archived_workflows_step_lets_its_package_go(db):
    a = parties.create("Example F Kft.", identities=[], actor="t")["id"]
    made = _make(db, a)
    wf_id, step = made["workflow"]["id"], {s["id"]: s for s in made["steps"]}["invoices"]
    wf.update(wf_id, actor="t", archived=True)
    work.delete_workpackage(step["package"]["id"], actor="someone")
    with store.connect() as c:
        assert c.execute("SELECT workpackage_id FROM workflow_steps WHERE workflow_id=? AND step='invoices'",
                         (wf_id,)).fetchone()[0] is None


# --- 153 (review D2): a start that was interrupted does not stay "starting" for good ----------------------------------------


def test_an_interrupted_start_releases_its_claim(db, monkeypatch):
    a = parties.create("Example G Kft.", identities=[], actor="t")["id"]
    wf_id = _make(db, a, advance_now=False)["workflow"]["id"]

    def stopped(*args, **kwargs):  # the process stops while the package is being made
        raise KeyboardInterrupt

    monkeypatch.setattr(work, "create_from_folder", stopped)
    with pytest.raises(KeyboardInterrupt):
        wf.advance(wf_id, actor="t")
    monkeypatch.undo()
    step = {s["id"]: s for s in wf.view(wf_id)["steps"]}["invoices"]
    assert step["state"] == "failed" and step["note"] == wf.INTERRUPTED
    out = wf.start_step(wf_id, "invoices", actor="t")  # a person starts it again
    assert {s["id"]: s for s in out["steps"]}["invoices"]["state"] != "failed"


def test_a_claim_left_by_a_stopped_process_is_released_by_the_workers_turn(db):
    a = parties.create("Example H Kft.", identities=[], actor="t")["id"]
    wf_id = _make(db, a, advance_now=False)["workflow"]["id"]
    with store.connect() as c:  # a process claimed the start two hours ago and never came back
        c.execute("UPDATE process_steps SET phase='starting' WHERE case_id=? AND step_id='invoices'", (wf_id,))
        c.execute("UPDATE workflow_steps SET updated_at='2026-01-01T00:00:00+00:00' WHERE workflow_id=? AND step='invoices'",
                  (wf_id,))
    assert wf.release_stale_starts() == 1
    step = {s["id"]: s for s in wf.view(wf_id)["steps"]}["invoices"]
    assert step["state"] == "failed" and step["note"] == wf.INTERRUPTED
    assert wf.release_stale_starts() == 0
