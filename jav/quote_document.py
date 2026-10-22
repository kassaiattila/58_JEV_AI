"""The approved quote as a Word document (196, plan F-Word-output W2, DECISIONS 196).

Plain-language summary: the owner asked that an approved quote becomes a Word document, from a built-in template in
Hungarian or English or from a template of their own. The quote's data - its heading, its lines priced by code, its
totals - is built here as the output contract's `quote` (`configs/outputs.json`), and laid out by the output layer:
the package's chosen own Word template, or the built-in one (`configs/quote_documents.json`), filled the same way
(`jav/outputs/docx.py`). No number is computed here: every amount is the approved quote's, priced by
`jav/quote_pricing.py`. The approval stores the document with its version (`package_release.store_own_files`), so the
download of a version never changes; a reopened version keeps the document it was approved with. The draft can be
downloaded too, marked as a draft.

The quote's language (hu or en) chooses the built-in template and how numbers and dates are written. It is estimated
by code from the request's subject and requested items (`language_of`) and a person changes it on the quote's page.

- `language_of(texts)`, `languages()`;
- `data(content, package, ...)`: the output's data; `builtin_template(data)`: the built-in template for it;
- `file_name(content, package, version)`;
- `store(c, wp_id, n, content, package, actor, approved_at)`: at the approval, in its transaction;
- `version_file(wp_id, n)`, `draft_file(wp_id, view)`: a version's stored document, the draft's document.

Layer: business module of the quotes domain over the output layer and the version store.
"""

from __future__ import annotations

import io
import re
import sqlite3
from typing import Any

from jav import cfg, naming, package_release
from jav.clock import utc_stamp as _now
from jav.outputs import builtin, contract, templates

OUTPUT = "quote"
TABLE = "lines"
HEADER = ("customer_name", "customer_tax_number", "contact_name", "contact_email", "contact_phone", "deadline", "reference")
COLUMNS = ("position", "sku", "name", "quantity", "unit", "list_price", "unit_price", "discount_percent", "net")
NUMERIC = ("quantity", "unit_price", "discount_percent", "net", "list_price")  # right-aligned in the built-in table
HUNGARIAN_LETTERS = re.compile("[áéíóöőúüű]")
WORD = re.compile(r"[^\W\d_]+")


class QuoteDocumentError(ValueError):
    """The quote cannot be made a document yet (a line it cannot price)."""


def settings() -> dict[str, Any]:
    return cfg.load("quote_documents")


def languages() -> tuple[str, ...]:
    return tuple(settings()["language"]["languages"])


def default_language() -> str:
    return settings()["language"]["default"]


def language_of(texts: list[str]) -> str:
    """The language of a request's texts, by code: Hungarian accented letters and listed Hungarian words against the
    listed English words; English only with a higher score, so nothing to go by is the default."""
    lang = settings()["language"]
    text = " ".join(t for t in texts if t).lower()
    words = WORD.findall(text)
    hu = len(HUNGARIAN_LETTERS.findall(text)) + sum(w in set(lang["hints"]["hu"]) for w in words)
    en = sum(w in set(lang["hints"]["en"]) for w in words)
    return "en" if en > hu else lang["default"]


def request_texts(req: Any) -> list[str]:
    """The texts of a request the language is estimated from: its subject and its requested items' descriptions."""
    if req is None:
        return []
    return [req.title or "", *(str(i.get("description") or "") for i in req.items)]


def _texts(language: str) -> dict[str, Any]:
    quote = settings()["quote"]
    return quote[language if language in quote else default_language()]


def _language(content: dict[str, Any]) -> str:
    language = content.get("language")
    return language if language in languages() else default_language()


# --- the data ---------------------------------------------------------------------------------------------------------


def data(content: dict[str, Any], *, package: str, version: int | None = None, approved_by: str | None = None,
         approved_at: str | None = None) -> contract.OutputData:
    """The quote's output data from its approved content (or a draft's priced content, `version` None: marked a draft).
    `QuoteDocumentError` when a line or the totals are not priced."""
    totals = content.get("totals")
    if not totals or any("net" not in line for line in content["lines"]):
        raise QuoteDocumentError("the quote has a line that is not priced yet")
    language = _language(content)
    header = content.get("header") or {}
    prices = content.get("price_list") or {}
    values: dict[str, Any] = {
        "package": package, "version": version, "state": None if version else _texts(language)["draft"],
        "language": language, "quote_date": (approved_at or _now())[:10], "approved_by": approved_by,
        **{f: header.get(f) for f in HEADER}, "note": header.get("note"),
        "request_title": (content.get("request") or {}).get("title"),
        "price_list": f"{prices.get('name')} ({prices.get('version')})" if prices else None,
        "currency": content.get("currency"), "vat_percent": content.get("vat_percent"),
        "net_total": totals["net"], "vat_total": totals["vat"], "gross_total": totals["gross"]}
    labels = _value_labels()
    rows = [[n, line.get("sku"), line.get("name"), line.get("quantity"), line.get("unit"), line.get("list_price"),
             line.get("unit_price"), line.get("discount_percent"), line.get("net")]
            for n, line in enumerate(content["lines"], start=1)]
    spec = contract.spec(OUTPUT)["tables"][TABLE]["columns"]
    heads = _heads()
    table = contract.table(TABLE, TABLE, COLUMNS, tuple(heads[c] for c in COLUMNS), rows, tuple(spec[c] for c in COLUMNS))
    return contract.OutputData(OUTPUT, tuple(contract.Value(k, labels.get(k, k), v) for k, v in values.items()), (table,))


def _value_labels() -> dict[str, str]:
    return dict(settings()["labels"])


def _heads() -> dict[str, str]:
    """The Hungarian headers of the table's columns: the built-in table's, and the list price's."""
    return {**settings()["quote"]["hu"]["heads"], "list_price": settings()["labels"]["list_price"]}


def sample_heads() -> dict[str, dict[str, str]]:
    """The headers of the output's table, for a template's marker list and preview."""
    return {TABLE: _heads()}


def sample_values() -> dict[str, str]:
    return {k: v for k, v in _value_labels().items() if k in contract.spec(OUTPUT)["values"]}


def file_name(content: dict[str, Any], *, package: str, version: int | None) -> str:
    texts = _texts(_language(content))
    slug = naming.safe_part(package, limit=40) or "quote"
    return f"{texts['file']}-{slug}-{f'v{version}' if version else texts['draft'].lower()}.docx"


# --- the built-in template --------------------------------------------------------------------------------------------


def _page_field(paragraph: Any, around: list[str]) -> None:
    """The page number field with its text before and after (`1. oldal`, `Page 1`)."""
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    paragraph.add_run(around[0])
    paragraph._p.append(parse_xml(f'<w:fldSimple {nsdecls("w")} w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple>'))
    paragraph.add_run(around[1])


def _line(doc: Any, label: str, marker: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = 0
    p.add_run(f"{label}: ").bold = True
    p.add_run(marker)


def builtin_template(d: contract.OutputData) -> bytes:
    """The built-in Word template for the quote's data, in its language: a heading line is left out when its value is
    empty, so the template depends on the data; it is filled like an own template."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt

    values = {v.key: v.value for v in d.values}
    tx = _texts(str(values.get("language") or ""))
    has = {k for k, v in values.items() if v not in (None, "")}
    layout = settings()["quote"]
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(layout["page"]["width_cm"]), Cm(layout["page"]["height_cm"])
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Cm(layout["page"]["margin_cm"]))
    doc.add_heading(tx["title"] + (" – {{state}}" if "state" in has else ""), level=1)
    for label, key in ((tx["date"], "quote_date"), (tx["reference"], "reference")):
        if key in has:
            _line(doc, label, "{{" + key + "}}")
    doc.add_paragraph()
    if "customer_name" in has:
        _line(doc, tx["customer"], "{{customer_name}}")
    for label, key in ((tx["tax_number"], "customer_tax_number"), (tx["contact"], "contact_name"),
                       (tx["email"], "contact_email"), (tx["phone"], "contact_phone"), (tx["deadline"], "deadline")):
        if key in has:
            _line(doc, label, "{{" + key + "}}")
    doc.add_paragraph()
    columns = layout["columns"]
    table = doc.add_table(rows=2, cols=len(columns))
    table.style = "Table Grid"
    table.autofit = False
    for k, column in enumerate(columns):
        head, cell = table.rows[0].cells[k], table.rows[1].cells[k]
        table.columns[k].width = head.width = cell.width = Cm(layout["widths_cm"][column])
        head.text = tx["heads"][column]
        head.paragraphs[0].runs[0].bold = True
        cell.text = "{{" + f"{TABLE}.{column}" + "}}"
        for c in (head, cell):
            c.paragraphs[0].runs[0].font.size = Pt(9)
            if column in NUMERIC:
                c.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
    doc.add_paragraph()
    for key, bold in (("net_total", False), ("vat_total", False), ("gross_total", True)):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        p.paragraph_format.space_after = 0
        p.add_run(f"{tx[key]}: ").bold = bold
        p.add_run("{{" + key + "}} {{currency}}").bold = bold
    if "note" in has:
        doc.add_paragraph()
        _line(doc, tx["note"], "{{note}}")
    footer = section.footer.paragraphs[0]
    footer.text = "{{package}}" + (" · " + tx["version"] if "version" in has else "") + " · "
    _page_field(footer, tx["page"])
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# --- the stored document ----------------------------------------------------------------------------------------------


def store(c: sqlite3.Connection, wp_id: str, n: int, content: dict[str, Any], *, package: str, actor: str) -> None:
    """At the approval, in its write transaction: the version's document made with the package's chosen template (the
    built-in one without a choice), stored with the version and the template that made it."""
    approved_at = package_release.own_version(wp_id, n, c)["approved_at"]
    d = data(content, package=package, version=n, approved_by=actor, approved_at=approved_at)
    file, made = templates.render(d, wp_id, c)
    package_release.store_own_files(c, wp_id, n, package_release.APPROVED,
                                    [(file_name(content, package=package, version=n), len(content["lines"]), file, made)])


def version_file(wp_id: str, n: int, *, package: str) -> tuple[bytes, str]:
    """An approved version's document as it was stored when approved; a version approved before 196 is made now with
    the built-in template (KeyError: no such version)."""
    stored = package_release.own_file(wp_id, n, package_release.APPROVED)
    if stored is not None:
        return stored["content"], stored["name"]
    v = package_release.own_version(wp_id, n)
    content = v["content"]
    d = data(content, package=package, version=n, approved_by=v["approved_by"], approved_at=v["approved_at"])
    return builtin.render(d), file_name(content, package=package, version=n)


def draft_file(wp_id: str, content: dict[str, Any], *, package: str) -> tuple[bytes, str]:
    """The draft's document, marked as a draft, with the package's chosen template. `QuoteDocumentError` while a line
    is not priced."""
    file, _made = templates.render(data(content, package=package), wp_id)
    return file, file_name(content, package=package, version=None)


__all__ = ["COLUMNS", "OUTPUT", "QuoteDocumentError", "builtin_template", "data", "default_language", "draft_file",
           "file_name", "language_of", "languages", "request_texts", "sample_heads", "sample_values", "settings", "store",
           "version_file"]
