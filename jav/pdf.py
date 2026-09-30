"""Reading the PDF text layer (pdfplumber) and the shared line / cell builder that OCR (`jav/ocr.py`) uses too.

A PDF without text -> `has_text_layer=False`; OCR is not called here but in a separate flow step (`ocr_pdf`), so
that it shows in the contract and the decision (whether to go to OCR) is data. `read_document()` does both
(for evals and the CLI).

Why word-level reconstruction and not `extract_text(layout=True)`:
- in Számlázz.hu PDFs the layout mode glues words together ("BestIxComKft.", "Fizetésimód:"),
  whereas `extract_words(x_tolerance=1.5)` splits them correctly;
- in two-column (seller | buyer) headers the lines must be split into cells (a wide horizontal gap = column
  boundary), so that multi-line names can be joined vertically, column by column.

The same line and cell building runs on the OCR word boxes (converted to points), so the shape seen by the
candidate finders and the JEV state does not depend on the source.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

# pdfminer warns on every line for broken font descriptors ("Could not get FontBBox") - noise, the text is still fine
logging.getLogger("pdfminer").setLevel(logging.ERROR)

from jav.models import CellLayout, LineLayout

MIN_TEXT_CHARS = 40
MIN_ALNUM_RATIO = 0.3
# PDFs with a broken font mapping (only accented letters come through: "á á ó / é á / ő") must not count as text:
# at least this many "real" words are needed (≥3 characters, mostly Latin letters/digits).
MIN_REAL_WORDS = 12
_REAL_WORD = re.compile(r"^[A-Za-z0-9ÁÉÍÓÖŐÚÜŰáéíóöőúüű.,:/-]{3,}$")
X_TOLERANCE = 1.5  # word boundary (pt) - the layout mode's default (3) glues words together
Y_TOLERANCE = 3.0  # `top` difference of words belonging to one line (pt)
COLUMN_GAP_CHARS = 2.5  # a gap wider than this many median character widths = column boundary
COLUMN_GAP_MIN_PT = 10.0


class DocumentTooLarge(ValueError):
    """067: the document exceeds the `input_limits` of `configs/service.json` (file size or page count); the item stops
    with a named error, and the run cannot be approved."""


@dataclass(frozen=True)
class InputLimits:
    max_document_mb: float
    max_document_pages: int
    max_page_megapixels: float


def input_limits() -> InputLimits:
    """The input limits (067) from the `input_limits` section of `configs/service.json`."""
    from jav import cfg

    return InputLimits(**cfg.load("service")["input_limits"])


def fit_scale(width_pt: float, height_pt: float, *, scale: float, max_megapixels: float) -> float:
    """The requested scale if the page image fits the pixel budget; otherwise the scale at which it just fits
    (only shrinks)."""
    pixels = width_pt * scale * height_pt * scale
    budget = max_megapixels * 1_000_000
    return scale if pixels <= budget else scale * (budget / pixels) ** 0.5 * 0.999


def check_document_size(path: Path) -> None:
    """The file size limit, checked before opening (the PDF reader never receives a file that is too large)."""
    limit = input_limits().max_document_mb
    size_mb = path.stat().st_size / 1_000_000
    if size_mb > limit:
        raise DocumentTooLarge(f"{path.name}: {size_mb:.1f} MB is over the {limit:g} MB input limit (configs/service.json)")


@dataclass
class PdfText:
    path: str
    text: str
    lines: list[str] = field(default_factory=list)
    layout: list[LineLayout] = field(default_factory=list)
    page_count: int = 0
    has_text_layer: bool = False
    text_source: str | None = None  # "pdf" (text layer) | "ocr" | None (no usable text)
    ocr: dict[str, Any] | None = None  # OCR quality (jav/ocr.py: mean_conf, low_conf_ratio, words, engine, cached)
    # 045: the word boxes (per page `{text, x0, x1, top, bottom, line_no}` in points) and the page sizes (width,
    # height in points) — the word layer is built from these (jav/source_layer.py). The lines (`layout`) are
    # independent of them and unchanged.
    words: list[list[dict[str, Any]]] = field(default_factory=list)
    page_sizes: list[tuple[float, float]] = field(default_factory=list)


# PDFs with LaTeX/T1 fonts give the accent as a separate glyph in the text layer ("Bal´azs", "Vev˝o", "U¨gyvitel").
# The accent usually stands BEFORE the letter, less often after it ("sza´ml´at") - both are reattached.
_ACCENT_MAP = {
    "´": {"a": "á", "e": "é", "i": "í", "ı": "í", "o": "ó", "u": "ú", "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú"},
    "˝": {"o": "ő", "u": "ű", "O": "Ő", "U": "Ű"},
    "¨": {"o": "ö", "u": "ü", "O": "Ö", "U": "Ü"},
}
_ACCENT_BEFORE = re.compile(r"([´˝¨])([A-Za-zı])")
_ACCENT_AFTER = re.compile(r"([A-Za-zı])([´˝¨])")
_CID_RE = re.compile(r"\(cid:\d+\)")
# 065: a glyph missing from the font comes out as NUL; between two letters / digits it was always a hyphen in the
# trial's documents (Stripe invoices: "AB12CD34-0009" → "AB12CD34\x000009", hyphenated postcode). Elsewhere (at the
# end of a word: a lost letter; before a digit: a "+" sign) we do not guess. One character for one character: the
# word's position and length do not change.
_LOST_GLYPH_RE = re.compile(r"(?<=[^\W_])\x00(?=[^\W_])")
# 069 (066 Á10, decision of 2026-09-29): only in an identifier-shaped word that contains digits. Not after a currency
# code and before an amount-shaped continuation ("USD\x0049.00": the hyphen would give a negative amount), and not in
# an all-letter word (a lost letter pair in a name). In the 988 local documents the replacement stood between two
# digits 163 times and between a letter and a digit 61 times; between two letters and in the currency–amount position
# 0 times.
_CURRENCY_BEFORE_RE = re.compile(r"(?<![A-Za-z])(?:USD|EUR|GBP|HUF|CHF|TRY|PLN|CZK|AUD|CAD|SEK|NOK|DKK|RON|JPY)$")
_AMOUNT_AFTER_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})*[.,]\d{2}(?!\w)|\d+[.,]\d{2}(?!\w)")


# 066 Á33: unambiguous hyphen variants (U+2010–2012, U+2212 minus sign, U+FE63, U+FF0D) -> "-" (one character for one
# character, the position does not change). The en and em dashes (U+2013, U+2014) stay: they mark both periods and
# dashes (067 measurement: inside a word 13 times in the local store, also as periods and times; the unambiguous
# variants 0 times).
_DASHES = str.maketrans({ch: "-" for ch in "\u2010\u2011\u2012\u2212\ufe63\uff0d"})


def normalize_dashes(text: str) -> str:
    return text.translate(_DASHES)


def _identifier_gap(text: str, pos: int) -> bool:
    start = max(text.rfind(ch, 0, pos) for ch in " \t\n") + 1
    ends = [i for i in (text.find(ch, pos) for ch in " \t\n") if i >= 0]
    word = text[start:min(ends) if ends else len(text)]
    if not any(ch.isdigit() for ch in word):
        return False
    return not (_CURRENCY_BEFORE_RE.search(text, start, pos) or _AMOUNT_AFTER_RE.match(text, pos + 1))


def fix_lost_glyphs(text: str) -> str:
    if "\x00" not in text:
        return text
    return _LOST_GLYPH_RE.sub(lambda m: "-" if _identifier_gap(text, m.start()) else m.group(0), text)


def _fix_latex_accents(text: str) -> str:
    if not any(ch in text for ch in "´˝¨"):
        return text

    def before(m: re.Match) -> str:
        return _ACCENT_MAP[m.group(1)].get(m.group(2), m.group(0))

    def after(m: re.Match) -> str:
        return _ACCENT_MAP[m.group(2)].get(m.group(1), m.group(0))

    text = _ACCENT_BEFORE.sub(before, text)
    return _ACCENT_AFTER.sub(after, text)


def _group_lines(words: list[dict], y_tol: float = Y_TOLERANCE) -> list[list[dict]]:
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict]] = []
    for w in words:
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= y_tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return lines


def _split_cells(line_words: list[dict], gap_pt: float) -> list[CellLayout]:
    line_words = sorted(line_words, key=lambda w: w["x0"])
    cells: list[CellLayout] = []
    buf: list[dict] = []
    for w in line_words:
        if buf and (w["x0"] - buf[-1]["x1"]) > gap_pt:
            cells.append(CellLayout(text=" ".join(x["text"] for x in buf), x0=buf[0]["x0"], x1=buf[-1]["x1"]))
            buf = []
        buf.append(w)
    if buf:
        cells.append(CellLayout(text=" ".join(x["text"] for x in buf), x0=buf[0]["x0"], x1=buf[-1]["x1"]))
    return cells


def build_layout(pages: list[list[dict]], *, y_tol: float | None = None) -> list[LineLayout]:
    """Lines and column cells from word boxes (`text`, `x0`, `x1`, `top`, in points), numbered across the document.

    Side effect (045): every word dict gets a `line_no` key (the line it went into), so the word layer can be tied to
    the lines. The returned layout does not change because of this.

    Shared by text-layer PDFs (pdfplumber words) and OCR (tesseract word boxes converted to points). `y_tol` defaults to
    the text layer's 3 pt; OCR passes a larger one derived from the median word height (skewed scans)."""
    layout: list[LineLayout] = []
    for page_no, words in enumerate(pages, 1):
        words = [w for w in words if w["text"]]
        if not words:
            continue
        char_w = statistics.median((w["x1"] - w["x0"]) / max(len(w["text"]), 1) for w in words)
        gap_pt = max(COLUMN_GAP_CHARS * char_w, COLUMN_GAP_MIN_PT)
        for line_words in _group_lines(words, y_tol if y_tol is not None else Y_TOLERANCE):
            cells = _split_cells(line_words, gap_pt)
            text = "   ".join(c.text for c in cells)
            layout.append(LineLayout(no=len(layout) + 1, page=page_no, text=text, cells=cells))
            for w in line_words:
                w["line_no"] = len(layout)
    return layout


def text_layer_ok(text: str) -> bool:
    """Whether there is usable text: enough characters, enough alphanumeric ratio and enough real words (filters out
    broken fonts)."""
    stripped = text.strip()
    alnum = sum(ch.isalnum() for ch in stripped)
    words = [w for w in stripped.split() if _REAL_WORD.match(w) and sum(ch.isascii() and ch.isalnum() for ch in w) >= 2]
    return (
        len(stripped) >= MIN_TEXT_CHARS
        and (alnum / max(len(stripped), 1)) >= MIN_ALNUM_RATIO
        and len(words) >= MIN_REAL_WORDS
    )


def read_pdf(path: str | Path) -> PdfText:
    path = Path(path)
    check_document_size(path)
    pages: list[list[dict]] = []
    sizes: list[tuple[float, float]] = []
    with pdfplumber.open(str(path)) as pdf:
        page_count = len(pdf.pages)
        max_pages = input_limits().max_document_pages
        if page_count > max_pages:
            raise DocumentTooLarge(f"{path.name}: {page_count} pages is over the {max_pages} page input limit "
                                   "(configs/service.json)")
        for page in pdf.pages:
            sizes.append((float(page.width), float(page.height)))
            words = page.extract_words(x_tolerance=X_TOLERANCE, y_tolerance=Y_TOLERANCE, keep_blank_chars=False)
            pages.append([
                {**w, "text": normalize_dashes(fix_lost_glyphs(_fix_latex_accents(_CID_RE.sub("", w["text"]).replace(" ", " ")))).strip()}
                for w in words
            ])
    layout = build_layout(pages)
    lines = [ln.text for ln in layout]
    text = "\n".join(lines)
    has_text = text_layer_ok(text)
    return PdfText(
        path=str(path), text=text, lines=lines, layout=layout, page_count=page_count, has_text_layer=has_text,
        text_source="pdf" if has_text else None, words=pages, page_sizes=sizes,
    )


def read_document(path: str | Path, *, ocr: bool = True) -> PdfText:
    """Text layer, and if there is none, OCR (from the disk cache if it has run before). The entry point of the evals
    and the CLI; the flows do the same in two steps (`load_pdf` -> `ocr_pdf`) so that it shows in the contract."""
    pdf = read_pdf(path)
    if pdf.has_text_layer or not ocr:
        return pdf
    from jav.ocr import OcrUnavailableError, ocr_pdf

    try:
        return ocr_pdf(path, page_count=pdf.page_count)
    except OcrUnavailableError:
        return pdf
