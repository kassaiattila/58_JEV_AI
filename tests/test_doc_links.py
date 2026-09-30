"""A dokumentumok relatív hivatkozásai élnek (040, K0; docs/guides/DOCUMENTATION.md).

070 (döntés 2026-09-29): a kódtári dokumentum belső munkaanyagra nem hivatkozhat linkkel, mert az a tárban nincs meg
(`jav/doc_scope.py`). A belső belépő dokumentumok hivatkozásai csak helyben ellenőrizhetők; friss klónon kimaradnak.
"""

import re
from pathlib import Path
from urllib.parse import unquote

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


# 073: links to a heading ("file.md#anchor" or "#anchor") must match a heading of the target, using GitHub's slug
# rules; translating a heading otherwise breaks the link silently.
_ANCHOR_LINK = re.compile(r"\]\(([^)\s:#]*)#([^)\s]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


def _slug(heading: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)  # a link in a heading keeps only its text
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        m = None if in_fence else _HEADING.match(line)
        if m:
            base = _slug(m.group(1))
            n = counts.get(base, 0)
            anchors.add(base if n == 0 else f"{base}-{n}")  # GitHub numbers repeated headings: x, x-1, x-2
            counts[base] = n + 1
    return anchors


def test_slug_follows_github_rules():
    assert _slug("6. Execution layer: work package → run → worker (040 K1, 2026-09-27)") == \
        "6-execution-layer-work-package--run--worker-040-k1-2026-09-27"
    assert _slug("10.3 Receptek") == "103-receptek"


@pytest.mark.parametrize("doc", PUBLIC_DOCS)
def test_public_doc_heading_links_resolve(doc):
    path = ROOT / doc
    broken = []
    for target, anchor in _ANCHOR_LINK.findall(path.read_text(encoding="utf-8")):
        file = (path.parent / target) if target else path
        if file.suffix == ".md" and file.is_file() and unquote(anchor) not in _anchors(file):
            broken.append(f"{target}#{anchor}")
    assert broken == []


@pytest.mark.parametrize("doc", INTERNAL_ENTRY_DOCS)
def test_internal_entry_doc_links_resolve(doc):
    path = ROOT / doc
    if not path.is_file():
        pytest.skip("belső munkaanyag: csak helyben van meg")
    assert [m for m in _links(path) if not (path.parent / m).exists()] == []
