"""171 (plan 170, K20): every action a package's log records has a label in the activity log ("My work today").
Six codes showed raw before: the statement package's scope, account and added statements, and the reconciliation's
accepted sources, approval and reopening."""

from __future__ import annotations

import re
from pathlib import Path

from jav import activity, datasets

JAV = Path(__file__).resolve().parents[1] / "jav"

# the ways the code writes a package event: work.record_event / work._event, add_entries(event=...), work._set_wp
_RECORDED = (
    re.compile(r"\b(?:record_event|_event)\(c, [^,]+, \"([a-z_]+)\""),
    re.compile(r"\bevent=\(\"([a-z_]+)\""),
    re.compile(r"\b_set_wp\([^,]+, \"([a-z_]+)\""),
)


def _recorded_actions() -> set[str]:
    found: set[str] = set()
    for path in JAV.rglob("*.py"):
        if path.name == "workflows.py":  # its own `_event` writes the workflow's log, not a package's
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in _RECORDED:
            found.update(pattern.findall(text))
    return found


def test_the_scan_finds_the_package_events() -> None:
    found = _recorded_actions()
    assert {"archive", "items_add", "run_supersede", "reconcile_approve", "statement_scope"} <= found


def test_every_recorded_package_event_has_an_activity_label() -> None:
    labels = datasets._labels("activity_action")
    assert sorted(_recorded_actions() - set(labels)) == []


def test_every_activity_source_has_a_label() -> None:
    labels = datasets._labels("activity_action")
    assert sorted({code for code, _sql in activity._SOURCES if code != "event"} - set(labels)) == []


def test_the_six_new_labels() -> None:
    labels = datasets._labels("activity_action")
    assert labels["statement_scope"] == "statement package: party and period set"
    assert labels["statement_account"] == "statement package: bank account assigned to the party"
    assert labels["statement_add"] == "statement package: statements added"
    assert labels["reconcile_accept_sources"] == "reconciliation: command-line results accepted as sources"
    assert labels["reconcile_approve"] == "reconciliation: version approved"
    assert labels["reconcile_reopen"] == "reconciliation: approval reopened"
