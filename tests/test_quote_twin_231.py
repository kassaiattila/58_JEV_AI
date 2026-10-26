"""231 (stage D0, D0-b; the reassessment of 2026-10-26, F04, P02): the same capability twice in one case keeps two
states.

An invented pack matches one request with two price lists (two `catalogue_match` steps) and composes a quote from each
(two `line_draft` steps, each naming its match): each match step keeps its own proposal and budget, each composition
its own draft, approval, task and version; approving one leaves the other waiting, reopening one leaves the other
approved, and another case's steps of the same names are its own. A proposal job a worker took and never finished (a
stop) is run again at the next start, under its own step. The invented requests and the stand-in match of the quote
path; no paid call.
"""

from __future__ import annotations

import copy
import json

from jav.app import capabilities, human_tasks, process_runtime
from jav.core import cfg, identity
from jav.core import queue
from jav.core.process import engine, tasks
from jav.domains.quotes import invented_golden, price_lists, quote_draft, quote_proposal
from jav.runtime import job_kinds
from tests import test_document_result_174 as rows
from tests.test_quote_path_231 import ACTOR, FIXTURE, _drain, golden  # noqa: F401 - the fixture

PERSON = identity.who(ACTOR)
PACK = "twin_quote"


def _pack(list_a: str, list_b: str) -> dict:
    data = copy.deepcopy(cfg.load("process:it_quote"))
    request = next(s for s in data["steps"] if s["id"] == "request")
    data.update(id=PACK, title="Invented twin quote", intake=[{"on": "manual", "starts": "manual"}], partners=[],
                outputs=[], goldens=[], resources={})
    data["meta"] = {**data["meta"], "name": f"process:{PACK}", "version": "1.0.0"}
    data["steps"] = [request] + [
        step for side, catalogue in (("a", list_a), ("b", list_b)) for step in (
            {"id": f"match_{side}", "uses": "catalogue_match@1", "gates": ["request"], "start": "person",
             "params": {"catalogue": catalogue, "callsite": "quote_match"}},
            {"id": f"compose_{side}", "uses": "line_draft@1", "gates": ["request"], "after": [f"match_{side}"],
             "params": {"catalogue": catalogue, "from_step": f"match_{side}"}})]
    data["screens"] = {"tabs": [
        {"id": side, "label": side.upper(), "elements": [{"type": "match_proposal", "step": f"match_{side}"},
                                                         {"type": "line_editor", "step": f"compose_{side}"},
                                                         {"type": "approval", "step": f"compose_{side}"}]}
        for side in ("a", "b")] + [{"id": "history", "label": "History", "elements": [{"type": "timeline"}, {"type": "cost"}]}]}
    return data


def _second_list(tmp_path) -> str:
    made = price_lists.add("Invented B", "b.xlsx", invented_golden.write_price_list(tmp_path / "b.xlsx").read_bytes(),
                           actor=ACTOR)
    price_lists.activate(made["price_list"], 1, actor=ACTOR)
    return made["price_list"]


def _start(case) -> str:
    return process_runtime.start_case(PACK, {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}},
                                      name=f"Twin {case.id}", actor=ACTOR)


def _move(case_id: str, rounds: int = 20) -> None:
    """The core's turns, the queued jobs and a person starting each waiting step, until both drafts are made."""
    for _ in range(rounds):
        engine.turn(case_id, wake=True)
        _drain()
        for t in engine.state(case_id)["tasks"]:
            if t["status"] == tasks.OPEN and t["task_id"].startswith(f"step_start:{case_id}:"):
                tasks.decide(t["task_id"], PERSON)
        if all(quote_draft.view(case_id, step=s)["draft"] is not None for s in ("compose_a", "compose_b")):
            return


def _approve(case_id: str, step: str) -> int:
    view = quote_draft.view(case_id, step=step)
    return quote_draft.approve(case_id, fingerprint=view["fingerprint"], actor=ACTOR, step=step)["version"]


def _task(case_id: str, step: str) -> str:
    return tasks.get(tasks.task_id(human_tasks.OWN_APPROVAL, f"{case_id}:{step}")).status


def test_the_same_capability_twice_in_a_case_keeps_two_proposals_drafts_and_approvals(golden, tmp_path, monkeypatch):  # noqa: F811
    cases, _seen = golden
    list_a = price_lists.chosen().price_list
    list_b = _second_list(tmp_path)
    data = _pack(list_a, list_b)
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data if name == f"process:{PACK}" else real(name))
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    case = next(c for c in cases if "letter" in record[c.id])  # a request whose lines hold nothing after the match
    case_id = _start(case)
    _move(case_id)

    a, b = (quote_proposal.current(case_id, step=s) for s in ("match_a", "match_b"))
    assert (a["state"], a["price_list"], b["state"], b["price_list"]) == ("done", list_a, "done", list_b)
    scopes = {s: capabilities.step_scopes(case_id, s, "catalogue_match@1") for s in ("match_a", "match_b")}
    assert all(len(v) == 1 for v in scopes.values()) and scopes["match_a"] != scopes["match_b"]  # each its own budget
    drafts = {s: quote_draft.view(case_id, step=s) for s in ("compose_a", "compose_b")}
    assert {s: v["draft"]["price_list"] for s, v in drafts.items()} == {"compose_a": list_a, "compose_b": list_b}
    assert (_task(case_id, "compose_a"), _task(case_id, "compose_b")) == ("open", "open")

    assert _approve(case_id, "compose_a") == 1
    assert (_task(case_id, "compose_a"), _task(case_id, "compose_b")) == ("decided", "open")  # the other still waits
    assert quote_draft.view(case_id, step="compose_b")["approval"]["active"] is None
    assert _approve(case_id, "compose_b") == 2  # the case's next number
    engine.turn(case_id, wake=True)
    steps = engine.state(case_id)["steps"]
    assert (steps["compose_a"]["state"], steps["compose_b"]["state"]) == ("done", "done")

    quote_draft.reopen(case_id, note="The customer asked for another monitor", actor=ACTOR, step="compose_a")
    assert quote_draft.view(case_id, step="compose_a")["approval"]["active"] is None
    assert quote_draft.view(case_id, step="compose_b")["approval"]["active"]["version"] == 2  # left approved
    steps = engine.state(case_id)["steps"]
    assert (steps["compose_a"]["state"], steps["compose_b"]["state"]) == ("running", "done")
    assert (_task(case_id, "compose_a"), _task(case_id, "compose_b")) == ("open", "decided")

    other = _start(case)  # another case: its steps of the same names are its own
    assert quote_proposal.current(other, step="match_a") is None and quote_draft.view(other, step="compose_a")["draft"] is None


def test_a_proposal_job_left_by_a_stopped_worker_runs_again_under_its_own_step(golden, tmp_path, monkeypatch):  # noqa: F811
    cases, _seen = golden
    list_a = price_lists.chosen().price_list
    list_b = _second_list(tmp_path)
    data = _pack(list_a, list_b)
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data if name == f"process:{PACK}" else real(name))
    case_id = _start(cases[0])
    quote_proposal.request(case_id, actor=ACTOR, step="match_b")
    job = queue.claim("stopped-worker", kinds=(*(k.kind for k in job_kinds.kinds()),))
    assert job is not None and job.payload["step_id"] == "match_b"  # taken, never finished: the worker stopped
    assert queue.recover_orphans().requeued == 1  # the next start puts it back
    _drain()
    assert quote_proposal.current(case_id, step="match_b")["state"] == "done"
    assert quote_proposal.current(case_id, step="match_a") is None


def test_an_older_store_s_quote_table_is_rebuilt_with_its_case_s_step(tmp_path) -> None:
    from jav.core import store
    from jav.domains.quotes import quote_steps

    with store.use_store(tmp_path / "older.sqlite"):
        with store.connect() as c:  # the drafts' table as a store before D0-b keeps it: one row a case's, one not
            c.execute("DROP TABLE quote_drafts")
            c.execute("CREATE TABLE quote_drafts (workpackage_id TEXT PRIMARY KEY, content TEXT NOT NULL, started_by TEXT"
                      " NOT NULL, started_by_id TEXT, started_at TEXT NOT NULL, updated_by TEXT NOT NULL, updated_by_id TEXT,"
                      " updated_at TEXT NOT NULL)")
            definition = json.dumps({"id": "pack_it_quote", "version": "1.3.0", "title": "IT quote",
                                     "steps": [{"id": "request", "kind": "cap.record_assembly.v1"},
                                               {"id": "compose", "kind": "cap.line_draft.v1"}]})
            c.execute("INSERT INTO process_cases(case_id, definition_id, definition_version, definition_sha, definition, data,"
                      " start_sha, status, started_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      ("wp-00000000c0de", "pack_it_quote", "1.3.0", "x", definition, "{}", "y", "open", "{}", "t", "t"))
            for wp in ("wp-00000000c0de", "wp-00000000beef"):
                c.execute("INSERT INTO quote_drafts VALUES (?, '{}', 'anna', NULL, 't', 'anna', NULL, 't')", (wp,))
            c.commit()
            quote_steps.rebuild(c, "quote_drafts", quote_draft._DDL, quote_steps.COMPOSE)
            quote_steps.rebuild(c, "quote_drafts", quote_draft._DDL, quote_steps.COMPOSE)  # once
            rows = sorted(tuple(r) for r in c.execute("SELECT workpackage_id, step_id, started_by FROM quote_drafts"))
    assert rows == [("wp-00000000beef", "", "anna"), ("wp-00000000c0de", "compose", "anna")]
