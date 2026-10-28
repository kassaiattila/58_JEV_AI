"""The invented insurance application documents and the facts they hold (231, stage D, D-e2).

Plain-language summary: about twenty invented documents of businesses asking for property insurance - quote request
forms, a property schedule per site, claims history statements, with incomplete and faulty ones among them - kept as
data (`configs/golden_property_documents.json`). Each document is kept as what a correct reading of it gives (the type
pack's values); its printed page is made from those values here, in the layout the document names, so what is
expected is always what is printed. Each set of documents names the facts they hold (the units, what cannot be read,
the facts two documents disagree on), and the five sets of the invented product set's reference cases hold that case's
facts: the documents are read into the same facts the rules were measured on.

- `load(name)`, `PropertyDocuments`: the documents, by set (231 U-A6: a golden file of its own names its form - the
  request's title and the covers it prints - and its readings; the invented insurer's is the default, and
  `golden_allianz_property_documents` holds the real corporate product's invented customers).
- `pages(document, form)`: its printed lines, page by page; `write_pdfs(folder, name)`: every document as a PDF; (231 U0)
  `example_packets(titles, name)`: every set as a packet of a process's example documents, printed.
- `facts_of(document_set, readings)`: the units, the values not read and the disagreements its documents give.
- `score(document, got)`, `measure(options, *, read=, recognise=)`: the golden set
  `insurance_application:documents` (`jav/evals/goldens.py`): each document recognised (its main and its
  detailed type) and read with its own pack (each scored field, each list's number of rows, each row's values), and
  each set's facts read from what was read; the round's reader and recogniser are the flows' (paid, within the
  owner's sub-budget) or, in the tests, stand-ins.

Layer: measurement (it reads the shared readings and the product set); every name and number is invented.
"""

from __future__ import annotations

import json
import tempfile
import time
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from jav.app import fact_readings, facts
from jav.ai import typepack
from jav.core import cfg
from jav.core.config import RUNS_DIR
from jav.documents.synthetic_pdf import write_unicode_pdf_pages

__all__ = ["BROAD", "DATA", "KEY", "Document", "DocumentSet", "PropertyDocuments", "count", "facts_of", "load", "measure",
           "pages", "score", "write_pdfs"]

DATA = "golden_property_documents"
KEY = "insurance_application:documents"
BROAD = "insurance_application"
_MONTHS = ("január", "február", "március", "április", "május", "június", "július", "augusztus", "szeptember", "október",
           "november", "december")
_COVERS = ("vagyonbiztosítás", "betöréses lopás és rablás", "túlfeszültség", "üzemszünet")  # the form's printed boxes


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Document(_Model):
    id: str
    pack: str
    layout: str = "standard"  # standard | two_pages
    values: dict[str, Any]  # what a correct reading gives (the type pack's values); a value null is not printed
    note: str | None = None


class ExpectedUnit(_Model):
    key: str
    level: str
    parent: str | None = None
    facts: dict[str, Any]


class DocumentSet(_Model):
    id: str
    title: str
    case: str | None = None  # a reference case of the invented product set whose facts its documents hold
    documents: tuple[Document, ...] = Field(min_length=1)
    units: tuple[ExpectedUnit, ...]
    unread: tuple[tuple[str | None, str], ...] = ()  # (unit, fact)
    conflicts: tuple[tuple[str, str], ...] = ()  # (unit, fact): two documents disagree


class Form(_Model):
    """231 (U-A6): what the quote request form prints of its own: its title line and the covers it lists as boxes."""

    title: str = "Vállalkozói vagyonbiztosítás"
    covers: tuple[str, ...] = _COVERS


class PropertyDocuments(_Model):
    form: Form = Form()
    readings: str = "fact_readings_property"  # 231 (U-A6): the rule file its documents are read into facts by
    key: str = KEY  # the golden set's key
    sets: tuple[DocumentSet, ...]


def load(name: str = DATA) -> PropertyDocuments:
    return PropertyDocuments.model_validate({k: v for k, v in cfg.load(name).items() if k != "meta"})


# --- the printed page --------------------------------------------------------------------------------------------------


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.year}. {_MONTHS[d.month - 1]} {d.day}."


def _amount(text: str) -> str:
    return f"{int(Decimal(text)):,}".replace(",", " ") + " Ft"


def _line(label: str, value: Any, fmt: Any = str) -> list[str]:
    return [] if value is None else [f"{label}: {fmt(value)}"]


def _request(v: dict[str, Any], form: Form) -> list[list[str]]:
    wanted = {row["cover"] for row in v.get("requested_covers") or []}
    lines = ["BIZTOSÍTÁSI AJÁNLATKÉRŐ LAP", form.title,
             *_line("Szerződő", v.get("policyholder_name")), *_line("Adószám", v.get("policyholder_tax_number")),
             *_line("Fő tevékenység (TEÁOR)", v.get("activity_code"))]
    if v.get("contact_name"):
        lines.append(f"Kapcsolattartó: {v['contact_name']}" + (f", {v['contact_email']}" if v.get("contact_email") else ""))
    lines += [*_line("Kockázatviselés kezdete", v.get("cover_start"), _day), *_line("Díjfizetés", v.get("payment_frequency")),
              # 231 (U-A6): the request's three new fields, printed only when given (the invented insurer's forms
              # have none, so their pages stay as they were)
              *_line("Választott önrész", v.get("chosen_deductible"), _amount), *_line("Szerződés tartama", v.get("contract_term")),
              "Kért fedezetek:", *[f"[{'X' if c in wanted else ' '}] {c}" for c in form.covers],
              *_line("Üzemszüneti elszámolás módja", v.get("accounting_method")),
              *_line("Üzemszüneti biztosítási összeg", v.get("interruption_sum_insured"), _amount),
              *_line("Üzemszüneti időönrész", v.get("bi_deductible_days"), lambda d: f"{d} munkanap"),
              # 231 (D-h): the address last, where it has room (the writer puts cells at fixed points; a long address
              # in the middle ran into the country's cell and the two were read as one, measured on 2026-10-27)
              "Telephelyek:", "Sorszám   Ország   Cím",
              *["   ".join(str(s.get(c) or "") for c in ("site_no", "country", "address")) for s in v.get("sites") or []]]
    return [lines]


def _schedule(v: dict[str, Any], layout: str) -> list[list[str]]:
    head = ["VAGYONADATLAP", *_line("Szerződő", v.get("policyholder_name")), *_line("Telephely száma", v.get("site_no")),
            *_line("Telephely címe", v.get("site_address")), *_line("Alapterület", v.get("floor_area"), lambda a: f"{a} m²"),
            *_line("Árvízi zóna", v.get("flood_zone")), *_line("Távfelügyeletes riasztó", v.get("alarm_remote")),
            *_line("Túlfeszültség-védelem", v.get("surge_protection")), *_line("Pinceszinti tárolás", v.get("basement_storage")),
            *_line("Védelmi szint", v.get("protection_class"))]
    table = ["Vagyoncsoport   Biztosítási összeg   Értékelés   Avultság",
             *[f"{g['asset_group']}   {_amount(g['sum_insured'])}   {g['valuation']}   "
               + ("–" if g.get("wear") is None else f"{g['wear']}%") for g in v.get("asset_groups") or []]]
    return [head, table] if layout == "two_pages" else [head + table]


def _statement(v: dict[str, Any]) -> list[list[str]]:
    lines = ["KÁRELŐZMÉNY-NYILATKOZAT"]
    who = v.get("policyholder_name") or ""
    lines.append(f"Nyilatkozattevő: {who}" + (f", adószám: {v['policyholder_tax_number']}" if v.get("policyholder_tax_number") else ""))
    if v.get("period_start") and v.get("period_end"):
        lines.append(f"Vizsgált időszak: {_day(v['period_start'])} – {_day(v['period_end'])}")
    claims = v.get("claims") or []
    if claims:
        lines += ["Káresemény napja   Kár oka   Kifizetett kárösszeg",
                  *[f"{_day(c['claim_date'])}   {c['cause']}   {_amount(c['paid'])}" for c in claims]]
    else:
        lines.append("Az időszakban káresemény nem történt.")
    lines += [*_line("Károk száma összesen", v.get("claims_count")),
              *_line("Kifizetett kárösszeg összesen", v.get("claims_paid_total"), _amount)]
    return [lines]


def pages(document: Document, form: Form | None = None) -> list[list[str]]:
    """The document's printed lines, page by page, made from its values in its layout (Hungarian: document text); a
    request on its golden file's form (the invented insurer's by default)."""
    if document.pack == "insurance_request":
        return _request(document.values, form or Form())
    if document.pack == "property_schedule":
        return _schedule(document.values, document.layout)
    if document.pack == "claims_history":
        return _statement(document.values)
    raise ValueError(f"no page layout for {document.pack}")


def example_packets(titles: dict[str, str], name: str = DATA) -> list[dict[str, Any]]:
    """231 (stage U, U0): every set as a packet of a process's example documents (`configs/examples_<name without
    golden_>.json`): its id, its title (from `titles`, else the set's), and each document's file name and printed pages."""
    docs = load(name)
    return [{"id": s.id, "title": titles.get(s.id, s.title),
             "documents": [{"file": f"{d.id}.pdf", "pages": pages(d, docs.form)} for d in s.documents]} for s in docs.sets]


def write_pdfs(folder: Path, name: str = DATA) -> list[Path]:
    """Every document as a PDF in `folder` (`<set>/<document>.pdf`), as the measurement reads them."""
    out = []
    docs = load(name)
    for doc_set in docs.sets:
        for document in doc_set.documents:
            path = folder / doc_set.id / f"{document.id}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            out.append(write_unicode_pdf_pages(path, pages(document, docs.form)))
    return out


# --- the facts the documents hold ------------------------------------------------------------------------------------


def facts_of(document_set: DocumentSet, readings: fact_readings.Readings) -> tuple[list[dict[str, Any]], list[tuple[str | None, str]],
                                                                              list[tuple[str, str]]]:
    """The units its documents' values give ({key, level, parent, facts}, in the order they first appear), what could
    not be read ((unit, fact)), and the facts two documents give differently ((unit, fact): left to a person)."""
    cat = facts.catalogue(readings.catalogue)
    units: dict[str, dict[str, Any]] = {}
    unread: list[tuple[str | None, str]] = []
    conflicts: list[tuple[str, str]] = []
    for document in document_set.documents:
        claims, missed = fact_readings.claims(readings, document.pack, document.values,
                                              source=lambda *_a, d=document: {"item": d.id}, reading=f"type:{document.pack}")
        unread += [(m["unit"], m["fact"]) for m in missed]
        for claim in claims:
            unit = units.setdefault(claim["unit"], {"key": claim["unit"], "level": claim["level"], "parent": claim["parent"],
                                                    "facts": {}})
            have = unit["facts"].get(claim["fact"])
            if have is None:
                unit["facts"][claim["fact"]] = claim["value"]
                continue
            d = cat.facts[claim["fact"]]
            if facts.typed_value(claim["fact"], d, have) != facts.typed_value(claim["fact"], d, claim["value"]):
                conflicts.append((claim["unit"], claim["fact"]))
    return list(units.values()), unread, conflicts


# --- the measurement -------------------------------------------------------------------------------------------------

Reader = Callable[[Document, Path], dict[str, Any] | None]  # what a document's reading gave (None: no answer)
Recogniser = Callable[[Path], tuple[str | None, str | None]]  # (main type, detailed type)


def count(name: str = DATA) -> int:
    return sum(len(s.documents) for s in load(name).sets)


def _same(want: Any, got: Any) -> bool:
    """A value as read against the expected one: a number by its amount, a text without case or extra spaces."""
    if want is None or got is None:
        return want is None and got is None
    try:
        return Decimal(str(want)) == Decimal(str(got))
    except InvalidOperation:
        return " ".join(str(want).casefold().split()) == " ".join(str(got).casefold().split())


def score(document: Document, got: dict[str, Any]) -> dict[str, Any]:
    """Each scored field right or not; each list: whether its number of rows is right, and each expected row's
    values (by position)."""
    pack = typepack.get(document.pack)
    fields = {f: _same(document.values.get(f), got.get(f)) for f in pack.scored_fields}
    lists = {}
    for name, columns in pack.list_fields.items():
        want, have = document.values.get(name) or [], got.get(name) or []
        cells = [_same(row.get(c), (have[i] if i < len(have) and isinstance(have[i], dict) else {}).get(c))
                 for i, row in enumerate(want) for c in columns]
        lists[name] = {"rows": len(want) == len(have), "cells": cells}
    return {"fields": fields, "lists": lists}


def _marks(s: dict[str, Any]) -> list[bool]:
    return [*s["fields"].values(), *(m for lst in s["lists"].values() for m in (lst["rows"], *lst["cells"]))]


def _flow_reader(*, use_cache: bool, jev: bool) -> Reader:
    def read(document: Document, path: Path) -> dict[str, Any] | None:
        from jav.flows.flow import run_one

        state = run_one(str(path), f"property-{document.id}", "G", use_cache=use_cache, doc_type=document.pack, jev=jev)
        return state.record.to_datapoints(typepack.get(document.pack).record_fields) if state.record is not None else None

    return read


def _flow_recogniser(*, use_cache: bool, jev: bool) -> Recogniser:
    def recognise(path: Path) -> tuple[str | None, str | None]:
        from jav.flows.flow_detect import run_detect

        st = run_detect(str(path), use_cache=use_cache, run_id=f"property-{path.stem}-detect", jev=jev)
        return (st.result.doc_type if st.result else None), (st.detail.key if st.detail else None)

    return recognise


def _fact_same(readings: fact_readings.Readings, fact: str, want: Any, got: Any) -> bool:
    if got is None:
        return False
    d = facts.catalogue(readings.catalogue).facts[fact]
    try:
        return facts.typed_value(fact, d, want) == facts.typed_value(fact, d, got)
    except facts.FactError:
        return False


def _set_facts(doc_set: DocumentSet, got_values: dict[str, dict[str, Any]], readings: fact_readings.Readings) -> dict[str, bool]:
    """Each fact the set records, read from what was read; and whether what was not read and the disagreements are the
    ones it records."""
    read_set = doc_set.model_copy(update={"documents": tuple(d.model_copy(update={"values": got_values[d.id]})
                                                              for d in doc_set.documents)})
    units, unread, conflicts = facts_of(read_set, readings)
    have = {(u["key"], f): v for u in units for f, v in u["facts"].items()}
    marks = {f"{u.key}.{f}": _fact_same(readings, f, v, have.get((u.key, f))) for u in doc_set.units for f, v in u.facts.items()}
    marks["unread"] = [tuple(u) for u in unread] == [tuple(u) for u in doc_set.unread]
    marks["conflicts"] = [tuple(c) for c in conflicts] == [tuple(c) for c in doc_set.conflicts]
    return marks


def measure(options: Any, *, read: Reader | None = None, recognise: Recogniser | None = None, name: str = DATA) -> Any:
    """The golden set's measurement, as `python -m jav.cli measure insurance_application:documents` runs it (231 U-A6:
    `name` another golden file, `insurance_application:allianz_documents`): within the owner's sub-budgets, or earlier
    answers only without one. `read`, `recognise`: stand-ins (the tests)."""
    from jav.core import calls
    from jav.evals import goldens

    limits = {p: Decimal(str(v)) for p, v in (("openai", options.budget_usd), ("jev", options.jev_budget_usd)) if v is not None}
    if not limits:
        print(calls.NO_BUDGET_NOTE)
    docs = load(name)
    readings = fact_readings.load(docs.readings)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    rows: list[dict[str, Any]] = []
    right = scored = answered = 0
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="property-documents-") as tmp, \
            calls.measurement(f"measure-{stamp}-{name.removeprefix('golden_').replace('_', '-')}", limits, reuse=options.use_cache):
        read = read or _flow_reader(use_cache=options.use_cache, jev=options.jev)
        recognise = recognise or _flow_recogniser(use_cache=options.use_cache, jev=options.jev)
        for doc_set in docs.sets:
            got_values: dict[str, dict[str, Any]] = {}
            for document in doc_set.documents:
                path = Path(tmp) / doc_set.id / f"{document.id}.pdf"
                path.parent.mkdir(parents=True, exist_ok=True)
                write_unicode_pdf_pages(path, pages(document, docs.form))
                t0 = time.perf_counter()
                broad, detail = recognise(path)
                got = read(document, path)
                row: dict[str, Any] = {"set": doc_set.id, "document": document.id, "pack": document.pack,
                                       "recognised": [broad, detail], "got": got, "seconds": round(time.perf_counter() - t0, 2)}
                marks = [broad == BROAD, detail == document.pack]
                if got is not None:
                    answered += 1
                    got_values[document.id] = got
                    row["score"] = score(document, got)
                    marks += _marks(row["score"])
                right += sum(marks)
                scored += len(marks)
                if not all(marks):
                    failures.append(f"{document.id}: {len(marks) - sum(marks)} of {len(marks)} wrong")
                rows.append(row)
            if len(got_values) == len(doc_set.documents):  # the set's facts, from what was read
                marks_of_set = _set_facts(doc_set, got_values, readings)
                rows.append({"set": doc_set.id, "facts": marks_of_set})
                right += sum(marks_of_set.values())
                scored += len(marks_of_set)
                failures += [f"{doc_set.id}: {k}" for k, ok in marks_of_set.items() if not ok]
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = RUNS_DIR / f"{stamp}_{name.removeprefix('golden_')}_{options.engine}.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), encoding="utf-8")
    print(f"{docs.key} ({options.engine}): {answered}/{count(name)} read; {right}/{scored} judgements right -> {out}")
    return goldens.Outcome(cases=count(name), answered=answered, right=right, scored=scored, unit="judgements",
                           failures=tuple(failures))
