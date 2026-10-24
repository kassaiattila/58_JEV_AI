"""The general capabilities of the quote's back half (231, plan stage A, A3c; DECISIONS 231).

Plain-language summary: the owner's rule is that every process is built only from general capabilities. The quote's
back half is six such building blocks, described here with what a process sets for each: putting a record together
from an email and its attachments, matching requested items with a catalogue (a price list), pricing lines from a
catalogue, a person's line-by-line draft with its approval, a priced document from an output template, and a letter
draft around a model's paragraph. They are described but cannot run as a process pack's step yet: they run as the quote
package's parts and, since 231 A5, as a process pack's steps too (`run`, on a case's container: the general work
package that holds the case's rows); their code moves to general domains later. Their parameters' defaults are not the
quote's: a process names them. Each step is repeatable: when its work is already there it goes on at once, and while a
job or a person works it waits with a retry timer (`POLL_S`).

Layer: domain (quotes); it registers into the application's capability registry.
"""

from __future__ import annotations

import time
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from jav.app import human_tasks
from jav.app.capabilities import Capability, RuleKey
from jav.core.process import kinds

POLL_S = 5.0  # how soon a waiting step looks again at the job or the person it waits for


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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


class CatalogueMatch(_Params):
    """Which catalogue the items are matched with (`newest_active` or a named price list), and the call site that asks."""

    catalogue: str = Field(min_length=1)
    callsite: str = Field(min_length=1)
    _catalogue = field_validator("catalogue")(lambda cls, v: _catalogue(v))


class LinePricing(_Params):
    catalogue: str = Field(min_length=1)
    _catalogue = field_validator("catalogue")(lambda cls, v: _catalogue(v))


class LineDraft(_Params):
    """A person composes the lines from the match; the approval is the record's own version."""

    catalogue: str = Field(min_length=1)
    approval: Literal["own_version"] = "own_version"
    _catalogue = field_validator("catalogue")(lambda cls, v: _catalogue(v))


class PricedDocument(_Params):
    """The output contract it fills, and the step whose approved version it prints."""

    output: str = Field(min_length=1)
    from_step: str = Field(min_length=1)

    @field_validator("output")
    @classmethod
    def _known_output(cls, value: str) -> str:
        from jav.core import cfg

        if value not in (cfg.load("outputs").get("outputs") or {}):
            raise ValueError(f"no output {value!r}")
        return value


class LetterDraft(_Params):
    """The letter frame's key and the call site that asks for the paragraph."""

    frame: str = Field(min_length=1)
    callsite: str = Field(min_length=1)

    @field_validator("frame")
    @classmethod
    def _known_frame(cls, value: str) -> str:
        from jav.domains.quotes import quote_document

        if not isinstance(quote_document.settings().get(value), dict):
            raise ValueError(f"no letter frame {value!r}")
        return value


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


def _catalogue_match(ctx: Any, params: CatalogueMatch) -> kinds.StepOutcome:
    from jav.domains.quotes import quote_proposal

    wp = _container(ctx)
    current = quote_proposal.current(wp)
    if current is None:
        try:
            quote_proposal.request(wp, actor=ctx.actor, selection=params.catalogue)
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
    from jav.domains.quotes import quote_draft

    wp = _container(ctx)
    view = quote_draft.view(wp)
    if view["draft"] is None:
        quote_draft.start(wp, source="proposal", actor=ctx.actor, expected_state=None, catalogue=params.catalogue)
        with ctx.transaction() as c:
            human_tasks.own_approval_waits(c, wp)  # a person approves it, from the waiting list
        return _again(ctx, "approval")
    active = view["approval"]["active"]
    if active is None:
        return _again(ctx, "approval")
    return kinds.Done({"version": active["version"]})


def _priced_document(ctx: Any, params: PricedDocument) -> kinds.StepOutcome:
    from jav.domains.quotes import quote_document, quote_draft

    wp = _container(ctx)
    version = ctx.result_of(params.from_step)[1]["version"]
    approved = quote_draft.approved_version(wp, version)
    data = quote_document.data(approved["quote"], package=ctx.data.get("name") or wp, version=version,
                               approved_by=approved.get("approved_by"), approved_at=approved.get("approved_at"),
                               output=params.output)
    return kinds.Done({"output": data.output, "version": version, "values": len(data.values)})


def _letter_draft(ctx: Any, params: LetterDraft) -> kinds.StepOutcome:
    from jav.domains.quotes import quote_letter

    wp = _container(ctx)
    view = quote_letter.view(wp)
    if view["state"] is None:
        try:
            quote_letter.request(wp, actor=ctx.actor, frame=params.frame)  # 231 (B0): the pack's letter frame
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
    first: the job keeps its scope in its row."""
    def scopes(case_id: str, _step: str) -> list[str]:
        from jav.core import store

        with store.connect() as c:
            return [r["scope"] for r in c.execute(f"SELECT scope FROM {table} WHERE workpackage_id=? AND scope IS NOT NULL"
                                                  " ORDER BY rowid", (case_id,))]
    return scopes


_OWNER = __name__
CAPABILITIES = (
    Capability(name="record_assembly", version=1, module=_OWNER, run=_record_assembly, kind="machine", params=RecordAssembly, effects="pure",
               summary="Puts a record together from an email's text, its table attachments and its attachments."),
    Capability(name="catalogue_match", version=1, module=_OWNER, run=_catalogue_match, kind="machine", params=CatalogueMatch,
               providers=("jev", "openai"), rule_files=("callsite:quote_match", "gpt_quote_match", "quotes", "price_lists"),
               summary="Matches each requested item with a catalogue item: sure, to check, or not listed.",
               spent=_spent("quote_proposals"),
               # 231 (B3): only fewer items than the file's (more would raise what a proposal may spend)
               rule_keys=(RuleKey("quotes", "proposal.max_items", "int", "At most this many requested items are matched in one"
                                  " proposal", least=1, most=200),)),
    Capability(name="line_pricing", version=1, module=_OWNER, kind="machine", params=LinePricing, effects="pure",
               rule_files=("price_lists",), summary="Prices lines from a catalogue: unit price, discount rules, totals."),
    Capability(name="line_draft", version=1, module=_OWNER, run=_line_draft, kind="human", params=LineDraft,
               rule_files=("quotes", "price_lists"),
               summary="A person composes the lines from the match, gives own prices with a note, and approves.",
               rule_keys=(RuleKey("quotes", "draft.max_lines", "int", "A quote holds at most this many lines", least=1, most=1000),
                          RuleKey("price_lists", "rounding.HUF", "choice", "A forint quote's amounts are rounded to this unit",
                                  options=("1", "0.01")),
                          RuleKey("price_lists", "rounding.default", "choice", "Another currency's amounts are rounded to this"
                                  " unit", options=("0.01", "1")))),
    Capability(name="priced_document", version=1, module=_OWNER, run=_priced_document, kind="machine", params=PricedDocument,
               rule_files=("quote_documents", "outputs"), summary="Fills a priced document from an output template."),
    Capability(name="letter_draft", version=1, module=_OWNER, run=_letter_draft, kind="machine", params=LetterDraft, providers=("openai",),
               rule_files=("gpt_quote_letter", "quote_documents", "quotes"),
               summary="Drafts a reply letter: the frame written by code around a model's checked paragraph; done once a person"
                       " accepted it.", spent=_spent("quote_letters"),
               rule_keys=(RuleKey("quotes", "letter.max_chars", "int", "The model's paragraph is at most this many characters",
                                  least=100, most=2000),)),
)


def _quote_view(case_id: str, _step: str | None, shared: dict[str, Any]) -> dict[str, Any]:
    """231 (A6): what the quote's elements show on a case's page: the quote view the quote package's page had, read once
    per page view, so the same components render it."""
    from jav.domains.quotes import quote_package

    if "quote" not in shared:
        shared["quote"] = quote_package.view(case_id)
    nxt = quote_package._next_of(shared["quote"])
    # the next step, and the element whose tab it is done on (the quote package's stages: request, quote, approval)
    return {"quote": shared["quote"], "next": {**nxt, "element": _NEXT_ELEMENT[nxt["stage"]]}}


_NEXT_ELEMENT = {"process": "record_view", "review": "match_proposal", "result": "approval"}


def _marks() -> tuple[Any, ...]:
    """231 (A3d): what the quote view reads changes with these (the price lists, the proposal, the draft, the letter)."""
    from jav.domains.quotes import price_lists, quote_draft, quote_letter, quote_proposal

    return price_lists.mark(), quote_proposal.mark(), quote_draft.mark(), quote_letter.mark()


# 231 (A6): the elements a step of these capabilities shows, each with the quote view
ELEMENTS = (("record_view", "record_assembly"), ("match_proposal", "catalogue_match"), ("line_editor", "line_draft"),
            ("approval", "line_draft"), ("document_view", "priced_document"), ("form", "letter_draft"))


def _letter_message(case_id: str, source: Any) -> Any:
    """231 (A7c): the accepted letter of the approved version the letter step names (its result), as the email file
    the send capability hands over: the letter with the version's Word document attached."""
    from email import message_from_bytes
    from email.policy import default

    from jav.app import sending
    from jav.domains.quotes import quote_letter

    version = (source or {}).get("version") or quote_letter.view(case_id)["version"]
    data, name = quote_letter.eml(case_id, int(version))
    headers = message_from_bytes(data, policy=default)
    return sending.Message(data, name, str(headers["To"]) if headers["To"] else None, str(headers["Subject"] or ""))


def register() -> None:
    from jav.app import capabilities, case_views, sending

    for cap in CAPABILITIES:
        capabilities.register(cap)
    for element, capability in ELEMENTS:
        case_views.register(case_views.ElementData(element, capability, _OWNER, _quote_view, mark=_marks))
    sending.register_builder(sending.MessageBuilder("quote_letter", _OWNER, _letter_message,
                                                    "The accepted reply letter with the quote's Word document."))


__all__ = ["CAPABILITIES", "CatalogueMatch", "LetterDraft", "LineDraft", "LinePricing", "PricedDocument", "RecordAssembly",
           "register"]
