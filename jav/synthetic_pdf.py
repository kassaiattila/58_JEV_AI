"""Kitalált, szövegréteges PDF teljes magyar ékezetkészlettel (067), szondákhoz és próbákhoz.

A tesztek egyszerű PDF-írója (`tests/pdfgen.py`) csak ASCII-t tud, egy oszlopban. Ez a PDF beépített Helvetica betűjét
használja (betűfájl nélkül) a Windows-kódtáblával, amelyből a magyarban nem használt „õ, û, Õ, Û” helyére a „ő, ű, Ő, Ű”
kerül (a kódtábla `Differences` kiegészítése), így a szövegréteg-olvasó (pdfminer) a teljes magyar ábécét és a sima
kötőjelet adja vissza. (A beágyazott TrueType betűs út a PDFium ToUnicode-táblája miatt a kötőjelet lágy elválasztóként
vagy tipográfiai kötőjelként adta vissza, ami valódi iratban nem fordul elő.)

A sorokat a jelöltkereső sor- és cellaépítője (`jav/pdf.py: build_layout`) ugyanúgy bontja cellákra, mint egy valódi
számlánál: a három szóközzel elválasztott részek külön oszlopba kerülnek. Valódi iratot nem gyárt, csak a megadott,
kitalált szöveget írja ki.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

PAGE_W, PAGE_H = 595, 842  # A4 pontban
TOP, LINE_GAP, FONT_SIZE = 800, 16, 10
COLUMN_X = (50, 230, 330, 420, 500)  # a cellák kezdete; a hatodiktól 90 pontonként
CELL_SEP = "   "
WRAP_CHARS = 100  # egycellás hosszú sor tördelése: 10 pontos Helveticával ~480 pont, az oldalon belül marad
# a Windows-kódtábla (WinAnsi) magyarban nem használt helyei a hiányzó magyar betűknek
_HU_DIFFERENCES = {"ő": (0xF5, "ohungarumlaut"), "ű": (0xFB, "uhungarumlaut"), "Ő": (0xD5, "Ohungarumlaut"),
                   "Ű": (0xDB, "Uhungarumlaut")}


def _column_x(k: int) -> int:
    return COLUMN_X[k] if k < len(COLUMN_X) else COLUMN_X[-1] + 90 * (k - len(COLUMN_X) + 1)


def layout_rows(rows: list[str]) -> list[str]:
    """A kiírt sorok: az egycellás, `WRAP_CHARS`-nál hosszabb sor szóhatáron több sorra törik, a többi változatlan."""
    out: list[str] = []
    for row in rows:
        if CELL_SEP not in row and len(row) > WRAP_CHARS:
            out.extend(textwrap.wrap(row, WRAP_CHARS))
        else:
            out.append(row)
    return out


def _encode(text: str) -> bytes:
    """A cella szövege a kiegészített Windows-kódtáblában, PDF-szövegként escape-elve; más betű `UnicodeEncodeError`."""
    raw = bytearray()
    for ch in text:
        raw += bytes([_HU_DIFFERENCES[ch][0]]) if ch in _HU_DIFFERENCES else ch.encode("cp1252")
    return bytes(raw).replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def write_unicode_pdf(path: Path, rows: list[str]) -> Path:
    """Egyoldalas PDF a `rows` soraival; a sorban a `CELL_SEP` (három szóköz) oszlophatár. A szondák rövid iratokat írnak:
    a lap aljáról kifutó sorok nem kerülnek új oldalra."""
    ops = bytearray()
    y = TOP
    for row in layout_rows(rows):
        for k, cell in enumerate(row.split(CELL_SEP)):
            if cell.strip():
                ops += b"BT /F1 %d Tf %d %d Td (" % (FONT_SIZE, _column_x(k), y) + _encode(cell.strip()) + b") Tj ET\n"
        y -= LINE_GAP
    differences = " ".join(f"{code} /{name}" for code, name in sorted(_HU_DIFFERENCES.values()))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        % (PAGE_W, PAGE_H),
        ("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding << /Type /Encoding /BaseEncoding /WinAnsiEncoding "
         f"/Differences [{differences}] >> >>").encode("ascii"),
        b"<< /Length %d >>\nstream\n" % len(ops) + bytes(ops) + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    Path(path).write_bytes(bytes(out))
    return Path(path)
