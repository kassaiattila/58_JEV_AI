"""061: rossz kódolással visszaírt szöveg (UTF-8 bájtok cp1250/cp1252-ként olvasva) ne kerülhessen a forrásba.

A választó pipája egyszer „âś“” alakban került a stíluslapba, és a felületen „ásm”-szerű jelként látszott minden
legördülő listában. A jellemző kettős-kódolású részletek keresése a felület, a konfigok és a Python-kód fájljaiban.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# UTF-8 ékezetes betűk / jelek cp1250-ként vagy cp1252-ként dekódolva (pl. „é” → „Ă©”, „ő” → „Ĺ‘”, „✓” → „âś“”, „–” → „â€“”)
BAD = ("Ă©", "Ăˇ", "Ăł", "Ă¶", "ĂĽ", "Ĺ‘", "Ĺ±", "Ă­", "Ăş", "âś", "â€", "Ã©", "Ã¡", "Ã³", "Ã¶", "Ã¼", "Å‘", "Å±")
GLOBS = ("ui/src/**/*.ts", "ui/src/**/*.tsx", "ui/src/**/*.css", "ui/src/**/*.json", "configs/**/*.json", "jav/**/*.py")


def test_no_mojibake_in_sources():
    hits = []
    for pattern in GLOBS:
        for path in ROOT.glob(pattern):
            text = path.read_text(encoding="utf-8")
            for bad in BAD:
                if bad in text:
                    line = text[: text.index(bad)].count("\n") + 1
                    hits.append(f"{path.relative_to(ROOT)}:{line}: {bad!r}")
    assert not hits, "rossz kódolású szöveg:\n" + "\n".join(hits)
