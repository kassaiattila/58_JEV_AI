"""Codebase documents are public: no internal references, round codes or figures from real use (076).

The owner's decision of 2026-09-30 (docs/guides/DOCUMENTATION.md, rule 7): a document that goes to GitHub describes
the system, not the development process or the owner's data. This test catches the patterns that can be recognised
mechanically; the rest (amounts spent, trial details written out in words) is left to review.

`CLAUDE.md` is out of scope: it has to name the internal documents it tells the development model to read.
"""

import re
from pathlib import Path

import pytest

from jav.core import doc_scope

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
    # 265 (code review DOC-02): the later rounds (100-299) where only a round reference stands: after "since", "until",
    # "built in" ..., at the start of a parenthesis or a clause, after "DECISIONS"; a quantity ("100 invoices",
    # "0-100", "in 100 ms") is not one
    "later round number": re.compile(
        r"\b(?:[Ss]ince|[Uu]ntil|[Bb]uilt in|[Rr]etired in|[Ss]plit by field in|DECISIONS?|round|plan|stage) (?:1\d\d|2\d\d)\b"
        r"|\((?:1\d\d|2\d\d)(?:-[A-Z])?(?:[);:]|,(?!\d))"
        r"|(?:^|\| |^- |[;.] )(?:1\d\d|2\d\d)(?:-[A-Z])?:"
        r"|(?<=[;,] )(?:1\d\d|2\d\d)(?:-[A-Z])?[);]"),
    "plan code": re.compile(r"\b(?:[Pp]lan )?[Ss]tage [A-Z]\d?\b|\b(?:[A-D]\d[a-z]\d?|D-[a-z]\d\w*|U-A\d+|D0-[a-z])\b"),
    # 272 (K6): the forms the 265 pass left: a decision's or a review's number, a round heading or list label, a round
    # with its stage code, "before" a round, a plan letter, a numbered rule
    "decision or review number": re.compile(r"\((?:decisions?|review) [12]?\d{2,3}\b"),
    "round label": re.compile(r"(?<![\w.,/-])(?:1\d\d|2\d\d)(?:-[A-Z])? \((?:review|decisions?)\b|\*\*(?:1\d\d|2\d\d)[: (]"
                              r"|(?<=, )(?:1\d\d|2\d\d): "),
    "round with its code": re.compile(r"(?<![\w.,/-])(?:1\d\d|2\d\d) [A-Z]\d{1,2}[a-z]?\b"),
    "before a round": re.compile(r"\bbefore (?:1\d\d|2\d\d)\b(?! ?(?:ms|seconds?|minutes?|hours?|days?|%|\d))"),
    "plan letter": re.compile(r"\(plan [A-Z]\d?[a-z]?\b|\bplan [A-Z]\d[a-z]\b"),
    "review finding id": re.compile(r"\b(?:SEC|CORE|AI|APPW|APPR|DOM|UI|DOC|TOOL)-\d{2}\b"),
    "numbered rule": re.compile(r"\(rule (?:1\d\d|2\d\d)\)|\brule of (?:1\d\d|2\d\d)\b"),
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
        "the case list (since 231) shows",
        "a step's source (185; the owner's request)",
        "| 188: `measure` measures every golden set |",
        "decided in DECISIONS 231",
        "the process pack (plan stage C, C2b)",
        "the product's facts (D-c6)",
        "Stage D0: the shared capability that fills an output",
        "does not change a released result (decision 160 D1); the run view",
        "agree (decision 163) and the preselection",
        "the documents only 174 (review 160): the sure pairs",
        "**141 (the sports club's trial; engine 1.9.0):** a line",
        "**137: a ledger export and its PDF companion.**",
        "`activity`, 216: `waiting`",
        "**New case** (*Uj ugy*, 231 U0) on the Cases page",
        "a version released before 178: the built-in template",
        "the logic pack's (plan A3, A4)",
        "approved again (rule 218), as it reopened",
        "the workflows' rule of 146 for a case's step",
        "Code review SEC-03, SEC-04, TOOL-10: push rules",
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
        "After a live run of 100 invoices two more come in; a score between 0 and 100",
        "Character 100 of the part is character 8100 of the document; up to 200 M Ft",
        "the candidates are capped at 250; a page of 120 lines",
        "a meter reading of \"882 kWh\", \"(143,00 m3)\"",
        "at most 255 per Choice; above a total of 200 000 000 HUF; within 120 seconds before 100 ms",
        "the review (Settings > Rules), a decision's rule file, plan the release; 15 → 7",
    ],
)
def test_patterns_leave_ordinary_text_alone(line):
    assert _hits(line) == []


# 265 (code review DOC-17): the config files go to GitHub too; their notes (the changelog, the file's description, a
# code-level note) describe the system, not the development process
CONFIG_NOTE_KEYS = ("note", "_note", "notes", "description")
INTERNAL_DOCUMENT = re.compile(r"\b(?:handoffs?|BACKLOG|ROADMAP|DECISIONS?)\b|\bbacklog [A-Z]")


# A file whose fingerprint is kept with results: an approved reconciliation statement (its rules have changed, a note),
# a kept AI answer or proposal (an older question), a statement read, a party proposal. Its description is part of the
# fingerprint (the changelog is not), so it is cleaned at the file's next real change, not by itself.
FINGERPRINT_BOUND = {"configs/reconcile.json", "configs/callsites/reconcile_line.json", "configs/statement_tables.json",
                     "configs/gpt_quote_letter.json", "configs/rule_proposals.json", "configs/gpt_rule_proposal.json",
                     "configs/callsites/rule_proposal.json", "configs/parties.json"}


def _config_notes(obj, bound=False, top=True):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and k in CONFIG_NOTE_KEYS:
                if not (bound and top is None):
                    yield v
            else:
                yield from _config_notes(v, bound, None if (top and k == "meta") else False)
    elif isinstance(obj, list):
        for v in obj:
            yield from _config_notes(v, bound, False)


CONFIGS = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "configs").rglob("*.json"))


@pytest.mark.parametrize("config", CONFIGS)
def test_config_notes_have_no_internal_information(config):
    import json

    found = []
    for note in _config_notes(json.loads((ROOT / config).read_text(encoding="utf-8")), config in FINGERPRINT_BOUND):
        found += [f"{hit} in a note starting {note[:60]!r}" for hit in _hits(note)]
        if INTERNAL_DOCUMENT.search(note):
            found.append(f"internal document: {INTERNAL_DOCUMENT.search(note).group(0)!r} in {note[:80]!r}")
    assert found == []
