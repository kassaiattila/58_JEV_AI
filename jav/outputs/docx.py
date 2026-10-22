"""An own Word template: its check at upload and its filling with an output's data (196, plan F-Word-output W1).

Plain-language summary (DECISIONS 196): a Word template works like an Excel one (`jav/outputs/fill.py`). The person's
document keeps its look - letterhead, fonts, a logo, tables - and the system writes the data into the same markers
(`jav/outputs/markers.py`). A table row holding a table's markers is repeated once per row of the table, with that
row's formatting; so is a paragraph outside a table (a list). Without rows it goes. A value, a total or a count is
written where its marker stands: in the body, the headers and footers, the text boxes and the notes. The text before
and after a marker keeps its own formatting; the value takes the formatting of the marker's first character. Every
value is written as text formatted by code, never by Word: money and numbers with a non-breaking space between
thousands and a decimal comma, a date as 2026. 10. 22.; with the output's `language` value `en`, 1,234.50 and
22 October 2026. A line break in a value is a line break in the document. What a value contains is never read as a
marker.

The check refuses a template that would not fill safely or correctly:
- not a Word document (.docx), or too large;
- macros, embedded objects or programs (the package check of `jav/readers/limits.py`), or another file's content
  imported (`altChunk`);
- a link to another file: an external relationship other than a web link or the attached template;
- a field that computes or imports: only the fields of `configs/outputs.json` `templates.word_fields` stay (page
  numbers, dates, web links, references), as an Excel template holds no formula (the owner's decision of 2026-10-19);
- a marker the output does not have, two tables' markers in one row, a value marker in a table's row, the months (an
  Excel layout), a vertically merged cell in a table's row, a repeated row inside another, or no marker at all.

The attached template (the path of the .dotx the document was made from) is a warning: it is removed when the template
is filled, so an output names no file of the person's machine.

Ported from the legacy project (`10_AIFLOW_V4/sidecar/app/render/docx_render.py`: the row cloned per element, the
markers found across Word's runs, the unfilled markers), with three changes: every story part, not only the body;
only the runs a marker spans are joined; and the package's XML is changed directly, so what the filler does not touch
stays as it was.

Layer: adapter (file format), called by `jav/outputs/templates.py`.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable, Iterator
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from jav.outputs import contract, markers
from jav.outputs.fill import ISO_DATE, Lookup, TemplateCheck, TemplateError, as_decimal

MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DOCUMENT = "word/document.xml"
SETTINGS = "word/settings.xml"
SETTINGS_RELS = "word/_rels/settings.xml.rels"
# the parts that hold a document's text: the body, the headers and footers, the notes (text boxes are inside them)
STORY = re.compile(r"^word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")
# jav/readers/limits.py raises this after every member of the package passed its checks; a Word template's web links
# and attached template are then judged here (the readers' rule for documents read as input stays as it is)
EXTERNAL_REFUSAL = "External Office relationship is not followed"
INERT = ("hyperlink",)  # an external relationship that stays: a web link a person may click
DROPPED = ("attachedTemplate",)  # an external relationship removed when the template is filled
NOT_XML = re.compile("[^\t\n\r\x20-퟿-�\U00010000-\U0010ffff]")
NBSP = " "
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December")


def _w(tag: str) -> str:
    return f"{{{W}}}{tag}"


P, T, TR, TC, TBL, BR = _w("p"), _w("t"), _w("tr"), _w("tc"), _w("tbl"), _w("br")
# the containers a paragraph of which must stay (Word refuses an empty table cell, text box or note)
KEEP_A_PARAGRAPH = (TC, _w("txbxContent"), _w("footnote"), _w("endnote"), _w("hdr"), _w("ftr"))


# --- the XML --------------------------------------------------------------------------------------------------------


def _parse(data: bytes) -> Any:
    from lxml import etree

    # the package check parsed every part without a DTD or entities first; this parser never loads either
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False)
    return etree.fromstring(data, parser)


def _serialise(root: Any) -> bytes:
    from lxml import etree

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _owner(node: Any, tags: tuple[str, ...]) -> Any:
    """The nearest ancestor of `node` with one of `tags`, None without one (an lxml element is never tested for truth:
    an element without children is false)."""
    parent = node.getparent()
    while parent is not None and parent.tag not in tags:
        parent = parent.getparent()
    return parent


def _texts(p: Any) -> list[Any]:
    """The paragraph's own text nodes in order (not those of a paragraph inside it, such as a text box's)."""
    return [t for t in p.iter(T) if _owner(t, (P,)) is p]


def _text(p: Any) -> str:
    return "".join(t.text or "" for t in _texts(p))


@dataclass
class _Para:
    """A paragraph holding markers: its element, its text, its markers, and the row or paragraph repeated with a table's
    rows that it belongs to (None: its markers are written once)."""

    p: Any
    text: str
    found: list[markers.Marker]
    unit: Any = None


@dataclass
class _Story:
    """A story part's paragraphs with markers, and its repeated rows and paragraphs: element -> the table's name."""

    paras: list[_Para] = field(default_factory=list)
    units: dict[Any, str] = field(default_factory=dict)


def _problem(check: TemplateCheck | None, code: str, where: str, detail: str = "") -> None:
    if check is None:
        raise TemplateError(f"{where}: {code} {detail}".strip())
    check.add(code, where, detail)


def _story(root: Any, output: str, where: str, check: TemplateCheck | None) -> _Story:
    """The part's paragraphs with markers and its repeated units; with `check` the problems are recorded there,
    without it a problem raises TemplateError."""
    story = _Story()
    for p in root.iter(P):
        text = _text(p)
        if "{{" not in text:
            continue
        found, problems = markers.find(output, text)
        for problem in problems:
            _problem(check, "unknown_marker", where, problem)
        story.paras.append(_Para(p, text, found))
    for para in story.paras:
        for m in para.found:
            if not m.in_row:
                continue
            row = _owner(para.p, (TR,))
            unit = row if row is not None else para.p
            if story.units.get(unit, m.name) != m.name:
                _problem(check, "row_mixes_tables", where, f"{story.units[unit]}, {m.name}")
            story.units.setdefault(unit, m.name)
    for para in story.paras:
        row = _owner(para.p, (TR,))
        para.unit = row if row is not None and row in story.units else para.p if para.p in story.units else None
    return story


def _fields(root: Any) -> Iterator[str]:
    """The instruction of every field of the part: a simple one, or one written across runs (nested ones too)."""
    for f in root.iter(_w("fldSimple")):
        yield f.get(_w("instr"), "")
    stack: list[list[str] | None] = []
    for el in root.iter(_w("fldChar"), _w("instrText")):
        if el.tag == _w("instrText"):
            if stack and stack[-1] is not None:
                stack[-1].append(el.text or "")
            continue
        kind = el.get(_w("fldCharType"))
        if kind == "begin":
            stack.append([])
        elif kind == "separate" and stack and stack[-1] is not None:
            yield "".join(stack[-1])
            stack[-1] = None
        elif kind == "end" and stack:
            done = stack.pop()
            if done is not None:
                yield "".join(done)


def field_name(instruction: str) -> str:
    """A field's name: its first word in capitals; `=` for a calculation."""
    text = instruction.strip()
    if text.startswith("="):
        return "="
    return text.split(None, 1)[0].upper() if text else ""


# --- the check ------------------------------------------------------------------------------------------------------


def _members(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {i.filename: z.read(i) for i in z.infolist()}


def _package(data: bytes, check: TemplateCheck) -> dict[str, bytes] | None:
    """The file's parts when it is a Word document without active content or links to other files (a web link and
    the attached template stay); None when it is refused."""
    from jav.readers.limits import DEFAULT_LIMITS, ReadFailure, inspect_package, xml

    if len(data) > contract.templates()["max_bytes"]:
        check.add("too_large", detail=str(len(data)))
        return None
    if not zipfile.is_zipfile(io.BytesIO(data)):
        check.add("not_docx")
        return None
    try:
        parts = inspect_package(data, DEFAULT_LIMITS)
    except ReadFailure as e:
        if str(e) != EXTERNAL_REFUSAL:
            check.add("unsafe_content" if e.status == "excluded" else "too_large" if e.status == "resource_limited"
                      else "unreadable", detail=str(e))
            return None
        parts = _members(data)  # every member passed the package check before its external links were looked at
    except Exception as e:  # noqa: BLE001 - a DTD, an entity or broken XML: the file's failure, recorded, never swallowed
        check.add("unreadable", detail=type(e).__name__)
        return None
    if DOCUMENT not in parts:
        check.add("not_docx")
        return None
    if b"macroenabled" in parts.get("[Content_Types].xml", b"").lower():
        check.add("unsafe_content", detail="macro-enabled document")
    for name, content in parts.items():
        if not name.endswith(".rels"):
            continue
        for rel in xml(content).iter():
            if rel.attrib.get("TargetMode", "").lower() != "external":
                continue
            kind = rel.attrib.get("Type", "").rsplit("/", 1)[-1]
            if kind in DROPPED:
                check.add("attached_template", name, warning=True)
            elif kind not in INERT:
                check.add("external_link", name, kind)
    return parts if check.ok else None


def _story_names(parts: dict[str, bytes]) -> list[str]:
    """The story parts, the body first."""
    return sorted((n for n in parts if STORY.match(n)), key=lambda n: (n != DOCUMENT, n))


def _check_story(root: Any, output: str, where: str, check: TemplateCheck) -> None:
    allowed = set(contract.templates()["word_fields"])
    for instruction in _fields(root):
        name = field_name(instruction)
        if name not in allowed:
            check.add("field", where, name or instruction.strip()[:40])
    if next(root.iter(_w("altChunk")), None) is not None:
        check.add("unsafe_content", where, "altChunk")
    story = _story(root, output, where, check)
    for unit in story.units:
        if unit.tag != TR:
            continue
        if any(a in story.units for a in unit.iterancestors(TR)):
            check.add("nested_rows", where, story.units[unit])
        if next(unit.iter(_w("vMerge")), None) is not None:
            check.add("merged_row", where, story.units[unit])
    for para in story.paras:
        for m in para.found:
            if m.kind in ("months", "month_names"):
                check.add("months_in_word", where, m.text)
            elif para.unit is not None and not m.in_row:
                check.add("value_in_row", where, m.text)
            if m.kind == "value" and m.name not in check.values:
                check.values.append(m.name)
            elif m.kind != "value":
                cols = check.tables.setdefault(m.name, [])
                if m.column and m.column not in cols:
                    cols.append(m.column)


def check(output: str, data: bytes) -> TemplateCheck:
    """The check of a Word document as a template of the output (`TemplateCheck.ok`: it can be stored)."""
    result = TemplateCheck(output)
    contract.spec(output)
    parts = _package(data, result)
    if parts is None:
        return result
    for name in _story_names(parts):
        try:
            root = _parse(parts[name])
        except Exception as e:  # noqa: BLE001 - the reading library's failure is the file's: recorded, never swallowed
            result.add("unreadable", name, type(e).__name__)
            continue
        _check_story(root, output, name, result)
    if result.ok and not result.values and not result.tables:
        result.add("no_marker")
    return result


# --- the filling ----------------------------------------------------------------------------------------------------


def _number(n: Decimal, *, money: bool, english: bool) -> str:
    """A number as a document shows it: a whole number without decimals, money otherwise with two, any other number
    with the digits it has."""
    if n == n.to_integral_value():
        text = f"{int(n):,}"
    elif money:
        text = f"{n:,.2f}"
    else:
        text = f"{n.normalize():,f}"
    return text if english else text.replace(",", NBSP).replace(".", ",")


def shown(value: Any, kind: str, language: str = "hu") -> str:
    """A value as the document's text, by its kind and the output's language (`en`: English; anything else: Hungarian)."""
    if value is None:
        return ""
    english = language == "en"
    if kind in ("money", "number", "count") and (n := as_decimal(value)) is not None:
        return _number(n, money=kind == "money", english=english)
    if kind == "date" and isinstance(value, str) and ISO_DATE.match(value):
        d = date.fromisoformat(value)
        return f"{d.day} {MONTHS_EN[d.month - 1]} {d.year}" if english else f"{d.year}. {d.month:02d}. {d.day:02d}."
    return str(value)


def _set(node: Any, text: str) -> None:
    """A text node's new text; each line break becomes a break of its run."""
    lines = text.split("\n")
    node.text = lines[0]
    node.set(XML_SPACE, "preserve")
    anchor = node
    for line in lines[1:]:
        br = node.makeelement(BR, {})
        anchor.addnext(br)
        t = node.makeelement(T, {XML_SPACE: "preserve"})
        t.text = line
        br.addnext(t)
        anchor = t


def _replace(p: Any, found: list[markers.Marker], value_of: Callable[[markers.Marker], str]) -> None:
    """The paragraph's markers replaced, each where it stands. Only the text nodes a marker spans change: the value
    goes into the node of its first character, the rest of the marker is cut from the others, and what stands around
    it keeps its formatting. The markers are found once, in the template's text, so a value is never read again."""
    by_text = {m.text: m for m in found}
    nodes = _texts(p)
    texts = [n.text or "" for n in nodes]
    starts, pos = [], 0
    for t in texts:
        starts.append(pos)
        pos += len(t)
    ends = [s + len(t) for s, t in zip(starts, texts, strict=True)]

    def node_at(offset: int) -> int:
        return next(k for k in range(len(nodes)) if starts[k] <= offset < ends[k])

    touched: set[int] = set()
    for match in reversed(list(markers.ANY.finditer("".join(texts)))):  # from the end: an earlier offset stays valid
        m = by_text.get(match.group(0))
        if m is None:
            continue
        a, b = match.span()
        first, last = node_at(a), node_at(b - 1)
        value = NOT_XML.sub("", value_of(m))
        head = texts[first][: a - starts[first]]
        if first == last:
            texts[first] = head + value + texts[first][b - starts[first]:]
        else:
            texts[first] = head + value
            for k in range(first + 1, last):
                texts[k] = ""
            texts[last] = texts[last][b - starts[last]:]
        touched.update(range(first, last + 1))
    for k in sorted(touched):
        _set(nodes[k], texts[k])


def _cell(t: contract.Table | None, m: markers.Marker, row: Any) -> Any:
    if t is None:
        return None
    i = t.columns.index(m.column) if m.column in t.columns else len(row)  # a list column no row of it has
    return row[i] if i < len(row) else None


def _remove(unit: Any) -> None:
    """Removes a repeated row or paragraph; a table left without rows goes too, and an emptied cell, text box, note,
    header or footer keeps an empty paragraph."""
    parent = unit.getparent()
    parent.remove(unit)
    if parent.tag == TBL and parent.find(TR) is None:
        _remove(parent)
    elif parent.tag in KEEP_A_PARAGRAPH and parent.find(P) is None:
        parent.append(parent.makeelement(P, {}))


def _fill_story(root: Any, d: Lookup, language: str) -> Any:
    story = _story(root, d.output, "", None)
    for para in story.paras:  # first the values: a repeated unit's copies hold a row's values only
        if para.unit is None:
            _replace(para.p, para.found, lambda m: shown(d.single(m), d.kind(m), language))
    for unit, name in story.units.items():
        t = d.table(name)
        members = [para for para in story.paras if para.unit is unit]
        index = {p: k for k, p in enumerate(unit.iter(P))}
        for row in (t.rows if t else ()):
            clone = deepcopy(unit)
            copies = list(clone.iter(P))
            for para in members:
                _replace(copies[index[para.p]], para.found,
                         lambda m, row=row: shown(_cell(t, m, row), d.kind(m), language))
            unit.addprevious(clone)
        _remove(unit)
    return root


def _without_attached_template(rels: bytes, settings: bytes | None) -> tuple[bytes, bytes | None]:
    """The settings' relationships without the attached template's, and the settings without its reference."""
    root = _parse(rels)
    dropped = set()
    for rel in list(root):
        if rel.get("TargetMode", "").lower() == "external" and rel.get("Type", "").rsplit("/", 1)[-1] in DROPPED:
            dropped.add(rel.get("Id"))
            root.remove(rel)
    if not dropped or settings is None:
        return _serialise(root), settings
    s = _parse(settings)
    for el in list(s.iter(_w("attachedTemplate"))):
        if el.get(f"{{{R}}}id") in dropped:
            el.getparent().remove(el)
    return _serialise(root), _serialise(s)


def fill(data: contract.OutputData, template: bytes) -> bytes:
    """The output's Word document from the template. TemplateError when the template does not fill (checked when
    stored); `contract.ContractError` when the data disagrees with the contract."""
    contract.check(data)
    d = Lookup.of(data)
    language = str(d.values.get("language") or "hu")
    parts = _members(template)
    if DOCUMENT not in parts:
        raise TemplateError("not a Word document")
    changed = {name: _serialise(_fill_story(_parse(parts[name]), d, language)) for name in _story_names(parts)}
    if SETTINGS_RELS in parts:
        changed[SETTINGS_RELS], settings = _without_attached_template(parts[SETTINGS_RELS], parts.get(SETTINGS))
        if settings is not None:
            changed[SETTINGS] = settings
    buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(template)) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info, changed.get(info.filename, zin.read(info)))
    return buf.getvalue()


__all__ = ["MEDIA", "check", "field_name", "fill", "shown"]
