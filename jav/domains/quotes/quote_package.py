"""The quote made from a quote request: what the IT quote's case shows (191, plan F-quote-package B3; 231).

Plain-language summary (DECISIONS 191): the owner asked that the quote can be chosen as a kind of work, as the
reconciliation or the data extraction can, that the system proposes the quote's content, and that a person reviews and
changes it beside the request. A quote package starts from one request: an email or a document already processed and
read as a quote request, in any package (the owner's choice; uploading files into the quote is not part of it). Its
processing stays in that package; the quote reads its counted result, put together from the email's text and its
attachments (`jav/domains/quotes/quote_request.py`), as the reconciliation reads the statements' results. Its gaps are judged on the
whole request: no customer, no requested item, no active price list, or a request that can no longer be read.

B3 made the package and shows its request; B4 proposes the quote's lines (`jav/domains/quotes/quote_proposal.py`); B5 (192) is the
page where a person composes the quote from the proposal and approves it as a version of the package's own
(`jav/domains/quotes/quote_draft.py`). 231 (A5, A3d): the quote runs as a case of the IT quote's process pack on its
container (a general work package of kind `case`); the quote package, its logic pack and its page are gone, and what
remains here is what the case's page and the email's part show.

- `candidates(q)`: the requests a quote can start from, each with the quotes already made from it;
- `view(wp_id)`, `_next_of(view)`: the request, its source, the active price lists and the gaps, the proposal, the
  draft and its approval, the letter; the next step.

Layer: application operation of the quotes domain over the work packages, the scopes and the quote request.
231 (C3c): the new work wizard's quote template is the IT quote pack's (its general form chooses the request, by the
record step's capability, `capabilities._records`); the quote's own kind of work went.
"""

from __future__ import annotations

import json
from typing import Any

from jav.app import app_settings, package_scope, scopes, work
from jav.core import store
from jav.domains.quotes import price_lists, quote_draft, quote_letter, quote_proposal, quote_request, quote_steps
from jav.app.tablequery import fold

KIND = "quote"  # the golden sets' key prefix (the quote package's kind until 231 A3d, the wizard's kind until C3c)
CONTAINER = "case"  # 231 (A5): the general container of a process pack's case (`jav/app/process_runtime.py`)
MAX_CANDIDATES = 50


# --- the requests a quote can start from -----------------------------------------------------------------------------


def _quotes_by_request() -> dict[tuple[str, str], list[dict[str, Any]]]:
    """The quotes made from each request: (231, A6) the cases started from it as their record."""
    with store.connect() as c:
        rows = c.execute("SELECT s.workpackage_id, s.parts, w.name FROM workpackage_scopes s JOIN workpackages w"
                         " ON w.id = s.workpackage_id WHERE w.source_kind = ? ORDER BY w.created_at", (CONTAINER,)).fetchall()
    out: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        ref = json.loads(r["parts"]).get(scopes.RECORD) or {}
        out.setdefault((ref.get("workpackage_id", ""), ref.get("item_id", "")), []).append(
            {"id": r["workpackage_id"], "name": r["name"], "case": True})
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


def request_of(wp_id: str) -> dict[str, str] | None:
    """The request the case was started from: {"workpackage_id", "item_id"}, its container's record (the general scope
    part); None when it names none."""
    return (package_scope.stored(wp_id) or {}).get("parts", {}).get(scopes.RECORD)


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


def view(wp_id: str, step: str | None = None) -> dict[str, Any]:
    """The package's own part of its page: its request put together (None when it can no longer be read), where it came
    from, the active price lists and the gaps that keep the quote from being made. D0-b: the proposal, draft and letter
    of the case's steps that go with `step` (`steps`: which ones, for the page's addresses). D0-e: a case that keeps
    the price list version of its start shows that one."""
    steps = quote_steps.of(wp_id, step)
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
    lists = price_lists.listed(quote_steps.catalogue(wp_id, steps.match))  # D0-e: the version the case keeps
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
            "price_lists": lists, "blockers": blockers, "proposal": quote_proposal.current(wp_id, step=steps.match),
            "proposal_cap": {"engine": engine, "items": n_items,
                             "usd": {k: str(v) for k, v in quote_proposal.cap(n_items, engine).items()}},
            "draft": quote_draft.view(wp_id, step=steps.compose),  # B5: the quote as a person composes it, and its approval
            "letter": quote_letter.view(wp_id, step=steps.letter),  # 196: the approved version's reply letter
            "steps": steps.as_dict()}


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


__all__ = ["CONTAINER", "KIND", "candidates", "request_gaps", "request_of", "view"]
