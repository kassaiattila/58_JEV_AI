"""A letter that goes with a printed document, a general capability (231, stage D, D-f8).

Plain-language summary: once a case's step printed a document and stored it (the insurance offer's Word document,
`priced_document@1`), this step writes the covering letter from a frame (`configs/letter_frames.json`): the greeting
with the addressee's name, the frame's paragraphs and the closing, each marker written by code with a value of the
printed document's output, as the document writes it. No model writes any of it. A person reads it, may change the
address, the subject and the text, and accepts it; the letter is then the step's own approved version, kept as an email
file (Outlook opens it as a message to send) with the document attached, and the send step (`send@1`, the message
`letter`) hands that very file over. A page showing an older document is refused; a new document (a reopened premium,
say) makes the accepted letter out of date, and a person accepts it again. The quote's reply letter stays the quote's
(it asks a model for a paragraph); this one is any process's.

- `CAPABILITY` (`letter@1`): params `frame`, `from_step` (a priced document's step that stored its file), `to` and
  `name` (the document's values holding the address and the addressee's name); result: the letter's version, its
  address and subject, the document it attaches and its email file.
- `view(case_id, step)`: the document, the draft, the accepted letter and the approval; `accept(...)`; the action
  `accept`; the message builder `letter`; the element `letter`.

Layer: application; it names no process and no business (the frame and the document's values are data).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from email.message import EmailMessage
from email.policy import SMTP
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jav.app import capabilities, human_tasks, letter_frames, naming, package_release, work
from jav.app.approved_document import StoredFile
from jav.app.outputs import contract, docx, markers, parts
from jav.core import activity_kinds, cfg, decisions, identity, store
from jav.core.process import cases, kinds
from jav.core.user_messages import explained

CONFIG = "letter_frames"
MESSAGE = "letter"  # the message builder the send step names
POLL_S = 5.0
ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_OWNER = __name__

activity_kinds.register_events("package", ("letter_approve", "letter_reopen"), __name__)


class CoveringLetterError(ValueError):
    """A letter that cannot be accepted: no printed document yet, an empty or too long text, a marker left in it, or an
    address that is none."""


def _settings(case_id: str | None = None) -> dict[str, Any]:
    """The letter frames, as the case started with them (its rule file kept at its start)."""
    with capabilities.case_rules(case_id):
        return cfg.load(CONFIG)


def _frame_choices() -> list[tuple[str, str]]:
    return [(key, key) for key in (cfg.load(CONFIG).get("frames") or {})]


class _Printed(capabilities.Result):
    """What the letter expects of the step it goes with: the version it printed, its output and the file it stored
    (the priced document's form may leave it empty, as the quote's does: such a result does not fit, and the letter
    stops before it writes anything)."""

    version: int
    output: str
    file: StoredFile | None = None


class Letter(BaseModel):
    """The frame, the printed document's step, and which of the document's values hold the address and the name."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    frame: str = Field(min_length=1, title="Letter frame")
    from_step: str = capabilities.step_ref(min_length=1, of="priced_document", expects=_Printed)
    to: str = Field("contact_email", min_length=1, title="The value holding the address")
    name: str | None = Field("contact_name", title="The value holding the addressee's name")

    @field_validator("frame")
    @classmethod
    def _known_frame(cls, value: str) -> str:
        if value not in (cfg.load(CONFIG).get("frames") or {}):
            raise ValueError(f"no letter frame {value!r}")
        return value


class LetterResult(capabilities.Result):
    """The accepted letter: its version, its address and subject, the document it attaches, its email file."""

    version: int
    to: str | None = None
    subject: str
    document: dict[str, Any]
    file: StoredFile


def _params(c: Any, case_id: str, step: str) -> Letter:
    case = cases.find_case_in(c, case_id)
    if case is None:
        raise KeyError(case_id)
    return Letter.model_validate({k: v for k, v in cases.definition_of(case).step(step).params.items() if not k.startswith("_")})


def _package(c: Any, case_id: str) -> str:
    case = cases.find_case_in(c, case_id) or {}
    return str((case.get("data") or {}).get("name") or case_id)


def _document(c: Any, case_id: str, params: Letter) -> dict[str, Any] | None:
    """The document the step goes with, once its step printed and stored it: its step, version, output, name, sha256."""
    row = cases.find_step_in(c, case_id, params.from_step) or {}
    result = row.get("result") if row.get("state") == cases.DONE else None
    if not result or not result.get("file"):
        return None
    return {"step": params.from_step, "version": int(result["version"]), "output": result["output"],
            "name": result["file"]["name"], "sha256": result["file"]["sha256"]}


def _values(case_id: str, document: dict[str, Any], package: str) -> tuple[dict[str, Any], dict[str, str]]:
    """The printed document's values, as its output's builder makes them from the version it printed, with their kinds."""
    approved = package_release.own_version(case_id, document["version"])
    d = parts.version_document(document["output"]).build(
        approved["content"], case_id=case_id, package=package, version=document["version"],
        approved_by=approved.get("approved_by"), approved_at=approved.get("approved_at"), output=document["output"])
    return {v.key: v.value for v in d.values}, dict(contract.spec(document["output"])["values"])


def compose(frame: dict[str, Any], values: dict[str, Any], kinds_of: dict[str, str], params: Letter, *,
            signer: str | None = None) -> dict[str, Any]:
    """The letter's draft from its frame: the address, the subject and the body (greeting, paragraphs, closing), each
    marker written with the document's value as the document writes it; an unknown marker stays as it is. U1: signed
    by `signer` (the person the case belongs to) under the closing, when named."""
    language = frame.get("language") or "hu"

    def fill(text: str) -> str:
        def value(m: re.Match) -> str:
            key = m.group(1).strip()
            return docx.shown(values.get(key), kinds_of.get(key, "text"), language) if key in kinds_of else m.group(0)
        return markers.ANY.sub(value, text)

    named = params.name is not None and values.get(params.name) not in (None, "")
    greeting = fill(frame["greeting"]) if named else frame["greeting_none"]
    closing = frame["closing"] + (f"\n{signer.strip()}" if signer and signer.strip() else "")
    body = "\n\n".join([greeting, *(fill(p) for p in frame["paragraphs"]), closing]) + "\n"
    address = values.get(params.to)
    return {"to": str(address) if address not in (None, "") else None, "subject": fill(frame["subject"]), "body": body}


def view(case_id: str, step: str) -> dict[str, Any]:
    """What a person reads before accepting: the printed document, the draft from the frame (None until printed; with the
    reason when it cannot be made), the result versions to send back, the approval and the accepted letter."""
    from jav.app import process_runtime

    with store.connect() as c:
        params = _params(c, case_id, step)
        document = _document(c, case_id, params)
        basis = process_runtime.basis_of(case_id, step, c)
        package = _package(c, case_id)
    settings = _settings(case_id)
    draft = problem = None
    if document is not None:
        try:
            values, kinds_of = _values(case_id, document, package)
            draft = compose(settings["frames"][params.frame], values, kinds_of, params, signer=work.person_owner(work.get(case_id)))
        except (KeyError, ValueError) as exc:  # the document's version or its builder: the reason shows
            problem = str(exc)
    approval = package_release.approval_state(case_id, step=step)
    accepted = None
    if approval["active"] is not None:
        n = approval["active"]["version"]
        content = package_release.own_version(case_id, n, step=step)["content"]
        stored = package_release.own_file(case_id, n, package_release.APPROVED)
        accepted = {"version": n, "to": content["to"], "subject": content["subject"], "body": content["body"],
                    "document": content["document"], "by": approval["active"]["approved_by"],
                    "at": approval["active"]["approved_at"],
                    "file": {"name": stored["name"], "sha256": stored["sha256"]} if stored else None}
    return {"frame": params.frame, "document": document, "draft": draft, "problem": problem, "basis": basis,
            "approval": approval, "accepted": accepted, "limits": settings["limits"]}


def _eml(content: dict[str, Any], document: dict[str, Any]) -> bytes:
    """The letter as an email file Outlook opens as an unsent message, with the document attached."""
    msg = EmailMessage(policy=SMTP)
    if content["to"]:
        msg["To"] = content["to"]
    msg["Subject"] = content["subject"]
    msg["X-Unsent"] = "1"  # Outlook opens the file as a message to send, not as a received one
    msg.set_content(content["body"])
    maintype, subtype = package_release.media(document["name"]).split("/", 1)
    msg.add_attachment(document["content"], maintype=maintype, subtype=subtype, filename=document["name"])
    return msg.as_bytes()


def accept(case_id: str, step: str, *, to: str | None, subject: str, body: str, expected_basis: dict[str, int] | None,
           actor: identity.Who) -> dict[str, Any]:
    """A person's letter as the step's next own version, kept as an email file with the document attached. Refused: a
    page showing an older document (`RevisionConflict`), no printed document, an empty or too long subject or text, a
    marker left in it, an address that is none (`CoveringLetterError`)."""
    from jav.app import process_runtime

    to, subject, body = (to or "").strip() or None, (subject or "").strip(), (body or "").strip()
    settings = _settings(case_id)
    limits = settings["limits"]
    if not subject or len(subject) > limits["subject_chars"]:
        raise explained(CoveringLetterError, "the subject is empty or longer than {{n}} characters", n=limits["subject_chars"])
    if not body or len(body) > limits["body_chars"]:
        raise explained(CoveringLetterError, "the letter is empty or longer than {{n}} characters", n=limits["body_chars"])
    if (left := markers.ANY.search(subject + "\n" + body)) is not None:
        raise explained(CoveringLetterError, "the letter still holds a marker: {{marker}}", marker=left.group(0))
    if to is not None and not ADDRESS.match(to):
        raise explained(CoveringLetterError, "{{to}} is not an email address", to=to)
    with store.connect() as c:
        store.begin_immediate(c)
        params = _params(c, case_id, step)
        basis = process_runtime.basis_of(case_id, step, c)
        if expected_basis is not None and basis != expected_basis:
            raise explained(decisions.RevisionConflict, "the document the letter goes with changed meanwhile; reload it")
        document = _document(c, case_id, params)
        if document is None:
            raise explained(CoveringLetterError, "the document is not printed yet")
        stored = package_release.own_file(case_id, document["version"], package_release.APPROVED, c)
        if stored is None or stored["sha256"] != document["sha256"]:
            raise explained(CoveringLetterError, "the document's stored file is not the one printed")
        content = {"frame": params.frame, "to": to, "subject": subject, "body": body + "\n", "document": document}
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        email = _eml(content, stored)
        slug = naming.safe_part(_package(c, case_id), limit=40) or "letter"
        prefix = settings["frames"][params.frame]["file"]
        made = {"template": "builtin", "template_version": str(settings["meta"]["version"])}
        n = package_release.approve_own(
            c, case_id, event="letter", content=content, fingerprint=fingerprint, locks=[], actor=actor,
            files=lambda conn, v: package_release.store_own_files(  # U1: named by the letter's own number
                conn, case_id, v, package_release.APPROVED,
                [(f"{prefix}-{slug}-v{package_release.step_number(case_id, v, step, conn)}.eml", 1, email, made)]),
            details={"step": step, "document_version": document["version"]}, step=step, basis=basis)
    return {"version": n, "fingerprint": fingerprint}


class AcceptForm(BaseModel):
    """A person's letter as the page sends it: the address, the subject, the text, and the result versions it showed."""

    model_config = ConfigDict(extra="forbid")
    to: str | None = None
    subject: str
    body: str
    expected_basis: dict[str, int]


def _waits(case_id: str, step: str) -> bool:
    """The letter waits: its document is printed, and no letter of it holds."""
    with store.connect() as c:
        row = cases.find_step_in(c, case_id, step)
        if not row or row["state"] != cases.RUNNING:
            return False
        if _document(c, case_id, _params(c, case_id, step)) is None:
            return False
    return package_release.own_approval(case_id, step=step)["active"] is None


ACTIONS = (capabilities.form_action("accept", "Accept the letter", _waits, AcceptForm,
                                    lambda case_id, step, actor, v: accept(case_id, step, to=v.to, subject=v.subject,
                                                                           body=v.body, expected_basis=v.expected_basis,
                                                                           actor=actor)),)


def _run(ctx: Any, params: Letter) -> kinds.StepOutcome:
    from jav.app import process_runtime

    case_id = str(ctx.data["container"])
    if (why := process_runtime.outdated(case_id, ctx.step.id)) is not None:
        with store.connect() as c:  # the document it goes with changed: accepted again
            store.begin_immediate(c)
            package_release.reopen_logged(c, case_id, event="letter", note=why, actor=ctx.actor, step=ctx.step.id)
    approval = package_release.own_approval(case_id, step=ctx.step.id)
    if approval["active"] is None:
        if not approval["versions"]:  # its first round; a reopened version opened its task again
            # the printed document, checked against its form: one that stored no file (the quote's) stops the step
            capabilities.read_result(ctx, params, "from_step")
            with ctx.transaction() as c:
                human_tasks.own_approval_waits(c, case_id, ctx.step.id)
        return ctx.wait("letter", timer=("check", time.time() + POLL_S))
    n = approval["active"]["version"]
    content = package_release.own_version(case_id, n, step=ctx.step.id)["content"]
    stored = package_release.own_file(case_id, n, package_release.APPROVED)
    if stored is None:
        return kinds.Fail(f"letter version {n} has no stored email file")
    return kinds.Done({"version": n, "to": content["to"], "subject": content["subject"], "document": content["document"],
                       "file": {"name": stored["name"], "sha256": stored["sha256"]}})


CAPABILITY = capabilities.Capability(
    name="letter", version=1, module=_OWNER, run=_run, kind="human", params=Letter, state="step", output=LetterResult,
    own_version=True, reads=lambda p: (CONFIG,), actions=ACTIONS, approval_what="Accept the letter",
    choices={"frame": _frame_choices}, refers={"frame": "letter_frame"},  # U3d
    summary="A letter that goes with a printed document: its frame written by code with the document's values, read,"
            " changed and accepted by a person, kept as an email file with the document attached.")


def _message(case_id: str, source_step: str | None, source: Any) -> Any:
    """The send step's message: the accepted letter's stored email file, as it was accepted."""
    from jav.app import sending

    n = int((source or {})["version"])
    stored = package_release.own_file(case_id, n, package_release.APPROVED)
    if stored is None:
        raise sending.SendError(f"letter version {n} has no stored email file")
    content = package_release.own_version(case_id, n, step=source_step)["content"]
    return sending.Message(stored["content"], stored["name"], content["to"], content["subject"])


def _letter_view(case_id: str, step: str | None, _shared: dict[str, Any]) -> dict[str, Any]:
    """The letter element's data: the view, whether it waits for a person, and the page's next step while it does."""
    step_id = str(step)
    waits = _waits(case_id, step_id)
    return {**view(case_id, step_id), "waits": waits,
            "next": {"code": "letter_accept", "label": "Accept the letter", "stage": "review", "element": "letter"}
            if waits else None}


# 231 (U3f; the owner's decision of 2026-10-28): the covering letters' frames, edited as versions in the shared library
FRAME_KIND = letter_frames.FrameKind(
    kind="letter_frame", title="Covering letters",
    what="The letter that goes with a printed document, such as an insurance offer: its subject, greeting, paragraphs"
         " and closing, the markers filled in from the document.",
    config=CONFIG, prefix="frames.", frames=letter_frames.config_frames(CONFIG, "frames."), outputs=parts.version_outputs,
    fields=(letter_frames.FrameField("subject", "Subject"),
            letter_frames.FrameField("greeting", "Greeting with the addressee's name"),
            letter_frames.FrameField("greeting_none", "Greeting without a name"),
            letter_frames.FrameField("paragraphs", "Paragraphs", letter_frames.PARAGRAPHS),
            letter_frames.FrameField("closing", "Closing")),
    module=_OWNER)


def register() -> None:
    from jav.app import case_views, sending

    capabilities.register(CAPABILITY)
    letter_frames.register_kind(FRAME_KIND)
    case_views.register(case_views.ElementData("letter", "letter", _OWNER, _letter_view))
    sending.register_builder(sending.MessageBuilder(MESSAGE, _OWNER, _message,
                                                    "An accepted letter's email file, with the document it goes with."))


__all__ = ["AcceptForm", "CAPABILITY", "Letter", "CoveringLetterError", "LetterResult", "accept", "compose", "register", "view"]
