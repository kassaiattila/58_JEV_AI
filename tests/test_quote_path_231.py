"""231 (plan stage A, A0): the IT quote's whole path on the invented requests, recorded before stage A moves it.

Stage A moves the IT quote onto the process core and makes its parts general. The live store holds no quote, and the
quote request's extraction in a package has no earlier answers to replay, so the path is recorded here instead: each
invented request (`configs/golden_quotes.json`) is stored as a processed quote request with its expected values, and
goes through the real code: the quote package (231, A3d: the quote package is gone; the same steps run on a case's
container, without the process core moving it), the proposal job, the draft from the proposal, the approval, the Word
quote's data and the reply letter. Only the two calls to a model are stand-ins: an item's match answers what the golden
set expects (an item code written in the request still goes through the real code match), and the letter's paragraph
is a fixed sentence. The stand-ins also record a fingerprint of every request the code would send to a model (the
match's state, questions and GPT instructions, the letter's prompt), so a refactoring that changes what a model is
asked shows here, before it would cost a paid re-measurement.

The record is `tests/fixtures/quote_path_231.json`; after a deliberate change it is written again with
`JAV_WRITE_QUOTE_PATH=1 pytest tests/test_quote_path_231.py`, and the difference is reviewed like code.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from jav.core import queue, store
from jav.domains.quotes import (invented_golden, price_lists, quote_document, quote_draft, quote_letter, quote_match,
                                quote_package, quote_proposal)
from jav.runtime import job_kinds, worker
from jav.app import process_runtime, work
from tests import test_document_result_174 as rows

FIXTURE = Path(__file__).parent / "fixtures" / "quote_path_231.json"
WRITE = os.environ.get("JAV_WRITE_QUOTE_PATH") == "1"
ACTOR = "anna"
PARAGRAPH = {"hu": "Koszonjuk megkereseset, a kert ajanlatot mellekelten kuldjuk.",
             "en": "Thank you for your request; please find our quote attached."}
_VOLATILE = {"id", "line", "fingerprint", "state", "scope", "usage", "revision", "expected_state", "version_state"}


def _clean(value: Any) -> Any:
    """The business content: identifiers (a line's, a price list's random one), times, fingerprints and states left
    out; today's date written as a word (the local one, or the UTC one, which a stamp written after local midnight
    may still carry)."""
    if isinstance(value, dict):
        return {k: ("<price list>" if k == "price_list" and isinstance(v, str) and v.startswith("pl-") else _clean(v))
                for k, v in sorted(value.items())
                if k not in _VOLATILE and not k.endswith(("_id", "_at", "_ids"))}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        for today in {date.today().isoformat(), datetime.now(timezone.utc).date().isoformat()}:
            value = value.replace(today, "<today>")
        return value
    return value


def _digest(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      default=lambda o: o.model_dump() if hasattr(o, "model_dump") else str(o))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _values(request: invented_golden.Request) -> dict[str, Any]:
    """The expected request as the quote request's extraction stores it."""
    return {"customer_name": request.customer_name, "customer_tax_number": request.customer_tax_number,
            "contact_name": request.contact_name, "contact_email": request.contact_email,
            "contact_phone": request.contact_phone,
            "deadline": request.deadline.isoformat() if request.deadline else None, "reference": request.reference,
            "requested_items": [{"description": i.written, "quantity": str(i.quantity), "unit": i.unit}
                                for i in request.items]}


def _drain() -> None:
    """Every queued job processed the way the worker would, one after the other."""
    while (job := queue.claim("quote-path", kinds=(work.JOB_KIND, *(k.kind for k in job_kinds.kinds())))) is not None:
        worker.handle(job)


@pytest.fixture()
def golden(tmp_path, monkeypatch):
    data = invented_golden.load()
    seen: dict[str, list[dict[str, Any]]] = {}
    expected = {}
    for case in data.cases:
        if case.expected.request is not None:
            for m in case.expected.matches:
                expected[case.expected.request.items[m.item].written] = m
    real_match = quote_match.match

    def match(requested, context, prices, *, engine, run_id, use_cache=True):
        text = str(requested.get("description") or "")
        if quote_match.code_match(text, prices) is not None:  # an item code written in it: the real code, no call
            return real_match(requested, context, prices, engine=engine, run_id=run_id, use_cache=use_cache)
        items = quote_match.options(text, prices)
        seen.setdefault("match", []).append({
            "item": text, "state": _digest(quote_match.build_state(requested, context, items)),
            "questions": _digest(quote_match.build_questions(items)),
            "gpt": _digest([quote_match.gpt_instructions(items), quote_match.gpt_fields(items)])})
        m = expected[text]
        base = {"engine": engine, "method": "stand-in", "measured": True, "model": None, "cost_usd": 0.0,
                "probability": 0.99, "confidence": 0.99, "listed": 0.99, "specific": 0.99}
        if m.blocker == "not_in_price_list":
            return {**base, "mark": "not_listed", "sku": None, "candidates": [], "distribution": {}}
        if m.blocker == "ambiguous":
            return {**base, "mark": "check", "sku": None, "candidates": list(m.candidates),
                    "distribution": dict.fromkeys(m.candidates, 0.5)}
        return {**base, "mark": "sure", "sku": m.sku, "candidates": [m.sku], "distribution": {m.sku: 0.99}}

    def ask(prompt, *, run_id):
        seen.setdefault("letter", []).append(_digest([quote_letter._site()["instructions"], prompt]))
        language = json.loads(prompt).get("language")
        return PARAGRAPH["en" if language in ("English", "angol", "en") else "hu"]

    monkeypatch.setattr(quote_match, "match", match)
    monkeypatch.setattr(quote_letter, "ask", ask)
    with store.use_store(tmp_path / "quote-path.sqlite"):
        with store.connect() as c:
            c.execute("INSERT INTO workpackages(id, name, source_kind, created_at, updated_at) VALUES (?,?,?,?,?)",
                      (rows.WP, "invented quote requests", "manual", rows.NOW, rows.NOW))
        pl = data.price_list
        made = price_lists.add("Invented 2026", "p.xlsx", invented_golden.write_price_list(tmp_path / "p.xlsx", data).read_bytes(),
                               actor=ACTOR, currency=pl.currency, vat_percent=str(pl.vat_percent))
        version = 1
        if pl.discounts:
            price_lists.change_settings(made["price_list"], 1, actor=ACTOR, currency=pl.currency, vat_percent=str(pl.vat_percent),
                                        discounts=[{"category": d.category, "min_quantity": str(d.min_quantity),
                                                    "percent": str(d.percent)} for d in pl.discounts])
            version = 2
        price_lists.activate(made["price_list"], version, actor=ACTOR)
        cases = [c for c in data.cases if c.expected.request is not None]
        rows._run("run-requests", {c.id: _values(c.expected.request) for c in cases}, at=rows.NOW, doc_type="quote_request")
        yield cases, seen


def _path(case: invented_golden.Case, seen: dict[str, list]) -> dict[str, Any]:
    """One request along the whole path; a step that cannot go on (a blocker) ends it, as a person would see it."""
    seen.clear()
    name = f"Quote {case.id}"
    wp = process_runtime.start_case("it_quote", {"record": {"workpackage_id": rows.WP, "item_id": rows._id(case.id)}},
                                    name=name, actor=ACTOR)
    out: dict[str, Any] = {"package": _clean(quote_package.view(wp))}
    quote_proposal.request(wp, actor=ACTOR)
    _drain()
    out["proposal"] = _clean(quote_proposal.current(wp))
    view = quote_draft.start(wp, source="proposal", actor=ACTOR, expected_state=None)
    out["draft"] = _clean(view)
    if not view["blockers"]:
        version = quote_draft.approve(wp, fingerprint=view["fingerprint"], actor=ACTOR)
        out["approved"] = _clean(version)
        approved = quote_draft.approved_version(wp, version["version"])
        data = quote_document.data(approved["quote"], package=name, version=version["version"], approved_by=ACTOR)
        out["document"] = _clean(json.loads(json.dumps(dataclasses.asdict(data), default=str)))
        quote_letter.request(wp, actor=ACTOR)
        _drain()
        out["letter"] = _clean(quote_letter.view(wp))
        out["package_after"] = _clean(quote_package.view(wp))
    out["requests_to_models"] = {k: list(v) for k, v in sorted(seen.items())}
    return out


def test_the_quote_path_on_the_invented_requests_is_as_recorded(golden) -> None:
    cases, seen = golden
    record = {case.id: _path(case, seen) for case in cases}
    text = json.dumps(record, ensure_ascii=True, indent=1, sort_keys=True) + "\n"  # ASCII: the language guard counts letters
    if WRITE:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8", newline="\n")
    assert FIXTURE.is_file(), "no record yet: write it with JAV_WRITE_QUOTE_PATH=1"
    assert json.loads(text) == json.loads(FIXTURE.read_text(encoding="utf-8"))
    approved = [c for c, r in record.items() if "letter" in r]
    assert len(cases) == 10 and approved  # the record covers the approval and the letter, not only the blockers
