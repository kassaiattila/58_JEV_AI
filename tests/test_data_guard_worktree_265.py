"""265 (code review SEC-01): the data guard checks the keys' values in a linked worktree too.

Development happens in linked worktrees, which have no `.env` of their own (the keys stay in the main checkout,
CLAUDE.md §7). Before 265 the guard read `.env` from the worktree's own top folder only, so the check of the secret
values was silently off for every commit and push made there. The guard now also reads the main checkout's `.env` and
says so when it finds none. A literal assignment to one of the project's key variables is blocked by shape as well.

The secrets below are invented at run time; no real key appears in this file.
"""

from __future__ import annotations

import secrets
import subprocess
from pathlib import Path

import pytest

from jav.devtools import data_guard

AT = "@"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8").stdout


@pytest.fixture
def main_and_worktree(tmp_path, monkeypatch):
    """A main checkout with one commit and a linked worktree beside it; the installation's own `.env` is elsewhere."""
    monkeypatch.setattr(data_guard, "ENV_FILE", tmp_path / "nowhere" / ".env")
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "t" + AT + "example.com")
    _git(main, "config", "user.name", "Test")
    (main / "README.md").write_text("x\n", encoding="utf-8")
    _git(main, "add", "README.md")
    _git(main, "commit", "-q", "-m", "init")
    worktree = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "side", str(worktree))
    return main, worktree


def test_a_worktree_reads_the_main_checkouts_env(main_and_worktree):
    main, worktree = main_and_worktree
    secret = "ts-" + secrets.token_hex(16)
    (main / ".env").write_text(f"TypeSafeJAV_API_KEY={secret}\n", encoding="utf-8")
    assert not (worktree / ".env").exists()
    found = [p.resolve() for p in data_guard.env_files(worktree)]
    assert (main / ".env").resolve() in found
    guard = data_guard.load_guard(worktree)
    assert guard.env_secrets == {"TypeSafeJAV_API_KEY": secret}
    hits = guard.scan_line("a.py", 1, f"key = '{secret}'")
    assert [f.kind for f in hits] == ["env_secret"]
    assert secret not in hits[0].shown


def test_the_checkouts_own_env_counts_once(main_and_worktree):
    main, _worktree = main_and_worktree
    (main / ".env").write_text("OPENAI_API_KEY=" + "sk-" + secrets.token_hex(16) + "\n", encoding="utf-8")
    assert [p.resolve() for p in data_guard.env_files(main)] == [(main / ".env").resolve()]


def test_without_any_env_the_guard_says_so(main_and_worktree):
    _main, worktree = main_and_worktree
    guard = data_guard.load_guard(worktree)
    assert guard.env_secrets == {}
    note = data_guard.env_note(guard)
    assert note is not None and "no .env" in note


def test_with_an_env_there_is_no_note(main_and_worktree):
    main, worktree = main_and_worktree
    (main / ".env").write_text("AZURE_DI_KEY=" + secrets.token_hex(16) + "\n", encoding="utf-8")
    assert data_guard.env_note(data_guard.load_guard(worktree)) is None


@pytest.mark.parametrize("name", ["TypeSafeJAV_API_KEY", "TYPESAFE_API_KEY", "OPENAI_API_KEY", "AZURE_DI_KEY"])
@pytest.mark.parametrize("shape", ["{n}={v}", "{n} = '{v}'", '"{n}": "{v}"', "export {n}={v}"])
def test_a_literal_key_assignment_is_blocked_by_shape(name, shape):
    guard = data_guard.Guard(data_guard.load_config(), env_secrets={})
    value = secrets.token_hex(12)
    hits = guard.scan_line("a.py", 1, shape.format(n=name, v=value))
    assert "api_key" in [f.kind for f in hits]
    assert value not in " ".join(f.shown for f in hits)


@pytest.mark.parametrize("text", ["TypeSafeJAV_API_KEY=ts-...", "OPENAI_API_KEY=sk-...", "os.environ['OPENAI_API_KEY']",
                                  "AZURE_DI_KEY=", 'monkeypatch.delenv("AZURE_DI_KEY", raising=False)'])
def test_placeholders_and_names_alone_pass(text):
    guard = data_guard.Guard(data_guard.load_config(), env_secrets={})
    assert [f for f in guard.scan_line(".env.example", 1, text) if f.kind == "api_key"] == []
