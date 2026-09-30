"""The boundary between codebase and internal documentation (070, the owner's decision of 2026-09-29).

**Internal working material** is the local record of how development proceeds: handoffs, plans, reports, the old
dated root reports, the continuation instructions, the backlog, the decisions log, the roadmap, the internal landing
page, and the call-site catalogue generated from the local call log. Git does not track it (`.gitignore`), it never
goes to GitHub, and the daily backup carries it (`jav/backup.py`). The paths have not changed: links in the old
handoffs and the hooks point to the same places.

A **codebase document** is every other, version-controlled description (README, architecture, glossary, guides,
generated flow descriptions). A codebase document may not link to an internal file (`tests/test_doc_links.py`).

One place: the patterns live here, `.gitignore` matches them (tested), and the backup reads them from here too.
"""

from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from jav.config import PROJECT_ROOT

# A pattern ending in `/` means the whole content of the folder; any other pattern means one file at the given depth
# (`*` does not cross folders).
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
    """Whether a path relative to the project root is internal working material."""
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
    """The internal document files in the working tree, sorted (empty in a fresh clone)."""
    docs = root / "docs"
    if not docs.is_dir():
        return []
    return sorted(p for p in docs.rglob("*") if p.is_file() and is_internal(p.relative_to(root).as_posix()))


__all__ = ["INTERNAL_DOC_PATTERNS", "internal_doc_files", "is_internal"]
