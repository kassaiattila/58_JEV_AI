"""073 language guard (plan N-angol): tracked files may not gain Hungarian lines, and comment-only translations are
verifiable (jav/lang_guard.py)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from jav import lang_guard

ROOT = Path(__file__).resolve().parents[1]


def _guard(baseline: dict[str, int] | None = None, allow: tuple[str, ...] = ()) -> lang_guard.Guard:
    return lang_guard.Guard(version="test", allow=allow, baseline=baseline or {})


def test_counts_lines_with_hungarian_letters_only():
    assert lang_guard.hungarian_lines("plain English\n# megjegyzés\nszámla, fizetés\nReceptek\n") == 2


def test_a_file_may_not_exceed_its_baseline_and_a_new_file_may_not_have_any():
    guard = _guard({"jav/a.py": 3})
    over = lang_guard.excess({"jav/a.py": 3, "jav/b.py": 1, "jav/c.py": 0}, guard)
    assert [(e.path, e.lines, e.limit) for e in over] == [("jav/b.py", 1, 0)]
    assert [e.path for e in lang_guard.excess({"jav/a.py": 4}, guard)] == ["jav/a.py"]


def test_update_only_lowers_and_accept_raises_one_file():
    guard = _guard({"docs/A.md": 10, "jav/a.py": 5, "jav/gone.py": 2})
    counts = {"docs/A.md": 4, "jav/a.py": 7, "tests/new.py": 3}
    assert lang_guard.lowered_baseline(counts, guard) == {"docs/A.md": 4, "jav/a.py": 5}
    assert lang_guard.lowered_baseline(counts, guard, ("tests/new.py",)) == {"docs/A.md": 4, "jav/a.py": 5, "tests/new.py": 3}


def test_allowed_patterns_are_never_counted():
    assert _guard(allow=("ui/src/i18n/*.json",)).allowed("ui/src/i18n/en-core.json")
    assert not _guard(allow=("ui/src/i18n/*.json",)).allowed("ui/src/labels.ts")


OLD = '''"""Modul leírása."""
import os


def f(x):
    """Összead."""
    # megjegyzés
    return x + 1  # sorvégi


class K:
    """Osztály."""
'''


def test_same_code_ignores_comments_and_docstrings():
    new = OLD.replace("Modul leírása.", "Module description.").replace("Összead.", "Adds one.") \
        .replace("# megjegyzés", "# comment").replace("# sorvégi", "# trailing").replace('"""Osztály."""', '"""Class."""')
    assert lang_guard.same_python_code(OLD, new)


def test_same_code_ignores_a_removed_docstring():
    assert lang_guard.same_python_code(OLD, OLD.replace('    """Összead."""\n', ""))


@pytest.mark.parametrize("old,new", [("x + 1", "x + 2"), ("import os", "import sys"), ("def f(x)", "def f(y)")])
def test_same_code_detects_real_changes(old, new):
    assert not lang_guard.same_python_code(OLD, OLD.replace(old, new))


def test_same_code_treats_a_message_change_as_a_code_change():
    assert not lang_guard.same_python_code('print("szia")\n', 'print("hello")\n')


def test_changed_python_code_in_a_scratch_repo(tmp_path: Path):
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "core.hooksPath=/dev/null"]
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text(OLD, encoding="utf-8")
    (tmp_path / "b.py").write_text("X = 1\n", encoding="utf-8")
    subprocess.run([*git, "add", "."], cwd=tmp_path, check=True)
    subprocess.run([*git, "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text(OLD.replace("# megjegyzés", "# comment"), encoding="utf-8")
    (tmp_path / "b.py").write_text("X = 2\n", encoding="utf-8")
    assert lang_guard.changed_python_code(tmp_path, "HEAD") == ["b.py"]


def test_the_repository_is_within_its_baseline():
    guard = lang_guard.load_guard(ROOT)
    assert lang_guard.excess(lang_guard.scan(ROOT, guard), guard) == []
