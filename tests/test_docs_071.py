"""071 D-teljesség: a kódtári leírások követik a kódot.

- A beállítófájlok leírása (`docs/guides/CONFIGS.md`) minden `configs/*.json`-t megnevez: új beállítófájl nem maradhat le.
- A változáslista a mostani verziót is tartalmazza (a kiadáskor a verzióval együtt lép).
- A README jegyzéke az új kódtári dokumentumokra mutat.
"""

from __future__ import annotations

from pathlib import Path

from jav import version

ROOT = Path(__file__).resolve().parents[1]


def test_configs_guide_names_every_top_level_config():
    guide = (ROOT / "docs" / "guides" / "CONFIGS.md").read_text(encoding="utf-8")
    missing = [p.name for p in sorted((ROOT / "configs").glob("*.json")) if p.name not in guide]
    assert missing == []


def test_changelog_has_the_current_version():
    assert f"## v{version.VERSION} " in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def test_readme_lists_the_codebase_documents():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for rel in ("docs/SECURITY.md", "docs/guides/USER_GUIDE.md", "docs/guides/CONFIGS.md", "CHANGELOG.md",
                "docs/ARCHITECTURE.md", "docs/GLOSSARY.md", "docs/guides/SETUP.md"):
        assert f"]({rel})" in readme, rel
