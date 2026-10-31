"""265 (code review TOOL-12): the start-up check runs the UI's own tsc and vitest, never through npx.

With a partial `node_modules`, `npx tsc` could fetch an unrelated package named `tsc` from the network, unasked. The
check now runs `ui/node_modules/.bin/tsc` and `vitest` and says so when they are missing. Synthetic folders.
"""

from __future__ import annotations

from jav.devtools import preflight


def test_the_local_binaries_are_found_or_their_absence_is_said(tmp_path) -> None:
    ui = tmp_path / "ui"
    (ui / "node_modules" / ".bin").mkdir(parents=True)
    assert preflight.run_ui_checks(tmp_path, ui_dir=ui) == (
        False, "the UI's tsc or vitest is not installed in ui/node_modules (npm ci)")
    (ui / "node_modules" / ".bin" / "tsc.cmd").write_text("", encoding="utf-8")
    assert preflight.local_bin(ui, "tsc") == ui / "node_modules" / ".bin" / "tsc.cmd"
    assert preflight.local_bin(ui, "vitest") is None
