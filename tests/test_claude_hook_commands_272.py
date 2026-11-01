"""272 (K3, the check of TOOL-13): every Claude Code hook command starts its script from the project folder.

265 (TOOL-13) made the hooks name their script under `$CLAUDE_PROJECT_DIR`, so a session started in a subfolder still
finds it; the change was tried by hand only. Here every command hook of `.claude/settings.json` is read: it names a
script under the project folder, and the script exists. The agent hooks have no command. Offline.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _commands() -> list[str]:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return [h["command"] for groups in settings["hooks"].values() for group in groups for h in group["hooks"]
            if h.get("type") == "command"]


def test_every_command_hook_starts_from_the_project_folder() -> None:
    commands = _commands()
    assert len(commands) >= 3
    for command in commands:
        script = re.search(r'"\$CLAUDE_PROJECT_DIR/([^"]+)"', command)
        assert script is not None, command
        assert (ROOT / script.group(1)).is_file(), script.group(1)
