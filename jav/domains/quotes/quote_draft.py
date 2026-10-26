"""The quote as a person composes it, priced by code, and its approval (192, plan F-quote-package B5).

Plain-language summary (DECISIONS 191, 192): the owner asked for a page where the request and its data can be seen and
the quote changed on their basis. A person starts the quote's draft from the proposal (each requested item with the
price list item proposed for it) or from the requested items alone. The draft holds the quote's header (the request's
customer, contact, deadline and reference, and a note) and its lines: a price list item, or a line of a person's own
with its description, unit and price; each with a quantity, and optionally a price or a discount of a person's own.

Every change is saved at once: the page sends the whole draft with the state it read, the service reads the numbers
the Hungarian way (`jav/core/numbers.py`), prices every line by code (`jav/domains/quotes/quote_pricing.py`) and records the change in the
decision journal; a change from a stale page is a version conflict. What holds the approval is said line by line: a
line without an item or a price, without a quantity, a line outside the list or with a price or discount of a person's
own without a note, and (the owner's choice, DECISIONS 192) a line the proposal marked "to check" with an item no
person has confirmed or chosen. The approval records the priced quote as the package's own version
(`jav/app/package_release.py`), with the price list version it was priced from and its request; while it stands the quote
is not changed, and reopening it needs a reason.

- `view(wp_id)`: the draft with each line priced, the totals, what holds the approval, the warnings, the draft's state
  and fingerprint, the price list it is priced from and the approval;
- `start(wp_id, source, actor, expected_state, replace)`, `save(wp_id, draft, actor, expected_state)`;
- `approve(wp_id, fingerprint, actor)`, `reopen(wp_id, note, actor)`, `approved_version(wp_id, n)`;
- (196) the quote's documents' language (estimated from the request at the start, changed by a person) and its Word
  document: stored at the approval (`jav/domains/quotes/quote_document.py`), `version_docx(wp_id, n)`, `draft_docx(wp_id)`;
- `delete_guard(c, wp_id)`, `mark()`: for the quote package's logic pack.

Stage D0 (D0-b): a draft, its decisions and its approval are the case's line composition step's (`step`; None: the
case's first, `jav/domains/quotes/quote_steps.py`), started from the proposal of the match step it names; two
composition steps of a case keep two drafts and two approvals.

Layer: application operation of the quotes domain over the decision journal, the package versions, the price lists,
the quote request, its proposal and the pricing.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from jav.app import package_release, work
from jav.core import activity_kinds, cfg, decisions, identity, numbers, store, trace
from jav.core.process import cases
from jav.domains.quotes import price_lists, quote_document, quote_pricing, quote_proposal, quote_request, quote_steps
from jav.ai.typepack import get as get_pack
from jav.core.user_messages import explained
from jav.core.clock import utc_stamp as _now

KIND = "quote_draft"  # the decision kind: one draft per quote package, keyed by the package
CHECK_MARKS = ("check", "failed")  # the proposal's marks a person confirms before the approval (DECISIONS 192)
# the parts of a line the page sends back; the rest (its requested item, the proposal's mark and candidates, who
# confirmed it) is the service's
EDITABLE = ("id", "sku", "description", "unit", "quantity", "unit_price", "discount_percent", "note", "checked")
NOTE = "note"  # the header's own field beside the request's

_DDL = """
-- 192 (plan F-quote-package B5): a quote package's draft as a person composes it
CREATE TABLE IF NOT EXISTS quote_drafts (
    workpackage_id TEXT NOT NULL,
    step_id        TEXT NOT NULL DEFAULT '',  -- D0-b: the case's line composition step ('': a package that is no case's)
    content        TEXT NOT NULL,      -- JSON: the price list version, the header, the lines, where it started from
    started_by     TEXT NOT NULL,
    started_by_id  TEXT,               -- 229 (SZ2c): the stable ids beside the names (`jav.core.identity`)
    started_at     TEXT NOT NULL,
    updated_by     TEXT NOT NULL,
    updated_by_id  TEXT,
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (workpackage_id, step_id)
);
"""
store.register_schema("quote_drafts", _DDL)
store.register_migration("quote_drafts_actor_ids",
                         lambda conn: store.add_actor_ids(conn, "quote_drafts", ("started_by", "updated_by")))  # 229
store.register_migration("quote_drafts_steps",  # D0-b: keyed by the case's line composition step
                         lambda conn: quote_steps.rebuild(conn, "quote_drafts", _DDL, quote_steps.COMPOSE))

decisions.register(decisions.Kind(KIND, ("start", "save"), __name__))
activity_kinds.register_events("package", ("quote_approve", "quote_reopen"), __name__)


class QuoteDraftError(ValueError):
    """A draft that cannot be started, saved, approved or reopened as asked: no proposal or request to start from, a
    number that cannot be read, an item the price list does not have, a price list version that is not active, an
    approved quote, or a reopening without a reason."""


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


Number = Annotated[str | None, Field(max_length=40)]


class LineIn(_In):
    """A line as the page sends it: `id` None for a line a person added."""

    id: Annotated[str | None, Field(max_length=40)] = None
    sku: Annotated[str | None, Field(max_length=100)] = None
    description: Annotated[str | None, Field(max_length=500)] = None
    unit: Annotated[str | None, Field(max_length=40)] = None
    quantity: Number = None
    unit_price: Number = None
    discount_percent: Number = None
    note: Annotated[str | None, Field(max_length=2000)] = None
    checked: bool = False


class DraftIn(_In):
    """The draft as the page sends it after a change."""

    price_list: Annotated[str, Field(min_length=1, max_length=100)]
    version: Annotated[int, Field(ge=1)]
    header: dict[str, Annotated[str | None, Field(max_length=2000)]]
    lines: list[LineIn]
    language: Annotated[str | None, Field(pattern=r"^[a-z]{2}$")] = None  # 196: the quote's documents' language


def header_fields() -> tuple[str, ...]:
    """The request's header fields (its type pack's), then the quote's own note."""
    return (*get_pack(quote_request.TYPE).header_fields, NOTE)


def max_lines() -> int:
    return int(cfg.load("quotes")["draft"]["max_lines"])


def _text(value: Any) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


def _canonical(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _decimal(text: str | None) -> Decimal | None:
    return None if text is None else Decimal(text)


def _requested_quantity(raw: Any) -> str | None:
    """A requested item's quantity as the extraction left it (a number, or text typed the Hungarian way); None when it
    cannot be read."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int | float | Decimal):
        return _canonical(Decimal(str(raw)))
    try:
        return numbers.read_input(raw, kind="number")
    except ValueError:  # AmbiguousNumber too: the person gives the quantity
        return None


# --- the stored draft ----------------------------------------------------------------------------------------------------


def _quote_package() -> Any:
    from jav.domains.quotes import quote_package  # the package imports this module

    return quote_package


def _package(wp_id: str) -> None:
    """KeyError for a package that holds no quote (the service's 404): 231 (A5, A3d) a case's container."""
    if work.get(wp_id)["source_kind"] != _quote_package().CONTAINER:
        raise KeyError(wp_id)


def _request(wp_id: str) -> quote_request.Request | None:
    ref = _quote_package().request_of(wp_id)
    if not ref:
        return None
    try:
        return quote_request.read(ref["workpackage_id"], ref["item_id"])
    except quote_request.RequestNotFound:
        return None


def _step(wp_id: str, step: str | None) -> str:
    """D0-b: the case's line composition step a draft is of (None: the case's first)."""
    return quote_steps.of(wp_id).compose if step is None else step


def _approving(step: str) -> str | None:
    """D0-b: the approving step of the package's own versions (None: a package that is no case's)."""
    return step or None


def _stored(c: sqlite3.Connection, wp_id: str, step: str) -> dict[str, Any] | None:
    row = c.execute("SELECT content FROM quote_drafts WHERE workpackage_id=? AND step_id=?", (wp_id, step)).fetchone()
    return json.loads(row["content"]) if row is not None else None


def _refuse_if_approved(c: sqlite3.Connection, wp_id: str, step: str) -> None:
    if active := package_release.own_approval(wp_id, c, step=_approving(step))["active"]:
        raise explained(QuoteDraftError, "the quote is approved (version {{version}}); reopen it to change it",
                        version=active["version"])


def _write(c: sqlite3.Connection, wp_id: str, step: str, content: dict[str, Any], action: str, actor: identity.Who) -> None:
    now = _now()
    c.execute("INSERT INTO quote_drafts(workpackage_id, step_id, content, started_by, started_by_id, started_at, updated_by,"
              " updated_by_id, updated_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(workpackage_id, step_id) DO UPDATE SET"
              " content=excluded.content, updated_by=excluded.updated_by, updated_by_id=excluded.updated_by_id,"
              " updated_at=excluded.updated_at"
              + (", started_by=excluded.started_by, started_by_id=excluded.started_by_id, started_at=excluded.started_at"
                 if action == "start" else ""),
              (wp_id, step, json.dumps(content, ensure_ascii=False), identity.name_of(actor), identity.id_of(actor), now,
               identity.name_of(actor), identity.id_of(actor), now))
    decisions.record(c, KIND, quote_steps.key(wp_id, step), action, actor=actor, value=content, workpackage_id=wp_id, at=now)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _line(*, row: int | None, requested: dict[str, Any] | None, sku: str | None, description: str | None,
          unit: str | None, quantity: str | None, mark: str | None = None, candidates: list[str] | None = None,
          proposed_sku: str | None = None) -> dict[str, Any]:
    return {"id": _new_id(), "row": row, "requested": requested, "sku": sku, "description": description, "unit": unit,
            "quantity": quantity, "unit_price": None, "discount_percent": None, "note": None, "checked": False,
            "checked_by": None, "checked_at": None, "mark": mark, "proposed_sku": proposed_sku,
            "candidates": candidates or []}


def _requested(item: dict[str, Any]) -> dict[str, Any]:
    return {"description": _text(item.get("description")), "quantity": item.get("quantity"), "unit": _text(item.get("unit"))}


def _from_proposal(line: dict[str, Any]) -> dict[str, Any]:
    """A proposal's line: its item unless it is not in the price list; a failed match is one to check."""
    answer = line.get("answer") or {}
    mark = answer.get("mark") or "failed"
    proposed = answer.get("sku")
    requested = _requested(line)
    return _line(row=line.get("row"), requested=requested, sku=None if mark == "not_listed" else proposed,
                 description=requested["description"], unit=requested["unit"],
                 quantity=_requested_quantity(line.get("quantity")), mark=mark,
                 candidates=list(answer.get("candidates") or []), proposed_sku=proposed)


def _from_request(row: int, item: dict[str, Any]) -> dict[str, Any]:
    requested = _requested(item)
    return _line(row=row, requested=requested, sku=None, description=requested["description"], unit=requested["unit"],
                 quantity=_requested_quantity(item.get("quantity")))


def start(wp_id: str, *, source: Literal["proposal", "request"], actor: identity.Who, expected_state: int | None,
          replace: bool = False, catalogue: str = price_lists.NEWEST_ACTIVE, step: str | None = None) -> dict[str, Any]:
    """The package's draft from its latest proposal (`proposal`, priced from the list version the proposal used) or
    from its requested items alone (`request`, priced from the list `catalogue` names: 231 B0, a process pack's
    resource, by default the newest active one); a draft already there is replaced only with `replace`. Returns the
    view. D0-b: the draft of the case's composition `step`, from the proposal of the match step it names."""
    _package(wp_id)
    step = _step(wp_id, step)
    req = _request(wp_id)
    if req is None:
        raise explained(QuoteDraftError, "the request can no longer be read")
    proposal = None
    if source == "proposal":
        proposal = quote_proposal.current(wp_id, step=quote_steps.of(wp_id, step or None).match)
        if proposal is None or proposal["state"] != "done":
            raise explained(QuoteDraftError, "the quote has no proposal to start from")
        prices = price_lists.version(proposal["price_list"], proposal["version"])
        lines = [_from_proposal(line) for line in proposal["lines"]]
    else:
        chosen = price_lists.chosen(catalogue)  # 231 (A3b): the same choice as the proposal's; (B0) the step's
        if chosen is None:
            raise explained(QuoteDraftError, "there is no active price list")
        prices = chosen
        lines = [_from_request(n, item) for n, item in enumerate(req.items)]
    content = {"price_list": prices.price_list, "version": prices.version,
               "header": {name: _text(req.fields.get(name)) for name in header_fields()}, "lines": lines[:max_lines()],
               "started_from": source, "request_key": quote_proposal.request_key(req.items),
               "proposal_at": proposal["finished_at"] if proposal else None,
               "language": quote_document.language_of(quote_document.request_texts(req))}
    with store.connect() as c:
        store.begin_immediate(c)
        decisions.check(c, KIND, quote_steps.key(wp_id, step), expected_state)
        _refuse_if_approved(c, wp_id, step)
        if _stored(c, wp_id, step) is not None and not replace:
            raise explained(QuoteDraftError, "the quote already has a draft; replace it to start again")
        _write(c, wp_id, step, content, "start", actor)
    return view(wp_id, step=step)


def _number(raw: str | None, old: str | None, kind: numbers.Kind) -> str | None:
    """A typed number as its canonical text; the stored text sent back unchanged stays as it is (it is canonical
    already, and "2.5" would read two ways)."""
    text = _text(raw)
    if text is None or text == old:
        return text
    return numbers.read_input(text, kind=kind)


def _read_line(line: LineIn, old: dict[str, Any] | None) -> dict[str, str | None]:
    """The line's numbers read, or `QuoteDraftError` naming the one that cannot be."""
    old = old or {}
    out: dict[str, str | None] = {}
    try:
        out["quantity"] = _number(line.quantity, old.get("quantity"), "number")
    except ValueError as exc:
        raise explained(QuoteDraftError, "the quantity is not a number: {{value}}", value=line.quantity) from exc
    try:
        out["unit_price"] = _number(line.unit_price, old.get("unit_price"), "money")
    except ValueError as exc:
        raise explained(QuoteDraftError, "the unit price is not a number: {{value}}", value=line.unit_price) from exc
    try:
        out["discount_percent"] = _number(line.discount_percent, old.get("discount_percent"), "number")
    except ValueError as exc:
        raise explained(QuoteDraftError, "the discount is not a number: {{value}}", value=line.discount_percent) from exc
    if out["unit_price"] is not None and Decimal(out["unit_price"]) < 0:
        raise explained(QuoteDraftError, "a unit price is not negative: {{value}}", value=line.unit_price)
    if out["discount_percent"] is not None and not 0 <= Decimal(out["discount_percent"]) < 100:
        raise explained(QuoteDraftError, "a discount is from 0 to less than 100 percent: {{value}}",
                        value=line.discount_percent)
    return out


def _merged(sent: DraftIn, stored: dict[str, Any], prices: price_lists.PriceList, actor: identity.Who) -> list[dict[str, Any]]:
    """The sent lines over the stored ones: the page's parts from the page, the service's kept; a line's item chosen or
    confirmed by a person is checked by them."""
    by_id = {ln["id"]: ln for ln in stored["lines"]}
    seen: set[str] = set()
    out = []
    for line in sent.lines:
        old = by_id.get(line.id) if line.id else None
        if line.id and (old is None or line.id in seen):
            raise explained(QuoteDraftError, "the quote has no such line: {{line}}", line=line.id)
        if line.id:
            seen.add(line.id)
        sku = _text(line.sku)
        if sku is not None and prices.item(sku) is None and (old is None or old["sku"] != sku):
            raise explained(QuoteDraftError, "the item {{sku}} is not in the price list {{name}} version {{version}}",
                            sku=sku, name=prices.name, version=prices.version)
        base = old or _line(row=None, requested=None, sku=None, description=None, unit=None, quantity=None)
        merged = {**base, **_read_line(line, old), "sku": sku, "description": _text(line.description),
                  "unit": _text(line.unit), "note": _text(line.note)}
        chose = sku is not None and old is not None and old["sku"] != sku
        if line.checked or chose:
            if not base["checked"] or chose:
                merged.update(checked=True, checked_by=identity.name_of(actor), checked_at=_now())  # the content shows the name
        else:
            merged.update(checked=False, checked_by=None, checked_at=None)
        out.append(merged)
    return out


def save(wp_id: str, draft: DraftIn | dict[str, Any], *, actor: identity.Who, expected_state: int | None,
         step: str | None = None) -> dict[str, Any]:
    """The draft as the page sends it after a change, read, checked and recorded. Returns the view. D0-b: of the case's
    composition `step`."""
    _package(wp_id)
    step = _step(wp_id, step)
    try:
        sent = draft if isinstance(draft, DraftIn) else DraftIn.model_validate(draft)
    except ValidationError as exc:
        raise explained(QuoteDraftError, "the draft cannot be read: {{problem}}",
                        problem=exc.errors()[0]["msg"]) from exc
    if unknown := sorted(set(sent.header) - set(header_fields())):
        raise explained(QuoteDraftError, "the quote has no header field {{field}}", field=unknown[0])
    if len(sent.lines) > max_lines():
        raise explained(QuoteDraftError, "a quote holds at most {{n}} lines", n=max_lines())
    if sent.language is not None and sent.language not in quote_document.languages():
        raise explained(QuoteDraftError, "the quote has no language {{language}}", language=sent.language)
    try:
        prices = price_lists.version(sent.price_list, sent.version)
    except price_lists.PriceListNotFound as exc:
        raise explained(QuoteDraftError, "the price list version {{version}} is not active", version=sent.version) from exc
    with store.connect() as c:
        store.begin_immediate(c)
        decisions.check(c, KIND, quote_steps.key(wp_id, step), expected_state)
        _refuse_if_approved(c, wp_id, step)
        stored = _stored(c, wp_id, step)
        if stored is None:
            raise explained(QuoteDraftError, "the quote has no draft yet")
        switched = (sent.price_list, sent.version) != (stored["price_list"], stored["version"])
        if switched and prices.state != "active":
            raise explained(QuoteDraftError, "the price list version {{version}} is not active", version=sent.version)
        content = {**stored, "price_list": prices.price_list, "version": prices.version,
                   "header": {name: _text(sent.header.get(name)) for name in header_fields()},
                   "lines": _merged(sent, stored, prices, actor), "language": sent.language or stored.get("language")}
        _write(c, wp_id, step, content, "save", actor)
    return view(wp_id, step=step)


# --- the view: each line priced, what holds the approval -----------------------------------------------------------------


def _priced(p: quote_pricing.PricedLine) -> dict[str, Any]:
    return {"sku": p.sku, "name": p.name, "quantity": _canonical(p.quantity), "unit": p.unit,
            "list_price": None if p.list_price is None else str(p.list_price), "unit_price": str(p.unit_price),
            "manual_price": p.manual_price, "discount_percent": _canonical(p.discount_percent),
            "discount_from": p.discount_from, "net": str(p.net)}


def _issues(line: dict[str, Any], prices: price_lists.PriceList) -> list[str]:
    """What holds the approval of one line."""
    own = line["sku"] is None
    codes = []
    if own and line["unit_price"] is None:
        codes.append("quote:line_no_item")
    elif own and not line["description"]:
        codes.append("quote:line_no_description")
    if not own and prices.item(line["sku"]) is None:  # kept from another version of the list
        codes.append("quote:line_unknown_item")
    if line["quantity"] is None or Decimal(line["quantity"]) <= 0:
        codes.append("quote:line_no_quantity")
    if not own and line["mark"] in CHECK_MARKS and not line["checked"]:
        codes.append("quote:line_unchecked")
    manual = own or line["unit_price"] is not None or line["discount_percent"] is not None
    if manual and not line["note"] and "quote:line_no_item" not in codes:
        codes.append("quote:line_note_missing")
    return codes


def _price_line(line: dict[str, Any], prices: price_lists.PriceList) -> quote_pricing.PricedLine | None:
    """The line priced, or None while it cannot be (no item and no price, no quantity, an unknown item)."""
    if line["quantity"] is None or (line["sku"] is None and line["unit_price"] is None):
        return None
    try:
        return quote_pricing.price_line(quote_pricing.LineInput(
            quantity=Decimal(line["quantity"]), sku=line["sku"], description=line["description"], unit=line["unit"],
            unit_price=_decimal(line["unit_price"]), discount_percent=_decimal(line["discount_percent"])), prices)
    except quote_pricing.PricingError:
        return None


def _blocker(code: str, line: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "line": line["id"] if line else None, "row": line["row"] if line else None}


def _content(stored: dict[str, Any], prices: price_lists.PriceList, priced: list[quote_pricing.PricedLine | None],
             totals: dict[str, str] | None, ref: dict[str, str] | None, req: quote_request.Request | None) -> dict[str, Any]:
    """The quote as an approval records it; 196: with its documents' language (a draft started before 196: estimated
    from the request)."""
    lines = [{"id": ln["id"], "row": ln["row"], "requested": ln["requested"], "mark": ln["mark"], "note": ln["note"],
              "checked_by": ln["checked_by"], **(_priced(p) if p else {"sku": ln["sku"], "name": ln["description"]})}
             for ln, p in zip(stored["lines"], priced, strict=True)]
    language = stored.get("language") or quote_document.language_of(quote_document.request_texts(req))
    return {"header": stored["header"], "lines": lines, "totals": totals, "currency": prices.currency, "language": language,
            "vat_percent": _canonical(prices.vat_percent),
            "price_list": {"price_list": prices.price_list, "name": prices.name, "version": prices.version,
                           "fingerprint": prices.fingerprint},
            "request": {**(ref or {}), "title": req.title if req else None, "key": stored["request_key"]}}


def fingerprint(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _items(prices: price_lists.PriceList) -> list[dict[str, Any]]:
    return [{"sku": i.sku, "name": i.name, "unit": i.unit, "unit_price": str(i.unit_price), "category": i.category}
            for i in prices.items]


def _warnings(stored: dict[str, Any], prices: price_lists.PriceList, req: quote_request.Request | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if prices.state != "active":
        newer = price_lists.active(prices.price_list)
        out.append({"code": "quote:price_list_superseded", "version": newer.version if newer else None})
    if req is None:
        out.append({"code": "quote:request_missing"})
    elif quote_proposal.request_key(req.items) != stored["request_key"]:
        out.append({"code": "quote:request_changed"})
    return out


@store.one_connection
def view(wp_id: str, *, step: str | None = None) -> dict[str, Any]:
    """The package's draft (None before one is started) with each line priced (`priced` None while it cannot be), the
    totals (None until every line is priced), what holds the approval, the warnings, the draft's state (the page sends
    it back with a change) and fingerprint (the approval names it), the price list version's items, whether a newer
    proposal is there to start from, and the approval with the approved quote. D0-b: of the case's composition
    `step` (`step` in the view)."""
    step = _step(wp_id, step)
    with store.connect() as c:
        stored = _stored(c, wp_id, step)
        state = decisions.state(c, KIND, quote_steps.key(wp_id, step))
        approval = package_release.own_approval(wp_id, c, step=_approving(step))
        active = approval["active"]
        approved = package_release.own_version(wp_id, active["version"], c)["content"] if active else None
    out: dict[str, Any] = {"draft": stored, "state": state, "approval": approval, "approved": approved, "lines": [],
                           "totals": None, "currency": None, "vat_percent": None, "blockers": [], "warnings": [],
                           "fingerprint": None, "price_list": None, "proposal_newer": False, "language": None,
                           "languages": list(quote_document.languages()), "step": step}
    if stored is None:
        return out
    prices = price_lists.version(stored["price_list"], stored["version"])
    ref = _quote_package().request_of(wp_id)
    req = _request(wp_id)
    priced = [_price_line(line, prices) for line in stored["lines"]]
    totals = None
    if priced and all(p is not None for p in priced):
        net, vat, gross = quote_pricing.totals([p for p in priced if p is not None], prices)
        totals = {"net": str(net), "vat": str(vat), "gross": str(gross)}
    blockers = [_blocker(code, line) for line in stored["lines"] for code in _issues(line, prices)]
    if not stored["lines"]:
        blockers.append(_blocker("quote:no_lines"))
    if not stored["header"].get("customer_name"):
        blockers.insert(0, _blocker("quote:no_customer"))
    proposal = quote_proposal.current(wp_id, step=quote_steps.of(wp_id, step or None).match)
    content = _content(stored, prices, priced, totals, ref, req)
    out.update(lines=[{**line, "priced": _priced(p) if p else None} for line, p in zip(stored["lines"], priced, strict=True)],
               totals=totals, language=content["language"], currency=prices.currency, vat_percent=_canonical(prices.vat_percent), blockers=blockers,
               warnings=_warnings(stored, prices, req), fingerprint=fingerprint(content),
               price_list={"price_list": prices.price_list, "name": prices.name, "version": prices.version,
                           "state": prices.state, "items": _items(prices)},
               proposal_newer=bool(proposal and proposal["state"] == "done"
                                   and (proposal["finished_at"] or "") > (stored.get("proposal_at") or "")))
    return out


# --- the approval --------------------------------------------------------------------------------------------------------


def approve(wp_id: str, *, fingerprint: str, actor: identity.Who, step: str | None = None) -> dict[str, Any]:
    """Approves the quote the person saw (its `fingerprint`) as the package's next own version. `work.NotReady` with
    what holds it; `work.RevisionConflict` when the draft changed meanwhile. Returns the version's record. D0-b: the
    draft of the case's composition `step`, as that step's own version."""
    _package(wp_id)
    step = _step(wp_id, step)
    with store.connect() as c:
        state = decisions.state(c, KIND, quote_steps.key(wp_id, step))  # read before the view: a later change conflicts
    current = view(wp_id, step=step)
    if active := current["approval"]["active"]:
        raise explained(QuoteDraftError, "version {{version}} is approved; reopen it before approving again",
                        version=active["version"])
    if current["draft"] is None:
        raise explained(QuoteDraftError, "the quote has no draft yet")
    if current["blockers"]:
        raise explained(work.NotReady, "the quote cannot be approved yet",
                        [{"code": b["code"], "message": b["line"] or ""} for b in current["blockers"]])
    if fingerprint != current["fingerprint"]:
        raise explained(work.RevisionConflict, "the quote changed since it was shown; reload it and check it again")
    package = work.get(wp_id)["name"]
    content = _view_content(wp_id, current)
    with store.connect() as c:
        store.begin_immediate(c)
        if decisions.state(c, KIND, quote_steps.key(wp_id, step)) != state:
            raise explained(work.RevisionConflict, "the quote changed since it was shown; reload it and check it again")
        _refuse_if_approved(c, wp_id, step)
        n = package_release.approve_own(
            c, wp_id, event="quote", content=content, fingerprint=fingerprint, locks=[], actor=actor,
            files=lambda c, n: quote_document.store(c, wp_id, n, content, package=package, actor=actor),  # 196: its Word document
            details={"lines": len(content["lines"]), "gross": content["totals"]["gross"]}, step=_approving(step))
        # 231 (B3): the totals in the decision trace, so a process's own rounding can be tried on its approved quotes
        inputs = quote_pricing.amount_inputs(content)
        trace.record_in(c, quote_pricing.AMOUNTS, subject=("quote_version", f"{wp_id}:{n}"),
                        inputs=inputs, outcome=quote_pricing.amounts(inputs),  # the approved totals, without trailing zeros
                        keys=quote_pricing.rounding_keys(content["currency"]),
                        case_id=wp_id if cases.find_case_in(c, wp_id) else None)
    return approved_version(wp_id, n, with_quote=False)


def _view_content(wp_id: str, current: dict[str, Any]) -> dict[str, Any]:
    """The content an approval would record from the view `current`."""
    prices = price_lists.version(current["draft"]["price_list"], current["draft"]["version"])
    return _content(current["draft"], prices, [_price_line(line, prices) for line in current["draft"]["lines"]],
                    current["totals"], _quote_package().request_of(wp_id), _request(wp_id))


def reopen(wp_id: str, *, note: str, actor: identity.Who, step: str | None = None) -> dict[str, Any]:
    """Reopens the approved quote with a reason: it stays as an earlier version, and the draft can be changed again.
    Returns the view. D0-b: the version of the case's composition `step`."""
    _package(wp_id)
    step = _step(wp_id, step)
    note = (note or "").strip()
    if not note:
        raise explained(QuoteDraftError, "reopening needs a reason")
    with store.connect() as c:
        store.begin_immediate(c)
        if package_release.reopen_logged(c, wp_id, event="quote", note=note, actor=actor, step=_approving(step)) is None:
            raise explained(QuoteDraftError, "the quote has no approved version to reopen")
    return view(wp_id, step=step)


def approved_version(wp_id: str, n: int, *, with_quote: bool = True) -> dict[str, Any]:
    """An approved version of the quote as it was approved: {quote, version, fingerprint, approved_by, ...}
    (KeyError: no such version)."""
    _package(wp_id)
    found = package_release.own_version(wp_id, n)
    content = found.pop("content")
    return {**({"quote": content} if with_quote else {}), **found}


# --- the Word document (196) --------------------------------------------------------------------------------------------


def version_docx(wp_id: str, n: int) -> tuple[bytes, str]:
    """An approved version's Word document as it was stored when approved, and its file name (KeyError: no such
    version)."""
    _package(wp_id)
    return quote_document.version_file(wp_id, n, package=work.get(wp_id)["name"])


def draft_docx(wp_id: str, *, step: str | None = None) -> tuple[bytes, str]:
    """The draft as a Word document marked as a draft, with the package's chosen template, and its file name.
    `QuoteDraftError` without a draft or while a line is not priced. D0-b: of the case's composition `step`."""
    _package(wp_id)
    current = view(wp_id, step=step)
    if current["draft"] is None:
        raise explained(QuoteDraftError, "the quote has no draft yet")
    if current["totals"] is None:
        raise explained(QuoteDraftError, "the quote has a line that is not priced yet")
    return quote_document.draft_file(wp_id, _view_content(wp_id, current), package=work.get(wp_id)["name"])


# --- the list's mark ------------------------------------------------------------------------------------------------------


def mark() -> tuple[Any, ...]:
    """What changes when a draft is saved or a quote approved or reopened (the mark of the case's element data)."""
    with store.connect() as c:
        saved = c.execute("SELECT MAX(id) FROM decision_journal WHERE kind=?", (KIND,)).fetchone()[0]
        versions = c.execute("SELECT COUNT(*), COUNT(v.reopened_at), MAX(v.id) FROM package_versions v"
                             " JOIN workpackages w ON w.id = v.workpackage_id WHERE w.source_kind=?",
                             (_quote_package().CONTAINER,)).fetchone()
    return (saved, *tuple(versions))


__all__ = ["CHECK_MARKS", "EDITABLE", "KIND", "DraftIn", "LineIn", "QuoteDraftError", "approve", "approved_version",
           "draft_docx", "fingerprint", "header_fields", "mark", "reopen", "save", "start", "version_docx",
           "view"]
