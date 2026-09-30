"""A dokumentumok relatív hivatkozásai élnek (040, K0; docs/guides/DOCUMENTATION.md).

070 (döntés 2026-09-29): a kódtári dokumentum belső munkaanyagra nem hivatkozhat linkkel, mert az a tárban nincs meg
(`jav/doc_scope.py`). A belső belépő dokumentumok hivatkozásai csak helyben ellenőrizhetők; friss klónon kimaradnak.
"""

import re
from pathlib import Path

import pytest

from jav import doc_scope

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = sorted(
    p.relative_to(ROOT).as_posix()
    for p in [ROOT / "README.md", ROOT / "CLAUDE.md", *(ROOT / "docs").rglob("*.md")]
    if p.is_file() and p.name != "STATE.md" and not doc_scope.is_internal(p.relative_to(ROOT).as_posix())
)
INTERNAL_ENTRY_DOCS = ["docs/INDEX.md", "docs/plans/070/PLAN.md", "docs/reports/2026-09-27-readme-tortenet.md"]
_LINK = re.compile(r"\]\(([^)#:\s]+)(?:#[^)]*)?\)")


def _links(path: Path) -> list[str]:
    # helyi bizonyíték (runs/) és generált állapotoldal: friss klónon nincs meg, a létezésük nem ellenőrizhető
    return [m for m in _LINK.findall(path.read_text(encoding="utf-8")) if "runs/" not in m and not m.endswith("STATE.md")]


def _target(path: Path, link: str) -> str:
    return (path.parent / link).resolve().relative_to(ROOT).as_posix()


def test_public_docs_are_found():
    assert {"README.md", "CLAUDE.md", "docs/ARCHITECTURE.md", "docs/guides/SETUP.md"} <= set(PUBLIC_DOCS)
    assert not [d for d in PUBLIC_DOCS if doc_scope.is_internal(d)]


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_public_doc_links_resolve_and_stay_in_the_repository(doc):
    path = ROOT / doc
    links = _links(path)
    assert [m for m in links if doc_scope.is_internal(_target(path, m))] == []
    assert [m for m in links if not (path.parent / m).exists()] == []


@pytest.mark.parametrize("doc", INTERNAL_ENTRY_DOCS)
def test_internal_entry_doc_links_resolve(doc):
    path = ROOT / doc
    if not path.is_file():
        pytest.skip("belső munkaanyag: csak helyben van meg")
    assert [m for m in _links(path) if not (path.parent / m).exists()] == []
