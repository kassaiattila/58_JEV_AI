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


def test_eslint_runs_after_the_type_check_and_its_failure_is_named(tmp_path, monkeypatch) -> None:
    """265 (code review UI-14): ESLint is part of the check; a finding fails it with ESLint's summary."""
    from pathlib import Path
    from types import SimpleNamespace

    ui = tmp_path / "ui"
    (ui / "node_modules" / ".bin").mkdir(parents=True)
    for name in ("tsc", "vitest"):
        (ui / "node_modules" / ".bin" / f"{name}.cmd").write_text("", encoding="utf-8")
    out = "C:/ui/src/a.tsx\n  3:7  error  'x' is assigned a value but never used  no-unused-vars\n\n1 problem (1 error, 0 warnings)\n"
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        linting = Path(cmd[0]).stem == "eslint"
        return SimpleNamespace(stdout=out if linting else "", stderr="", returncode=1 if linting else 0)

    monkeypatch.setattr(preflight.subprocess, "run", run)
    assert preflight.run_ui_checks(tmp_path, ui_dir=ui) == (
        False, "the UI's eslint is not installed in ui/node_modules (npm ci)")
    (ui / "node_modules" / ".bin" / "eslint.cmd").write_text("", encoding="utf-8")
    seen.clear()
    ok, summary = preflight.run_ui_checks(tmp_path, ui_dir=ui)
    assert not ok and summary.startswith("ESLint: 1 problem (1 error, 0 warnings)") and "no-unused-vars" in summary
    assert [c for c in seen if Path(c[0]).stem == "vitest"] == []  # the tests do not run after a finding
