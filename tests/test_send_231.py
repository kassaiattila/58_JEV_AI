"""231 (plan stage A, A7c; DECISIONS 231): the general send capability.

A case sends what one of its steps made by the mode its process pack names: into the output folder as a file (built
now), as an Outlook draft or straight out through Outlook (their bridge comes with A8). The message is recorded with the
case first and handed over once under its id: a handover the receiver refused fails the step, and a person's retry
sends it again as a new attempt; a handover whose outcome is unknown waits for a person, who says from the "Waiting for
me" list whether it arrived. The real send reaches only the allowlist's recipients, which is empty. Synthetic messages
and folders; no AI call.
"""

from __future__ import annotations

import pytest

from jav.app import app_settings, capabilities, sending, waiting
from jav.core import identity
from jav.core.process import cases, engine, outbox, tasks
from jav.core.process.definition import ProcessDef, StepDef

CLERK = identity.person("Clerk")
MACHINE = identity.machine("tests")
LETTER = b"To: buyer@example.com\r\nSubject: Our offer\r\n\r\nDear Buyer,\r\n"


def _letter(case_id: str, source) -> sending.Message:
    return sending.Message(LETTER, "offer.eml", "buyer@example.com", f"Our offer {(source or {}).get('attempt', '')}".strip())


@pytest.fixture()
def senders(monkeypatch, tmp_path):
    """The invented message builder, the send capability's registrations and an output folder of the test's own."""
    capabilities.of("send@1")  # the application's registrations
    monkeypatch.setattr(sending, "_BUILDERS", {**sending._BUILDERS})
    monkeypatch.setattr(sending, "_SENDERS", {**sending._SENDERS})
    sending.register_builder(sending.MessageBuilder("invented_letter", __name__, _letter, "An invented letter."))
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(app_settings, "output_folder", lambda: str(out))
    return out


def _case(case_id: str, **params) -> str:
    step = StepDef(id="send", kind="cap.send.v1", params={"message": "invented_letter", **params})
    definition = ProcessDef(id="invented_send", version="1", title="An invented send", steps=(step,))
    cases.start(case_id, definition, {}, MACHINE)
    engine.turn(case_id, wake=True)
    return case_id


def _state(case_id: str) -> dict:
    return engine.state(case_id)


def test_a_case_sends_its_message_into_the_output_folder_once(senders) -> None:
    case_id = _case("case-send-1")
    state = _state(case_id)
    assert state["status"] == "closed" and state["steps"]["send"]["state"] == "done"
    result = state["steps"]["send"]["result"]
    written = senders / "cases" / f"case_{case_id}" / "offer.eml"
    assert result["receipt"] == {"path": str(written)} and written.read_bytes() == LETTER
    assert (result["mode"], result["file_name"], result["to"], result["attempt"]) == ("output_folder", "offer.eml",
                                                                                      "buyer@example.com", 1)
    assert [h["status"] for h in state["handovers"]] == [outbox.ACKNOWLEDGED]
    assert sorted(p.name for p in written.parent.iterdir()) == ["offer.eml"]


def test_another_file_under_the_same_name_is_never_overwritten(senders) -> None:
    folder = senders / "cases" / "case_case-send-2"
    folder.mkdir(parents=True)
    (folder / "offer.eml").write_bytes(b"someone else's file")
    _case("case-send-2")
    assert (folder / "offer.eml").read_bytes() == b"someone else's file"
    assert (folder / "offer__2.eml").read_bytes() == LETTER


def test_without_an_output_folder_the_step_fails_and_a_retry_sends_it_again(senders, monkeypatch) -> None:
    monkeypatch.setattr(app_settings, "output_folder", lambda: None)
    case_id = _case("case-send-3")
    step = _state(case_id)["steps"]["send"]
    assert step["state"] == "failed" and "no output folder" in step["note"]
    monkeypatch.setattr(app_settings, "output_folder", lambda: str(senders))
    cases.retry(case_id, "send", CLERK)
    engine.turn(case_id, wake=True)
    state = _state(case_id)
    assert state["steps"]["send"]["state"] == "done" and state["steps"]["send"]["result"]["attempt"] == 2
    assert [h["status"] for h in state["handovers"]] == [outbox.FAILED, outbox.ACKNOWLEDGED]


@pytest.mark.parametrize(("said", "step_state"), [(outbox.ACKNOWLEDGED, "done"), (outbox.FAILED, "failed")])
def test_an_uncertain_handover_waits_for_a_person_who_says_whether_it_arrived(senders, said, step_state) -> None:
    def lost(_handover_id, _payload):
        raise OSError("the network share stopped answering")

    sending._SENDERS[sending.OUTPUT_FOLDER] = sending.Sender(sending.OUTPUT_FOLDER, __name__, lost)
    case_id = _case(f"case-send-4-{said}")
    state = _state(case_id)
    assert state["steps"]["send"]["state"] == "running" and state["steps"]["send"]["waiting_for"] == tasks.EVENT
    assert [h["status"] for h in state["handovers"]] == [outbox.UNCERTAIN]
    listed = [r for r in waiting.rows(CLERK.name) if r["kind"] == sending.SETTLE_TASK]
    assert [r["_key"] for r in listed] == [f"{sending.SETTLE_TASK}:{case_id}:send:1"]
    engine.turn(case_id, wake=True)  # nothing moves before the person says
    assert _state(case_id)["steps"]["send"]["state"] == "running"
    sending.settle(case_id, "send", said, CLERK)
    engine.turn(case_id, wake=True)
    state = _state(case_id)
    assert state["steps"]["send"]["state"] == step_state and [h["status"] for h in state["handovers"]] == [said]
    with pytest.raises(sending.SendError):
        sending.settle(case_id, "send", said, CLERK)


def test_the_real_send_reaches_only_the_allowlist(senders, monkeypatch) -> None:
    def config(allow):
        monkeypatch.setattr(sending.cfg, "load", lambda name: {"meta": {"version": "x"}, "outlook_send": {"allow": allow}})

    assert sending.cfg.load(sending.CONFIG)["outlook_send"]["allow"] == []  # the shipped rules: nothing goes out
    assert not sending.allowed("buyer@example.com") and not sending.allowed(None)
    config(["@example.com", "boss@example.org"])
    assert sending.allowed("Buyer <buyer@example.com>") and sending.allowed("buyer@example.com, boss@example.org")
    assert not sending.allowed("buyer@example.com, someone@example.net") and not sending.allowed("")
    config([])
    sent: list = []
    sending._SENDERS[sending.OUTLOOK_SEND] = sending.Sender(sending.OUTLOOK_SEND, __name__,
                                                            lambda hid, payload: sent.append(hid) or {})
    case_id = _case("case-send-5", mode="outlook_send")
    state = _state(case_id)
    assert state["steps"]["send"]["state"] == "failed" and "allowlist" in state["steps"]["send"]["note"]
    assert state["handovers"] == [] and sent == []


def test_a_mode_without_its_sender_or_an_unknown_message_fails_the_step(senders) -> None:
    sending._SENDERS.pop(sending.OUTLOOK_DRAFT)  # a version without the Outlook ways (the email domain registers them)
    assert _state(_case("case-send-6", mode="outlook_draft"))["steps"]["send"]["note"] == \
        "the outlook_draft mode is not available in this version"
    refused = _state(_case("case-send-7", message="nothing"))["steps"]["send"]["note"]
    assert refused == "the step's parameters do not fit send@1: message"  # a pack naming it is refused when checked


def test_the_message_is_made_from_the_step_it_names(senders) -> None:
    step_a = StepDef(id="letter", kind="cap.send.v1", params={"message": "invented_letter"})
    step_b = StepDef(id="send", kind="cap.send.v1", params={"message": "invented_letter", "from_step": "letter"},
                     after=("letter",))
    definition = ProcessDef(id="invented_send_from", version="1", title="An invented send", steps=(step_a, step_b))
    cases.start("case-send-8", definition, {}, MACHINE)
    engine.turn("case-send-8", wake=True)
    state = _state("case-send-8")
    assert state["steps"]["letter"]["result"]["subject"] == "Our offer"  # it names no step
    assert state["steps"]["send"]["result"]["subject"] == "Our offer 1"  # made from the first step's result
