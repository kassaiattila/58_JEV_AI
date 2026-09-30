"""Mesterséges, szövegréteges PDF a tesztekhez (külső csomag nélkül). Csak ASCII szöveg, Helvetica betűvel."""

from pathlib import Path


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_text_pdf(path: Path, lines: list[str]) -> Path:
    stream = "BT /F1 11 Tf 14 TL 50 800 Td " + " ".join(f"({_escape(line)}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return path


INVOICE_LINES = [
    "SZAMLA",
    "Szamlaszam: MINTA-2026-001",
    "Elado: Minta Kereskedelmi Kft.",
    "Adoszam: 13570008-1-13",
    "Vevo: Proba Szolgaltato Bt.",
    "Kelt: 2026.09.01.  Teljesites: 2026.09.01.  Fizetesi hatarido: 2026.09.15.",
    "Netto osszeg: 10 000 Ft   AFA 27%: 2 700 Ft",
    "Brutto osszesen: 12 700 Ft",
    "Fizetesi mod: atutalas",
]
