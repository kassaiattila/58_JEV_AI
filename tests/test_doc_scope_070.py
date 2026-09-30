"""070 (decision of 2026-09-29): internal working documents stay local, untracked; one boundary (`jav/doc_scope.py`)."""

from pathlib import Path

import pytest

from jav import doc_scope

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("rel", [
    "docs/handoffs/069-2026-09-29-handoff.md", "docs/handoffs/TEMPLATE.md", "docs/plans/070/PLAN.md",
    "docs/plans/039/ui-concept.html", "docs/reports/2026-09-29-v1.0.4-kiadas.md", "docs/callsites/select.md",
    "docs/BACKLOG.md", "docs/DECISIONS.md", "docs/ROADMAP.md", "docs/INDEX.md", "docs/CONTINUE_PROMPT_031.md",
    "docs/FRAMEWORK_ASSESSMENT_2026-09-22.md", "docs/CAPABILITY_CATALOG_2026-09-22.md", "docs\\handoffs\\001-x.md",
])
def test_internal_paths(rel):
    assert doc_scope.is_internal(rel)


@pytest.mark.parametrize("rel", [
    "README.md", "CLAUDE.md", "docs/ARCHITECTURE.md", "docs/GLOSSARY.md", "docs/JEV_PLAYBOOK.md",
    "docs/guides/SETUP.md", "docs/flows/invoice/FLOW.md", "docs/handoffs", "docs/plans_notes.md",
    "docs/guides/NOTES_2026-09-22.md", "jav/handoffs/x.md", "x/docs/BACKLOG.md",
])
def test_public_paths(rel):
    assert not doc_scope.is_internal(rel)


def test_gitignore_lists_every_internal_pattern():
    lines = {ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert [p for p in doc_scope.INTERNAL_DOC_PATTERNS if p not in lines] == []


def test_internal_doc_files_walks_only_internal_files(tmp_path):
    for rel in ("docs/handoffs/001-a.md", "docs/plans/070/PLAN.md", "docs/BACKLOG.md", "docs/ARCHITECTURE.md",
                "docs/guides/SETUP.md", "README.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    got = [p.relative_to(tmp_path).as_posix() for p in doc_scope.internal_doc_files(tmp_path)]
    assert got == ["docs/BACKLOG.md", "docs/handoffs/001-a.md", "docs/plans/070/PLAN.md"]
    assert doc_scope.internal_doc_files(tmp_path / "nincs") == []
