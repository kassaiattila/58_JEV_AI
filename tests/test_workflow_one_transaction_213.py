"""A workflow step's change and its event are written in one transaction (213, plan G-process-core P1b-1).

Plan 212 P0 rule 4 found that the workflow engine wrote a step's new state and the event of its log in two
transactions, so a process stopping between them left a change without its event. Now both are written together, or
neither: an event that cannot be written leaves the step as it was, and a claim another process got first writes no
event either. Synthetic data, temporary store, no paid calls.
"""

from __future__ import annotations

import pytest

from jav.app import parties, workflows as wf
from jav.core import store
from tests.test_workflow_references_153 import _make, db  # noqa: F401 - the fixture is used by name


def _steps(wf_id: str) -> dict[str, dict]:
    return {s["id"]: s for s in wf.view(wf_id)["steps"]}


def _events(wf_id: str) -> list[tuple]:
    with store.connect() as c:
        return [tuple(r) for r in c.execute("SELECT step, action FROM workflow_events WHERE workflow_id=? ORDER BY id",
                                            (wf_id,))]


def test_a_failing_event_leaves_the_step_as_it_was(db, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    a = parties.create("Example T Kft.", identities=[], actor="t")["id"]
    wf_id = _make(db, a, advance_now=False)["workflow"]["id"]
    before, events = _steps(wf_id)["invoices"], _events(wf_id)

    def broken(*args, **kwargs):
        raise RuntimeError("the log could not be written")

    with monkeypatch.context() as m:
        m.setattr(wf, "_event", broken)
        with pytest.raises(RuntimeError):
            wf.start_step(wf_id, "invoices", actor="t", budget={"openai": "0.5"})
    after = _steps(wf_id)["invoices"]
    assert after["budget"] == before["budget"] and after["state"] == before["state"] == "waiting"
    assert _events(wf_id) == events


def test_a_claim_another_process_got_first_writes_no_event(db) -> None:  # noqa: F811
    a = parties.create("Example U Kft.", identities=[], actor="t")["id"]
    wf_id = _make(db, a, advance_now=False)["workflow"]["id"]
    events = _events(wf_id)
    assert not wf._set_logged(wf_id, "invoices", "failed", "t", {"note": "x"}, expect=("starting",), state="failed")
    assert _steps(wf_id)["invoices"]["state"] == "waiting" and _events(wf_id) == events
    assert wf._set_logged(wf_id, "invoices", "failed", "t", {"note": "x"}, expect=("waiting",), state="failed", note="x")
    assert _steps(wf_id)["invoices"]["state"] == "failed" and _events(wf_id) == [*events, ("invoices", "failed")]
