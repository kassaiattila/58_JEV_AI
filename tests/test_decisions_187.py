"""187 (plan G-full-move T2c): the shared decision handler, and the email task decisions recorded through it.

The handler writes every change of a decision into one journal, in the owner's transaction; a decision's state is its
latest journal row, which a page sends back, so a change made on a stale page is refused. The email task decision is
the first owner: before, a changed decision overwrote the earlier one and nothing kept it (the schema's comment
promised a log that did not exist), and a stale page's decision or done mark was written over a newer one.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from jav import api, corrections, datasets, decisions, mailbox, store, work
from tests.test_audit_fixes_1002 import _reviewed_email
from tests.test_mailbox import env  # noqa: F401 - `env` is a fixture

HUMAN = {"X-Actor": "teszt.elek"}


@pytest.fixture()
def journal(tmp_path, monkeypatch):
    monkeypatch.setitem(decisions._KINDS, "probe", decisions.Kind("probe", ("set", "clear"), __name__))
    with store.use_store(tmp_path / "j.sqlite"):
        yield


def test_each_change_is_kept_and_the_state_follows_the_latest(journal) -> None:
    with store.connect() as c:
        assert decisions.state(c, "probe", "k") == 0
        first = decisions.record(c, "probe", "k", "set", actor="a", value={"v": 1}, run_id="run-1")
        second = decisions.record(c, "probe", "k", "clear", actor="b", note="why")
        decisions.record(c, "probe", "other", "set", actor="a")
        assert decisions.state(c, "probe", "k") == second > first
        assert decisions.states(c, "probe", ["k", "other", "none"]) == {"k": second, "other": second + 1, "none": 0}
        assert decisions.run_state(c, "run-1") == first and decisions.run_state(c, "run-2") == 0
    rows = decisions.history("probe", "k")
    assert [(r["action"], r["value"], r["actor"], r["note"]) for r in rows] == [("set", {"v": 1}, "a", None),
                                                                               ("clear", None, "b", "why")]


def test_a_stale_state_is_a_conflict_and_none_is_not_compared(journal) -> None:
    with store.connect() as c:
        decisions.check(c, "probe", "k", 0)
        decisions.check(c, "probe", "k", None)
        now = decisions.record(c, "probe", "k", "set", actor="a")
        decisions.check(c, "probe", "k", now)
        with pytest.raises(work.RevisionConflict, match="changed meanwhile"):
            decisions.check(c, "probe", "k", 0)


def test_an_unknown_kind_or_action_is_refused(journal) -> None:
    with store.connect() as c, pytest.raises(ValueError, match="no module registered"):
        decisions.record(c, "nope", "k", "set", actor="a")
    with store.connect() as c, pytest.raises(ValueError, match="no action"):
        decisions.record(c, "probe", "k", "drop", actor="a")
    with pytest.raises(ValueError, match="registered twice"):
        decisions.register(decisions.Kind("probe", ("set",), __name__))
    decisions.register(decisions.Kind("probe", ("set", "clear"), __name__))  # the same kind again adds nothing


def test_one_change_of_a_scope_at_a_time() -> None:
    seen: list[str] = []

    def change(name: str) -> None:
        with decisions.one_at_a_time("probe", "wp-1"):
            seen.append(f"{name}:in")
            time.sleep(0.05)
            seen.append(f"{name}:out")

    threads = [threading.Thread(target=change, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen in (["a:in", "a:out", "b:in", "b:out"], ["b:in", "b:out", "a:in", "a:out"])


# --- the email task decisions -----------------------------------------------------------------------------------


def _task(run_id: str, item_id: str) -> dict:
    return corrections.item_result(run_id, item_id)["email"]["tasks"]["tasks"][0]


def test_a_changed_task_decision_keeps_the_earlier_one(env, monkeypatch) -> None:  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)
    state = _task(run_id, item["item_id"])["decision_state"]
    mailbox.decide_task(run_id, item["item_id"], 0, decision="rejected", actor="second", note="not ours",
                        expected_state=state)
    key = f"{work.flow_run_id(run_id, item['item_id'])}#0"
    rows = decisions.history(mailbox.TASK_KIND, key)
    assert [(r["action"], r["value"], r["actor"], r["note"]) for r in rows] == [
        ("decide", {"decision": "accepted"}, "t", None), ("decide", {"decision": "rejected"}, "second", "not ours")]
    assert rows[0]["run_id"] == run_id and rows[0]["workpackage_id"] == work.get_run(run_id)["workpackage_id"]
    assert _task(run_id, item["item_id"])["decision_state"] == rows[-1]["id"]


def test_a_task_decision_from_a_stale_page_is_refused(env, monkeypatch) -> None:  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)
    seen = _task(run_id, item["item_id"])["decision_state"]
    mailbox.decide_task(run_id, item["item_id"], 0, decision="rejected", actor="other tab", expected_state=seen)
    with pytest.raises(work.RevisionConflict):
        mailbox.decide_task(run_id, item["item_id"], 0, decision="accepted", actor="stale tab", expected_state=seen)
    with pytest.raises(work.RevisionConflict):
        mailbox.mark_task_done(run_id, item["item_id"], 0, done=True, actor="stale tab", expected_state=seen)
    assert _task(run_id, item["item_id"])["decision"]["decision"] == "rejected"
    c = TestClient(api.create_app(store_path=store.active_path()), base_url="http://127.0.0.1:8930")
    url = f"/api/runs/{run_id}/items/{item['item_id']}/tasks/0/decision"
    r = c.post(url, json={"decision": "accepted", "expected_state": seen}, headers=HUMAN)
    assert r.status_code == 409 and r.json()["error"] == "revision_conflict"
    now = _task(run_id, item["item_id"])["decision_state"]
    r = c.post(url, json={"decision": "accepted", "expected_state": now}, headers=HUMAN)
    assert r.status_code == 200 and r.json()["email"]["tasks"]["tasks"][0]["decision_state"] > now


def test_the_done_mark_is_journaled_and_changes_the_runs_cache_mark_not_its_reviewed_version(env, monkeypatch) -> None:  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)
    version, mark = corrections.review_version(run_id), datasets._run_fingerprint({"run_id": run_id})
    mailbox.mark_task_done(run_id, item["item_id"], 0, done=True, actor="t")
    assert corrections.review_version(run_id) == version
    assert datasets._run_fingerprint({"run_id": run_id}) != mark
    key = f"{work.flow_run_id(run_id, item['item_id'])}#0"
    assert [r["action"] for r in decisions.history(mailbox.TASK_KIND, key)] == ["decide", "done"]


def test_a_refused_change_writes_no_journal_row(env, monkeypatch) -> None:  # noqa: F811
    run_id, item = _reviewed_email(env, monkeypatch)
    mailbox.decide_task(run_id, item["item_id"], 0, decision="rejected", actor="t")
    key = f"{work.flow_run_id(run_id, item['item_id'])}#0"
    before = decisions.history(mailbox.TASK_KIND, key)
    with pytest.raises(work.RevisionConflict, match="not accepted"):
        mailbox.mark_task_done(run_id, item["item_id"], 0, done=True, actor="t")
    assert decisions.history(mailbox.TASK_KIND, key) == before


# --- the duplicate decisions and the statement choices ----------------------------------------------------------


@pytest.fixture()
def db(tmp_path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield


def test_a_duplicate_decision_is_journaled_and_a_stale_one_refused(db) -> None:
    from jav import duplicates
    from tests import test_duplicates_126 as d126

    earlier, now = d126._pair_in_run()
    [pair] = duplicates.item_pairs(now, store.review_open_reasons("document", now))
    assert pair["decision_state"] == 0
    duplicates.decide("run-1", now, earlier, decision="variant", actor="reviewer", expected_state=0)
    with pytest.raises(work.RevisionConflict):
        duplicates.decide("run-1", now, earlier, decision="copy", actor="stale tab", expected_state=0)
    [pair] = duplicates.item_pairs(now, [])
    duplicates.decide("run-1", earlier, now, decision="different", actor="other", expected_state=pair["decision_state"])
    rows = decisions.history(duplicates.DECISION_KIND, duplicates.pair_key(now, earlier))
    assert [(r["value"]["decision"], r["actor"], r["run_id"]) for r in rows] == [("variant", "reviewer", "run-1"),
                                                                                ("different", "other", "run-1")]
    assert duplicates.decisions_for([now])[0]["decided_at"] == rows[-1]["at"]  # one time for the row and its journal


def test_a_statement_pair_decided_in_an_approved_run_is_frozen_for_another_run(db) -> None:
    """Bug 3 of the survey (186): a later choice made in another run changed the reviewed version of the approved run
    that had decided the pair. Now it is refused, as a duplicate decision is."""
    from jav import statement_months as sm
    from tests import test_reconcile_k2_129 as k2
    from tests.test_statement_months_store_139 import _pair_in_run

    a, b = _pair_in_run()
    sm.decide(k2.RUN, b, a, keep=a, actor="reviewer")
    with store.connect() as c:
        c.execute("UPDATE runs SET approval='approved' WHERE run_id=?", (k2.RUN,))
    approved = corrections.review_version(k2.RUN)
    k2._run("run-2", ["b"])
    with pytest.raises(work.RevisionConflict, match="decided in an approved run"):
        sm.decide("run-2", b, a, keep=None, actor="later")
    assert corrections.review_version(k2.RUN) == approved
    [row] = [r for r in sm.choice_rows() if r["pair_key"] == sm.pair_key(a, b)]
    assert (row["keep_doc_id"], row["run_id"]) == (a, k2.RUN)


def test_a_statement_choice_is_journaled_and_a_stale_one_refused(db) -> None:
    from jav import statement_months as sm
    from tests import test_reconcile_k2_129 as k2
    from tests.test_statement_months_store_139 import _pair_in_run

    a, b = _pair_in_run()
    [view] = sm.item_view(b, [])
    assert view["decision_state"] == 0
    sm.decide(k2.RUN, b, a, keep=a, actor="reviewer", expected_state=0)
    with pytest.raises(work.RevisionConflict, match="changed meanwhile"):
        sm.decide(k2.RUN, b, a, keep=None, actor="stale tab", expected_state=0)
    [view] = sm.item_view(b, [])
    sm.decide(k2.RUN, a, b, keep=None, actor="reviewer", expected_state=view["decision_state"])
    rows = decisions.history(sm.CHOICE_KIND, sm.pair_key(a, b))
    assert [(r["value"], r["actor"]) for r in rows] == [({"keep": a}, "reviewer"), ({"keep": None}, "reviewer")]
