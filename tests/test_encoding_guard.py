"""061: text written back with the wrong encoding (UTF-8 bytes read as cp1250/cp1252) must not get into the sources.

The selector's tick mark once ended up in the stylesheet as "âś“" and showed up in the UI as an "ásm"-like sign in
every drop-down list. Searches the UI, config and Python source files for the typical double-encoded fragments.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# UTF-8 accented letters / symbols decoded as cp1250 or cp1252 (e.g. "é" → "Ă©", "ő" → "Ĺ‘", "✓" → "âś“", "–" → "â€“")
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
