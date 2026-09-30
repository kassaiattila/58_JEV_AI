"""A kódtári és a belső dokumentáció határa (070, a felhasználó döntése 2026-09-29).

A **belső munkaanyag** a fejlesztés menetének helyi dokumentuma: átadók, tervek, jelentések, a régi dátumozott
gyökérjelentések, a folytatási utasítások, a teendőlista, a döntésnapló, az útiterv, a belső belépő oldal, és a helyi
hívásnaplóból generált hívásihely-katalógus. A git nem követi (`.gitignore`), a GitHubra nem kerül, a napi mentés
viszi (`jav/backup.py`). Az útvonalak nem változtak: a régi átadók hivatkozásai és a horgok ugyanide mutatnak.

A **kódtári dokumentum** minden más, verziókövetett leírás (README, architektúra, fogalomtár, útmutatók, generált
folyamatleírások). Kódtári dokumentum belső fájlra nem hivatkozhat linkkel (`tests/test_doc_links.py`).

Egy hely: a minták itt vannak, a `.gitignore` ezekkel egyezik (teszt), és a mentés is innen olvas.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from jav.config import PROJECT_ROOT

# `/`-re végződő minta: a mappa teljes tartalma; más minta: egy fájl a megadott mélységben (a `*` nem lép át mappát).
INTERNAL_DOC_PATTERNS: tuple[str, ...] = (
    "docs/handoffs/",
    "docs/plans/",
    "docs/reports/",
    "docs/callsites/",
    "docs/BACKLOG.md",
    "docs/DECISIONS.md",
    "docs/ROADMAP.md",
    "docs/INDEX.md",
    "docs/CONTINUE_PROMPT_*.md",
    "docs/*_????-??-??.md",
)


def is_internal(rel_path: str | PurePosixPath) -> bool:
    """A projektgyökérhez viszonyított útvonal belső munkaanyag-e."""
    parts = PurePosixPath(str(rel_path).replace("\\", "/")).parts
    for pattern in INTERNAL_DOC_PATTERNS:
        pat = PurePosixPath(pattern.rstrip("/")).parts
        if pattern.endswith("/"):
            matched = len(parts) > len(pat)
        else:
            matched = len(parts) == len(pat)
        if matched and all(fnmatchcase(a, b) for a, b in zip(parts, pat)):
            return True
    return False


def internal_doc_files(root: Path = PROJECT_ROOT) -> list[Path]:
    """A munkafán lévő belső dokumentumfájlok, rendezve (friss klónon üres)."""
    docs = root / "docs"
    if not docs.is_dir():
        return []
    return sorted(p for p in docs.rglob("*") if p.is_file() and is_internal(p.relative_to(root).as_posix()))


__all__ = ["INTERNAL_DOC_PATTERNS", "internal_doc_files", "is_internal"]
