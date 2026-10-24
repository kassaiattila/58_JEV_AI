"""231 (plan stage A, A5; DECISIONS 231): the IT quote as a case of its process pack, with the recorded results.

The IT quote's process pack (`configs/processes/it_quote.json`) runs each invented request as a case of the process
core: the request put together, the match a person starts, the draft a person approves, the priced document, the letter
a person starts. Every step goes through its capability, on the case's container. The business results are the ones the
quote package's path recorded before stage A (`tests/fixtures/quote_path_231.json`): the same proposal, draft, Word
data and letter, and the same requests to the models. The two requests whose lines a person still has to resolve wait
at the draft, as they do on the package's path.
"""

from __future__ import annotations

import dataclasses
import json

from jav.app import process_runtime
from jav.core import identity
from jav.core.process import engine, tasks
from jav.domains.quotes import quote_document, quote_draft, quote_letter, quote_proposal
from tests import test_document_result_174 as rows
from tests.test_quote_path_231 import ACTOR, FIXTURE, _clean, _drain, golden  # noqa: F401 - the fixture

PERSON = identity.who(ACTOR)


def _start_tasks(case_id: str) -> list[str]:
    return [t["task_id"] for t in engine.state(case_id)["tasks"]
            if t["status"] == tasks.OPEN and t["task_id"].startswith(f"step_start:{case_id}:")]


def _drive(case_id: str, rounds: int = 40) -> dict:
    """The case moved on as the worker and a person would: the core's turns (retry timers at once), the queued jobs, a
    person starting each waiting paid step and approving a draft that holds nothing."""
    for _ in range(rounds):
        engine.turn(case_id, wake=True)
        _drain()
        for tid in _start_tasks(case_id):
            tasks.decide(tid, PERSON)
        view = quote_draft.view(case_id)
        if view["draft"] is not None and not view["blockers"] and view["approval"]["active"] is None:
            quote_draft.approve(case_id, fingerprint=view["fingerprint"], actor=ACTOR)
        state = engine.state(case_id)
        if state["status"] != "open":
            break
    return engine.state(case_id)


def test_the_it_quote_runs_as_cases_with_the_recorded_results(golden) -> None:
    cases, seen = golden
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for case in cases:
        seen.clear()
        case_id = process_runtime.start_case("it_quote", {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}},
                                             name=f"Quote {case.id}", actor=ACTOR)
        assert process_runtime.pack_of(case_id) == ("it_quote", "1.0.0")
        state = _drive(case_id)
        want = record[case.id]
        steps = state["steps"]  # by step id
        assert _clean(quote_proposal.current(case_id)) == want["proposal"], case.id
        assert _clean(quote_draft.view(case_id))["lines"] == want["draft"]["lines"], case.id
        if "letter" not in want:  # a line a person has to resolve holds the approval, as on the package's path
            assert state["status"] == "open" and steps["compose"]["state"] == "running", case.id
            continue
        assert state["status"] == "closed", (case.id, {k: s["state"] for k, s in steps.items()})
        version = steps["compose"]["result"]["version"]
        approved = quote_draft.approved_version(case_id, version)
        data = quote_document.data(approved["quote"], package=f"Quote {case.id}", version=version, approved_by=ACTOR)
        assert _clean(json.loads(json.dumps(dataclasses.asdict(data), default=str))) == want["document"], case.id
        assert _clean(quote_letter.view(case_id)) == want["letter"], case.id
        assert {k: list(v) for k, v in sorted(seen.items())} == want["requests_to_models"], case.id
