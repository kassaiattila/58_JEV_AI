"""Sending (231, plan stage A, A7c; DECISIONS 231): the general `send` capability of every process pack.

Plain-language summary: a case sends what one of its steps made (the IT quote's accepted letter with its Word
document, say) by one of three ways a process pack chooses (the owner's decision of 2026-10-24): into the output folder
as a file a person opens and sends, as a draft in the person's Outlook (A8), or straight out through Outlook. The real
send goes only to the addresses an owner put on the allowlist (`configs/send.json`, empty: nothing goes out). Whatever
is sent is first recorded with the case and then handed over once, under the same id (the process core's handover
record); a handover whose outcome is unknown is never repeated by itself: a person says whether it arrived, from the
"Waiting for me" list. A handover that failed fails the step, which a person may start again.

- `Message`: what is sent: the file's bytes, its name, the recipient and the subject.
- `MessageBuilder`: how a capability's result becomes a message (`register_builder`); the quote registers its letter.
- `Sender`: how a mode hands a message over (`register_sender`); the output folder is built in, the Outlook modes come
  with their bridge (A8).
- `allowed(to)`: whether the real send may reach these recipients.
- `settle(case_id, step_id, outcome, actor)`: a person says whether an uncertain handover arrived.

Layer: application; it uses the process core's handovers and tasks, the settings' output folder and the file names'
safe parts. The message builders live in the domains and register from their `register()`.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from email.utils import getaddresses
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jav.app import app_settings, capabilities, naming, process_runtime, work
from jav.core import cfg, identity, store
from jav.core.process import cases, kinds, outbox, tasks
from jav.core.process.engine import StepContext
from jav.core.user_messages import explained

__all__ = ["CONFIG", "MODES", "Message", "MessageBuilder", "SETTLE_TASK", "Send", "SendError", "Sender", "allowed",
           "builder", "register", "register_builder", "register_sender", "settle"]

CONFIG = "send"
OUTPUT_FOLDER, OUTLOOK_DRAFT, OUTLOOK_SEND = "output_folder", "outlook_draft", "outlook_send"
MODES = (OUTPUT_FOLDER, OUTLOOK_DRAFT, OUTLOOK_SEND)
SETTLE_TASK = "handover_settle"  # a person says whether a handover whose outcome is unknown arrived
_OWNER = __name__


class SendError(ValueError):
    """A send that cannot be asked for: no such message builder, sender or uncertain handover."""


@dataclass(frozen=True)
class Message:
    data: bytes
    file_name: str
    to: str | None
    subject: str


@dataclass(frozen=True)
class MessageBuilder:
    """`build(case_id, source)`: the message from the case and the result of the step it builds on (None when the step
    names none)."""

    name: str
    module: str
    build: Callable[[str, Any], Message]
    summary: str


@dataclass(frozen=True)
class Sender:
    """`deliver(handover_id, payload)` hands the recorded message over once and returns its receipt; it raises
    `outbox.Refused` when the receiver did not take it, anything else when the outcome is unknown."""

    mode: str
    module: str
    deliver: Callable[[str, dict[str, Any]], dict[str, Any]]


_BUILDERS: dict[str, MessageBuilder] = {}
_SENDERS: dict[str, Sender] = {}


def _register(table: dict[str, Any], key: str, item: Any, what: str) -> None:
    prior = table.get(key)
    if prior is not None and prior.module != item.module:
        raise SendError(f"the {what} {key!r} is registered by {prior.module}, not by {item.module}")
    table[key] = item


def register_builder(b: MessageBuilder) -> None:
    """Adds a message builder; its owner may register it again, another module may not."""
    _register(_BUILDERS, b.name, b, "message builder")


def register_sender(s: Sender) -> None:
    """Adds a mode's sender; its owner may register it again, another module may not."""
    if s.mode not in MODES:
        raise SendError(f"unknown mode {s.mode!r}")
    _register(_SENDERS, s.mode, s, "sender")


def builder(name: str) -> MessageBuilder:
    try:
        return _BUILDERS[name]
    except KeyError:
        raise SendError(f"no message builder {name!r} is registered") from None


# --- the allowlist of the real send ---------------------------------------------------------------------------------


def allowed(to: str | None) -> bool:
    """Whether every recipient is on the real send's allowlist (an address, or `@domain` for a whole domain); no
    recipient is never allowed."""
    allow = {str(a).strip().lower() for a in cfg.load(CONFIG)["outlook_send"]["allow"]}
    addresses = [a.strip().lower() for _, a in getaddresses([to or ""]) if a.strip()]
    return bool(addresses) and all(a in allow or "@" + a.rpartition("@")[2] in allow for a in addresses)


# --- the output folder ----------------------------------------------------------------------------------------------


def _place(folder: Path, name: str, data: bytes) -> Path:
    """The file written into `folder` under `name`, or `name__2`... when another file has it; a file with the same
    bytes under the name is the one sent already (nothing is ever overwritten)."""
    stem, suffix = Path(name).stem, Path(name).suffix
    target, n = folder / name, 2
    while True:
        try:
            with open(target, "xb") as fh:
                fh.write(data)
            return target
        except FileExistsError:
            if target.read_bytes() == data:
                return target
            target, n = folder / f"{stem}__{n}{suffix}", n + 1


def _to_output_folder(_handover_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The message as a file in the output folder (Settings), under `<process>/<case>/`."""
    root = app_settings.output_folder()
    if not root:
        raise outbox.Refused("no output folder is set (Settings > Work folders)")
    try:
        base = app_settings.check_output_folder(Path(root))
    except ValueError as exc:
        raise outbox.Refused(str(exc)) from exc
    folder = base.joinpath(*payload["folder"])
    folder.mkdir(parents=True, exist_ok=True)
    return {"path": str(_place(folder, payload["file_name"], base64.b64decode(payload["data"])))}


# --- the capability -------------------------------------------------------------------------------------------------


class Send(BaseModel):
    """What a process pack sets for its send step: the message builder, the mode, and the step whose result the message
    is made from."""

    model_config = ConfigDict(extra="forbid")
    message: str
    mode: Literal["output_folder", "outlook_draft", "outlook_send"] = Field(OUTPUT_FOLDER, title="Send mode")
    from_step: str | None = capabilities.step_ref(None)

    @field_validator("message")
    @classmethod
    def _registered(cls, name: str) -> str:
        """A process pack naming a message builder nobody registered is refused when it is checked."""
        if name not in _BUILDERS:
            raise ValueError(f"no message builder {name!r} is registered")
        return name


def _folder(case_id: str) -> list[str]:
    """The case's folder parts under the output folder: its process pack and its name with its id."""
    pinned = process_runtime.pack_of(case_id)
    try:
        name = work.get(case_id)["name"]
    except KeyError:
        name = None
    return [pinned[0] if pinned else "cases", f"{naming.safe_part(name, limit=60) or 'case'}_{case_id}"]


def _handovers_of(case_id: str, step_id: str) -> list[dict[str, Any]]:
    """The step's handovers, oldest first (one per attempt)."""
    with store.connect() as c:
        return [h for h in outbox.of_case(c, case_id) if h["step_id"] == step_id]


def _record(ctx: StepContext, params: Send, attempt: int) -> str | kinds.Fail:
    """The message made and recorded with the case as this attempt's handover; a Fail when it cannot be."""
    try:
        made = builder(params.message)
    except SendError as exc:
        return kinds.Fail(str(exc))
    source = ctx.result_of(params.from_step)[1] if params.from_step else None
    message = made.build(ctx.case_id, source)
    if params.mode == OUTLOOK_SEND and not allowed(message.to):
        return kinds.Fail(f"the real send is switched off for {message.to or 'a message without a recipient'}: "
                          f"not on the allowlist ({CONFIG}.json)")
    payload = {"message": params.message, "mode": params.mode, "file_name": message.file_name, "to": message.to,
               "subject": message.subject, "size": len(message.data),
               "sha256": hashlib.sha256(message.data).hexdigest(), "folder": _folder(ctx.case_id),
               "data": base64.b64encode(message.data).decode("ascii")}
    return ctx.record_handover(params.mode, payload, handover_id=f"{ctx.case_id}:{ctx.step.id}:{attempt}")


def _settlement(ctx: StepContext, handover: dict[str, Any]) -> kinds.StepOutcome | None:
    """An uncertain handover: a person's task, which the step waits for; once decided, the handover is settled as the
    person said and None is returned (the step goes on with the settled handover)."""
    hid = handover["handover_id"]
    with ctx.transaction() as c:
        task = tasks.task_in(c, tasks.task_id(SETTLE_TASK, hid))
        if task is None or task.status not in (tasks.OPEN, tasks.DECIDED):
            tasks.open_in(c, SETTLE_TASK, hid, ctx.actor, case_id=ctx.case_id, step_id=ctx.step.id,
                          detail={"handover_id": hid, "mode": handover["target"], "error": handover.get("error")})
            return kinds.WAIT
        if task.status == tasks.OPEN:
            return kinds.WAIT
    outcome = (task.outcome or {}).get("outcome")
    outbox.settle(hid, outcome if outcome in (outbox.ACKNOWLEDGED, outbox.FAILED) else outbox.FAILED,
                  task.closed_by or ctx.actor, note=task.note or "settled by a person")
    return None


def _run(ctx: StepContext, params: Send) -> kinds.StepOutcome:
    """Sends the step's message once; after a failed handover a person's retry sends it again as a new attempt."""
    if params.mode not in _SENDERS:
        return kinds.Fail(f"the {params.mode} mode is not available in this version")
    mine = _handovers_of(ctx.case_id, ctx.step.id)
    if not mine or mine[-1]["status"] == outbox.FAILED:  # the first send, or again after a person's retry
        recorded = _record(ctx, params, len(mine) + 1)
        if isinstance(recorded, kinds.Fail):
            return recorded
        mine = _handovers_of(ctx.case_id, ctx.step.id)
    last = mine[-1]
    if last["status"] in (outbox.RECORDED, outbox.SENT):
        ctx.send(last["handover_id"], _SENDERS[params.mode].deliver)
        last = _handovers_of(ctx.case_id, ctx.step.id)[-1]
    if last["status"] == outbox.UNCERTAIN:
        waiting = _settlement(ctx, last)
        if waiting is not None:
            return waiting
        last = _handovers_of(ctx.case_id, ctx.step.id)[-1]
    if last["status"] == outbox.FAILED:
        return kinds.Fail(last.get("error") or "the handover failed")
    row = outbox.get(last["handover_id"]) or {}
    payload = row.get("payload") or {}
    return kinds.Done({"handover_id": last["handover_id"], "attempt": len(mine), "mode": params.mode,
                       "file_name": payload.get("file_name"), "to": payload.get("to"), "subject": payload.get("subject"),
                       "receipt": json.loads(row["receipt"]) if row.get("receipt") else None})


def settle(case_id: str, step_id: str, outcome: str, actor: identity.Who) -> None:
    """A person says whether the step's uncertain handover arrived (`acknowledged`) or not (`failed`); the step goes on
    at the case's next turn."""
    if outcome not in (outbox.ACKNOWLEDGED, outbox.FAILED):
        raise SendError(f"a handover is settled as acknowledged or failed, not {outcome!r}")
    open_ = [t for t in _open_settlements(case_id) if t.step_id == step_id]
    if not open_:
        raise explained(SendError, "the step {{step}} has no handover to settle", step=step_id)
    tasks.decide(open_[0].task_id, identity.who(actor), outcome={"outcome": outcome})


def _open_settlements(case_id: str) -> list[tasks.Task]:
    with store.connect() as c:
        return [t for t in tasks.of_kind_in(c, SETTLE_TASK, status=tasks.OPEN) if t.case_id == case_id]


def _settling(case_id: str, step_id: str) -> bool:
    return any(t.step_id == step_id for t in _open_settlements(case_id))


CAPABILITY = capabilities.Capability(
    name="send", version=1, module=_OWNER, run=_run, kind="machine", params=Send, effects="external", state="step",
    rule_files=(CONFIG,), described={"modes": list(MODES)},
    summary="Sends a step's message once: into the output folder, as an Outlook draft or out through Outlook.",
    # 231 (B4): a process may choose between the two ways a person still sends from; the real send stays a change of
    # its pack's file, by the owner's decision (DECISIONS 231)
    choices={"mode": lambda: [(OUTPUT_FOLDER, "Into the output folder"), (OUTLOOK_DRAFT, "As a draft in the person's Outlook")]},
    actions=(capabilities.Action("delivered", "It arrived", _settling,
                                 lambda case_id, step_id, actor, _note: settle(case_id, step_id, outbox.ACKNOWLEDGED, actor)),
             capabilities.Action("not_delivered", "It did not arrive", _settling,
                                 lambda case_id, step_id, actor, _note: settle(case_id, step_id, outbox.FAILED, actor))))


def _handover_view(case_id: str, step_id: str | None, shared: dict[str, Any]) -> dict[str, Any]:
    """231 (A7e): what a send step shows on its case's page: its mode and message, where the output folder is, each
    attempt's handover (without the file's bytes) and, while the step waits for a person, the case's next step."""
    step = str(step_id)
    with store.connect() as c:
        row = cases.find_step_in(c, case_id, step) or {}
        params = cases.definition_of(cases.case_row(c, case_id)).step(step).params
    attempts = []
    for n, h in enumerate(_handovers_of(case_id, step), 1):
        full = outbox.get(h["handover_id"]) or {}
        payload = full.get("payload") or {}
        attempts.append({"attempt": n, "status": h["status"], "error": h["error"], "created_at": full.get("created_at"),
                         "updated_at": full.get("updated_at"),
                         "receipt": json.loads(full["receipt"]) if full.get("receipt") else None,
                         **{k: payload.get(k) for k in ("mode", "file_name", "to", "subject", "size")}})
    mode = params.get("mode", OUTPUT_FOLDER)
    nxt = None
    if row.get("phase") == capabilities.AWAITING_START:
        nxt = {"code": "case_send", "label": "Send", "stage": "result"}
    elif _settling(case_id, step):
        nxt = {"code": "case_send_settle", "label": "Say whether it arrived", "stage": "result"}
    elif row.get("state") == cases.FAILED:
        nxt = {"code": "case_send_failed", "label": "The send failed", "stage": "result"}
    return {"mode": mode, "message": params.get("message"), "state": row.get("state"),
            "output_folder": app_settings.output_folder() if mode == OUTPUT_FOLDER else None, "attempts": attempts,
            "next": {**nxt, "element": "handover_view"} if nxt else None}


def register() -> None:
    from jav.app import case_views

    capabilities.register(CAPABILITY)
    register_sender(Sender(OUTPUT_FOLDER, _OWNER, _to_output_folder))
    case_views.register(case_views.ElementData("handover_view", "send", _OWNER, _handover_view))


tasks.register_kind(tasks.TaskKind(SETTLE_TASK, __name__))
