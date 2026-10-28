"""231 (stage U, U2b; the owner's decisions of 2026-10-28: one work list, the cases; the 52 batches not archived taken
over; a watched folder and a mailbox download start a case).

The document batches made before every batch was a case's (a folder's, chosen files', a watched folder's, an upload's,
a mailbox download's) are wrapped by a new case of the documents process or of the mailbox process (`wraps` by their
kind in `configs/processes/documents.json` and `mailbox.json`): the batch keeps its id, items and runs, the case's step
starts in the state its runs give (done with an approved live run). A batch a person hid stays out (it is found in the
list of every batch), and so does one whose rule another process takes (a statement batch is the bank statements'). A
watched folder's new batch gets its case at once. Made-up documents; the runs are finished by the test, never
processed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jav.app import (app_settings, document_processing, process_runtime, registrations, work, work_readiness,
                     work_runs)
from jav.core import identity, store
from jav.core.process import cases
from tests.test_workflow_tasks_215 import _finish
from tests.test_workflows_146 import _invoices

registrations.load_all()
PERSON = "anna"
MACHINE = identity.machine("cases-adopt")


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "batches.sqlite"):
        yield tmp_path


def _case_of(wp: str) -> str | None:
    owner = document_processing.owner_of(wp)
    return owner[0] if owner else None


def _approved(wp: str) -> None:
    ready = work_readiness.readiness(wp)
    run = work_runs.start_run(wp, mode="apply", expected_assignment_revision=ready["assignment_revision"],
                              input_hash=ready["input_hash"], actor=PERSON)["run_id"]
    _finish(run)
    work_runs.approve_run(run, actor=PERSON)


def test_a_folder_batch_with_an_approved_live_run_gets_a_done_documents_case(db) -> None:
    wp = work.create_from_folder(_invoices(db / "inv", n=2), name="April invoices", owner=PERSON)["id"]
    _approved(wp)
    runs = work_runs.run_rows(wp)
    rows = [r for r in process_runtime.adopt_all(actor=MACHINE, write=True) if r["workpackage_id"] == wp]
    assert [(r["pack"], r["result"]) for r in rows] == [("documents", "wrapped")]
    case = _case_of(wp)
    assert process_runtime.pack_of(case)[0] == "documents" and cases.get(case)["status"] == cases.CLOSED
    assert work_runs.run_rows(wp) == runs and work.get(case)["name"] == "April invoices"


def test_a_batch_without_a_live_run_gets_an_open_case_and_a_hidden_one_stays_out(db) -> None:
    open_wp = work.create_from_folder(_invoices(db / "a", n=1), name="May invoices", owner=PERSON)["id"]
    hidden = work.create_from_folder(_invoices(db / "b", n=1), name="Old invoices", owner=PERSON)["id"]
    work.archive_workpackage(hidden, actor=PERSON)
    process_runtime.adopt_all(actor=MACHINE, write=True)
    assert cases.get(_case_of(open_wp))["status"] == cases.OPEN
    assert _case_of(hidden) is None  # the owner's decision: a hidden batch is found in the list of every batch


def test_a_mailbox_batch_gets_a_mailbox_case(db) -> None:
    wp = work.create_workpackage(name="Office mailbox", source_kind="mailbox", source_ref="office", owner=PERSON)["id"]
    [row] = [r for r in process_runtime.adopt_all(actor=MACHINE, write=True) if r["workpackage_id"] == wp]
    assert (row["pack"], row["result"]) == ("mailbox", "wrapped") and process_runtime.pack_of(_case_of(wp))[0] == "mailbox"


def test_a_batch_whose_rule_another_process_takes_is_not_the_documents(db) -> None:
    wp = work.create_from_folder(_invoices(db / "inv", n=1), name="Rule batch", owner=PERSON)["id"]
    from jav.app import package_scope

    with store.connect() as c:
        package_scope.save(c, wp, party_id=None, period_start=None, period_end=None, role=None,
                           parts={work.RULE_PART: "statements"}, actor=PERSON, expected_revision=None)
    rows = [r for r in process_runtime.adopt_all(actor=MACHINE) if r["workpackage_id"] == wp]
    assert all(r["pack"] != "documents" for r in rows)


def test_a_watched_folder_s_new_batch_gets_its_case_at_once(db, tmp_path: Path) -> None:
    from datetime import datetime, timedelta, timezone

    folder = _invoices(tmp_path / "watched", n=2)
    [added] = app_settings.save_folders([app_settings.WatchedFolder(path=str(folder), name="Incoming")],
                                        check_dir=lambda raw: Path(raw))
    later = datetime.now(timezone.utc) + timedelta(minutes=5)  # the files have settled
    result = app_settings.scan(added["id"], now=later, actor=PERSON)
    wp = result["workpackage"]
    assert wp and process_runtime.pack_of(_case_of(wp))[0] == "documents"
    assert cases.get(_case_of(wp))["status"] == cases.OPEN
