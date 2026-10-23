"""A person's decision and the to-dos it settles in one transaction (215, plan G-process-core P2c).

Plain-language summary: decisions close to-dos: a duplicate pair's decision, a statement pair's choice, an email's
task decisions, an email's corrected intent (and a document's confirmed field, in `test_field_verdict_083.py`). Until
215 the decision was written first and its to-dos were closed in a second transaction, so a stop between the two left
a decision whose to-dos stayed open. Each test stops the work where the to-do is closed: nothing of the decision is
kept, and the to-do stays open. Synthetic documents and emails, stand-in models, no paid call.
"""

from __future__ import annotations

import pytest

from jav.app import corrections, work_readiness, work_recipes, work_runs
from jav.core import decisions, store
from jav.domains.email import email_store, email_tasks, mailbox
from jav.domains.finance import duplicates
from jav.domains.finance import statement_months as sm
from jav.runtime import worker
from tests import test_duplicates_126 as d126
from tests import test_reconcile_k2_129 as k2
from tests.test_email_results import _email_run, _fake_tasks
from tests.test_mailbox import MAILS, REQ, FakeBridge, env  # noqa: F401 - `env` is a fixture
from tests.test_statement_months_store_139 import _pair_in_run as _statement_pair


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield


def _stop_at_the_to_do(monkeypatch: pytest.MonkeyPatch) -> None:
    """The process stops while the decision's to-do is being closed."""
    def stopped(*args: object, **kwargs: object) -> None:
        raise RuntimeError("the process stopped while the to-do was closed")

    monkeypatch.setattr(store, "review_resolve", stopped)


def _open(kind: str, subject: str) -> list[str]:
    return [r["reason"] for r in store.review_open_reasons(kind, subject)]


def test_a_duplicate_decision_stopped_at_its_to_do_keeps_nothing(db, monkeypatch):  # noqa: F811
    earlier, now = d126._pair_in_run()
    _stop_at_the_to_do(monkeypatch)
    with pytest.raises(RuntimeError, match="process stopped"):
        duplicates.decide("run-1", now, earlier, decision="variant", actor="reviewer")
    assert duplicates.decisions_for([now]) == []
    assert decisions.history(duplicates.DECISION_KIND, duplicates.pair_key(now, earlier)) == []
    assert _open("document", now) == [f"duplicate:variant:{earlier[:16]}"]


def test_a_statement_choice_stopped_at_its_to_do_keeps_nothing(db, monkeypatch):  # noqa: F811
    a, b = _statement_pair()
    _stop_at_the_to_do(monkeypatch)
    with pytest.raises(RuntimeError, match="process stopped"):
        sm.decide(k2.RUN, b, a, keep=a, actor="reviewer")
    assert [r for r in sm.choice_rows() if r["pair_key"] == sm.pair_key(a, b)] == []
    assert decisions.history(sm.CHOICE_KIND, sm.pair_key(a, b)) == []
    assert _open("document", b) == [sm.reason(a)]


def _proposed_email(env, monkeypatch):  # noqa: F811 - the fixture's value
    """A live run over the mailbox's emails whose question email has one task proposal awaiting a decision."""
    monkeypatch.setattr(email_tasks, "extract", _fake_tasks)
    wp_id = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge(MAILS), inbox_root=env["inbox"])["workpackage"]
    work_recipes.assign_recipe(wp_id, "processing", params={"tasks": "propose"}, expected_revision=1, actor="t")
    ready = work_readiness.readiness(wp_id)
    run_id = work_runs.start_run(wp_id, mode="apply", expected_assignment_revision=2, input_hash=ready["input_hash"],
                                 actor="t")["run_id"]
    worker.run_worker(once=True)

    def proposed(i: dict) -> bool:
        tasks = corrections.item_result(run_id, i["item_id"])["email"]["tasks"]
        return bool(tasks and tasks["tasks"])

    item = next(i for i in work_runs.get_run(run_id)["input"]["items"] if proposed(i))
    return run_id, item


def test_an_email_task_decision_stopped_at_its_to_do_keeps_nothing(env, monkeypatch):  # noqa: F811
    run_id, item = _proposed_email(env, monkeypatch)
    before = [r["reason"] for r in work_runs.item_reasons(run_id, item["item_id"], item)["run"]]
    assert any(r.startswith("tasks:proposed") for r in before)
    _stop_at_the_to_do(monkeypatch)
    with pytest.raises(RuntimeError, match="process stopped"):
        mailbox.decide_task(run_id, item["item_id"], 0, decision="accepted", actor="t")
    flow_id = work_runs.flow_run_id(run_id, item["item_id"])
    assert email_store.email_task_decisions(flow_id) == {}
    assert decisions.history(mailbox.TASK_KIND, f"{flow_id}#0") == []
    assert [r["reason"] for r in work_runs.item_reasons(run_id, item["item_id"], item)["run"]] == before


def test_an_intent_correction_stopped_at_its_to_do_keeps_nothing(env, monkeypatch):  # noqa: F811
    _wp, run_id, items = _email_run(env)
    item_id = items[0]["item_id"]
    message_id = work_runs.review_subject(items[0])[1]
    store.review_enqueue(subject_kind="email", subject_id=message_id, run_id=work_runs.flow_run_id(run_id, item_id),
                         reasons=["intent:low_conf:szamlakuldes:0.41"], producer="email_intent")
    _stop_at_the_to_do(monkeypatch)
    with pytest.raises(RuntimeError, match="process stopped"):
        corrections.save(run_id, item_id, fields={"intent": "szamlakuldes"}, expected_revision=0, actor="ellenor")
    assert corrections.current(run_id, item_id)["revision"] == 0
    assert _open("email", message_id) == ["intent:low_conf:szamlakuldes:0.41"]
