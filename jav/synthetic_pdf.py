"""Fictitious PDF with a text layer and the full Hungarian accent set (067), for probes and trials.

The tests' simple PDF writer (`tests/pdfgen.py`) handles only ASCII, in one column. This PDF uses the built-in Helvetica
font (no font file) with the Windows code page, in which "ő, ű, Ő, Ű" replace "õ, û, Õ, Û", unused in Hungarian (a
`Differences` supplement to the code page), so the text-layer reader (pdfminer) returns the full Hungarian alphabet and
the plain hyphen. (The embedded TrueType font route returned the hyphen as a soft hyphen or a typographic dash, because
of PDFium's ToUnicode table, which does not happen in real documents.)

The candidate finder's row and cell builder (`jav/pdf.py: build_layout`) splits the rows into cells exactly as for a
real invoice: the parts separated by three spaces go into separate columns. It produces no real document; it only
writes out the given, fictitious text.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

PAGE_W, PAGE_H = 595, 842  # A4 in points
TOP, LINE_GAP, FONT_SIZE = 800, 16, 10
COLUMN_X = (50, 230, 330, 420, 500)  # cell starts; from the sixth on, every 90 points
CELL_SEP = "   "
WRAP_CHARS = 100  # wrapping of a long single-cell row: ~480 points in 10-point Helvetica, stays within the page
# slots of the Windows code page (WinAnsi) unused in Hungarian, for the missing Hungarian letters
_HU_DIFFERENCES = {"ő": (0xF5, "ohungarumlaut"), "ű": (0xFB, "uhungarumlaut"), "Ő": (0xD5, "Ohungarumlaut"),
                   "Ű": (0xDB, "Uhungarumlaut")}


def _column_x(k: int) -> int:
    return COLUMN_X[k] if k < len(COLUMN_X) else COLUMN_X[-1] + 90 * (k - len(COLUMN_X) + 1)


def layout_rows(rows: list[str]) -> list[str]:
    """The written rows: a single-cell row longer than `WRAP_CHARS` breaks into several rows at word boundaries; the
    rest are unchanged."""
    out: list[str] = []
    for row in rows:
        if CELL_SEP not in row and len(row) > WRAP_CHARS:
            out.extend(textwrap.wrap(row, WRAP_CHARS))
        else:
            out.append(row)
    return out


def _encode(text: str) -> bytes:
    """The cell text in the supplemented Windows code page, escaped as PDF text; any other letter raises
    `UnicodeEncodeError`."""
    raw = bytearray()
    for ch in text:
        raw += bytes([_HU_DIFFERENCES[ch][0]]) if ch in _HU_DIFFERENCES else ch.encode("cp1252")
    return bytes(raw).replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def write_unicode_pdf(path: Path, rows: list[str]) -> Path:
    """Single-page PDF with the rows of `rows`; within a row, `CELL_SEP` (three spaces) is the column boundary. The
    probes write short documents: rows running off the bottom of the page are not moved to a new page."""
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
