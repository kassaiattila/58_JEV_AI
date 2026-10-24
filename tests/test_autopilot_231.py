"""231 (DECISIONS 231): the autopilot of the Claude Code hooks.

The owner's decision of 2026-10-24: Claude goes on through an approved plan without a new session, and stops only when
the owner has to decide. While the autopilot is on, the Stop hook of Claude Code blocks the stop (`decision: block`)
unless the decision marker is written, a background task still runs, or two stops in a row changed nothing (stuck).
The Codex hooks call the same script without `--host claude`, so they never block.
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
    spec = importlib.util.spec_from_file_location("handoff_guard_231", ROOT / "scripts" / "hooks" / "handoff_guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = tmp_path / ".claude" / "autopilot"
    monkeypatch.setattr(module, "AUTOPILOT_DIR", folder)
    monkeypatch.setattr(module, "AUTOPILOT_STATE", folder / "state.json")
    monkeypatch.setattr(module, "NEEDS_OWNER", folder / "needs_owner.md")
    return module


def _main(guard, monkeypatch, capsys, *argv: str, payload: dict | None = None) -> str:
    monkeypatch.setattr(sys, "argv", ["handoff_guard.py", *argv])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload or {})))
    assert guard.main() == 0
    return capsys.readouterr().out


def test_after_work_the_stop_is_blocked_and_names_the_plan(guard) -> None:
    state = {"enabled": True, "plan": "docs/plans/x.md", "fingerprint": "old", "idle": 0}
    reason, new, message = guard.autopilot_stop(state, {}, needs_owner=False, fingerprint="new")
    assert reason is not None and "docs/plans/x.md" in reason and "needs_owner.md" in reason
    assert (new["fingerprint"], new["idle"], message) == ("new", 0, None)


def test_a_pending_owner_decision_lets_the_stop_through(guard) -> None:
    state = {"enabled": True, "plan": "p.md", "fingerprint": "old", "idle": 0}
    reason, new, message = guard.autopilot_stop(state, {}, needs_owner=True, fingerprint="new")
    assert reason is None and new == state and "needs_owner.md" in message


def test_a_running_background_task_lets_the_stop_through(guard) -> None:
    state = {"enabled": True, "plan": "p.md", "fingerprint": "old", "idle": 0}
    reason, new, message = guard.autopilot_stop(state, {"background_tasks": [{"id": "t1"}]}, needs_owner=False,
                                                fingerprint="new")
    assert (reason, new, message) == (None, state, None)


def test_two_stops_in_a_row_with_nothing_changed_let_the_stop_through(guard) -> None:
    state = {"enabled": True, "plan": "p.md", "fingerprint": "same", "idle": 0}
    reason, state, message = guard.autopilot_stop(state, {}, needs_owner=False, fingerprint="same")
    assert reason == guard.BLOCK_IDLE and state["idle"] == 1 and message is None
    reason, state, message = guard.autopilot_stop(state, {}, needs_owner=False, fingerprint="same")
    assert reason is None and state["idle"] == 2 and "stuck" in message
    # work again: the counter starts over
    reason, state, _ = guard.autopilot_stop(state, {}, needs_owner=False, fingerprint="changed")
    assert reason is not None and state["idle"] == 0


def test_the_switch_needs_an_existing_plan_and_off_keeps_the_rest(guard, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["handoff_guard.py", "autopilot", "on", "--plan", "docs/plans/none.md"])
    assert guard.main() == 2
    assert _main(guard, monkeypatch, capsys, "autopilot", "on", "--plan", "CLAUDE.md").startswith("autopilot ON")
    state = guard.autopilot_state()
    assert state["plan"] == "CLAUDE.md" and state["idle"] == 0
    assert _main(guard, monkeypatch, capsys, "autopilot", "off").startswith("autopilot OFF")
    assert guard.autopilot_state() is None
    assert json.loads(guard.AUTOPILOT_STATE.read_text(encoding="utf-8"))["plan"] == "CLAUDE.md"


def test_the_session_start_shows_the_pending_question_and_the_plans_progress(guard, tmp_path, monkeypatch) -> None:
    plan = tmp_path / "plan.md"
    heading = "## Halad" + chr(0xE1) + "s"  # the internal plans' Hungarian heading, spelt without the letter itself
    plan.write_text(f"# Plan\n\n{heading}\n\n- A0 done\n- A1 next\n\n## Other\n\nnot shown\n", encoding="utf-8")
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    guard.AUTOPILOT_DIR.mkdir(parents=True)
    guard.NEEDS_OWNER.write_text("Which reminder?\n- (A) a task\n", encoding="utf-8")
    text = "\n".join(guard.autopilot_lines({"enabled": True, "plan": "plan.md", "since": "2026-10-24T20:00:00+02:00"}))
    assert "[autopilot] ON" in text and "Which reminder?" in text
    assert "- A1 next" in text and "not shown" not in text


def test_without_the_claude_host_the_stop_never_blocks(guard, monkeypatch, capsys) -> None:
    guard.save_autopilot({"enabled": True, "plan": "CLAUDE.md", "fingerprint": "old", "idle": 0})
    monkeypatch.setattr(guard, "work_fingerprint", lambda: "new")
    monkeypatch.setattr(guard, "stop_message", lambda *a: None)
    out = _main(guard, monkeypatch, capsys, "stop")
    assert '"decision"' not in out


def test_with_the_claude_host_the_stop_is_blocked(guard, monkeypatch, capsys) -> None:
    guard.save_autopilot({"enabled": True, "plan": "CLAUDE.md", "fingerprint": "old", "idle": 0})
    monkeypatch.setattr(guard, "work_fingerprint", lambda: "new")
    out = _main(guard, monkeypatch, capsys, "stop", "--host", "claude")
    answer = json.loads(out)
    assert answer["decision"] == "block" and "CLAUDE.md" in answer["reason"]
    assert guard.autopilot_state()["fingerprint"] == "new"
