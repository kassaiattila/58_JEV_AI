"""The Windows lifecycle launcher preserves the guard's process status."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts" / "hooks" / "codex-hooks.json"


@pytest.mark.slow
@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher contract")
# 265 (code review TOOL-08): each event and each exit code once - three PowerShell processes, not nine
@pytest.mark.parametrize(("event", "exit_code"), [("SessionStart", 0), ("PreCompact", 2), ("Stop", 7)])
def test_windows_launcher_preserves_guard_exit_code(tmp_path, event, exit_code):
    command = json.loads(CONFIG.read_text(encoding="utf-8"))["hooks"][event][0]["hooks"][0]["commandWindows"]
    guard = tmp_path / "synthetic_guard.py"
    guard.write_text(f"raise SystemExit({exit_code})\n", encoding="utf-8")
    # Replace only the two resolved paths; execute the configured launcher itself.
    command = command.replace(
        "(Join-Path $projectRoot '.venv/Scripts/python.exe')",
        "'" + sys.executable.replace("'", "''") + "'",
    ).replace(
        "(Join-Path $projectRoot 'scripts/hooks/handoff_guard.py')",
        "'" + str(guard).replace("'", "''") + "'",
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT, input="{}", capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == exit_code, result.stderr
