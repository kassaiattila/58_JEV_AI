"""Codebase documents are public: no internal references, round codes or figures from real use (076).

The owner's decision of 2026-09-30 (docs/guides/DOCUMENTATION.md, rule 7): a document that goes to GitHub describes
the system, not the development process or the owner's data. This test catches the patterns that can be recognised
mechanically; the rest (amounts spent, trial details written out in words) is left to review.

`CLAUDE.md` is out of scope: it has to name the internal documents it tells the development model to read.
"""

import re
from pathlib import Path

import pytest

from jav import doc_scope

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = sorted(
    p.relative_to(ROOT).as_posix()
    for p in [ROOT / "README.md", ROOT / "CHANGELOG.md", *(ROOT / "docs").rglob("*.md")]
    if p.is_file() and p.name != "STATE.md" and not doc_scope.is_internal(p.relative_to(ROOT).as_posix())
)

FORBIDDEN = {
    # a pointer to an internal working document
    "internal pointer": re.compile(r"\(internal\b|\binternal:\s", re.I),
    "numbered handoff or plan": re.compile(r"\b(?:handoffs?|plans?)[ /]\d{3}\b", re.I),
    "internal report path": re.compile(r"\breports/20\d\d-|\b[A-Z][A-Z_]+_20\d\d-\d\d-\d\d\.md\b"),
    # the development process's three-digit round numbers ("since 058", "(040 K1)"), not decimals or file names
    "round number": re.compile(r"(?<![\w.,/-])0[2-9]\d(?![\w.,/-]|[.,]\d)"),
    "stage code": re.compile(r"(?<![\w-])(?:K[0-5](?:\.\d)?|T[1-3](?:\.\d)?|U1|H-0\d\d|R-0\d\d)(?![\w-])"),
    # the owner's infrastructure and real use
    # a path into someone's user folder or the development root, or a network share (plain examples such as
    # `D:\Backup` stay allowed)
    "local machine path": re.compile(r"\b[A-Za-z]:[\\/](?:Users|00_DEV)\b|\\\\[\w.-]+\\[\w$.-]+", re.I),
    "backup location": re.compile(r"\bNAS\b"),
    "count of real items": re.compile(r"\b(?:\d+|two|three|four|five|six|seven|eight|nine|ten)\s+real\b", re.I),
}


def _hits(text: str) -> list[str]:
    found = []
    for n, line in enumerate(text.splitlines(), 1):
        for name, pattern in FORBIDDEN.items():
            m = pattern.search(line)
            if m:
                found.append(f"{n}: {name}: {m.group(0)!r} in {line.strip()[:120]!r}")
    return found


def test_public_docs_are_found():
    assert {"README.md", "CHANGELOG.md", "docs/ARCHITECTURE.md", "docs/GLOSSARY.md", "docs/guides/SETUP.md"} <= set(
        PUBLIC_DOCS
    )
    assert "CLAUDE.md" not in PUBLIC_DOCS


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_public_doc_has_no_internal_information(doc):
    assert _hits((ROOT / doc).read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "line",
    [
        "see the T3.4 report (internal: `reports/2026-09-28-t3.md`)",
        "handoff 054",
        "History: plans/056/PLAN.md",
        "assessment (FRAMEWORK_ASSESSMENT_2026-09-22.md)",
        "Mailbox (048 T2): download from Outlook",
        "since 075 a recipe switch",
        "the second opinion (H-065)",
        r"powershell -File C:\Users\someone\legacy\scripts\x.ps1",
        r"a copy to \\server\share\backup",
        "a daily backup, locally and on the NAS",
        "tried on two real mailboxes",
        "Of the 47 real emails",
    ],
)
def test_patterns_catch_internal_information(line):
    assert _hits(line)


@pytest.mark.parametrize(
    "line",
    [
        "0.042 USD per million input tokens; a threshold of 0.60",
        "`tests/test_docs_071.py` and `ui/src/deps075.test.tsx`",
        "released as `v1.0.5` on 2026-09-30, listening on 127.0.0.1:8930",
        "M1, M2 and M3 are the reference flows; the S path and the G path",
        "Real documents never go into git; tests use synthetic data",
        "HTTP 409 on a version conflict; 300 pages, 40 megapixels",
        r"C:/Program Files/Tesseract-OCR/tesseract.exe; `<legacy-root>\scripts`; backup --out D:\Backup",
    ],
)
def test_patterns_leave_ordinary_text_alone(line):
    assert _hits(line) == []
