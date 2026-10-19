"""175 (plan 170 E4, decision K18): the kinds of what people do and what the logs record, in one registry
(`jav/activity_kinds.py`): the log events of packages and workflows, the sources of "My work today", the decisions a
run's reviewed version is made of, and the task kinds of an email's task proposal. Synthetic data only; no AI call.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from jav import activity_kinds, corrections, datasets, email_tasks, store, work, workflows
from tests.test_activity_labels_171 import _recorded_actions
from tests.test_characterisation_171 import RUN, _run, db  # noqa: F401  (the fixture)

ROOT = Path(__file__).resolve().parents[1]


def test_every_action_the_package_log_records_is_registered_and_none_is_stale() -> None:
    assert set(activity_kinds.events("package")) == _recorded_actions()


def test_every_package_event_and_activity_source_has_a_label() -> None:
    labels = datasets._labels("activity_action")
    assert sorted(set(activity_kinds.events("package")) - set(labels)) == []
    assert sorted({s.code for s in activity_kinds.sources() if s.action_prefix is None} - set(labels)) == []
    # a workflow's actions show in "My work today" too (the owner's decision of 2026-10-19)
    assert sorted({f"workflow_{code}" for code in activity_kinds.events("workflow")} - set(labels)) == []


def test_every_workflow_event_has_its_words_in_the_interface() -> None:
    text = (ROOT / "ui" / "src" / "views" / "workflows" / "Workflows.tsx").read_text(encoding="utf-8")
    words = text[text.index("function eventText"):]
    words = words[:words.index("\n}\n")]
    missing = [code for code in activity_kinds.events("workflow")
               if not re.search(rf"\b{code}: \"", words) and f'action === "{code}"' not in words]
    assert missing == []


def test_a_log_refuses_an_action_no_module_registered(db) -> None:  # noqa: F811
    with store.connect() as c, pytest.raises(activity_kinds.UnknownEvent):
        work._event(c, "wp-1", "renamed_by_mistake", "Reviewer One")
    with store.connect() as c, pytest.raises(activity_kinds.UnknownEvent):
        workflows._event(c, "wf-1", None, "created_by_mistake", "Reviewer One")


def test_an_action_belongs_to_one_module(monkeypatch) -> None:
    monkeypatch.setattr(activity_kinds, "_EVENTS", {log: dict(codes) for log, codes in activity_kinds._EVENTS.items()})
    activity_kinds.register_events("package", ("rename",), "jav.work")  # its own again: nothing changes
    with pytest.raises(ValueError, match="registered by jav.work already"):
        activity_kinds.register_events("package", ("rename",), "jav.elsewhere")


def test_the_reviewed_version_is_made_of_these_decisions_in_this_order() -> None:
    kinds = activity_kinds.decisions()
    assert [(k.name, k.wraps) for k in kinds] == [
        ("corrections", None), ("tasks", "corrections"), ("native", "review"), ("duplicates", "result"),
        ("reconcile", "reviewed"), ("statements", "checked")]
    assert {k.name for k in kinds} == datasets._FINGERPRINTED


def test_a_decision_kind_a_logic_package_registers_joins_the_reviewed_version_and_the_fingerprint(db, monkeypatch) -> None:  # noqa: F811
    _run()
    before = corrections.review_version(RUN), datasets._run_fingerprint({"run_id": RUN})
    monkeypatch.setattr(activity_kinds, "_DECISIONS", dict(activity_kinds._DECISIONS))
    found: list[list[str]] = []
    activity_kinds.register_decision(activity_kinds.DecisionKind("offers", lambda run_id, items, c: found, wraps="decided"))
    assert (corrections.review_version(RUN), datasets._run_fingerprint({"run_id": RUN})) == before  # none yet
    found.append(["offer-1", "accepted"])
    version, fingerprint = corrections.review_version(RUN), datasets._run_fingerprint({"run_id": RUN})
    assert version != before[0] and fingerprint.startswith(before[1] + "|")
    with pytest.raises(ValueError, match="registered twice"):
        activity_kinds.register_decision(activity_kinds.DecisionKind("offers", lambda *a: [], wraps="x"))
    with pytest.raises(ValueError, match="only the first part"):
        activity_kinds.register_decision(activity_kinds.DecisionKind("first_again", lambda *a: []))


def test_the_task_kinds_come_from_the_settings_in_the_schemas_order() -> None:
    from jav import cfg

    assert activity_kinds.task_kinds() == tuple(cfg.load("email_tasks")["actions"]) == email_tasks.ACTIONS
    assert email_tasks.Action.__args__ == email_tasks.ACTIONS  # the schema's bytes: `tests/test_characterisation_171.py`


def test_the_decisions_on_a_task_proposal_and_a_duplicate_pair_are_one_list_each() -> None:
    from jav import api, duplicates

    assert api.TaskDecision.model_fields["decision"].annotation.__args__ == store.TASK_DECISIONS == ("accepted", "rejected")
    assert api.DuplicateDecision.model_fields["decision"].annotation.__args__ == duplicates.DECISIONS


def test_a_source_and_its_order(monkeypatch) -> None:
    codes = [s.code for s in activity_kinds.sources()]
    assert codes[0] == "event" and len(codes) == len(set(codes))
    assert [s.code for s in activity_kinds.sources() if not s.flow_run] == [
        "run_start", "run_approve", "correction", "duplicate_decision", "statement_choice", "workflow"]
    monkeypatch.setattr(activity_kinds, "_SOURCES", dict(activity_kinds._SOURCES))
    with pytest.raises(ValueError, match="registered twice"):
        activity_kinds.register_source(replace(activity_kinds.sources()[0]))


def test_my_work_today_shows_a_persons_duplicate_decision_statement_choice_and_workflow_steps(db) -> None:  # noqa: F811
    """175 (the owner's decision of 2026-10-19): a person's duplicate decision, choice between two statements and own
    workflow steps are rows of the day, with their run or package; a step the workflow started by itself (recorded for
    "<maker> (auto)") and another person's are not the person's."""
    from jav import activity
    from tests.test_characterisation_171 import ACTOR, DAY, DOC_A, DOC_B, DOC_C, WP

    _run()
    with store.connect() as c:
        c.execute("INSERT INTO duplicate_decisions(pair_key, doc_id, other_doc_id, decision, run_id, actor, decided_at)"
                  " VALUES (?,?,?,?,?,?,?)", (f"{DOC_A}|{DOC_C}", DOC_A, DOC_C, "copy", RUN, ACTOR, "2026-10-08T10:01:30+00:00"))
        c.execute("INSERT INTO statement_choices(pair_key, keep_doc_id, run_id, actor, decided_at) VALUES (?,?,?,?,?)",
                  (f"{DOC_B}|{DOC_C}", DOC_B, RUN, ACTOR, "2026-10-08T10:02:00+00:00"))
        for at, action, actor, detail in (
                ("2026-10-08T10:03:00+00:00", "create", ACTOR, {"template": "monthly"}),
                ("2026-10-08T10:04:00+00:00", "link", ACTOR, {"workpackage": WP}),
                ("2026-10-08T10:05:00+00:00", "run", ACTOR, {"workpackage_id": WP, "run_id": RUN}),
                ("2026-10-08T10:06:00+00:00", "run", f"{ACTOR} (auto)", {"workpackage_id": WP, "run_id": RUN}),
                ("2026-10-08T10:07:00+00:00", "update", "Someone Else", {})):
            c.execute("INSERT INTO workflow_events(workflow_id, step, action, actor, detail, created_at) VALUES (?,?,?,?,?,?)",
                      ("wf-1", None, action, actor, json.dumps(detail), at))
    rows = activity.entries(ACTOR, DAY)
    assert [(r["action"], r["detail"], r["run_id"], r["workpackage_id"]) for r in rows] == [
        ("workflow_run", None, RUN, WP),
        ("workflow_link", None, None, WP),
        ("workflow_create", None, None, None),
        ("statement_choice", None, RUN, WP),
        ("duplicate_decision", "copy", RUN, WP),
        ("run_start", "apply", RUN, WP),
    ]
