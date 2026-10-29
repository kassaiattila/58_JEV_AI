"""231 (stage U, U3f; the owner's decision of 2026-10-28: the letter frames are edited now, with versions).

The shared library lists the letter frames of both kinds (the covering letters, the quote's reply letters) with the
file's text and the text in effect. A changed frame is saved as a draft, refused when a field is empty or a marker
names no value of the documents, and becomes the frame's text once made active: a case keeps the version active when
it starts (its own rule values over the rule file), and setting it aside brings the file's text back for the cases
that start after. The rule of who may make a version active is the process values' rule. Real rule files, an empty
store; nothing runs and no AI is asked.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from jav.app import capabilities, letter_frames, process_packs, process_settings, registrations
from jav.core import cfg, store
from jav.service.api import create_app

registrations.load_all()

SUBJECT = "Our offer - {{policyholder}}"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "frames.sqlite"):
        yield tmp_path


def _frame(kind: str, ident: str) -> dict:
    found = next(k for k in letter_frames.listing()["kinds"] if k["kind"] == kind)
    return next(f for f in found["frames"] if f["ident"] == ident)


def _kept_subject(pack_id: str) -> str:
    """The covering letter's subject as a case of the pack started now reads it."""
    values, refs = process_settings.effective_rules(process_packs.load(pack_id))
    over = capabilities.case_overlay({capabilities.RULES: values, capabilities.RULE_REFS: refs})
    with cfg.overlay(over):
        return cfg.load("letter_frames")["frames"]["offer_letter"]["subject"]


def test_both_kinds_are_listed_with_the_file_s_text(db) -> None:
    listed = letter_frames.listing()
    assert [k["kind"] for k in listed["kinds"]] == ["letter_frame", "quote_letter_frame"]
    offer = _frame("letter_frame", "offer_letter")
    assert offer["content"] == offer["file"] and offer["active"] is None and offer["versions"] == []
    assert "policyholder" in offer["markers"]
    assert {f["ident"] for f in next(k for k in listed["kinds"] if k["kind"] == "quote_letter_frame")["frames"]} == {"letter"}
    assert listed["policy"]["activation"] == "editor"


def test_a_changed_frame_reaches_the_cases_started_after_it_is_made_active(db) -> None:
    before = _kept_subject("insurance_offer")
    letter_frames.propose("letter_frame", "offer_letter", {"subject": SUBJECT}, "anna", note="shorter")
    assert _kept_subject("insurance_offer") == before  # a draft reaches no case
    letter_frames.activate("letter_frame", "offer_letter", 1, "bela")
    assert _kept_subject("insurance_offer") == SUBJECT
    assert _kept_subject("allianz_property_offer") == SUBJECT  # every process that uses the frame
    _values, refs = process_settings.effective_rules(process_packs.load("insurance_offer"))
    assert refs["letter_frames"]["frames.offer_letter"] == {"setting": "letter_frame/offer_letter", "version": 1}
    frame = _frame("letter_frame", "offer_letter")
    assert frame["content"]["subject"] == SUBJECT and frame["content"]["paragraphs"] == frame["file"]["paragraphs"]
    assert (frame["active"], frame["versions"][0]["note"]) == (1, "shorter")
    letter_frames.retire("letter_frame", "offer_letter", "anna")
    assert _kept_subject("insurance_offer") == before  # the file's text again


def test_paragraphs_and_a_reply_letter_s_language_are_edited_as_fields(db) -> None:
    letter_frames.propose("letter_frame", "renewal_letter", {"paragraphs": ["  First paragraph.  ", "", "Premium: {{total}}."]}, "anna")
    draft = _frame("letter_frame", "renewal_letter")["versions"][0]
    assert draft["state"] == "draft" and draft["content"]["paragraphs"] == ["First paragraph.", "Premium: {{total}}."]
    letter_frames.propose("quote_letter_frame", "letter", {"en.closing": "Best regards,"}, "anna")
    quote = _frame("quote_letter_frame", "letter")["versions"][0]["content"]
    assert quote["en"]["closing"] == "Best regards," and quote["hu"] == _frame("quote_letter_frame", "letter")["file"]["hu"]


@pytest.mark.parametrize(("values", "problem"), [
    ({"subject": "Offer - {{policy_holder}}"}, "names no value"),
    ({"subject": "Offer - {{policyholder"}, "not closed"),
    ({"closing": "  "}, "cannot be empty"),
    ({"subject": "two\nlines"}, "one line"),
    ({"paragraphs": []}, "at least one paragraph"),
    ({"file": "other"}, "has no field"),
])
def test_a_frame_with_a_problem_is_refused_naming_it(db, values, problem) -> None:
    with pytest.raises(letter_frames.FrameError, match=problem):
        letter_frames.propose("letter_frame", "offer_letter", values, "anna")


def test_an_unchanged_frame_or_an_unknown_one_is_refused(db) -> None:
    subject = _frame("letter_frame", "offer_letter")["file"]["subject"]
    with pytest.raises(letter_frames.FrameError, match="unchanged"):
        letter_frames.propose("letter_frame", "offer_letter", {"subject": f" {subject} "}, "anna")
    with pytest.raises(letter_frames.UnknownFrame):
        letter_frames.propose("letter_frame", "no_such_letter", {"subject": "x"}, "anna")
    with pytest.raises(letter_frames.UnknownFrame):
        letter_frames.propose("no_such_kind", "offer_letter", {"subject": "x"}, "anna")


def test_the_service_saves_makes_active_and_sets_aside(db) -> None:
    with TestClient(create_app(store_path=store.current_path()), base_url="http://127.0.0.1:8930") as c:
        human = {"X-Actor": "anna"}
        assert c.get("/api/library/letter-frames").status_code == 200
        made = c.post("/api/library/letter-frames/letter_frame/offer_letter", headers=human,
                      json={"values": {"subject": SUBJECT}, "note": None})
        assert made.status_code == 201
        bad = c.post("/api/library/letter-frames/letter_frame/offer_letter", headers=human,
                     json={"values": {"subject": "{{nope}}"}})
        assert bad.status_code == 422
        assert c.post("/api/library/letter-frames/letter_frame/offer_letter/versions/1/activate", headers=human,
                      json={}).status_code == 200
        assert c.post("/api/library/letter-frames/letter_frame/offer_letter/retire", headers=human, json={}).status_code == 200
        assert c.post("/api/library/letter-frames/letter_frame/offer_letter/retire", headers=human, json={}).status_code == 409
