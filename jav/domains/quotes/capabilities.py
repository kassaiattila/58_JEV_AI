"""The general capabilities of the quote's back half (231, plan stage A, A3c; DECISIONS 231).

Plain-language summary: the owner's rule is that every process is built only from general capabilities. The quote's
back half is such building blocks, described here with what a process sets for each: putting a record together
from an email and its attachments, matching requested items with a catalogue (a price list), pricing lines from a
catalogue, a person's line-by-line draft with its approval, and a letter draft around a model's paragraph (the priced
document from an output template moved to the shared layer in stage D0, D0-c: `jav/app/approved_document.py`; the
quote registers how its approved version becomes its Word document's data). Four of them run as a process pack's steps since 231 A5 (`run`, on a case's
container: the general work package that holds the case's rows); the line pricing is described only, and a pack cannot
use it (D0-a). Their parameters' defaults are not the quote's: a process names them. Each step is repeatable: when its
work is already there it goes on at once, and while a job or a person works it waits with a retry timer (`POLL_S`).
Stage D0 (D0-b): each keeps its state per step (`state="step"`): a match step's proposal, a composition step's draft and
approval, a letter step's letter and their budgets; a composition names the match it starts from and a letter the
composition it answers (`from_step`; without one, the case's only such step: `jav/domains/quotes/quote_steps.py`).

Layer: domain (quotes); it registers into the application's capability registry.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jav.app import human_tasks
from jav.app.capabilities import Capability, OwnVersionResult, Result, RuleKey, step_ref
from jav.core.process import kinds

POLL_S = 5.0  # how soon a waiting step looks again at the job or the person it waits for


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecordResult(Result):
    """D0-c: the record put together: its kind, how many listed items it has, its own fields and what it lacks."""

    kind: str
    items: int
    fields: dict[str, Any]
    gaps: list[str]


class MatchResult(Result):
    """D0-c: the proposal: how many items it matched and how many of each mark."""

    lines: int
    marks: dict[str, int]


class LetterResult(Result):
    """D0-c: the accepted letter: the approved version it answers, the code's check of the model's paragraph."""

    version: int
    problems: list[str]
    paragraph_used: bool
    accepted: bool


class RecordAssembly(_Params):
    """The record type an email's text, its table attachments and its attachments were read as, and its list field."""

    record_type: str = Field(min_length=1)
    items_field: str = Field(min_length=1)


def _catalogue(value: str) -> str:
    """231 (B2): `newest_active`, or a price list that has an active version (a process's own value is checked so)."""
    from jav.domains.quotes import price_lists

    if value != price_lists.NEWEST_ACTIVE and price_lists.active(value) is None:
        raise ValueError(f"no active price list {value!r}")
    return value


def _catalogues() -> list[tuple[str, str]]:
    """231 (B4): the price lists a process may choose: the newest active one, or one by name that has an active version."""
    from jav.domains.quotes import price_lists

    return [(price_lists.NEWEST_ACTIVE, "The newest active price list"),
            *((p["price_list"], p["name"]) for p in price_lists.listing() if p.get("active") and not p.get("retired"))]


PRICE_LIST = "Price list"  # 231 (B4): the parameters' titles name a process's resources on its settings page


class CatalogueMatch(_Params):
    """Which catalogue the items are matched with (`newest_active` or a named price list), and the call site that asks."""

    catalogue: str = Field(min_length=1, title=PRICE_LIST)
    callsite: str = Field(min_length=1)
    _catalogue = field_validator("catalogue")(lambda cls, v: _catalogue(v))


class LinePricing(_Params):
    catalogue: str = Field(min_length=1, title=PRICE_LIST)
    _catalogue = field_validator("catalogue")(lambda cls, v: _catalogue(v))


class LineDraft(_Params):
    """A person composes the lines from the match; the approval is the record's own version. D0-b: `from_step`, the
    match step it starts from (None: the case's only one)."""

    catalogue: str = Field(min_length=1, title=PRICE_LIST)
    approval: Literal["own_version"] = "own_version"
    from_step: str | None = step_ref(None)
    _catalogue = field_validator("catalogue")(lambda cls, v: _catalogue(v))


class LetterDraft(_Params):
    """The letter frame's key and the call site that asks for the paragraph. D0-b: `from_step`, the composition step
    whose approved version it answers (None: the case's only one). D0-c: `output`, the output whose builder fills the
    frame's values and whose stored document the letter attaches (the quote's by default); the approved version is
    read as an offer (`quote_letter.OfferContent`)."""

    frame: str = Field(min_length=1, title="Letter frame")
    callsite: str = Field(min_length=1)
    from_step: str | None = step_ref(None)
    output: str = Field("quote", min_length=1, title="Output")

    @field_validator("output")
    @classmethod
    def _known_output(cls, value: str) -> str:
        from jav.core import cfg

        if value not in (cfg.load("outputs").get("outputs") or {}):
            raise ValueError(f"no output {value!r}")
        return value

    @field_validator("frame")
    @classmethod
    def _known_frame(cls, value: str) -> str:
        from jav.domains.quotes import quote_letter

        if value not in quote_letter.frames():
            raise ValueError(f"no letter frame {value!r}")
        return value


def _frames() -> list[tuple[str, str]]:
    from jav.domains.quotes import quote_letter

    return [(key, key) for key in quote_letter.frames()]


def _container(ctx: Any) -> str:
    return str(ctx.data["container"])


def _again(ctx: Any, what: str) -> kinds.StepOutcome:
    return ctx.wait(what, timer=("check", time.time() + POLL_S))


def _record_assembly(ctx: Any, params: RecordAssembly) -> kinds.StepOutcome:
    from jav.domains.quotes import quote_package, quote_request

    record = ctx.data["scope"]["record"]
    try:
        req = quote_request.read(record["workpackage_id"], record["item_id"], record_type=params.record_type,
                                 items_field=params.items_field)
    except quote_request.RequestNotFound as exc:
        return kinds.Fail(f"the record can no longer be read: {exc}")
    # 231 (B1): the record's own fields (its header, not its list), which a pack's partner link reads
    fields = {k: v for k, v in req.fields.items() if isinstance(v, (str, int, float)) and not isinstance(v, bool)}
    return kinds.Done({"kind": req.kind, "items": len(req.items), "fields": fields,
                       "gaps": [g["code"] for g in quote_package.request_gaps(req)]})


def _record_preview(record: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | None:
    """231 (C1a): the record an email or a document holds, as the record step reads it at a case's start (None: it
    holds none), with what it lacks as a whole."""
    from jav.domains.quotes import quote_package, quote_request

    try:
        req = quote_request.read(record["workpackage_id"], record["item_id"], record_type=params["record_type"],
                                 items_field=params["items_field"])
    except quote_request.RequestNotFound:
        return None
    return {"record": req.as_dict(), "gaps": quote_package.request_gaps(req), "list_field": params["items_field"],
            "record_type": params["record_type"]}


def _records(q: str | None, _params: dict[str, Any]) -> list[dict[str, Any]]:
    """231 (C3c): the quote requests a case may start from (`quote_package.candidates`), as the general form's record
    chooser shows them: the request's subject, its customer, package and day, the name it gives a case (its customer,
    else its subject) and the cases already started from it."""
    from jav.domains.quotes import quote_package

    return [{"workpackage_id": r["workpackage_id"], "workpackage_name": r["workpackage_name"], "item_id": r["item_id"],
             "label": r["title"] or None, "name": r["customer_name"] or r["title"] or None,
             "detail": " · ".join(str(x) for x in (r["customer_name"], r["workpackage_name"], (r["received_at"] or "")[:10]) if x),
             "cases": [{"id": c["id"], "name": c["name"]} for c in r["quotes"]]}
            for r in quote_package.candidates(q)]


def _catalogue_match(ctx: Any, params: CatalogueMatch) -> kinds.StepOutcome:
    from jav.domains.quotes import quote_proposal

    wp = _container(ctx)
    current = quote_proposal.current(wp, step=ctx.step.id)  # D0-b: the step's own proposal
    if current is None:
        try:
            quote_proposal.request(wp, actor=ctx.actor, selection=params.catalogue, step=ctx.step.id)
        except quote_proposal.ProposalRefused as exc:
            return kinds.Fail(str(exc))
        return _again(ctx, "proposal")
    if current["state"] in ("queued", "running"):
        return _again(ctx, "proposal")
    if current["state"] != "done":
        return kinds.Fail(current.get("error") or f"the proposal ended {current['state']}")
    marks = Counter(str(line["answer"].get("mark")) for line in current["lines"])
    return kinds.Done({"lines": len(current["lines"]), "marks": dict(sorted(marks.items()))})


def _line_draft(ctx: Any, params: LineDraft) -> kinds.StepOutcome:
    from jav.app import process_runtime
    from jav.domains.quotes import quote_draft

    wp = _container(ctx)
    if (why := process_runtime.outdated(wp, ctx.step.id)) is not None:
        # D0-d: an earlier step it builds on changed since the approval: the approval is reopened with that reason,
        # and a person approves the quote again (nothing else runs by itself)
        quote_draft.reopen(wp, note=why, actor=ctx.actor, step=ctx.step.id)
    view = quote_draft.view(wp, step=ctx.step.id)  # D0-b: the step's own draft
    if view["draft"] is None:
        quote_draft.start(wp, source="proposal", actor=ctx.actor, expected_state=None, catalogue=params.catalogue,
                          step=ctx.step.id)
        with ctx.transaction() as c:
            human_tasks.own_approval_waits(c, wp, ctx.step.id)  # a person approves it, from the waiting list (D0-b: the step's)
        return _again(ctx, "approval")
    active = view["approval"]["active"]
    if active is None:
        return _again(ctx, "approval")
    return kinds.Done({"version": active["version"]})


def _letter_draft(ctx: Any, params: LetterDraft) -> kinds.StepOutcome:
    from jav.domains.quotes import quote_letter

    wp = _container(ctx)
    view = quote_letter.view(wp, step=ctx.step.id)  # D0-b: the step's own letter
    if view["state"] is None:
        try:
            quote_letter.request(wp, actor=ctx.actor, frame=params.frame, step=ctx.step.id,  # 231 (B0): the pack's frame
                                 output=params.output)  # D0-c: its output's builder and document
        except quote_letter.LetterError as exc:
            return kinds.Fail(str(exc))
        return _again(ctx, "letter")
    if view["state"] in ("queued", "running"):
        return _again(ctx, "letter")
    if view["state"] != "done":
        return kinds.Fail(view.get("error") or f"the letter ended {view['state']}")
    if view["accepted"] is None:  # 231 (A7b): done once a person accepted the letter
        return _again(ctx, "acceptance")
    return kinds.Done({"version": view["version"], "problems": list(view.get("problems") or []),
                       "paragraph_used": not view.get("problems"), "accepted": True})


def _spent(table: str) -> Any:
    """231 (A7e): the budget scopes a quote step's jobs spent from (the proposal's, the letter versions'), oldest
    first: the job keeps its scope in its row. D0-b: the step's own."""
    def scopes(case_id: str, step: str) -> list[str]:
        from jav.core import store

        with store.connect() as c:
            return [r["scope"] for r in c.execute(f"SELECT scope FROM {table} WHERE workpackage_id=? AND step_id=?"
                                                  " AND scope IS NOT NULL ORDER BY rowid", (case_id, step))]
    return scopes


_OWNER = __name__
CAPABILITIES = (
    Capability(name="record_assembly", version=1, module=_OWNER, run=_record_assembly, kind="machine", params=RecordAssembly, effects="pure", state="step", output=RecordResult,
               summary="Puts a record together from an email's text, its table attachments and its attachments.",
               preview=_record_preview, records=_records),  # C3c: the general form's record chooser
    Capability(name="catalogue_match", version=1, module=_OWNER, run=_catalogue_match, kind="machine", params=CatalogueMatch, state="step", output=MatchResult,
               providers=("jev", "openai"), rule_files=("callsite:quote_match", "gpt_quote_match", "quotes", "price_lists"),
               summary="Matches each requested item with a catalogue item: sure, to check, or not listed.",
               spent=_spent("quote_proposals"), choices={"catalogue": _catalogues},
               # 231 (B3): only fewer items than the file's (more would raise what a proposal may spend)
               rule_keys=(RuleKey("quotes", "proposal.max_items", "int", "At most this many requested items are matched in one"
                                  " proposal", least=1, most=200),)),
    Capability(name="line_pricing", version=1, module=_OWNER, kind="machine", params=LinePricing, effects="pure",
               rule_files=("price_lists",), summary="Prices lines from a catalogue: unit price, discount rules, totals.",
               choices={"catalogue": _catalogues}),
    Capability(name="line_draft", version=1, module=_OWNER, run=_line_draft, kind="human", params=LineDraft, state="step", output=OwnVersionResult,
               rule_files=("quotes", "price_lists"), own_version=True,  # 231 (C2d): reopening the quote reopens it
               summary="A person composes the lines from the match, gives own prices with a note, and approves.",
               choices={"catalogue": _catalogues},
               rule_keys=(RuleKey("quotes", "draft.max_lines", "int", "A quote holds at most this many lines", least=1, most=1000),
                          RuleKey("price_lists", "rounding.HUF", "choice", "A forint quote's amounts are rounded to this unit",
                                  options=("1", "0.01")),
                          RuleKey("price_lists", "rounding.default", "choice", "Another currency's amounts are rounded to this"
                                  " unit", options=("0.01", "1")))),
    Capability(name="letter_draft", version=1, module=_OWNER, run=_letter_draft, kind="machine", params=LetterDraft, providers=("openai",), state="step", output=LetterResult,
               rule_files=("gpt_quote_letter", "quote_documents", "quotes"),
               summary="Drafts a reply letter: the frame written by code around a model's checked paragraph; done once a person"
                       " accepted it.", spent=_spent("quote_letters"), choices={"frame": _frames},
               rule_keys=(RuleKey("quotes", "letter.max_chars", "int", "The model's paragraph is at most this many characters",
                                  least=100, most=2000),)),
)


def _quote_view(case_id: str, step: str | None, shared: dict[str, Any]) -> dict[str, Any]:
    """231 (A6): what the quote's elements show on a case's page: the quote view the quote package's page had, read once
    per page view, so the same components render it. D0-b: once per the case's steps that go together with the
    element's step (its match, composition and letter: `quote_steps.of`)."""
    from jav.domains.quotes import quote_package, quote_steps

    key = f"quote:{quote_steps.of(case_id, step)}"
    if key not in shared:
        shared[key] = quote_package.view(case_id, step)
    nxt = quote_package._next_of(shared[key])
    # the next step, and the element whose tab it is done on (the quote package's stages: request, quote, approval)
    return {"quote": shared[key], "next": {**nxt, "element": _NEXT_ELEMENT[nxt["stage"]]}}


_NEXT_ELEMENT = {"process": "record_view", "review": "match_proposal", "result": "approval"}


def _marks() -> tuple[Any, ...]:
    """231 (A3d): what the quote view reads changes with these (the price lists, the proposal, the draft, the letter)."""
    from jav.domains.quotes import price_lists, quote_draft, quote_letter, quote_proposal

    return price_lists.mark(), quote_proposal.mark(), quote_draft.mark(), quote_letter.mark()


# 231 (A6): the elements a step of these capabilities shows, each with the quote view
ELEMENTS = (("record_view", "record_assembly"), ("match_proposal", "catalogue_match"), ("line_editor", "line_draft"),
            ("approval", "line_draft"), ("form", "letter_draft"))


def _letter_message(case_id: str, source_step: str | None, source: Any) -> Any:
    """231 (A7c): the accepted letter of the approved version the letter step names (its result), as the email file
    the send capability hands over: the letter with the version's Word document attached. D0-b: the letter of the
    send step's `source_step` (None: the case's first letter step)."""
    from email import message_from_bytes
    from email.policy import default

    from jav.app import sending
    from jav.domains.quotes import quote_letter

    version = (source or {}).get("version") or quote_letter.view(case_id, step=source_step)["version"]
    data, name = quote_letter.eml(case_id, int(version), step=source_step)
    headers = message_from_bytes(data, policy=default)
    return sending.Message(data, name, str(headers["To"]) if headers["To"] else None, str(headers["Subject"] or ""))


def register() -> None:
    from jav.app import capabilities, case_views, sending
    from jav.app.outputs import parts
    from jav.domains.quotes import quote_document

    for cap in CAPABILITIES:
        capabilities.register(cap)
    # D0-c: how the quote's approved version becomes its Word document (the shared priced document prints it)
    parts.register_version_document(parts.VersionDocument(
        quote_document.OUTPUT, _OWNER, quote_document.data,
        file=lambda wp_id, n, package: quote_document.version_file(wp_id, n, package=package)))
    for element, capability in ELEMENTS:
        case_views.register(case_views.ElementData(element, capability, _OWNER, _quote_view, mark=_marks))
    sending.register_builder(sending.MessageBuilder("quote_letter", _OWNER, _letter_message,
                                                    "The accepted reply letter with the quote's Word document."))


__all__ = ["CAPABILITIES", "CatalogueMatch", "LetterDraft", "LineDraft", "LinePricing", "RecordAssembly", "register"]
