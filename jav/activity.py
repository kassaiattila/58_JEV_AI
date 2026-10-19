"""Per-user daily activity log ("Mai munkám" / My work today; 061 decision: active user + assignment).

No new bookkeeping; built from the existing rows that record an author: package events (rename, hide, owner…), recipe
assignment, starting and approving a run, field correction (including correcting an email's intent), closing a to-do,
task-proposal decision, mailbox pull. Modelled on the legacy V4 "Mai munkám" view (which read one shared audit table).

The day is the machine's local calendar day; timestamps are stored as UTC ISO strings, so the day bounds are converted
to UTC. Names match case-insensitively (rows from before 061 may spell the author differently). 175 (plan 170 E4): the
sources are entries of the activity registry (`jav/activity_kinds.py`), registered here in their order; a logic
package adds its own the same way.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from jav import activity_kinds, store

# every query returns the columns (at, actor, workpackage_id, run_id, detail), bound by the day; a run, a correction
# and a run's approval name the run itself, the others an item's flow id
for _source in (
    activity_kinds.Source("event", "SELECT created_at at, actor, workpackage_id, NULL run_id, action detail FROM workpackage_events"
                                   " WHERE created_at >= ? AND created_at < ?", action_prefix=""),
    activity_kinds.Source("recipe", "SELECT created_at at, actor, workpackage_id, NULL run_id, recipe_id detail FROM recipe_assignments"
                                    " WHERE created_at >= ? AND created_at < ?"),
    activity_kinds.Source("run_start", "SELECT created_at at, actor, workpackage_id, run_id, mode detail FROM runs"
                                       " WHERE created_at >= ? AND created_at < ?", flow_run=False),
    activity_kinds.Source("run_approve", "SELECT approved_at at, approved_by actor, workpackage_id, run_id, approval detail FROM runs"
                                         " WHERE approved_at >= ? AND approved_at < ?", flow_run=False),
    activity_kinds.Source("correction", "SELECT k.created_at at, k.actor, r.workpackage_id, k.run_id, k.fields detail"
                                        " FROM run_item_corrections k LEFT JOIN runs r ON r.run_id = k.run_id"
                                        " WHERE k.created_at >= ? AND k.created_at < ?", flow_run=False),
    activity_kinds.Source("reason_resolve", "SELECT closed_at at, actor, NULL workpackage_id, run_id, reason detail FROM review_reasons"
                                            " WHERE status='resolved' AND closed_at >= ? AND closed_at < ?"),
    activity_kinds.Source("task_decision", "SELECT d.decided_at at, d.actor, NULL workpackage_id, d.run_id, d.decision detail"
                                           " FROM email_task_decisions d WHERE d.decided_at >= ? AND d.decided_at < ?"),
    activity_kinds.Source("task_done", "SELECT d.done_at at, d.done_by actor, NULL workpackage_id, d.run_id, NULL detail"
                                       " FROM email_task_decisions d WHERE d.done_at >= ? AND d.done_at < ?"),  # 062
    activity_kinds.Source("mailbox_pull", "SELECT created_at at, actor, NULL workpackage_id, NULL run_id, request detail FROM mailbox_pulls"
                                          " WHERE created_at >= ? AND created_at < ?"),
    # 175 (the owner's decision of 2026-10-19): a person's duplicate decisions, statement choices and own steps of a
    # workflow (a step the workflow starts by itself is recorded for "<maker> (auto)", so it is not the person's)
    activity_kinds.Source("duplicate_decision", "SELECT decided_at at, actor, NULL workpackage_id, run_id, decision detail"
                                                " FROM duplicate_decisions WHERE decided_at >= ? AND decided_at < ?", flow_run=False),
    activity_kinds.Source("statement_choice", "SELECT decided_at at, actor, NULL workpackage_id, run_id, NULL detail"
                                              " FROM statement_choices WHERE decided_at >= ? AND decided_at < ?", flow_run=False),
    activity_kinds.Source("workflow", "SELECT created_at at, actor, COALESCE(json_extract(detail, '$.workpackage_id'),"
                                      " json_extract(detail, '$.workpackage')) workpackage_id, json_extract(detail, '$.run_id') run_id,"
                                      " action detail FROM workflow_events WHERE created_at >= ? AND created_at < ?",
                          flow_run=False, action_prefix="workflow_"),
):
    activity_kinds.register_source(_source)


def day_bounds(day: str | None) -> tuple[str, str]:
    """Bounds of the local calendar day (YYYY-MM-DD; empty: today) as UTC ISO strings."""
    d = date.fromisoformat(day) if day else datetime.now().astimezone().date()
    # 153 (review F7): each midnight with the offset of its own date (today's offset shifted a day across a summer-time
    # change by an hour; such a day is 23 or 25 hours long)
    start = datetime.combine(d, time.min).astimezone().astimezone(timezone.utc)
    end = datetime.combine(d + timedelta(days=1), time.min).astimezone().astimezone(timezone.utc)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def _flow_run(run_id: str | None) -> str | None:
    """To-do reasons and task decisions store the item's flow id (`<run>:<item>`); the run is its first part."""
    return run_id.split(":", 1)[0] if run_id else None


def entries(actor: str, day: str | None = None) -> list[dict[str, Any]]:
    """The person's actions on the day, in time order (most recent first)."""
    lo, hi = day_bounds(day)
    who = " ".join(actor.split()).casefold()
    out: list[dict[str, Any]] = []
    with store.connect() as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM workpackages")}
        run_wp = {r["run_id"]: r["workpackage_id"] for r in c.execute("SELECT run_id, workpackage_id FROM runs")}
        for source in activity_kinds.sources():
            code = source.code
            table = source.sql.split(" FROM ", 1)[1].split()[0]
            if table not in tables:  # the module's table does not exist yet (e.g. no mailbox pull so far)
                continue
            for r in c.execute(source.sql, (lo, hi)):
                if not r["actor"] or " ".join(str(r["actor"]).split()).casefold() != who:
                    continue
                run_id = _flow_run(r["run_id"]) if source.flow_run else r["run_id"]
                wp_id = r["workpackage_id"] or (run_wp.get(run_id) if run_id else None)
                own_action = source.action_prefix is not None
                action = f"{source.action_prefix}{r['detail']}" if own_action else code
                out.append({"at": r["at"], "action": action, "detail": None if own_action else _detail(code, r["detail"]),
                            "workpackage_id": wp_id, "workpackage_name": names.get(wp_id) if wp_id else None, "run_id": run_id})
    out.sort(key=lambda e: e["at"], reverse=True)
    return out


def _detail(code: str, raw: Any) -> str | None:
    """Short detail for the action without personal data (field values and email content never go here)."""
    if raw is None or code == "event":
        return None
    if code == "mailbox_pull":
        try:
            req = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return req.get("mailbox") if isinstance(req, dict) else None
    if code == "correction":
        # 167 (review 153 E): which fields were corrected (their keys; the values never go here), so the row says what
        # was done; the item id it showed before is a hash and said nothing
        try:
            fields = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if not isinstance(fields, dict):
            return None
        return ",".join(sorted(fields)) or None
    return str(raw)
