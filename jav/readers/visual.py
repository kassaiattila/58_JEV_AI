"""PDF words and bounded rasters, produced inside the native reader boundary."""
from __future__ import annotations

import base64
from collections import defaultdict
import hashlib
from io import BytesIO
import json
import math
from typing import TYPE_CHECKING

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfminer.pdftypes import PDFObjectNotFound, PDFStream, resolve1
from pdfminer.psparser import PSLiteral
import pypdfium2 as pdfium

from jav import pdf as pdfmod, source_layer
from .contracts import PdfLocator
from .limits import ReadFailure, limited

if TYPE_CHECKING:
    from .native import Reading

RASTER_DPI = 300


def layer_for(source_sha: str, words: list[list[dict]], sizes: list[tuple[float, float]], *,
              recognised: bool = False, engine: str = "native") -> source_layer.SourceLayer:
    """Reuse the application's word-layer identity without writing its database."""
    layer = source_layer.build(source_sha, words, sizes, text_source="ocr" if recognised else "pdf",
                               engine=engine if recognised else None)
    if layer is not None:
        return layer
    pages = [source_layer.Page(page=i + 1, width_pt=w, height_pt=h) for i, (w, h) in enumerate(sizes)]
    body = json.dumps({"pages": [p.model_dump() for p in pages], "words": []}, sort_keys=True, separators=(",", ":"))
    identity = hashlib.sha256(f"{source_sha}:{body}".encode()).hexdigest()[:24]
    return source_layer.SourceLayer(layer_id=identity, doc_id=source_sha, pages=pages, words=[], text_source="pdf")


def add_layer(reading: Reading, layer: source_layer.SourceLayer) -> None:
    reading.source_layers[layer.layer_id] = layer.model_dump(mode="json")
    groups = defaultdict(list)
    for word in layer.words:
        groups[(word.page, word.line_no)].append(word)
    for (page, _line), words in groups.items():
        reading.add("text", PdfLocator(source_layer_id=layer.layer_id, page=page,
                    word_ids=tuple(w.id for w in words)), text=" ".join(w.text for w in words))


def raster(reading: Reading, picture, *, element_id: str, kind: str, page: int = 1,
           page_size: tuple[float, float] | None = None) -> None:
    """Keep a canonical PNG and its exact source-frame transform in the attempt."""
    pixels = picture.width * picture.height
    limited(reading.raster_pixels + pixels > reading.limits.image_pixels, "Combined raster pixel limit exceeded")
    stream = BytesIO()
    picture.convert("RGB").save(stream, format="PNG")
    data = stream.getvalue()
    limited(sum(r["byte_size"] for r in reading.rasters) + len(data) > reading.limits.expanded_bytes,
            "Combined raster byte limit exceeded")
    reading.raster_pixels += pixels
    reading.rasters.append({"sha256": hashlib.sha256(data).hexdigest(), "byte_size": len(data),
        "data": base64.b64encode(data).decode(), "width": picture.width, "height": picture.height,
        "kind": kind, "page": page, "page_size": page_size, "element_id": element_id})


_ACTIVE_KEYS = frozenset({"JS", "JavaScript", "AA", "XFA"})
# 121 (the owner's decision of 2026-10-07): embedded files are never opened; the visible content is read, partially
_EMBEDDED_KEYS = frozenset({"EmbeddedFiles", "EF"})


def _is_signature(field) -> bool:
    kind = resolve1(field.get("FT")) if isinstance(field, dict) else None
    return isinstance(kind, PSLiteral) and kind.name == "Sig"


def _signature_only(form, bound: int) -> bool:
    """121: an interactive form whose fields are all digital signatures (at least one) fills nothing in and runs
    nothing, so a signed PDF is read. An empty form, any other field kind (also below a signature field) and an XFA
    form are not one; actions are still rejected wherever they stand (`_inert`)."""
    form = resolve1(form)
    if not isinstance(form, dict) or "XFA" in form:
        return False
    fields = resolve1(form.get("Fields"))
    if not isinstance(fields, list) or not fields or not all(_is_signature(resolve1(f)) for f in fields):
        return False
    pending, seen = [resolve1(f) for f in fields], set()
    while pending:
        field = pending.pop()
        if id(field) in seen:  # a field and its widgets may refer to one another
            continue
        seen.add(id(field))
        limited(len(seen) > bound, "PDF form field limit exceeded")
        for kid in resolve1(field.get("Kids")) or []:
            kid = resolve1(kid)
            if not isinstance(kid, dict) or (kid.get("FT") is not None and not _is_signature(kid)):
                return False
            pending.append(kid)
    return True


def _inert(document, bound: int) -> set[str]:
    """Reject active content by parsed names, including escaped names; returns the parts left unread. 121 (the
    owner's decisions of 2026-10-07): a form of digital signatures only is no longer rejected (`_signature_only`); an
    opening view setting (a destination: a page and a zoom) is no action, while an opening action dictionary still
    rejects the file; embedded files are not opened and come back as `embedded_files`."""
    unread: set[str] = set()
    ids = set()
    for xref in document.xrefs:
        ids.update(xref.get_objids())
        limited(len(ids) > bound, "PDF object inventory limit exceeded")
    visited = 0

    def inspect(value, depth=0):
        nonlocal visited
        visited += 1
        limited(depth > 32 or visited > bound * 100, "PDF object structure limit exceeded")
        if isinstance(value, PDFStream):
            value = value.attrs
        if isinstance(value, dict):
            if (set(value) & _ACTIVE_KEYS or ("AcroForm" in value and not _signature_only(value["AcroForm"], bound))
                    or ("OpenAction" in value and not isinstance(resolve1(value["OpenAction"]), list))):
                raise ReadFailure("excluded", "excluded", "Active, embedded or form PDF content needs a separate adapter")
            if set(value) & _EMBEDDED_KEYS:
                unread.add("embedded_files")
            action = value.get("S")
            if isinstance(action, PSLiteral) and action.name in {"JavaScript", "Launch", "SubmitForm", "ImportData", "GoToR"}:
                raise ReadFailure("excluded", "excluded", "External or executable PDF action was excluded")
            for child in value.values():
                inspect(child, depth + 1)
        elif isinstance(value, (list, tuple)):
            for child in value:
                inspect(child, depth + 1)
    for identity in ids:
        try:
            obj = document.getobj(identity)
        except PDFObjectNotFound:  # 121: listed in a cross-reference table but absent (incremental saves); holds nothing
            continue
        inspect(obj)
    return unread


def read_pdf(data: bytes, reading: Reading, *, recognise: bool) -> None:
    pages_words, sizes, visual_pages = [], [], []
    source_sha = hashlib.sha256(data).hexdigest()
    try:
        with pdfplumber.open(BytesIO(data)) as document, pdfium.PdfDocument(data) as geometry:
            if "embedded_files" in _inert(document.doc, reading.limits.archive_entries):
                reading.issue("unread_content", "Embedded files remain unopened in the original PDF")
            limited(len(document.pages) > min(12, reading.limits.archive_entries), "PDF page limit exceeded")
            for index, page in enumerate(document.pages):
                width, height = float(page.width), float(page.height)
                if not all(math.isfinite(x) and x > 0 for x in (width, height)):
                    raise ReadFailure("corrupt", "corrupt", "Invalid PDF page dimensions")
                rendered_page = geometry[index]
                try:
                    render_size = tuple(map(float, rendered_page.get_size()))
                finally:
                    rendered_page.close()
                if not all(math.isfinite(x) and x > 0 for x in render_size):
                    raise ReadFailure("corrupt", "corrupt", "Invalid rendered PDF page dimensions")
                crop = page.cropbox or page.mediabox
                ambiguous = any(not math.isfinite(a) or not math.isfinite(b) or abs(a - b) > 0.01
                                for a, b in zip(crop, page.mediabox, strict=True))
                ambiguous |= any(abs(a - b) > 0.01 for a, b in zip(render_size, (width, height), strict=True))
                if ambiguous:
                    sizes.append(render_size)
                    pages_words.append([])
                    reading.issue("unread_content", f"PDF page {index + 1} has ambiguous crop geometry; its text and OCR were omitted")
                    continue
                sizes.append((width, height))
                words = page.extract_words(x_tolerance=pdfmod.X_TOLERANCE, y_tolerance=pdfmod.Y_TOLERANCE)
                limited(sum(map(len, pages_words)) + len(words) > reading.limits.visited_cells,
                        "PDF word limit exceeded")
                for word in words:
                    word["text"] = pdfmod.normalize_dashes(pdfmod.fix_lost_glyphs(word["text"]))
                    # pdfplumber uses the rotated media box; reject ambiguous crop offsets.
                    word["x0"] -= page.bbox[0]
                    word["x1"] -= page.bbox[0]
                    word["top"] -= page.bbox[1]
                    word["bottom"] -= page.bbox[1]
                    if (not all(math.isfinite(word[key]) for key in ("x0", "x1", "top", "bottom"))
                            or not 0 <= word["x0"] < word["x1"] <= width
                            or not 0 <= word["top"] < word["bottom"] <= height):
                        raise ReadFailure("corrupt", "corrupt", "PDF word geometry falls outside its page")
                pages_words.append(words)
                if not words or page.images:
                    visual_pages.append(index)
                # 121: presence only; resolving every annotation (pdfplumber `page.annots`) recursed without end on
                # the cycles of signature widgets and rejected valid signed PDFs as corrupt
                if resolve1(page.page_obj.attrs.get("Annots")):
                    reading.issue("unread_content", f"Page {index + 1} annotations remain in the original PDF")
    except PDFPasswordIncorrect as exc:
        raise ReadFailure("password_required", "password_required", "PDF requires a password") from exc
    pdfmod.build_layout(pages_words)
    layer = layer_for(source_sha, pages_words, sizes)
    add_layer(reading, layer)
    rendering = pdfium.PdfDocument(data) if recognise and visual_pages else None
    try:
        for index in visual_pages:
            identity = reading.add("text", PdfLocator(source_layer_id=layer.layer_id, page=index + 1),
                                   text="", availability="unreadable")
            reading.issue("needs_ocr", "PDF visual content requires recognition; native words remain separate", identity)
            if rendering is None:
                continue
            page = rendering[index]
            try:
                width, height = sizes[index]
                render_size = page.get_size()
                if any(abs(a - b) > 0.01 for a, b in zip(render_size, (width, height), strict=True)):
                    reading.issue("unread_content", "PDF crop and media boxes disagree; OCR mapping was not guessed", identity)
                    continue
                scale = RASTER_DPI / 72
                limited(reading.raster_pixels + math.ceil(width * scale) * math.ceil(height * scale)
                        > reading.limits.image_pixels, "PDF raster pixel limit exceeded")
                bitmap = page.render(scale=scale, may_draw_forms=False)
                try:
                    picture = bitmap.to_pil()
                    try:
                        raster(reading, picture, element_id=identity, kind="pdf", page=index + 1,
                               page_size=(width, height))
                    finally:
                        picture.close()
                finally:
                    bitmap.close()
            finally:
                page.close()
    finally:
        if rendering is not None:
            rendering.close()


def verify_layers(raw: dict, source_sha: str) -> None:
    """Validate saved PDF references without parsing the original a second time."""
    layers = {}
    for identity, payload in raw.get("source_layers", {}).items():
        layer = source_layer.SourceLayer.model_validate(payload)
        body = json.dumps({"pages": [p.model_dump() for p in layer.pages],
                           "words": [w.model_dump() for w in layer.words]}, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(f"{source_sha}:{body}".encode()).hexdigest()[:24]
        if identity != layer.layer_id or identity != expected or layer.doc_id != source_sha:
            raise ValueError("PDF word layer is not bound to its frozen source")
        if [p.page for p in layer.pages] != list(range(1, len(layer.pages) + 1)):
            raise ValueError("PDF page inventory is not sequential")
        if any(not all(math.isfinite(v) and v > 0 for v in (p.width_pt, p.height_pt)) for p in layer.pages):
            raise ValueError("Invalid saved PDF page geometry")
        if [w.id for w in layer.words] != list(range(len(layer.words))):
            raise ValueError("PDF word identities are not sequential")
        for word in layer.words:
            if (not 1 <= word.page <= len(layer.pages)
                    or not all(math.isfinite(v) for v in (word.x0, word.x1, word.y0, word.y1))
                    or not 0 <= word.x0 < word.x1 <= 1 or not 0 <= word.y0 < word.y1 <= 1):
                raise ValueError("Invalid saved PDF word geometry")
        layers[identity] = layer
    for element in raw["elements"]:
        locator = element["locator"]
        if locator["kind"] != "pdf":
            continue
        layer = layers.get(locator["source_layer_id"])
        if layer is None or not 1 <= locator["page"] <= len(layer.pages):
            raise ValueError("PDF locator names an absent frozen page")
        ids = locator["word_ids"]
        if len(set(ids)) != len(ids) or any(i >= len(layer.words) or i < 0 for i in ids):
            raise ValueError("PDF locator names invalid words")
        words = [layer.words[i] for i in ids]
        if any(w.page != locator["page"] for w in words) or " ".join(w.text for w in words) != (element.get("text") or ""):
            raise ValueError("PDF text differs from its referenced words")
