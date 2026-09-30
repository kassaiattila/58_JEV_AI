"""The non-blocking Stop behaviour of the handoff-guard hook (scripts/hooks/handoff_guard.py) (040, decision 4)."""

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "hooks" / "handoff_guard.py"
_spec = importlib.util.spec_from_file_location("handoff_guard", _PATH)
hg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hg)


def test_fresh_handoff_gives_no_message():
    g = {"branch": "main", "head": "abc1234", "dirty": 3, "commits_since_handoff": 5}
    assert hg.stop_message(hg.STALE_MINUTES - 1, g, 41) is None


def test_stale_handoff_reminds_without_blocking_text():
    g = {"branch": "k0", "head": "abc1234", "dirty": 2, "commits_since_handoff": 4}
    msg = hg.stop_message(hg.STALE_MINUTES + 30, g, 41)
    assert "041" in msg and "4 commit" in msg and "Commitold" in msg


def test_clean_tree_skips_commit_hint():
    g = {"branch": "k0", "head": "abc1234", "dirty": 0, "commits_since_handoff": 0}
    assert "Commitold" not in hg.stop_message(hg.STALE_MINUTES + 30, g, 41)


def test_git_line_handles_missing_git_and_unknown_count():
    assert hg.format_git_line(None) == "git: nem elérhető"
    g = {"branch": "main", "head": "abc1234", "dirty": 0, "commits_since_handoff": None}
    assert "nem állapítható meg" in hg.format_git_line(g)


def test_commits_are_counted_from_the_time_the_handoff_was_written(tmp_path, monkeypatch):
    """070: the handoff is an internal working document, not in any commit; counting starts from the handoff file's
    write time."""
    handoff = tmp_path / "070-2026-09-30-handoff.md"
    handoff.write_text("x", encoding="utf-8")
    calls = []

    def fake_git(*args):
        calls.append(args)
        return {"rev-parse": "abc1234", "status": " M a.py", "rev-list": "3", "branch": "main"}[args[0]]

    monkeypatch.setattr(hg, "git", fake_git)
    g = hg.git_summary(handoff)
    assert g == {"branch": "main", "head": "abc1234", "dirty": 1, "commits_since_handoff": 3}
    rev_list = next(a for a in calls if a[0] == "rev-list")
    assert rev_list[1] == "--count" and rev_list[2].startswith("--since=") and rev_list[3] == "HEAD"
    assert not [a for a in calls if a[0] == "log"]  # the handoff's git history does not matter


def test_stop_event_never_blocks(monkeypatch, capsys):
    monkeypatch.setattr(hg, "staleness_minutes", lambda _h: hg.STALE_MINUTES + 999)
    monkeypatch.setattr(hg, "refresh_state", lambda: "STATE.md friss")
    monkeypatch.setattr(hg.sys, "argv", ["handoff_guard.py", "stop"])
    monkeypatch.setattr(hg.sys, "stdin", type("S", (), {"read": staticmethod(lambda: "{}")})())
    assert hg.main() == 0
    out = capsys.readouterr().out
    assert '"decision"' not in out and "systemMessage" in out
