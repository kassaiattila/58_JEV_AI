"""The text-layer heuristic: a PDF with a broken font mapping ("accents only") must not count as having text."""

from jav import pdf as pdfmod


def _has_text(text: str) -> bool:
    stripped = text.strip()
    alnum = sum(ch.isalnum() for ch in stripped)
    words = [w for w in stripped.split() if pdfmod._REAL_WORD.match(w) and sum(ch.isascii() and ch.isalnum() for ch in w) >= 2]
    return len(stripped) >= pdfmod.MIN_TEXT_CHARS and alnum / max(len(stripped), 1) >= pdfmod.MIN_ALNUM_RATIO and len(words) >= pdfmod.MIN_REAL_WORDS


def test_garbled_accent_only_text_is_not_a_text_layer():
    garbled = "\n".join(["á", "á   á   ó", "é á", "á í ó", "ő", "ö", "É", "ó   ú ú", "ó á", "á", "ó á   ö ö á", "ó", "á", "ó   ó á"] * 3)
    assert not _has_text(garbled)


def test_real_invoice_text_is_a_text_layer():
    real = "SZÁMLA\nSorszám: INF-2022-3\nMINTALOGIC Bt.\n1234 Mintaváros Próba utca 1.\nAdószám: 13570008-1-13\n" \
           "Fizetési mód: átutalás\nTeljesítés dátuma: 2022.02.16.\nÖsszesen: 1 000 000 Ft\nVEVŐ: BestIxCom Kft."
    assert _has_text(real)
