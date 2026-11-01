"""265 (R4-b): a before/after snapshot or replay and a full test run never run at the same time.

Side by side on one machine they slowed each other: six tests failed in the full run (isolated readers past their time
limits, a timer past its deadline), all green one by one. The comparison now holds the full test run's lock and says
so when another heavy run holds it. A temporary lock file; nothing is read.
"""

from __future__ import annotations

import argparse

from jav.cli import maintenance_cli
from jav.devtools import preflight


def test_a_comparison_refuses_beside_a_full_run(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(preflight, "FULL_RUN_LOCK", tmp_path / "full.lock")
    args = argparse.Namespace(baseline=str(tmp_path / "none"), work=str(tmp_path / "w"), out=str(tmp_path / "o.jsonl"),
                              no_items=True, matches=False, size=1, jev_cache=None)
    with preflight.full_run_lock():
        assert maintenance_cli.cmd_before_after_snapshot(args) == 2
        assert maintenance_cli.cmd_before_after_replay(args) == 2
    said = capsys.readouterr().out
    assert said.count("a full test run or another comparison is going on this machine") == 2
    assert maintenance_cli.cmd_before_after_snapshot(args) == 2  # free again: now it fails on the missing backup
    assert "no snapshot:" in capsys.readouterr().out and not (tmp_path / "o.jsonl").exists()
