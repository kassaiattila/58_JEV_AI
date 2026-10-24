"""A document given as text: an email's own text, a text file or a table file, laid out like a PDF (190, plan 189 A2b).

Plain-language summary: the data extraction of a type pack used to read PDFs only, so a quote request written in the
body of an email could not reach it. Now a text becomes a document of the same shape as a PDF: numbered lines, split
into column cells where three or more spaces (or a tab) stand between two words. The shape is built by the PDF
reader's own line and cell builder (`jav.documents.pdf.build_layout`) from word boxes placed on a fixed character grid, so the
candidate finders, the GPT extraction and the JEV verification see a text exactly as they see a PDF's lines. A table
file (Excel, CSV) is opened by the isolated native reader (`jav/documents/readers/`) and each of its rows becomes one line, its
cells three spaces apart.

The kinds of input a type pack takes are its `inputs` (`jav/ai/typepack.py`): `pdf` (the default), `text` (a given text
or a `.txt` file) and `table` (`.xlsx`, `.csv`). There is no word layer: a text has no page image to point at, so the
source location of its values stays without one.

Layer: business module (a file read through the isolated reader); no AI call, no store.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from jav.documents.pdf import PdfText, build_layout, normalize_dashes

# 190: the input kinds a type pack may take (its `inputs`, `jav.ai.typepack`); 227 (plan R3c): named here, by the
# reading that serves them, so this layer needs nothing of the AI layer
INPUTS = ("pdf", "text", "table")
TEXT_SUFFIXES = {".txt": "text", ".xlsx": "table", ".csv": "table"}
CHAR_PT = 5.0  # the width of one character on the grid: three spaces are a gap over the column builder's 2.5 characters
LINE_PT = 12.0  # the distance of two lines (over the builder's 3 pt line tolerance)
TAB = "    "  # a tab separates columns
CELL_GAP = "   "  # how the cells of a table row are set apart (the column builder splits on it)


class TextDocumentError(ValueError):
    """The file is not a kind of text or table this module reads, or the isolated reader refused it."""


def input_kind(path: str | Path) -> str:
    """The input kind of a file by its suffix: `pdf`, `text` or `table`."""
    suffix = Path(path).suffix.lower()
    return "pdf" if suffix == ".pdf" else TEXT_SUFFIXES.get(suffix, "pdf")


def _clean(text: str) -> str:
    return normalize_dashes(text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", TAB).replace(" ", " "))


def _words(lines: list[str]) -> list[dict]:
    """Word boxes on the character grid: a word's left edge is its column times `CHAR_PT`, each line `LINE_PT` lower."""
    words: list[dict] = []
    for row, line in enumerate(lines):
        col = 0
        for part in line.split(" "):
            if part:
                words.append({"text": part, "x0": col * CHAR_PT, "x1": (col + len(part)) * CHAR_PT,
                              "top": row * LINE_PT, "bottom": row * LINE_PT + LINE_PT * 0.8})
            col += len(part) + 1
    return words


def layout_text(text: str, *, path: str = "text") -> PdfText:
    """The text as a one-page document: its lines and cells by the PDF reader's builder. An empty text has no lines
    (and no text, `text_source` None), so the flow treats it like a PDF without text."""
    lines = _clean(text).split("\n")
    layout = build_layout([_words(lines)])
    texts = [ln.text for ln in layout]
    joined = "\n".join(texts)
    return PdfText(path=path, text=joined, lines=texts, layout=layout, page_count=1, has_text_layer=bool(joined),
                   text_source="text" if joined else None)


def text_digest(text: str) -> str:
    """The identity of a given text as a document (its UTF-8 bytes' sha256), as a file's identity is its bytes'."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _table_lines(response: dict) -> list[str]:
    """The rows of the reader's cells, one line each, the cells of a row `CELL_GAP` apart; a workbook of more than one
    sheet names each sheet on a line before its rows. Empty and hidden cells are left out."""
    rows: dict[tuple[str, int], list[tuple[int, str]]] = {}
    sheets: list[str] = []
    for element in response.get("elements", []):
        if element.get("kind") != "cell" or element.get("hidden"):
            continue
        locator = element["locator"]
        cell = element["cell"]
        value = (cell.get("cached_value") or cell["value"]) if cell.get("formula") else cell["value"]
        text = (value.get("lexical") or "").strip()
        if not text:
            continue
        if locator["sheet"] not in sheets:
            sheets.append(locator["sheet"])
        rows.setdefault((locator["sheet"], locator["row"]), []).append((locator["column"], text))
    out: list[str] = []
    for sheet in sheets:
        if len(sheets) > 1:
            out.append(sheet)
        for (name, _row), cells in sorted((k, v) for k, v in rows.items() if k[0] == sheet):
            out.append(CELL_GAP.join(t for _c, t in sorted(cells)))
    return out


def read_file(path: str | Path) -> str:
    """The text of a text or table file: a `.txt` file as it is (UTF-8), a table's rows as lines. The table goes
    through the isolated native reader with its default limits (`jav.documents.readers.isolation`)."""
    path = Path(path)
    kind = input_kind(path)
    if kind == "text":
        return path.read_bytes().decode("utf-8-sig")
    if kind != "table":
        raise TextDocumentError(f"{path.name}: not a text or table file")
    from jav.documents.readers.isolation import run
    from jav.documents.readers.limits import DEFAULT_LIMITS, ReadFailure

    try:
        response = run(path.read_bytes(), path.name, DEFAULT_LIMITS)
    except ReadFailure as exc:
        raise TextDocumentError(f"{path.name}: the reader refused the table ({exc.code})") from exc
    return "\n".join(_table_lines(response))


__all__ = ["CELL_GAP", "INPUTS", "TEXT_SUFFIXES", "TextDocumentError", "input_kind", "layout_text", "read_file",
           "text_digest"]
