"""265 (the owner's decision of 2026-10-31): a second Claude session works beside the main one.

The autopilot's state is a file of the checkout, not of a session, so before 265 the Stop hook of any Claude session
started in the main folder was blocked by the main session's plan, and every stop moved that plan's idle count. Now the
autopilot belongs to the session that switched it on (or, when the switch could not tell, to the first session that
stops after it); another session's stops go through and leave the state alone. A session started in a linked worktree
reads the internal documents (handoffs, plans, STATE.md), which are not in git, from the main checkout.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def guard(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("handoff_guard_265", ROOT / "scripts" / "hooks" / "handoff_guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = tmp_path / ".claude" / "autopilot"
    monkeypatch.setattr(module, "AUTOPILOT_DIR", folder)
    monkeypatch.setattr(module, "AUTOPILOT_STATE", folder / "state.json")
    monkeypatch.setattr(module, "NEEDS_OWNER", folder / "needs_owner.md")
    monkeypatch.setattr(module, "DOCS_ROOT", ROOT)
    monkeypatch.setattr(module, "work_fingerprint", lambda: "new")
    monkeypatch.setattr(module, "stop_message", lambda *a: None)
    monkeypatch.delenv(module.SESSION_ENV, raising=False)
    monkeypatch.delenv("CLAUDE_ENV_FILE", raising=False)
    return module


def _main(guard, monkeypatch, capsys, *argv: str, payload: dict | None = None) -> str:
    monkeypatch.setattr(sys, "argv", ["handoff_guard.py", *argv])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload or {})))
    assert guard.main() == 0
    return capsys.readouterr().out


def _on(guard, session: str | None) -> dict:
    state = {"enabled": True, "since": "2026-10-31T11:00:00+01:00", "plan": "CLAUDE.md", "fingerprint": "old",
             "idle": 0, "session": session}
    guard.save_autopilot(state)
    return state


def test_another_sessions_stop_goes_through_and_leaves_the_state_alone(guard, monkeypatch, capsys) -> None:
    before = _on(guard, "main-session")
    out = _main(guard, monkeypatch, capsys, "stop", "--host", "claude", payload={"session_id": "parallel-session"})
    assert '"decision"' not in out
    assert json.loads(guard.AUTOPILOT_STATE.read_text(encoding="utf-8")) == before


def test_the_owners_stop_is_still_blocked(guard, monkeypatch, capsys) -> None:
    _on(guard, "main-session")
    out = _main(guard, monkeypatch, capsys, "stop", "--host", "claude", payload={"session_id": "main-session"})
    answer = json.loads(out)
    assert answer["decision"] == "block" and "CLAUDE.md" in answer["reason"]
    assert guard.autopilot_state()["fingerprint"] == "new"


def test_the_first_stop_after_the_switch_claims_an_unowned_autopilot(guard, monkeypatch, capsys) -> None:
    _on(guard, None)
    out = _main(guard, monkeypatch, capsys, "stop", "--host", "claude", payload={"session_id": "main-session"})
    assert json.loads(out)["decision"] == "block"
    assert guard.autopilot_state()["session"] == "main-session"
    out = _main(guard, monkeypatch, capsys, "stop", "--host", "claude", payload={"session_id": "parallel-session"})
    assert '"decision"' not in out


def test_a_claim_is_kept_when_the_stop_goes_through(guard, monkeypatch, capsys) -> None:
    _on(guard, None)
    guard.AUTOPILOT_DIR.mkdir(parents=True, exist_ok=True)
    guard.NEEDS_OWNER.write_text("Which order?\n", encoding="utf-8")
    out = _main(guard, monkeypatch, capsys, "stop", "--host", "claude", payload={"session_id": "main-session"})
    assert '"decision"' not in out and "needs_owner.md" in out
    assert guard.autopilot_state()["session"] == "main-session"


def test_a_host_that_names_no_session_is_treated_as_the_owner(guard, monkeypatch, capsys) -> None:
    _on(guard, "main-session")
    out = _main(guard, monkeypatch, capsys, "stop", "--host", "claude")
    assert json.loads(out)["decision"] == "block"


def test_the_switch_records_the_session_from_its_option_or_the_environment(guard, monkeypatch, capsys) -> None:
    out = _main(guard, monkeypatch, capsys, "autopilot", "on", "--plan", "CLAUDE.md", "--session", "s-option")
    assert out.startswith("autopilot ON") and guard.autopilot_state()["session"] == "s-option"
    monkeypatch.setenv(guard.SESSION_ENV, "s-env")
    _main(guard, monkeypatch, capsys, "autopilot", "on", "--plan", "CLAUDE.md")
    assert guard.autopilot_state()["session"] == "s-env"
    monkeypatch.delenv(guard.SESSION_ENV)
    _main(guard, monkeypatch, capsys, "autopilot", "on", "--plan", "CLAUDE.md")
    assert guard.autopilot_state()["session"] is None
    assert "session: -" in _main(guard, monkeypatch, capsys, "autopilot", "status")


def test_another_sessions_start_names_the_autopilot_without_its_plan(guard, tmp_path, monkeypatch) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n\n## Progress\n\n- A1 next\n", encoding="utf-8")
    monkeypatch.setattr(guard, "DOCS_ROOT", tmp_path)
    state = {"enabled": True, "plan": "plan.md", "since": "2026-10-31T11:00:00+01:00", "session": "main-session"}
    text = "\n".join(guard.autopilot_lines(state, "parallel-session"))
    assert "another Claude session" in text and "plan.md" in text
    assert "- A1 next" not in text and "Continue the plan" not in text
    own = "\n".join(guard.autopilot_lines(state, "main-session"))
    assert "Continue the plan" in own and "- A1 next" in own


def test_the_session_start_names_the_session_for_its_own_commands(guard, tmp_path, monkeypatch, capsys) -> None:
    env_file = tmp_path / "session.env"
    monkeypatch.setenv("CLAUDE_ENV_FILE", str(env_file))
    _main(guard, monkeypatch, capsys, "session-start", "--host", "claude", payload={"session_id": "9d28d8ab-1234"})
    # a plain NAME=value line: on Windows the PowerShell tool takes only such lines, and only if every line is one
    assert env_file.read_text(encoding="utf-8") == f"{guard.SESSION_ENV}=9d28d8ab-1234\n"
    # a session id that is not a plain token never reaches the shell file
    _main(guard, monkeypatch, capsys, "session-start", "--host", "claude", payload={"session_id": "x; rm -rf /"})
    assert env_file.read_text(encoding="utf-8").count("\n") == 1


def test_a_linked_worktree_reads_the_internal_documents_from_the_main_checkout(tmp_path, guard) -> None:
    main, worktree = tmp_path / "main", tmp_path / "main_worktrees" / "par"
    (main / ".git").mkdir(parents=True)
    worktree.mkdir(parents=True)
    common = str(main / ".git")
    assert guard.docs_root(worktree, common) == worktree  # the main checkout has no handoffs: nothing to read there
    (main / "docs" / "handoffs").mkdir(parents=True)
    assert guard.docs_root(worktree, common) == main
    assert guard.docs_root(main, ".git") == main  # the main checkout reads its own
    assert guard.docs_root(worktree, None) == worktree  # no git: the checkout itself


def test_the_plan_is_read_from_the_documents_root(guard, tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    (tmp_path / "docs" / "plans" / "p.md").write_text("# P\n\n## Progress\n\n- step one\n", encoding="utf-8")
    monkeypatch.setattr(guard, "DOCS_ROOT", tmp_path)
    assert _main(guard, monkeypatch, capsys, "autopilot", "on", "--plan", "docs/plans/p.md").startswith("autopilot ON")
    assert guard.plan_progress("docs/plans/p.md")[-1] == "- step one"
