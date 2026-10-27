"""To-dos and a logic pack's own approval as human tasks; the ones made before adopted (215, plan G-process-core P2d).

Plain-language summary: every open to-do item (a document's or an email's to-dos) is a human task: it opens with the
item, for the responsible person of the package whose run raised it (a measurement's is anyone's), goes to another
person when another package's run raises it, is decided when a person resolves its last reason and withdrawn when a
machine closes it, and the item and its task are always written together. A reconciliation or a quote waits for its
approval as a task from when it is made: an approval decides it, a reopening opens it again, a deletion withdraws it,
and in a workflow its approval moves the chain on at once. A package's new responsible person takes its open tasks.
The items, runs and packages made before get their tasks at the next start of a process, once. Synthetic data, a
temporary store, no paid calls.
"""

from __future__ import annotations

import time
import uuid

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from jav.app import human_tasks, logic_packs, work, work_readiness, work_recipes, work_runs, workflows as wf
from jav.core import store
from jav.core.process import engine, tasks
from jav.domains.email import email_routing
from jav.domains.finance import reconcile_package as rp, reconcile_statement as rs
from jav.domains.quotes import quote_draft
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_quote_draft_192 import _done, env, quote  # noqa: F401 - the fixtures are used by name
from tests.test_reconcile_package_131 import _line, _stmt
from tests.test_reconcile_package_131 import _package as _reconcile_package
from tests.test_reconcile_statement_145 import _world
from tests.test_workflow_case_214 import _next_start
from tests.test_workflow_core_steps_214 import _core
from tests.test_workflow_tasks_215 import _finish, _monthly
from tests.test_workflows_146 import _process_all, _steps, db  # noqa: F401 - the fixture is used by name


def _pkg(db, folder: str, owner: str | None) -> dict:  # noqa: F811
    root = db / folder
    root.mkdir()
    write_text_pdf(root / "a.pdf", INVOICE_LINES)
    wp = work.create_from_folder(root, name=f"Synthetic {folder}", owner=owner)
    work_recipes.assign_recipe(wp["id"], "processing", params={"arm": "S"}, expected_revision=0, actor="t")
    ready = work_readiness.readiness(wp["id"])
    return {"wp": wp["id"], "start": {"expected_assignment_revision": 1, "input_hash": ready["input_hash"]}}


def _run(pkg: dict, mode: str = "apply", actor: str = "t") -> str:
    return work_runs.start_run(pkg["wp"], mode=mode, actor=actor, **pkg["start"])["run_id"]


def _raise(subject: str, run: str, *reasons: str, kind: str = "document") -> int:
    return store.review_enqueue(subject_kind=kind, subject_id=subject, run_id=f"{run}:{subject}", reasons=list(reasons),
                                producer="tests")


def _review(rid: int) -> tasks.Task:
    return tasks.get(tasks.task_id(human_tasks.REVIEW, str(rid)))


def _reconcile(name: str = "April") -> str:
    """A reconciliation package over a made-up account (a statement makes it known)."""
    if not rp.accounts():
        _stmt("stmt", _line())
    return _reconcile_package(name=name)


def _open_items() -> set[str]:
    with store.connect() as c:
        return {str(r[0]) for r in c.execute("SELECT id FROM review_queue WHERE status='open'")}


def _open_review_tasks() -> set[str]:
    return {t.subject for t in tasks.open_tasks(kind=human_tasks.REVIEW)}


# --- a to-do item ------------------------------------------------------------------------------------------------------


def test_an_open_to_do_item_is_a_task_for_the_owner_of_the_package_whose_run_raised_it(db):  # noqa: F811
    live = _run(_pkg(db, "a", owner="Teszt Elek"))
    rid = _raise("doc-a", live, "pick:supplier")
    task = _review(rid)
    assert (task.status, task.assignee, task.case_id, task.opened_by.id) == ("open", "local:Teszt Elek", None,
                                                                             "machine:work-runs")
    assert task.detail == {"subject_kind": "document", "subject_id": "doc-a", "run": live, "origin": "live"}
    _raise("doc-a", live, "pick:supplier", "money:total")  # the same run again: the same task, nobody new
    assert [h["kind"] for h in tasks.history(task.task_id)] == ["opened"]
    trial = _run(_pkg(db, "b", owner="Minta Anna"), mode="shadow")
    assert _raise("doc-a", trial, "pick:supplier") == rid  # one item per subject
    task = _review(rid)
    assert (task.status, task.assignee) == ("open", "local:Minta Anna")
    assert tasks.history(task.task_id)[-1]["detail"] == {"from": "local:Teszt Elek", "to": "local:Minta Anna"}


def test_a_measurements_to_do_is_anyones(db):  # noqa: F811
    rid = store.review_enqueue(subject_kind="email", subject_id="msg-1", run_id="email-golden-1", reasons=["intent:low"],
                               producer="tests")
    task = _review(rid)
    assert (task.status, task.assignee, task.detail["origin"], task.detail["run"]) == ("open", None, "measurement",
                                                                                        "email-golden-1")


def test_a_person_resolving_the_last_reason_decides_the_task_and_a_machine_closing_it_withdraws_it(db):  # noqa: F811
    live = _run(_pkg(db, "a", owner="Teszt Elek"))
    rid = _raise("doc-a", live, "pick:supplier", "money:total")
    first, second = (r["id"] for r in store.review_open_reasons("document", "doc-a"))
    work_runs.resolve_reason(first, actor="Example Person", resolution=None, note="checked")
    assert _review(rid).status == "open"  # one reason is still open
    work_runs.resolve_reason(second, actor="Example Person", resolution=None, note=None)
    task = _review(rid)
    assert (task.status, task.closed_by.id, task.outcome) == ("decided", "local:Example Person",
                                                             {"resolved": [first, second]})
    closed = _raise("doc-b", live, "pick:supplier")
    store.review_close(subject_kind="document", subject_id="doc-b", producer="tests", run_id=f"{live}:doc-b")
    task = _review(closed)
    assert (task.status, task.closed_by.kind, task.note) == ("withdrawn", "machine", "the to-dos were closed: superseded")
    rerun = _raise("doc-c", live, "pick:supplier")
    with store.connect() as c:
        store.close_run_reasons(c, live)
    assert _review(rerun).status == "withdrawn"
    assert _open_items() == _open_review_tasks() == set()


def test_an_item_without_a_reason_left_opens_no_task(db):  # noqa: F811
    rid = store.review_enqueue(subject_kind="document", subject_id="doc-a", run_id="eval-1", reasons=[], producer="tests")
    assert _review(rid) is None and _open_items() == set()


def test_the_item_and_its_task_are_written_together_or_not_at_all(db, monkeypatch):  # noqa: F811
    rid = store.review_enqueue(subject_kind="document", subject_id="doc-a", run_id="eval-1", reasons=["pick:supplier"],
                               producer="tests")
    reason = store.review_open_reasons("document", "doc-a")[0]["id"]

    def stopped(*_a, **_k):
        raise RuntimeError("stopped between the two writes")

    monkeypatch.setattr(tasks, "open_in", stopped)
    with pytest.raises(RuntimeError):
        store.review_enqueue(subject_kind="document", subject_id="doc-b", run_id="eval-1", reasons=["pick:supplier"],
                             producer="tests")
    monkeypatch.setattr(tasks, "decide_in", stopped)
    with pytest.raises(RuntimeError):
        store.review_resolve(reason, actor="Example Person")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM review_queue WHERE subject_id='doc-b'").fetchone()[0] == 0
    assert [r["id"] for r in store.review_open_reasons("document", "doc-a")] == [reason]
    assert _review(rid).status == "open" and _open_items() == _open_review_tasks() == {str(rid)}


OPERATIONS = st.lists(st.tuples(st.sampled_from(["raise", "raise_none", "close", "resolve", "rerun"]),
                                st.sampled_from(["a", "b"]), st.sampled_from(["x", "y"])), min_size=1, max_size=12)


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(OPERATIONS)
def test_the_open_items_and_the_open_to_do_tasks_are_always_the_same(db, operations) -> None:  # noqa: F811
    prefix = uuid.uuid4().hex[:8]
    for op, subject, reason in operations:
        sid, run = f"{prefix}-{subject}", f"eval-{prefix}"
        if op == "raise":
            store.review_enqueue(subject_kind="document", subject_id=sid, run_id=f"{run}:{sid}", reasons=[f"pick:{reason}"],
                                 producer=f"step-{reason}")
        elif op == "raise_none":  # the step finds nothing now: its reasons are superseded
            store.review_enqueue(subject_kind="document", subject_id=sid, run_id=f"{run}:{sid}", reasons=[],
                                 producer=f"step-{reason}")
        elif op == "close":
            store.review_close(subject_kind="document", subject_id=sid, reason_prefix=f"pick:{reason}")
        elif op == "resolve":
            for r in store.review_open_reasons("document", sid)[:1]:
                store.review_resolve(r["id"], actor="Example Person")
        else:
            with store.connect() as c:
                store.begin_immediate(c)
                store.close_run_reasons(c, run)
        mine = {i for i in _open_items() if _subject(i).startswith(prefix)}
        assert mine == {t for t in _open_review_tasks() if _subject(t).startswith(prefix)}, (op, subject, reason)


def _subject(rid: str) -> str:
    with store.connect() as c:
        return c.execute("SELECT subject_id FROM review_queue WHERE id=?", (int(rid),)).fetchone()[0]


# --- a logic pack's own approval -----------------------------------------------------------------------------------------


def test_a_reconciliation_waits_for_its_approval_from_when_it_is_made(db):  # noqa: F811
    wp_id, _invoices, _lines = _world()
    tid = tasks.task_id(human_tasks.OWN_APPROVAL, f"{wp_id}:pair")  # D0-b: the pairing step's approval
    task = tasks.get(tid)
    assert (task.status, task.assignee, task.detail) == ("open", "local:reviewer", {"workpackage_id": wp_id, "step_id": "pair"})
    seen = rs.current(wp_id)["fingerprint"]
    rs.approve(wp_id, fingerprint=seen, actor="Example Person")
    task = tasks.get(tid)
    assert (task.status, task.closed_by.id, task.outcome) == ("decided", "local:Example Person", {"version": 1})
    assert tasks.history(tid)[-1]["detail"]["result_ref"] == seen
    rs.reopen(wp_id, note="a late invoice arrived", actor="Reviewer")
    task = tasks.get(tid)
    assert (task.status, task.round, task.opened_by.id) == ("open", 2, "local:Reviewer")
    rs.approve(wp_id, fingerprint=rs.current(wp_id)["fingerprint"], actor="Example Person")
    assert [h["kind"] for h in tasks.history(tid)] == ["opened", "decided", "reopened", "decided"]
    assert tasks.get(tid).outcome == {"version": 2}


def test_a_quotes_approval_is_its_task_too(quote):  # noqa: F811
    """231 (A3d): a case's quote waits for its approval once its draft step opens the task (capabilities.py)."""
    wp_id = quote["wp"]
    tid = tasks.task_id(human_tasks.OWN_APPROVAL, f"{wp_id}:compose")  # D0-b: the line composition step's approval
    assert tasks.get(tid) is None  # the quote package opened it when it was made; a case's step opens it
    with store.connect() as c:
        store.begin_immediate(c)
        human_tasks.own_approval_waits(c, wp_id, "compose")
    assert (tasks.get(tid).status, tasks.get(tid).assignee) == ("open", "local:anna")
    v = _done(wp_id)
    quote_draft.approve(wp_id, fingerprint=v["fingerprint"], actor="anna")
    assert (tasks.get(tid).status, tasks.get(tid).outcome) == ("decided", {"version": 1})
    quote_draft.reopen(wp_id, note="The customer asked for four monitors", actor="bela")
    assert (tasks.get(tid).status, tasks.get(tid).round, tasks.get(tid).opened_by.id) == ("open", 2, "local:bela")


def test_only_a_logic_pack_a_person_approves_as_its_own_version_waits_for_an_approval(db):  # noqa: F811
    # 231 (A3d): the quote package is gone; (C3a-2) the reconciliation's case owns its approval itself, not its kind
    assert set(logic_packs.kinds_with_own_approval()) == set()
    routing = work.create_workpackage(name="Routing", source_kind=email_routing.KIND, source_ref=None, owner="t")["id"]
    plain = work.create_workpackage(name="Plain", source_kind="manual", source_ref=None, owner="t")["id"]
    assert [tasks.get(tasks.task_id(human_tasks.OWN_APPROVAL, wp)) for wp in (routing, plain)] == [None, None]
    _next_start()  # nor does the adoption give them one
    assert tasks.open_tasks(kind=human_tasks.OWN_APPROVAL) == []


def test_an_archived_reconciliation_keeps_its_approval_task_and_its_case_is_not_deleted(db):  # noqa: F811
    hidden, kept = _reconcile(name="Hidden"), _reconcile(name="Kept")
    work.archive_workpackage(hidden, actor="Example Person")
    assert tasks.get(tasks.task_id(human_tasks.OWN_APPROVAL, f"{hidden}:pair")).status == "open"  # restoring it needs the same
    with pytest.raises(work.NotReady):  # 231 (C3a-2): a reconciliation is its pack's case; its container stays
        work.delete_workpackage(kept, actor="Example Person")
    assert tasks.get(tasks.task_id(human_tasks.OWN_APPROVAL, f"{kept}:pair")).status == "open"


def test_a_packages_new_owner_takes_its_open_tasks(db):  # noqa: F811
    pkg = _pkg(db, "a", owner="Teszt Elek")
    live = _run(pkg, actor="Run Starter")
    rid = _raise("doc-a", live, "pick:supplier")
    _finish(live)
    approval = tasks.task_id(human_tasks.RUN_APPROVAL, live)
    reconciliation = _reconcile()
    assert {tasks.get(approval).assignee, _review(rid).assignee} == {"local:Teszt Elek"}
    work.set_owner(pkg["wp"], "Minta Anna", actor="t")
    work.set_owner(reconciliation, "Minta Anna", actor="t")
    assert {tasks.get(approval).assignee, _review(rid).assignee,
            tasks.get(tasks.task_id(human_tasks.OWN_APPROVAL, f"{reconciliation}:pair")).assignee} == {"local:Minta Anna"}
    assert tasks.history(approval)[-1] | {"at": None} == {"round": 1, "kind": "assigned", "actor": "machine:work-runs",
                                                          "detail": {"from": "local:Teszt Elek", "to": "local:Minta Anna"},
                                                          "at": None}
    work.set_owner(pkg["wp"], None, actor="t")  # nobody: the run's starter (any name while the list is empty)
    assert {tasks.get(approval).assignee, _review(rid).assignee} == {"local:Run Starter"}
    assert tasks.get(tasks.task_id(human_tasks.OWN_APPROVAL, f"{reconciliation}:pair")).assignee == "local:Minta Anna"


def test_the_approval_of_a_workflows_reconciliation_moves_the_chain_on_at_the_workers_next_look(db):  # noqa: F811
    wf_id = _monthly(db, invoices=0)
    _process_all()
    work_runs.approve_run(_steps(wf.view(wf_id))["statements"]["run_id"], actor="Example Person")
    assert engine.turn_due() == 2  # 231 (C3a-2): and the reconciliation case its step started
    looked = time.time()  # the later looks at this moment: the step's check timer, 5 s on, never comes due in them
    wp_id = _steps(wf.view(wf_id))["reconcile"]["package"]["id"]
    assert _core(wf_id)["reconcile"] == "running:approval"
    assert engine.turn_due(looked) == 0
    rs.approve(wp_id, fingerprint=rs.current(wp_id)["fingerprint"], actor="Example Person")
    assert engine.turn_due(looked) == 1  # no check timer came due: the approval's event moved it
    assert _core(wf_id)["reconcile"] == "done"


# --- the ones made before ----------------------------------------------------------------------------------------------------


def _as_before() -> None:
    """The store as an older version left it: no human task of any to-do, run approval or own approval."""
    with store.connect() as c:
        for table in ("process_task_history", "process_tasks"):
            c.execute(f"DELETE FROM {table} WHERE task_id LIKE 'review:%' OR task_id LIKE 'run_approval:%'"
                      " OR task_id LIKE 'own_approval:%'")


def _count(table: str) -> int:
    with store.connect() as c:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_the_to_dos_and_approvals_made_before_get_their_tasks_at_the_next_start_once(db):  # noqa: F811
    live, approved = _run(_pkg(db, "a", owner="Teszt Elek")), _run(_pkg(db, "b", owner="Teszt Elek"))
    open_item = _raise("doc-a", live, "pick:supplier")
    measured = store.review_enqueue(subject_kind="email", subject_id="msg-1", run_id="eval-1", reasons=["intent:low"],
                                    producer="tests")
    closed = _raise("doc-b", live, "pick:supplier")
    store.review_close(subject_kind="document", subject_id="doc-b", run_id=f"{live}:doc-b")  # a live run's are pinned
    _finish(live)
    _finish(approved)
    work_runs.approve_run(approved, actor="Example Person")
    done = _world()[0]
    waiting = _reconcile(name="Waiting")
    rs.approve(done, fingerprint=rs.current(done)["fingerprint"], actor="Example Person")
    _as_before()
    _next_start()
    assert _open_review_tasks() == _open_items()  # the reconciliation's synthetic world raises one of its own too
    assert {str(open_item), str(measured)} <= _open_items() and str(closed) not in _open_items()
    assert _review(closed) is None  # a closed item waits for nobody
    adopted = _review(open_item)
    assert (adopted.assignee, adopted.opened_by.id, adopted.detail["origin"]) == ("local:Teszt Elek",
                                                                                "machine:human-task-adoption", "live")
    assert _review(measured).assignee is None
    assert [t.subject for t in tasks.open_tasks(kind=human_tasks.RUN_APPROVAL)] == [live]
    assert tasks.get(tasks.task_id(human_tasks.RUN_APPROVAL, approved)) is None
    assert [t.subject for t in tasks.open_tasks(kind=human_tasks.OWN_APPROVAL)] == [f"{waiting}:pair"]
    rows = (_count("process_tasks"), _count("process_task_history"))
    _next_start()  # adopted once: the next start changes nothing
    assert (_count("process_tasks"), _count("process_task_history")) == rows


def test_a_task_left_open_while_an_older_version_settled_its_subject_is_withdrawn_at_the_next_start(db):  # noqa: F811
    pkg = _pkg(db, "a", owner="Teszt Elek")
    live = _run(pkg)
    item = _raise("doc-a", live, "pick:supplier")
    _finish(live)
    waiting, gone = _reconcile(name="Waiting"), _reconcile(name="Gone")
    with store.connect() as c:  # what the code before 215 writes: the subjects settled, their tasks left as they were
        c.execute("UPDATE review_reasons SET status='resolved', actor='Example Person' WHERE review_id=?", (item,))
        c.execute("UPDATE review_queue SET status='resolved', reasons='[]' WHERE id=?", (item,))
        c.execute("UPDATE runs SET approval='approved' WHERE run_id=?", (live,))
        c.execute("INSERT INTO package_versions(workpackage_id, version, mark, items, runs, released_by, released_at,"
                  " content, locks) VALUES (?, 1, 'fp', '[]', '[]', 'Example Person', '2026-10-23T10:00:00Z', '{}', '[]')",
                  (waiting,))
        c.execute("DELETE FROM workpackages WHERE id=?", (gone,))
    _next_start()
    for tid in (f"review:{item}", f"run_approval:{live}", f"own_approval:{waiting}:pair", f"own_approval:{gone}:pair"):
        task = tasks.get(tid)
        assert (task.status, task.closed_by.id, task.note) == ("withdrawn", "machine:human-task-adoption",
                                                              human_tasks.SETTLED_UNSEEN), tid
    rows = _count("process_task_history")
    _next_start()
    assert _count("process_task_history") == rows
