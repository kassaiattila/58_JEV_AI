"""The invented insurance application documents and the facts they hold (231, stage D, D-e2).

Plain-language summary: about twenty invented documents of businesses asking for property insurance - quote request
forms, a property schedule per site, claims history statements, with incomplete and faulty ones among them - kept as
data (`configs/golden_property_documents.json`). Each document is kept as what a correct reading of it gives (the type
pack's values); its printed page is made from those values here, in the layout the document names, so what is
expected is always what is printed. Each set of documents names the facts they hold (the units, what cannot be read,
the facts two documents disagree on), and the five sets of the invented product set's reference cases hold that case's
facts: the documents are read into the same facts the rules were measured on.

- `load()`, `PropertyDocuments`: the documents, by set.
- `pages(document)`: its printed lines, page by page; `write_pdfs(folder)`: every document as a PDF.
- `facts_of(document_set, readings)`: the units, the values not read and the disagreements its documents give.

Layer: measurement (it reads the shared readings and the product set); every name and number is invented.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from jav.app import fact_readings, facts
from jav.core import cfg
from jav.documents.synthetic_pdf import write_unicode_pdf_pages

__all__ = ["DATA", "Document", "DocumentSet", "PropertyDocuments", "facts_of", "load", "pages", "write_pdfs"]

DATA = "golden_property_documents"
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


class PropertyDocuments(_Model):
    sets: tuple[DocumentSet, ...]


def load() -> PropertyDocuments:
    return PropertyDocuments.model_validate({k: v for k, v in cfg.load(DATA).items() if k != "meta"})


# --- the printed page --------------------------------------------------------------------------------------------------


def _day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.year}. {_MONTHS[d.month - 1]} {d.day}."


def _amount(text: str) -> str:
    return f"{int(Decimal(text)):,}".replace(",", " ") + " Ft"


def _line(label: str, value: Any, fmt: Any = str) -> list[str]:
    return [] if value is None else [f"{label}: {fmt(value)}"]


def _request(v: dict[str, Any]) -> list[list[str]]:
    wanted = {row["cover"] for row in v.get("requested_covers") or []}
    lines = ["BIZTOSÍTÁSI AJÁNLATKÉRŐ LAP", "Vállalkozói vagyonbiztosítás",
             *_line("Szerződő", v.get("policyholder_name")), *_line("Adószám", v.get("policyholder_tax_number")),
             *_line("Fő tevékenység (TEÁOR)", v.get("activity_code"))]
    if v.get("contact_name"):
        lines.append(f"Kapcsolattartó: {v['contact_name']}" + (f", {v['contact_email']}" if v.get("contact_email") else ""))
    lines += [*_line("Kockázatviselés kezdete", v.get("cover_start"), _day), *_line("Díjfizetés", v.get("payment_frequency")),
              "Kért fedezetek:", *[f"[{'X' if c in wanted else ' '}] {c}" for c in _COVERS],
              *_line("Üzemszüneti elszámolás módja", v.get("accounting_method")),
              *_line("Üzemszüneti biztosítási összeg", v.get("interruption_sum_insured"), _amount),
              "Telephelyek:", "Sorszám   Cím   Ország",
              *["   ".join(str(s.get(c) or "") for c in ("site_no", "address", "country")) for s in v.get("sites") or []]]
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


def pages(document: Document) -> list[list[str]]:
    """The document's printed lines, page by page, made from its values in its layout (Hungarian: document text)."""
    if document.pack == "insurance_request":
        return _request(document.values)
    if document.pack == "property_schedule":
        return _schedule(document.values, document.layout)
    if document.pack == "claims_history":
        return _statement(document.values)
    raise ValueError(f"no page layout for {document.pack}")


def write_pdfs(folder: Path) -> list[Path]:
    """Every document as a PDF in `folder` (`<set>/<document>.pdf`), as the measurement reads them."""
    out = []
    for doc_set in load().sets:
        for document in doc_set.documents:
            path = folder / doc_set.id / f"{document.id}.pdf"
            path.parent.mkdir(parents=True, exist_ok=True)
            out.append(write_unicode_pdf_pages(path, pages(document)))
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
