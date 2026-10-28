"""231 (stage D, D-f8): a letter that goes with a printed document (`letter@1`), and its send.

An invented pack: a step approves a version of its own, the shared priced document prints it (a stand-in builder for
the offer's output) and stores the file, the letter is written from its frame with the document's values, a person
accepts it and the send step hands its email file over. The draft greets the addressee by name, or without one when the
document names none; a letter with a marker left in it, an address that is none, an empty or too long subject, or sent
from a page showing an older document is refused; the accepted letter is kept as an email file with the document
attached, and the send hands over that very file. A document step that stored no file (the quote's) gives no letter.
Invented data; no paid call.
"""

from __future__ import annotations

import email
import hashlib
import time
from email.policy import default

import pytest
from pydantic import BaseModel, ConfigDict

from jav.app import (app_settings, capabilities, letters, package_release, process_runtime, rated_offer,
                     registrations)
from jav.app.outputs import contract, parts
from jav.core import cfg, decisions, identity, store
from jav.core.process import cases, engine, kinds
from jav.core.process.definition import ProcessDef, StepDef
from jav.core.process.engine import StepContext

ANNA = "Minta Anna"
_CLOCK = [time.time()]


class _Nothing(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _approve(ctx, _p) -> kinds.StepOutcome:
    """An invented step done with an approved version of its own."""
    case_id = str(ctx.data["container"])
    active = package_release.own_approval(case_id, step=ctx.step.id)["active"]
    if active is None:
        with ctx.transaction() as c:
            n = package_release.record_own(c, case_id, content={"premium": "487000"}, fingerprint="f", locks=[],
                                           actor=identity.person("Minta Bela"), step=ctx.step.id)
        return kinds.Done({"version": n})
    return kinds.Done({"version": active["version"]})


def _offer(named: bool) -> contract.OutputData:
    labels = rated_offer.settings()["labels"]
    values = {"policyholder": "Minta Kft.", "contact_name": "Minta Anna" if named else None,
              "contact_email": "anna@minta.hu", "product": "Kitalált vállalkozói vagyonbiztosítás",
              "cover_start": "2027-01-01", "currency": "HUF", "total": "487000"}
    spec = contract.spec(rated_offer.OUTPUT)["tables"]["modules"]["columns"]
    heads = rated_offer.settings()["heads"]["modules"]
    table = contract.table("modules", "modules", rated_offer.COLUMNS, tuple(heads[c] for c in rated_offer.COLUMNS),
                           [["Vagyonbiztosítás", "487000"]], tuple(spec[c] for c in rated_offer.COLUMNS))
    return contract.OutputData(rated_offer.OUTPUT, tuple(contract.Value(k, labels[k], v) for k, v in values.items()), (table,))


def _pack(pid: str) -> dict:
    return {"meta": {"name": f"process:{pid}", "version": "1.0.0"}, "id": pid, "title": "Invented letter",
            "intake": [{"on": "manual", "starts": "manual"}],
            "steps": [{"id": "approved", "uses": "invented_approval@1", "params": {}},
                      {"id": "document", "uses": "priced_document@1", "after": ["approved"],
                       "params": {"output": "rated_offer", "from_step": "approved"}},
                      {"id": "letter", "uses": "letter@1", "after": ["document"],
                       "params": {"frame": "offer_letter", "from_step": "document"}},
                      {"id": "send", "uses": "send@1", "after": ["letter"],
                       "params": {"message": "letter", "mode": "output_folder", "from_step": "letter"}}],
            "screens": {"tabs": [{"id": "history", "label": "History", "elements": [{"type": "timeline"}]}]}}


@pytest.fixture()
def case(monkeypatch, tmp_path):
    """A case of the invented pack, its document printed by the stand-in builder (`named`: the addressee's name)."""
    registrations.load_all()
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    capabilities.register(capabilities.Capability(
        name="invented_approval", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Nothing,
        run=_approve, state="step", output=capabilities.OwnVersionResult))
    named = {"on": True}
    monkeypatch.setattr(parts, "_VERSIONS", {**parts._VERSIONS, rated_offer.OUTPUT: parts.VersionDocument(
        rated_offer.OUTPUT, "tests.synthetic", lambda content, **kw: _offer(named["on"]), reads_case=True,
        name=lambda content, package, n: f"ajanlat-v{n}.docx")})
    data = {"process:invented_letter": _pack("invented_letter")}
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data[name] if name in data else real(name))
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(app_settings, "output_folder", lambda: str(out))
    with store.use_store(tmp_path / "letters.sqlite"):
        case_id = process_runtime.start_case("invented_letter", {}, name="Minta Kft.", actor=ANNA)
        _turn(case_id)
        yield case_id, named, out


def _turn(case_id: str) -> dict:
    for _ in range(2):
        _CLOCK[0] = max(_CLOCK[0], time.time()) + 10  # never behind the real time the steps' timers are set from
        engine.turn(case_id, now=_CLOCK[0])
    return engine.state(case_id)


def _accept(case_id: str, **over) -> dict:
    shown = letters.view(case_id, "letter")
    values = {**shown["draft"], "expected_basis": shown["basis"], **over}
    return letters.accept(case_id, "letter", to=values["to"], subject=values["subject"], body=values["body"],
                          expected_basis=values["expected_basis"], actor=identity.person(ANNA))


def test_the_letter_is_written_from_its_frame_accepted_and_sent_as_that_file(case) -> None:
    case_id, _named, out = case
    shown = letters.view(case_id, "letter")
    draft, document = shown["draft"], shown["document"]
    assert (draft["to"], draft["subject"]) == ("anna@minta.hu", "Biztosítási ajánlat – Minta Kft.")
    assert draft["body"] == ("Tisztelt Minta Anna!\n\nKöszönjük ajánlatkérését. Mellékelten küldjük a(z) Kitalált vállalkozói"
                             " vagyonbiztosítás ajánlatunkat 2027. 01. 01. kockázatviselési kezdettel.\n\nAz éves díj"
                             " 487 000 Ft. A fedezetek díját és a vonatkozó feltételeket a mellékelt dokumentum"
                             " tartalmazza.\n\nÜdvözlettel:\nMinta Anna\n")  # U1: signed by the case's owner
    assert shown["accepted"] is None and shown["approval"]["state"] == "missing"
    _accept(case_id, body=draft["body"] + "\nMinta Anna, Kitalált Biztosító Zrt.")  # a person adds a signature
    state = _turn(case_id)
    result = state["steps"]["letter"]["result"]
    eml, name = package_release.own_file(case_id, result["version"], package_release.APPROVED)["content"], result["file"]["name"]
    assert result["file"]["sha256"] == hashlib.sha256(eml).hexdigest() and name == f"ajanlat-kiserolevel-Minta-Kft-v{result['version']}.eml"
    message = email.message_from_bytes(eml, policy=default)
    assert (message["To"], message["Subject"], message["X-Unsent"]) == ("anna@minta.hu", "Biztosítási ajánlat – Minta Kft.", "1")
    assert message.get_body().get_content().rstrip().endswith("Minta Anna, Kitalált Biztosító Zrt.")
    [attached] = list(message.iter_attachments())
    printed = package_release.own_file(case_id, document["version"], package_release.APPROVED)
    assert (attached.get_filename(), attached.get_content()) == (document["name"], printed["content"])
    assert state["steps"]["send"]["state"] == "done" and [p.read_bytes() for p in out.rglob("*.eml")] == [eml]
    with store.connect() as c:
        assert cases.find_case_in(c, case_id)["status"] == cases.CLOSED


def test_a_document_its_builder_cannot_print_holds_the_case_with_the_reason(monkeypatch, tmp_path) -> None:
    """D-f9: a step that did not finish is what holds the case, with its note (the invented pack shows no element for
    it, so no view resolves it)."""
    from jav.app import case_views

    registrations.load_all()
    monkeypatch.setattr(capabilities, "_CAPS", dict(capabilities._CAPS))
    monkeypatch.setattr(kinds, "_KINDS", dict(kinds._KINDS))
    capabilities.register(capabilities.Capability(
        name="invented_approval", version=1, module="tests.synthetic", kind="machine", summary="Invented.", params=_Nothing,
        run=_approve, state="step", output=capabilities.OwnVersionResult))

    def broken(content, **kw):
        raise rated_offer.RatedOfferError("the premium has no total")

    monkeypatch.setattr(parts, "_VERSIONS", {**parts._VERSIONS, rated_offer.OUTPUT: parts.VersionDocument(
        rated_offer.OUTPUT, "tests.synthetic", broken, reads_case=True)})
    data = {"process:invented_letter": {**_pack("invented_letter"), "screens": {"tabs": [
        {"id": "overview", "label": "Overview", "elements": [{"type": "blockers"}]}]}}}
    real = cfg.load
    monkeypatch.setattr(cfg, "load", lambda name: data[name] if name in data else real(name))
    with store.use_store(tmp_path / "broken.sqlite"):
        case_id = process_runtime.start_case("invented_letter", {}, name="Minta Kft.", actor=ANNA)
        _turn(case_id)
        [blockers] = [e["data"] for tab in case_views.view(case_id)["tabs"] for e in tab["elements"]]
    assert blockers == {"status": "open", "items": [{"step": "document", "kind": "stopped", "note": "the premium has no total",
                                                     "waiting_for": None, "tab": None}]}


def test_without_the_addressee_s_name_it_greets_without_one(case) -> None:
    case_id, named, _out = case
    named["on"] = False
    assert letters.view(case_id, "letter")["draft"]["body"].startswith("Tisztelt Hölgyem/Uram!\n\n")


@pytest.mark.parametrize(("over", "why"), [
    ({"body": "Tisztelt {{contact_name}}!"}, "the letter still holds a marker: {{contact_name}}"),
    ({"to": "anna.minta.hu"}, "anna.minta.hu is not an email address"),
    ({"subject": "  "}, "the subject is empty or longer than 200 characters"),
    ({"subject": "x" * 201}, "the subject is empty or longer than 200 characters"),
    ({"body": ""}, "the letter is empty or longer than 5000 characters"),
])
def test_a_letter_that_cannot_go_is_refused_with_the_reason(case, over, why) -> None:
    case_id, _named, _out = case
    with pytest.raises(letters.CoveringLetterError) as refused:
        _accept(case_id, **over)
    assert str(refused.value) == why
    assert package_release.own_approval(case_id, step="letter")["active"] is None


def test_a_page_showing_an_older_document_is_refused(case) -> None:
    case_id, _named, _out = case
    with pytest.raises(decisions.RevisionConflict):
        _accept(case_id, expected_basis={"document": 99})


def test_a_document_step_that_stored_no_file_gives_no_letter(tmp_path) -> None:
    document = StepDef(id="document", kind="cap.priced_document.v1")
    letter = StepDef(id="letter", kind="cap.letter.v1", after=("document",),
                     params={"frame": "offer_letter", "from_step": "document"})
    definition = ProcessDef(id="invented", version="1", title="Invented", steps=(document, letter))
    ctx = StepContext(case_id="wp-00000000d0f8", step=letter, definition=definition,
                      data={"container": "wp-00000000d0f8", "name": "Minta Kft."}, actor=identity.machine("test"))
    # as a quote's priced document: its domain stored the file at the approval, so its result names none
    object.__setattr__(ctx, "result_of", lambda step_id: (1, {"output": "quote", "version": 2, "values": 3, "file": None}))
    with store.use_store(tmp_path / "none.sqlite"):
        outcome = kinds.of("cap.letter.v1").run(ctx)
    assert outcome == kinds.Fail("the result of step 'document' does not fit: it has no 'file'")


def test_an_unknown_marker_of_the_frame_stays_as_it_is() -> None:
    frame = {"language": "hu", "subject": "{{nothing}} {{total}}", "greeting": "x", "greeting_none": "y", "paragraphs": [],
             "closing": "z"}
    drafted = letters.compose(frame, {"total": "487000"}, {"total": "money"}, letters.Letter(frame="offer_letter",
                                                                                            from_step="document"))
    assert drafted["subject"] == "{{nothing}} 487 000" and drafted["to"] is None  # so it cannot be accepted


def test_the_letter_is_signed_by_the_case_s_owner() -> None:
    """U1 (the walkthrough of 2026-10-28): the letter ended with its closing and no name; the draft signs it with the
    name of the person the case belongs to, which a person may change before accepting it."""
    frame = {"language": "hu", "subject": "s", "greeting": "x", "greeting_none": "y", "paragraphs": ["p"], "closing": "Regards,"}
    params = letters.Letter(frame="offer_letter", from_step="document")
    assert letters.compose(frame, {}, {}, params, signer="Minta Anna")["body"].endswith("Regards,\nMinta Anna\n")
    assert letters.compose(frame, {}, {}, params)["body"].endswith("Regards,\n")  # nobody named: no name
