"""The quote request's golden runs (190, plan 189 A2g): the intent of the invented emails and the requests read from them.

Plain-language summary: the invented golden set of the quote request (`configs/golden_quotes.json`, 13 emails to an
invented IT company) is measured in two parts. The intent part asks each email's intent, as the email flow asks it,
and counts how many are what a careful person would say (10 quote requests, 3 other emails). The request part reads
each of the 10 requests the way the processing reads them: the email's own text as a document, and each attachment
(a request form as a PDF, a request list as a table) as a document of the quote request's type; then it compares what
was read with the expected request: the customer, its tax number, the contact's name, email and phone, the deadline,
the customer's reference, the number of requested items and each item's quantity. The text and the attachments of
one email are put together field by field (the first value found, the email's text first; the items from an
attachment that has rows, else from the text); 191: the quote package puts them together by the same rule, one
function for both (`jav/domains/quotes/quote_request.py` `merged`). Each request PDF's detected type is reported too.

Raw rows: `runs/<stamp>_quote_intents.jsonl` and `runs/<stamp>_quote_requests.jsonl`. Budget (160): without one only
earlier answers count; a paid round measures one of the two parts, under the owner's sub-budget.

Layer: measurement (it runs the email flow, the detection and the extraction flow); no store of its own.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from jav.domains.quotes import invented_golden
from jav.core.config import RUNS_DIR
from jav.evals import field_equal
from jav.domains.quotes.quote_request import merged

TYPE = "quote_request"
TEXT_FIELDS = ("customer_name", "contact_name", "reference")


def _budget(budget_usd: Decimal | None, jev_budget_usd: Decimal | None) -> dict[str, Decimal]:
    return {p: b for p, b in (("openai", budget_usd), ("jev", jev_budget_usd)) if b is not None}


def _dump(rows: list[dict[str, Any]], name: str) -> Path:
    RUNS_DIR.mkdir(exist_ok=True)
    path = RUNS_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{name}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), encoding="utf-8")
    return path


def _laid_out(root: Path) -> list[tuple[invented_golden.Case, Path]]:
    golden = invented_golden.load()
    return list(zip(golden.cases, invented_golden.lay_out_all(root, golden), strict=True))


# --- the intent --------------------------------------------------------------------------------------------------------


def count_intents() -> int:
    return len(invented_golden.load().cases)


def quote_intents(*, use_cache: bool = True, jev: bool = True, budget_usd: Decimal | None = None,
                  jev_budget_usd: Decimal | None = None) -> list[dict[str, Any]]:
    """Every email's intent, asked as the email flow asks it (without the attachments' detection), against the
    expected one."""
    from jav.domains.email.flow_email import run_email
    from jav.core import calls

    limits = _budget(budget_usd, jev_budget_usd)
    if not limits:
        print(calls.NO_BUDGET_NOTE)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="quote-golden-") as tmp, \
            calls.measurement(f"measure-{datetime.now():%Y%m%d_%H%M%S}-quote-intents", limits, reuse=use_cache):
        for case, folder in _laid_out(Path(tmp)):
            t0 = time.perf_counter()
            st = run_email(str(folder), use_cache=use_cache, detect_attachments=False, jev=jev)
            r = st.result
            rows.append({"case_id": case.id, "language": case.language, "expected": case.expected.intent,
                         "got": r.intent if r else None, "confidence": r.confidence if r else None,
                         "probabilities": r.probabilities if r else None, "next_flow": st.next_flow,
                         "review_reasons": st.review_reasons, "seconds": round(time.perf_counter() - t0, 2)})
            print(f"  {case.id:30} {rows[-1]['got'] or '-':26} {rows[-1]['confidence'] or 0:.2f}")
    path = _dump(rows, "quote_intents" + ("" if jev else "_gpt"))
    answered = [r for r in rows if r["got"] is not None]
    right = sum(r["got"] == r["expected"] for r in answered)
    print(f"\n### Quote request golden set - intent: {right}/{len(answered)} as expected "
          f"({len(rows) - len(answered)} without a result)")
    for r in answered:
        if r["got"] != r["expected"]:
            print(f"  - {r['case_id']}: expected {r['expected']}, got {r['got']} ({r['confidence']:.2f})")
    print(f"\nRaw rows: {path}")
    return rows


# --- the requests ------------------------------------------------------------------------------------------------------


def count_requests() -> int:
    return sum(1 for c in invented_golden.load().cases if c.expected.request is not None)


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def field_right(field: str, got: Any, expected: Any) -> bool:
    """Whether a read value is the expected one: the phone by its digits (06 and +36 are the same prefix), the email
    address without case, the others by the pack's field kinds as the data point golden sets compare them."""
    if got in (None, "") or expected in (None, ""):
        return got in (None, "") and expected in (None, "")
    if field == "contact_phone":
        a, b = _digits(got), _digits(expected)
        return a == b or (a.startswith("36") and "06" + a[2:] == b) or (b.startswith("36") and "06" + b[2:] == a)
    if field == "contact_email":
        return str(got).strip().casefold() == str(expected).strip().casefold()
    from jav.ai.typepack import get as get_pack

    return field_equal(field, got, expected, get_pack(TYPE).kind(field))


def score(got: dict[str, Any], expected: invented_golden.Request) -> dict[str, Any]:
    """Per header field right or wrong; the number of items; each expected item's quantity in order (a missing row
    is wrong); the units as information only (the expected unit is the price list's, which matching decides)."""
    from jav.ai.typepack import get as get_pack

    exp = expected.model_dump(mode="json")
    fields = {f: field_right(f, got.get(f), exp.get(f)) for f in get_pack(TYPE).header_fields}
    rows = got.get("requested_items") or []
    quantities = [i < len(rows) and _quantity(rows[i].get("quantity")) == item.quantity
                  for i, item in enumerate(expected.items)]
    units = [i < len(rows) and str(rows[i].get("unit") or "").strip().casefold() == item.unit.casefold()
             for i, item in enumerate(expected.items)]
    return {"fields": fields, "row_count": len(rows) == len(expected.items), "rows": len(rows),
            "quantities": quantities, "units": units}


def _quantity(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)).normalize() if value is not None else None
    except ArithmeticError:
        return None


def _reading(state) -> dict[str, Any] | None:
    from jav.ai.typepack import get as get_pack

    if state.record is None:
        return None
    return state.record.to_datapoints(get_pack(TYPE).record_fields)


def _read_case(case: invented_golden.Case, folder: Path, *, use_cache: bool, jev: bool,
               run_one: Callable[..., Any]) -> dict[str, Any]:
    from jav.domains.email import emails
    from jav.documents import text_document
    from jav.flow_detect import run_detect

    msg = emails.load_message_dir(folder)
    text = emails.document_text(msg)
    sources: list[dict[str, Any]] = []
    states = [run_one(str(folder / "message.json"), f"{case.id}-text", "G", use_cache=use_cache, doc_type=TYPE,
                      jev=jev, source_text=text)]
    sources.append({"source": "text", "final_status": states[-1].final_status, "review_reasons": states[-1].review_reasons})
    for att in msg.attachments:
        if att.path is None:
            continue
        source: dict[str, Any] = {"source": att.filename}
        if text_document.input_kind(att.path) == "pdf":  # only a PDF is recognised by its type
            st = run_detect(att.path, use_cache=use_cache, run_id=f"{case.id}-{att.filename}-detect", jev=jev)
            source["detected"] = st.result.doc_type if st.result else None
        states.append(run_one(att.path, f"{case.id}-{att.filename}", "G", use_cache=use_cache, doc_type=TYPE, jev=jev))
        sources.append({**source, "final_status": states[-1].final_status, "review_reasons": states[-1].review_reasons})
    readings = [_reading(s) for s in states]
    return {"sources": sources, "readings": readings, "answered": all(r is not None for r in readings)}


def quote_requests(*, use_cache: bool = True, jev: bool = True, budget_usd: Decimal | None = None,
                   jev_budget_usd: Decimal | None = None, run_one: Callable[..., Any] | None = None) -> list[dict[str, Any]]:
    """Every quote request read from its email's text and its attachments, against the expected request."""
    from jav.core import calls

    if run_one is None:
        from jav.flow import run_one
    limits = _budget(budget_usd, jev_budget_usd)
    if not limits:
        print(calls.NO_BUDGET_NOTE)
    rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="quote-golden-") as tmp, \
            calls.measurement(f"measure-{datetime.now():%Y%m%d_%H%M%S}-quote-requests", limits, reuse=use_cache):
        for case, folder in _laid_out(Path(tmp)):
            if case.expected.request is None:
                continue
            t0 = time.perf_counter()
            read = _read_case(case, folder, use_cache=use_cache, jev=jev, run_one=run_one)
            got = merged([r or {} for r in read["readings"]]) if read["answered"] else None
            row = {"case_id": case.id, "language": case.language, "sources": read["sources"], "got": got,
                   "score": score(got, case.expected.request) if got is not None else None,
                   "seconds": round(time.perf_counter() - t0, 2)}
            rows.append(row)
            s = row["score"]
            print(f"  {case.id:30} " + (f"{sum(s['fields'].values())}/{len(s['fields'])} fields, rows {s['rows']}"
                                        if s else "without a result"))
    path = _dump(rows, "quote_requests" + ("" if jev else "_gpt"))
    print_requests_report(rows)
    print(f"\nRaw rows: {path}")
    return rows


def judgements(rows: list[dict[str, Any]]) -> tuple[int, int]:
    """(right, scored) over the scored judgements: each header field, each case's number of items, each item's
    quantity."""
    right = scored = 0
    for r in rows:
        s = r.get("score")
        if not s:
            continue
        marks = [*s["fields"].values(), s["row_count"], *s["quantities"]]
        right += sum(marks)
        scored += len(marks)
    return right, scored


def print_requests_report(rows: list[dict[str, Any]]) -> None:
    scored = [r for r in rows if r.get("score")]
    print(f"\n### Quote request golden set - requests: {len(scored)}/{len(rows)} read\n")
    if not scored:
        return
    fields = list(scored[0]["score"]["fields"])
    print("| field | right |\n|---|---|")
    for f in fields:
        print(f"| {f} | {sum(r['score']['fields'][f] for r in scored)}/{len(scored)} |")
    print(f"| number of items | {sum(r['score']['row_count'] for r in scored)}/{len(scored)} |")
    q = [m for r in scored for m in r["score"]["quantities"]]
    u = [m for r in scored for m in r["score"]["units"]]
    print(f"| item quantities | {sum(q)}/{len(q)} |\n| item units (information) | {sum(u)}/{len(u)} |")
    right, total = judgements(rows)
    print(f"\n**Scored judgements:** {right}/{total} = {right / max(total, 1):.1%}")
    detected = [(r["case_id"], s["source"], s["detected"]) for r in rows for s in r["sources"] if "detected" in s]
    if detected:
        print("\nRequest PDFs' detected type: " + ", ".join(f"{c} {src}: {d or '-'}" for c, src, d in detected))
    wrong = [f"{r['case_id']}: {f}" for r in scored for f, ok in r["score"]["fields"].items() if not ok]
    if wrong:
        print("\nWrong fields: " + "; ".join(wrong))


__all__ = ["count_intents", "count_requests", "field_right", "judgements", "merged", "quote_intents", "quote_requests",
           "score"]
