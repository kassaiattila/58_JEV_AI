"""The quote: a kind of work package started from a quote request (191, plan F-quote-package B3).

Plain-language summary (DECISIONS 191): the owner asked that the quote can be chosen as a kind of work, as the
reconciliation or the data extraction can, that the system proposes the quote's content, and that a person reviews and
changes it beside the request. A quote package starts from one request: an email or a document already processed and
read as a quote request, in any package (the owner's choice; uploading files into the quote is not part of it). Its
processing stays in that package; the quote reads its counted result, put together from the email's text and its
attachments (`jav/quote_request.py`), as the reconciliation reads the statements' results. Its gaps are judged on the
whole request: no customer, no requested item, no active price list, or a request that can no longer be read.

B3 made the package and shows its request; B4 proposes the quote's lines (`jav/quote_proposal.py`); B5 (192) is the
page where a person composes the quote from the proposal and approves it as a version of the package's own
(`jav/quote_draft.py`).

- `candidates(q)`: the requests a quote can start from, each with the quotes already made from it;
- `create(name, source, item_id)`: a quote package naming its request (the shared package scope's `request` part);
- `view(wp_id)`, `next_step(wp_id)`: the request, its source, the active price lists and the gaps, the proposal, the
  draft and its approval; the next step.
- `email_part(run, item)` (192, B6a): an email item's quote request, its gaps as a whole and the quotes made from it,
  shown under the email in its mailbox package (`EMAIL_PART`, an item part of the shared registry).

Layer: application operation of the quotes domain over the work packages, the scopes and the quote request.
"""

from __future__ import annotations

import json
from typing import Any

from jav import (app_settings, goldens, item_kinds, logic_packs, package_release, package_scope, price_lists, quote_draft,
                 quote_proposal, quote_request, store, work, workflow_steps)
from jav.tablequery import fold
from jav.user_messages import explained

KIND = "quote"
REQUEST = "request"  # the scope part naming the request: {"workpackage_id", "item_id"}
MAX_CANDIDATES = 50


class QuoteError(ValueError):
    """A quote that cannot be made: no name, or a source that is no quote request."""


# --- the requests a quote can start from -----------------------------------------------------------------------------


def _quotes_by_request() -> dict[tuple[str, str], list[dict[str, str]]]:
    with store.connect() as c:
        rows = c.execute("SELECT s.workpackage_id, s.parts, w.name FROM workpackage_scopes s JOIN workpackages w"
                         " ON w.id = s.workpackage_id WHERE w.source_kind = ? ORDER BY w.created_at", (KIND,)).fetchall()
    out: dict[tuple[str, str], list[dict[str, str]]] = {}
    for r in rows:
        ref = json.loads(r["parts"]).get(REQUEST) or {}
        out.setdefault((ref.get("workpackage_id", ""), ref.get("item_id", "")), []).append({"id": r["workpackage_id"], "name": r["name"]})
    return out


def candidates(q: str | None = None, limit: int = MAX_CANDIDATES) -> list[dict[str, Any]]:
    """The requests a quote can start from, newest first, matching `q` (the title, the sender, the customer or the
    package's name): each with its package, its customer and number of items, and the quotes already made from it."""
    made = _quotes_by_request()
    names = {wp["id"]: wp["name"] for wp in work.list_workpackages(include_archived=True)}
    needle = fold(q.strip()) if q and q.strip() else ""
    out = []
    for wp_id, item_id in quote_request.found():
        try:
            request = quote_request.read(wp_id, item_id)
        except quote_request.RequestNotFound:
            continue
        row = {"workpackage_id": wp_id, "workpackage_name": names.get(wp_id, wp_id), "item_id": item_id,
               "kind": request.kind, "title": request.title, "sender": request.sender, "received_at": request.received_at,
               "customer_name": request.fields.get("customer_name"), "items": len(request.items),
               "quotes": made.get((wp_id, item_id), [])}
        text = " ".join(str(row[k] or "") for k in ("title", "sender", "customer_name", "workpackage_name"))
        if not needle or needle in fold(text):
            out.append(row)
    out.sort(key=lambda r: (r["received_at"] or "", r["title"]), reverse=True)
    return out[:limit]


# --- the package ---------------------------------------------------------------------------------------------------------


def create(*, name: str, source: str, item_id: str, actor: str) -> dict[str, Any]:
    """A quote package from the request of `item_id` in the package `source` (an email or a document read as a quote
    request). `QuoteError` when the name is empty or the item is no quote request."""
    if not (name or "").strip():
        raise explained(QuoteError, "a quote needs a name")
    try:
        quote_request.read(source, item_id)
    except quote_request.RequestNotFound as exc:
        raise explained(QuoteError, "the chosen item is not a quote request that has been processed") from exc
    wp = work.create_workpackage(name=name, source_kind=KIND, source_ref=None, owner=actor)
    with store.connect() as c:
        store.begin_immediate(c)
        package_scope.save(c, wp["id"], parts={REQUEST: {"workpackage_id": source, "item_id": item_id}}, actor=actor)
    return {"workpackage_id": wp["id"]}


def request_of(wp_id: str) -> dict[str, str] | None:
    """The request the package was made from: {"workpackage_id", "item_id"}; None when it names none."""
    stored = package_scope.stored(wp_id)
    return (stored or {}).get("parts", {}).get(REQUEST)


def _blocker(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def request_gaps(request: quote_request.Request) -> list[dict[str, str]]:
    """What the whole request lacks for a quote (a part's own gap is only a note, DECISIONS 192)."""
    gaps = []
    if not request.fields.get("customer_name"):
        gaps.append(_blocker("quote:no_customer", "The request names no customer"))
    if not request.items:
        gaps.append(_blocker("quote:no_items", "The request names no item"))
    return gaps


def email_part(run: dict[str, Any], item: dict[str, Any]) -> dict[str, Any] | None:
    """192 (B6a): the quote request of an email item as its package counts it now, with what it lacks as a whole and
    the quotes already made from it; None for an email that is no quote request."""
    wp_id = run["workpackage_id"]
    try:
        request = quote_request.read(wp_id, item["item_id"])
    except quote_request.RequestNotFound:
        return None
    return {"request": request.as_dict(), "gaps": request_gaps(request),
            "quotes": _quotes_by_request().get((wp_id, item["item_id"]), []),
            "source": {"workpackage_id": wp_id, "item_id": item["item_id"]}}


def view(wp_id: str) -> dict[str, Any]:
    """The package's own part of its page: its request put together (None when it can no longer be read), where it came
    from, the active price lists and the gaps that keep the quote from being made."""
    ref = request_of(wp_id) or {}
    request = None
    if ref:
        try:
            request = quote_request.read(ref["workpackage_id"], ref["item_id"])
        except quote_request.RequestNotFound:
            request = None
    try:
        source_name = work.get(ref["workpackage_id"])["name"] if ref else None
    except KeyError:
        source_name = None
    lists = price_lists.active_lists()
    blockers = []
    if request is None:
        blockers.append(_blocker("quote:request_missing", "The request can no longer be read"))
    else:
        blockers.extend(request_gaps(request))
    if not lists:
        blockers.append(_blocker("quote:no_price_list", "There is no active price list"))
    # B4c: the latest proposal, and the cap a new one would reserve with the application's engine
    engine = app_settings.engine_default()
    n_items = len(request.items) if request else 0
    return {"request": request.as_dict() if request else None,
            "source": {**ref, "workpackage_name": source_name} if ref else None,
            "price_lists": lists, "blockers": blockers, "proposal": quote_proposal.current(wp_id),
            "proposal_cap": {"engine": engine, "items": n_items,
                             "usd": {k: str(v) for k, v in quote_proposal.cap(n_items, engine).items()}},
            "draft": quote_draft.view(wp_id)}  # B5: the quote as a person composes it, and its approval


def _next_of(current: dict[str, Any]) -> dict[str, Any]:
    draft = current["draft"]
    if active := draft["approval"]["active"]:
        return {"code": "quote_approved", "label": f"Approved: version {active['version']}", "stage": "result",
                "params": {"version": active["version"]}}
    if current["request"] is None:
        return {"code": "quote_request_missing", "label": "The request cannot be read", "stage": "process"}
    if current["blockers"]:
        return {"code": "quote_request_check", "label": "Check the request", "stage": "process",
                "params": {"n": len(current["blockers"])}}
    if draft["draft"] is not None:  # B5: the draft is composed, then approved
        if draft["blockers"]:
            return {"code": "quote_compose", "label": "Compose the quote", "stage": "review",
                    "params": {"n": len(draft["blockers"])}}
        return {"code": "quote_approve", "label": "Approve the quote", "stage": "result"}
    proposal = current.get("proposal")
    if proposal is None or proposal["state"] == "failed":
        return {"code": "quote_propose", "label": "Ask for the proposal", "stage": "review"}
    if proposal["state"] in ("queued", "running"):
        return {"code": "quote_proposing", "label": "The proposal is being made", "stage": "review"}
    return {"code": "quote_compose", "label": "Compose the quote", "stage": "review"}


def next_step(wp_id: str) -> dict[str, Any]:
    return _next_of(view(wp_id))


def _page(wp_id: str) -> dict[str, Any]:
    """The package's page (`work_views.workpackage_view`): its readiness (nothing runs), its next step and its own part."""
    current = view(wp_id)
    return {"readiness": {"ready": False, "blockers": [], "counts": {"items": 0}}, "next": _next_of(current),
            "quote": current}


def _approved(wp_id: str) -> bool:
    """A workflow's quote step is done when a version of the package's quote is approved (B5)."""
    return package_release.own_approval(wp_id)["active"] is not None


def _release_refusal() -> Exception:
    return explained(work.NotReady, "a quote package has no run result to release: its quote is approved on its own page")


def _measure_lines(_options: goldens.Options) -> goldens.Outcome:
    """B4a: the invented quotes priced from their expected matches; code only, free."""
    from jav import quote_golden, quote_pricing

    return quote_pricing.measure_golden(quote_golden.load())


def _count_quotes() -> int:
    from jav import quote_golden

    return sum(1 for c in quote_golden.load().cases if c.expected.quote is not None)


def _count_matches() -> int:
    from jav import quote_golden

    return sum(len(c.expected.matches) for c in quote_golden.load().cases)


def _measure_matches(options: goldens.Options) -> goldens.Outcome:
    """B4b: the invented requested items matched with the round's engine; without a budget, earlier answers only. A
    right item is one marked as expected; one a person would resolve (flagged), a missed and a silently wrong one are
    counted apart in the printed report."""
    from jav import quote_match

    budget, refused = options.answering_budget("the quote matches")
    if refused:
        return goldens.Outcome(refused=refused)
    limits = {quote_match.PROVIDERS[options.engine]: budget} if budget is not None else {}
    g = quote_match.golden(engine=options.engine, limits=limits, use_cache=options.use_cache,
                           **({} if limits else {"earlier_only": True}))
    quote_match.print_golden(g)
    answered = g["items"] - g["tally"].get("failed", 0)
    return goldens.Outcome(cases=g["items"], answered=answered, right=g["tally"].get("right", 0), scored=answered,
                           unit="items")


# B4a: the quote package's golden sets, measured by the shared measurement command (`jav/goldens.py`)
GOLDENS = (
    goldens.Golden(key=f"{KIND}:lines", layer="logic_pack", owner=KIND, engines=(), module=__name__,
                   what="the invented quotes' lines and totals priced by code from their expected matches "
                        "(configs/golden_quotes.json)", count=_count_quotes, measure=_measure_lines),
    goldens.Golden(key=f"{KIND}:matches", layer="logic_pack", owner=KIND, engines=goldens.ENGINES, module=__name__,
                   what="the price list item proposed for each invented requested item: sure, to check or not listed "
                        "(configs/golden_quotes.json)", count=_count_matches, measure=_measure_matches),
)

LOGIC = logic_packs.LogicPack(
    kind=KIND, module=__name__,
    roles=(logic_packs.InputRole(REQUEST, "linked_package", "the quote request: an email or a document read as one"),
           logic_packs.InputRole("price_list", "master_data", "the seller's active price list")),
    has_runs=False, add_refusal="a quote package has no documents of its own: its request stays in its package",
    release_refusal=_release_refusal, delete_guard=quote_draft.delete_guard, page=_page, approved=_approved,
    next_step=next_step, list_next=next_step,
    list_mark=lambda: (price_lists.mark(), quote_proposal.mark(), quote_draft.mark()), outputs=(),
    service="jav.api_quote_package", goldens=GOLDENS)


def _workflow_start(_ctx: workflow_steps.StepStart) -> None:
    from jav.workflows import WorkflowError

    raise explained(WorkflowError, "a quote is started from its request, not as a workflow's step")


# 192 (B6a): the quote request under its email in a mailbox package
EMAIL_PART = item_kinds.ItemPart("quote_request", __name__, item_kinds.EMAIL, email_part)

STEP = workflow_steps.StepKind(KIND, __name__, (KIND,), start=_workflow_start, paid=False, own_engine=False,
                               repeat_from=lambda _wp_id: {"kind": "none"},
                               statuses={"quote_request_missing": "attention", "quote_request_check": "review",
                                         "quote_propose": "review", "quote_proposing": "review",
                                         "quote_compose": "review", "quote_approve": "review",
                                         "quote_approved": "approved"})


__all__ = ["EMAIL_PART", "KIND", "LOGIC", "REQUEST", "STEP", "QuoteError", "candidates", "create", "email_part", "next_step",
           "request_gaps", "request_of", "view"]
