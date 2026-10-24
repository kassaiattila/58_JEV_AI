"""231 (plan stage A, A5; DECISIONS 231): the IT quote as a case of its process pack, with the recorded results.

The IT quote's process pack (`configs/processes/it_quote.json`) runs each invented request as a case of the process
core: the request put together, the match a person starts, the draft a person approves, the priced document, the letter
a person starts, and (A7e, pack 1.1.0) the accepted letter a person sends into the output folder and the reply the case
waits for. Every step goes through its capability, on the case's container. The business results are the ones the
quote package's path recorded before stage A (`tests/fixtures/quote_path_231.json`): the same proposal, draft, Word
data and letter, and the same requests to the models. The two requests whose lines a person still has to resolve wait
at the draft, as they do on the package's path.
"""

from __future__ import annotations

import dataclasses
import email
import json
from email.policy import default

import pytest

from jav.app import app_settings, process_runtime, replies
from jav.core import identity
from jav.core.process import engine, tasks
from jav.domains.quotes import quote_document, quote_draft, quote_letter, quote_proposal
from tests import test_document_result_174 as rows
from tests.test_quote_path_231 import ACTOR, FIXTURE, _clean, _drain, golden  # noqa: F401 - the fixture

PERSON = identity.who(ACTOR)


def _start_tasks(case_id: str, *, send: bool = True) -> list[str]:
    return [t["task_id"] for t in engine.state(case_id)["tasks"]
            if t["status"] == tasks.OPEN and t["task_id"].startswith(f"step_start:{case_id}:")
            and (send or t["task_id"] != f"step_start:{case_id}:send")]


@pytest.fixture()
def out(tmp_path, monkeypatch):
    """The output folder the send step writes into (Settings)."""
    folder = tmp_path / "out"
    folder.mkdir()
    monkeypatch.setattr(app_settings, "output_folder", lambda: str(folder))
    return folder


def _drive(case_id: str, rounds: int = 40, *, send: bool = True, reply: bool = True) -> tuple[dict, dict | None]:
    """The case moved on as the worker and a person would: the core's turns (retry timers at once), the queued jobs, a
    person starting each waiting step, approving a draft that holds nothing, (A7b) accepting the letter and (A7e)
    recording the reply. Returns the case's state and the letter as it was before it was accepted."""
    letter = None
    for _ in range(rounds):
        engine.turn(case_id, wake=True)
        _drain()
        for tid in _start_tasks(case_id, send=send):
            tasks.decide(tid, PERSON)
        view = quote_draft.view(case_id)
        if view["draft"] is not None and not view["blockers"] and view["approval"]["active"] is None:
            quote_draft.approve(case_id, fingerprint=view["fingerprint"], actor=ACTOR)
        shown = quote_letter.view(case_id)
        if shown["state"] == "done" and shown["accepted"] is None:
            letter = _clean(shown)
            quote_letter.accept(case_id, shown["body"], actor=ACTOR, expected_state=shown["decision_state"])
        state = engine.state(case_id)
        if reply and state["steps"].get("follow_up", {}).get("waiting_for") == replies.REPLY:
            replies.reply(case_id, "follow_up", replies.REPLIED, ACTOR)
            continue
        if state["status"] != "open":
            break
    return engine.state(case_id), letter


def test_the_it_quote_runs_as_cases_with_the_recorded_results(golden, out) -> None:  # noqa: F811 - the shared fixture
    cases, seen = golden
    record = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for case in cases:
        seen.clear()
        case_id = process_runtime.start_case("it_quote", {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}},
                                             name=f"Quote {case.id}", actor=ACTOR)
        assert process_runtime.pack_of(case_id) == ("it_quote", "1.1.0")
        state, letter = _drive(case_id)
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
        assert letter == want["letter"], case.id  # the letter a person accepted, as it was shown
        assert steps["letter"]["result"]["accepted"] is True, case.id
        # A7e: the accepted letter went into the output folder once, with the approved version's Word document
        sent = steps["send"]["result"]
        written = out / "it_quote" / f"Quote-{case.id.replace('_', '-')}_{case_id}" / sent["file_name"]
        assert sent["receipt"] == {"path": str(written)} and sent["attempt"] == 1, case.id
        message = email.message_from_bytes(written.read_bytes(), policy=default)
        assert message["X-Unsent"] == "1" and message["Subject"] == sent["subject"], case.id
        body = message.get_body(("plain",)).get_content().splitlines()  # an email's lines end in CRLF
        assert "\n".join(body).strip() == letter["body"].strip(), case.id
        assert [a.get_filename().endswith(".docx") for a in message.iter_attachments()] == [True], case.id
        assert steps["follow_up"]["result"]["reply"] == "replied" and steps["follow_up"]["result"]["by"] == ACTOR, case.id
        assert {k: list(v) for k, v in sorted(seen.items())} == want["requests_to_models"], case.id
