"""A workflow is a case of the process core (214, plan G-process-core P1b-2).

Plain-language summary: a new workflow starts its case under the same id, in the same transaction as its own rows, so
there is never one without the other; the case's process definition is the workflow's saved template, its version
and fingerprint taken from it. A workflow made before this change is adopted onto the core from the state it reached
(the store's schema change helper, at the next start): a step that waits for its download or its package's approval
keeps waiting, with a check timer; one waiting for a budget waits for a person; one that found nothing new is done; a
failed one stays failed. An archived workflow's case is on hold, and archiving or restoring it holds or resumes the
case with the workflow's own change. Synthetic data, temporary store, no paid calls.
"""

from __future__ import annotations

import pytest

from jav.app import parties, workflow_cases, workflows as wf
from jav.core import cfg, store
from jav.core.process import cases, engine
from tests.test_workflow_references_153 import _make, db  # noqa: F401 - the fixture is used by name


def _party(name: str = "Example C Kft.") -> str:
    return parties.create(name, identities=[], actor="t")["id"]


def _states(case_id: str) -> dict[str, str]:
    view = cases.view(case_id)
    return {sid: s["state"] if s["waiting_for"] is None else f"{s['state']}:{s['waiting_for']}"
            for sid, s in view["steps"].items()}


def _count(table: str) -> int:
    with store.connect() as c:
        return c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# --- the definition ------------------------------------------------------------------------------------------------------


def test_every_workflow_template_is_a_process_definition_whose_version_follows_the_saved_template():
    chains = [t for t in cfg.load("workflows")["templates"] if wf.is_workflow(t)]
    assert {t["id"] for t in chains} == {"monthly_reconciliation", "mailbox_reconciliation",
                                        "two_sources_reconciliation", "mailbox_routing"}
    for t in chains:
        d = workflow_cases.definition(t)
        assert d.id == f"workflow_{t['id']}" and d.title == t["title"]
        assert [(s.id, s.kind, s.after, s.gates, s.params) for s in d.steps] == [
            (s["id"], workflow_cases.STEP_KIND, tuple(s.get("after", ())), (), {"kind": s["kind"]}) for s in t["steps"]]
        assert workflow_cases.definition(dict(reversed(list(t.items())))).fingerprint() == d.fingerprint()
    changed = chains[0] | {"steps": [*chains[0]["steps"][:-1], chains[0]["steps"][-1] | {"after": []}]}
    assert workflow_cases.definition(changed).version != workflow_cases.definition(chains[0]).version


# --- a new workflow ------------------------------------------------------------------------------------------------------


def test_a_new_workflow_starts_its_case_under_the_same_id(db):  # noqa: F811
    wf_id = _make(db, _party(), advance_now=False)["workflow"]["id"]
    view = cases.view(wf_id)
    saved = wf._row(wf_id)["definition"]
    assert view["definition"]["id"] == "workflow_monthly_reconciliation"
    assert view["definition"]["version"] == workflow_cases.definition(saved).version
    assert view["data"] == {"workflow": wf_id} and view["status"] == "open" and view["waiting_for"] is None
    assert _states(wf_id) == {"invoices": "ready", "statements": "ready", "reconcile": "waiting"}
    assert [(h["kind"], h["actor"]) for h in view["history"]] == [("started", "local:tester")]


def test_the_workflow_and_its_case_are_written_together_or_not_at_all(db, monkeypatch):  # noqa: F811
    party = _party()

    def broken(*args, **kwargs):
        raise RuntimeError("the store could not be written")

    with monkeypatch.context() as m:
        m.setattr(workflow_cases.cases, "start_in", broken)  # the case cannot start: no workflow either
        with pytest.raises(RuntimeError):
            _make(db, party, advance_now=False)
    assert (_count("workflows"), _count("workflow_steps"), _count("workflow_events")) == (0, 0, 0)
    with monkeypatch.context() as m:
        m.setattr(wf, "_event", broken)  # the workflow's log cannot be written: no case either
        with pytest.raises(RuntimeError):
            _make(db, party, advance_now=False)
    assert (_count("workflows"), _count("process_cases"), _count("process_steps"), _count("process_history")) == (0, 0, 0, 0)


# --- the workflows made before ---------------------------------------------------------------------------------------------


def _as_before(wf_id: str, states: dict[str, tuple[str, str | None]], *, archived: bool = False) -> None:
    """The workflow as an older version left it: its steps in these states, no case."""
    with store.connect() as c:
        for step, (state, note) in states.items():
            c.execute("UPDATE workflow_steps SET state=?, note=? WHERE workflow_id=? AND step=?", (state, note, wf_id, step))
        if archived:
            c.execute("UPDATE workflows SET status='archived' WHERE id=?", (wf_id,))
        for table in ("process_cases", "process_steps", "process_history", "process_timers"):
            c.execute(f"DELETE FROM {table} WHERE case_id=?", (wf_id,))


def _next_start() -> None:
    """The store's set-up as a process starting next runs it (the schema and its change helpers)."""
    store._initialized.clear()
    with store.connect():
        pass


def test_the_workflows_made_before_are_adopted_from_the_state_they_reached(db):  # noqa: F811
    made = [_make(db, _party(f"Example {n} Kft."), advance_now=False)["workflow"]["id"] for n in "DEFG"]
    _as_before(made[0], {"invoices": ("started", None), "statements": ("nothing_new", "no documents"),
                         "reconcile": ("waiting", None)})
    _as_before(made[1], {"invoices": ("pulling", None), "statements": ("starting", None),
                         "reconcile": ("failed", "no account")})
    _as_before(made[2], {"invoices": ("needs_budget", '{"over": {"openai": "0.2"}}'), "statements": ("linked", None)},
               archived=True)
    _as_before(made[3], {step: ("nothing_new", None) for step in ("invoices", "statements", "reconcile")})
    _next_start()
    assert _states(made[0]) == {"invoices": "running:approval", "statements": "done", "reconcile": "waiting"}
    assert _states(made[1]) == {"invoices": "running:fetch", "statements": "running", "reconcile": "failed"}
    assert cases.view(made[1])["steps"]["reconcile"]["note"] == "no account"
    assert _states(made[2]) == {"invoices": "running:budget", "statements": "running:approval", "reconcile": "waiting"}
    assert cases.get(made[2])["waiting_for"] == workflow_cases.ARCHIVED
    assert (cases.get(made[3])["status"], cases.get(made[3])["outcome"]) == ("closed", "done")
    checks = {(t["step_id"], t["name"], t["status"]) for w in made for t in engine.state(w)["timers"]}
    assert checks == {("invoices", "check", "armed"), ("statements", "check", "armed")}
    first = cases.view(made[0])
    assert first["history"][0]["kind"] == "adopted" and first["history"][0]["actor"] == "machine:workflow-adoption"
    assert cases.get(made[0])["started_by"] == '{"id": "local:tester", "kind": "human", "name": "tester", "org": "local"}'
    rows = _count("process_history")
    _next_start()  # adopted once: the next start changes nothing
    assert _count("process_history") == rows


# --- archiving --------------------------------------------------------------------------------------------------------------


def test_archiving_holds_the_case_and_restoring_it_resumes_it_with_the_workflows_own_change(db, monkeypatch):  # noqa: F811
    wf_id = _make(db, _party(), advance_now=False)["workflow"]["id"]
    wf.update(wf_id, actor="Example Person", archived=True)
    assert cases.get(wf_id)["waiting_for"] == workflow_cases.ARCHIVED

    def broken(*args, **kwargs):
        raise RuntimeError("the log could not be written")

    with monkeypatch.context() as m:
        m.setattr(wf, "_event", broken)
        with pytest.raises(RuntimeError):
            wf.update(wf_id, actor="Example Person", archived=False)
    assert wf.view(wf_id)["workflow"]["status"] == "archived" and cases.get(wf_id)["waiting_for"] == workflow_cases.ARCHIVED
    wf.update(wf_id, actor="Example Person", archived=False)
    assert cases.get(wf_id)["waiting_for"] is None
    held = [(h["kind"], h["actor"]) for h in cases.view(wf_id)["history"] if h["kind"] in ("held", "resumed")]
    assert held == [("held", "local:Example Person"), ("resumed", "local:Example Person")]
