"""231 (plan stage A, A4; DECISIONS 231): the process pack, one kind of business process described as data.

A pack is checked before it is used: every step names a registered capability whose parameters fit, a paid step is
started by a person (2026-09-28), no intake starts a case by itself (stage C), every screen element and scope part and
output is known, every reference points at something that is there, and no string names a Python module. Its process
core definition gives each step its capability's step kind and keeps the pack's version, so a case keeps the version
it started with.
"""

from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from jav.app import process_packs, registrations
from jav.core import cfg


@pytest.fixture(scope="module", autouse=True)
def _registered() -> None:
    registrations.load_all()


def _it_quote() -> dict:
    return copy.deepcopy(cfg.load("process:it_quote"))


def _problems(data: dict) -> list[str]:
    return process_packs._problems(process_packs.ProcessPack.model_validate(data))


def test_every_process_pack_passes_its_check() -> None:
    # 231 (C1c): the email routing; (C2d) the reconciliation; (C3b3) the bank statements and the documents
    assert [p.id for p in process_packs.packs()] == ["bank_statements", "documents", "insurance_offer", "insurance_renewal",
                                                     "it_quote", "mail_routing", "mailbox", "reconciliation"]  # (C3d) the
    # mailbox download; (D-f3) the insurance quote; (D-g) its renewal


def test_the_it_quote_pack_becomes_a_process_definition_of_capability_steps() -> None:
    pack = process_packs.load("it_quote")
    defn = process_packs.definition(pack)
    assert (defn.id, defn.version) == ("pack_it_quote", pack.version)
    assert [(s.id, s.kind) for s in defn.steps] == [
        ("request", "cap.record_assembly.v1"), ("match", "cap.catalogue_match.v1"), ("compose", "cap.line_draft.v1"),
        ("document", "cap.priced_document.v1"), ("letter", "cap.letter_draft.v1"), ("send", "cap.send.v1"),
        ("follow_up", "cap.wait_reply.v1")]
    match = next(s for s in defn.steps if s.id == "match")
    assert match.params == {"catalogue": "newest_active", "callsite": "quote_match", "_start": "person"}
    send = next(s for s in defn.steps if s.id == "send")  # 1.1.0 (A7e): a person sends the letter into the output folder
    assert send.params == {"message": "quote_letter", "mode": "output_folder", "from_step": "letter", "_start": "person"}
    assert [t.id for t in pack.screens.tabs] == ["request", "quote", "approval", "sent", "follow_up", "history"]


def _set_step(data: dict, step_id: str, **changes) -> dict:
    step = next(s for s in data["steps"] if s["id"] == step_id)
    step.update(changes)
    return data


@pytest.mark.parametrize(("change", "expected"), [
    (lambda d: _set_step(d, "match", uses="catalogue_match@9"), "no capability catalogue_match@9"),
    (lambda d: _set_step(d, "match", params={"catalogue": "@price_list"}), "do not fit catalogue_match@1: callsite"),
    (lambda d: _set_step(d, "letter", start="auto"), "a paid step (letter_draft@1) is started by a person"),
    (lambda d: _set_step(d, "send", params={"message": "nothing", "from_step": "letter"}), "do not fit send@1: message"),
    (lambda d: _set_step(d, "match", params={"catalogue": "@nowhere", "callsite": "quote_match"}), "unknown resource @nowhere"),
    (lambda d: d["screens"]["tabs"][0]["elements"].append({"type": "gauge"}) or d, "unknown screen element 'gauge'"),
    (lambda d: d["screens"]["tabs"][1]["elements"].append({"type": "approval", "step": "ghost"}) or d, "shows no step 'ghost'"),
    (lambda d: d.update(scope={"parts": ["client"]}) or d, "unknown scope part 'client'"),
    (lambda d: d.update(outputs=["policy"]) or d, "unknown output 'policy'"),
    (lambda d: d["intake"].append({"on": "email_intent", "starts": "offer"}) or d, "an email intake names its intent"),
    (lambda d: _set_step(d, "request", title="see jav.domains.quotes.quote_request"), "names a Python module"),
    (lambda d: _set_step(d, "compose", after=["letter"]), "do not make a process definition"),
])
def test_a_pack_that_breaks_a_rule_is_refused(change, expected) -> None:
    problems = _problems(change(_it_quote()))
    assert any(expected in p for p in problems), problems


def test_an_intake_starts_a_case_by_itself_only_from_an_email_s_record() -> None:
    data = _it_quote()
    data["intake"][0]["starts"] = "auto"
    with pytest.raises(ValidationError):
        process_packs.ProcessPack.model_validate(data)
    data["intake"][0]["starts"] = "case"  # 231 (C1b): an email's record starts the case by itself
    assert _problems(data) == []
    data["intake"][1]["starts"] = "case"
    assert "only an email intake starts a case by itself" in _problems(data)
    data["intake"][1]["starts"] = "manual"
    data["scope"]["parts"] = ["party"]
    assert any("needs a record scope part" in p for p in _problems(data))


def test_a_missing_pack_is_named() -> None:
    with pytest.raises(process_packs.PackError, match="no process pack 'insurance_quote'"):
        process_packs.load("insurance_quote")


def test_a_pack_whose_steps_read_no_record_offers_none() -> None:
    """231 (C3c): the general form's record chooser asks the pack's record step's capability; a pack without one has none."""
    assert process_packs.records("documents") == []
    with pytest.raises(process_packs.UnknownPack):
        process_packs.records("no_such_pack")
