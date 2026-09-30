"""PDF szövegréteg beolvasása (pdfplumber) és a közös sor- / cella-építő, amit az OCR (`jav/ocr.py`) is használ.

Szöveg nélküli PDF -> `has_text_layer=False`; az OCR-t nem itt, hanem a flow külön lépésében (`ocr_pdf`) hívjuk, hogy
a kontraktban látszódjon és a döntés (megy-e OCR-re) adat legyen. `read_document()` a kettő együtt (evalokhoz, CLI-hez).

Miért szó-szintű rekonstrukció és nem `extract_text(layout=True)`:
- a Számlázz.hu-s PDF-eknél a layout-mód összeragasztja a szavakat ("BestIxComKft.", "Fizetésimód:"),
  az `extract_words(x_tolerance=1.5)` viszont helyesen bontja;
- a kétoszlopos (eladó | vevő) fejléceknél a sorokat cellákra kell bontani (nagy vízszintes rés = oszlophatár),
  hogy a többsoros nevek oszloponként, függőlegesen összefűzhetők legyenek.

Ugyanez a sor- és cella-építés fut az OCR szó-dobozain (pontra átváltva), így a jelöltkeresők és a Jev-state
formája forrástól független.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pdfplumber

# pdfminer hibás font-leíróknál soronként warningol ("Could not get FontBBox") - zaj, a szöveg attól még jó
logging.getLogger("pdfminer").setLevel(logging.ERROR)

from jav.models import CellLayout, LineLayout

MIN_TEXT_CHARS = 40
MIN_ALNUM_RATIO = 0.3
# Törött font-leképezésű PDF-ek (csak ékezetes betűk jönnek át: "á á ó / é á / ő") ne számítsanak szövegesnek:
# kell legalább ennyi "valódi" szó (≥3 karakter, többségében latin betű/számjegy).
MIN_REAL_WORDS = 12
_REAL_WORD = re.compile(r"^[A-Za-z0-9ÁÉÍÓÖŐÚÜŰáéíóöőúüű.,:/-]{3,}$")
X_TOLERANCE = 1.5  # szóhatár (pt) - a layout-mód alapértéke (3) ragaszt
Y_TOLERANCE = 3.0  # egy sorba tartozó szavak `top` eltérése (pt)
COLUMN_GAP_CHARS = 2.5  # ennyi medián-karakterszélességnél nagyobb rés = oszlophatár
COLUMN_GAP_MIN_PT = 10.0


class DocumentTooLarge(ValueError):
    """067: az irat a `configs/service.json` `input_limits` korlátja fölött van (fájlméret vagy oldalszám); a tétel
    nevesített hibával áll meg, a futás nem hagyható jóvá."""


@dataclass(frozen=True)
class InputLimits:
    max_document_mb: float
    max_document_pages: int
    max_page_megapixels: float


def input_limits() -> InputLimits:
    """A bemeneti korlátok (067) a `configs/service.json` `input_limits` szakaszából."""
    from jav import cfg

    return InputLimits(**cfg.load("service")["input_limits"])


def fit_scale(width_pt: float, height_pt: float, *, scale: float, max_megapixels: float) -> float:
    """A kért nagyítás, ha az oldalkép belefér a képpont-keretbe; különben akkora, hogy éppen beleférjen (csak kicsinyít)."""
    pixels = width_pt * scale * height_pt * scale
    budget = max_megapixels * 1_000_000
    return scale if pixels <= budget else scale * (budget / pixels) ** 0.5 * 0.999


def check_document_size(path: Path) -> None:
    """A fájlméret-korlát megnyitás előtt (a túl nagy fájlt a PDF-olvasó meg sem kapja)."""
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
    text_source: str | None = None  # "pdf" (szövegréteg) | "ocr" | None (nincs használható szöveg)
    ocr: dict[str, Any] | None = None  # OCR-minőségjelek (jav/ocr.py: mean_conf, low_conf_ratio, words, engine, cached)
    # 045: a szókeretek (oldalanként `{text, x0, x1, top, bottom, line_no}` pontban) és az oldalméretek (szélesség, magasság
    # pontban) — ebből készül a szóréteg (jav/source_layer.py). A sorok (`layout`) ettől függetlenek és változatlanok.
    words: list[list[dict[str, Any]]] = field(default_factory=list)
    page_sizes: list[tuple[float, float]] = field(default_factory=list)


# LaTeX/T1-fontos PDF-ek a szövegrétegben külön glifként adják az ékezetet ("Bal´azs", "Vev˝o", "U¨gyvitel").
# Az ékezet többnyire a betű ELŐTT áll, ritkábban utána ("sza´ml´at") - mindkettőt visszaillesztjük.
_ACCENT_MAP = {
    "´": {"a": "á", "e": "é", "i": "í", "ı": "í", "o": "ó", "u": "ú", "A": "Á", "E": "É", "I": "Í", "O": "Ó", "U": "Ú"},
    "˝": {"o": "ő", "u": "ű", "O": "Ő", "U": "Ű"},
    "¨": {"o": "ö", "u": "ü", "O": "Ö", "U": "Ü"},
}
_ACCENT_BEFORE = re.compile(r"([´˝¨])([A-Za-zı])")
_ACCENT_AFTER = re.compile(r"([A-Za-zı])([´˝¨])")
_CID_RE = re.compile(r"\(cid:\d+\)")
# 065: a betűkészletből hiányzó jel NUL-ként jön ki; két betű / szám között ez a próba iratain mindig kötőjel volt
# (Stripe-számlák: „AB12CD34-0009” → „AB12CD34\x000009”, kötőjeles irányítószám). Máshol (szó végén: elveszett betű,
# szám előtt: „+” jel) nem találgatunk. Egy karakter egy karakterre: a szó helye és hossza nem változik.
_LOST_GLYPH_RE = re.compile(r"(?<=[^\W_])\x00(?=[^\W_])")
# 069 (066 Á10, döntés 2026-09-29): csak számot tartalmazó, azonosító-alakú szóban. Pénznemkód után és összeg-alakú
# folytatás előtt nem („USD\x0049.00”: a kötőjel negatív összeget adna), csupa betűs szóban sem (elveszett betűpár a
# névben). A helyi 988 iratban a pótlás két szám között 163-szor, betű és szám között 61-szer állt; két betű között és
# pénznem–összeg helyzetben 0-szor.
_CURRENCY_BEFORE_RE = re.compile(r"(?<![A-Za-z])(?:USD|EUR|GBP|HUF|CHF|TRY|PLN|CZK|AUD|CAD|SEK|NOK|DKK|RON|JPY)$")
_AMOUNT_AFTER_RE = re.compile(r"\d{1,3}(?:[.,]\d{3})*[.,]\d{2}(?!\w)|\d+[.,]\d{2}(?!\w)")


# 066 Á33: egyértelmű kötőjel-változatok (U+2010–2012, U+2212 mínuszjel, U+FE63, U+FF0D) -> "-" (egy karakter egy
# karakterre, a hely nem változik). A hosszú gondolatjel (U+2013, U+2014) marad: időszakot és gondolatjelet is jelöl
# (067 mérés: a helyi adattárban szón belül 13-szor, időszakként és óraként is; az egyértelmű változatok 0-szor).
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
    """Szó-dobozokból (`text`, `x0`, `x1`, `top`, pontban) sorok és oszlop-cellák, dokumentum-szintű sorszámozással.

    Mellékhatás (045): minden szó-szótár megkapja a `line_no` kulcsot (melyik sorba került), hogy a szóréteg a sorokhoz
    köthető legyen. A visszaadott elrendezés ettől nem változik.

    Közös a szövegréteges PDF-nél (pdfplumber szavak) és az OCR-nél (tesseract szó-dobozok pontra váltva). `y_tol`
    alapból a szövegréteg 3 pt-ja; az OCR a szavak medián-magasságából ad nagyobbat (ferde szkennelés)."""
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
    """Van-e használható szöveg: elég karakter, elég alfanumerikus arány és elég valódi szó (törött font kiszűrése)."""
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
    """Szövegréteg, és ha nincs, OCR (a lemez-gyorsítótárból, ha már volt). Az evalok és a CLI belépési pontja; a flow-k
    ugyanezt két lépésben teszik (`load_pdf` -> `ocr_pdf`), hogy a kontraktban látszódjon."""
    pdf = read_pdf(path)
    if pdf.has_text_layer or not ocr:
        return pdf
    from jav.ocr import OcrUnavailableError, ocr_pdf

    try:
        return ocr_pdf(path, page_count=pdf.page_count)
    except OcrUnavailableError:
        return pdf
