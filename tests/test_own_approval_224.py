"""224 (plan G-process-core P3c): a logic pack's own approval writes in one order, whatever its kind.

Plain-language summary: a reconciliation's statement and a quote are approved by a person as the package's own
version. Each kind checks its own blockers and the fingerprint the person saw, in its own words; the write is shared
(`jav/app/package_release.py`): the version with its content and locks, the kind's files, and the package log's
`<kind>_approve` entry, in one transaction; reopening likewise. Only one own version of a package holds at a time: the
shared store refuses a second one, so a kind that forgot to check cannot approve twice in a race. The reconciliation's
and the quote's own tests (145, 186, 192) stay as they were.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from jav.app import package_release, registrations, work
from jav.core import store
from tests.test_reconcile_statement_145 import _world

JAV = Path(__file__).resolve().parents[1] / "jav"


@pytest.fixture
def db(tmp_path):
    registrations.load_all()
    with store.use_store(tmp_path / "r224.sqlite"):
        yield


def _events(wp_id: str, *actions: str) -> list[tuple[str, dict]]:
    return [(e["action"], json.loads(e["detail"] or "{}")) for e in work.workpackage_events(wp_id) if e["action"] in actions]


def test_an_approval_writes_its_version_its_files_and_its_log_entry_together(db) -> None:
    wp_id, _inv, _ids = _world()
    made = []
    with store.connect() as c:
        store.begin_immediate(c)
        n = package_release.approve_own(c, wp_id, event="reconcile", content={"lines": []}, fingerprint="f1",
                                        locks=["line-1"], actor="Reviewer", files=lambda c, n: made.append(n),
                                        details={"lines": 1})
    assert n == 1 and made == [1]
    assert package_release.own_approval(wp_id)["active"]["fingerprint"] == "f1"
    assert package_release.active_own()[wp_id]["locks"] == ["line-1"]
    assert _events(wp_id, "reconcile_approve") == [("reconcile_approve", {"version": 1, "fingerprint": "f1", "lines": 1})]


def test_a_failing_file_leaves_nothing_written(db) -> None:
    wp_id, _inv, _ids = _world()

    def broken(c, n):
        raise RuntimeError("the template could not be filled")

    with pytest.raises(RuntimeError), store.connect() as c:
        store.begin_immediate(c)
        package_release.approve_own(c, wp_id, event="reconcile", content={}, fingerprint="f1", locks=[], actor="Reviewer",
                                    files=broken, details={})
    assert package_release.own_versions(wp_id) == [] and _events(wp_id, "reconcile_approve") == []


def test_only_one_own_version_holds_at_a_time(db) -> None:
    wp_id, _inv, _ids = _world()
    with store.connect() as c:
        store.begin_immediate(c)
        package_release.record_own(c, wp_id, content={}, fingerprint="f1", locks=[], actor="Reviewer")
    with pytest.raises(package_release.OwnVersionHolds) as refused, store.connect() as c:
        store.begin_immediate(c)
        package_release.approve_own(c, wp_id, event="reconcile", content={}, fingerprint="f2", locks=[], actor="Other",
                                    files=lambda c, n: None, details={})
    assert isinstance(refused.value, work.RevisionConflict)
    assert refused.value.template == "version {{version}} was approved meanwhile; reload the package"  # type: ignore[attr-defined]
    assert [v["fingerprint"] for v in package_release.own_versions(wp_id)] == ["f1"]
    assert _events(wp_id, "reconcile_approve") == []


def test_reopening_writes_its_files_and_its_log_entry_and_nothing_without_a_holding_version(db) -> None:
    wp_id, _inv, _ids = _world()
    made = []
    with store.connect() as c:
        store.begin_immediate(c)
        assert package_release.reopen_logged(c, wp_id, event="reconcile", note="why", actor="Reviewer") is None
        package_release.record_own(c, wp_id, content={}, fingerprint="f1", locks=[], actor="Reviewer")
        n = package_release.reopen_logged(c, wp_id, event="reconcile", note="a line was wrong", actor="Reviewer",
                                          files=lambda c, n: made.append(n))
    assert n == 1 and made == [1]
    [v] = package_release.own_versions(wp_id)
    assert (v["reopened_by"], v["reopen_note"]) == ("Reviewer", "a line was wrong")
    assert _events(wp_id, "reconcile_reopen") == [("reconcile_reopen", {"version": 1, "note": "a line was wrong"})]


def test_the_kinds_approve_and_reopen_through_the_shared_steps() -> None:
    """No logic pack writes an own version or its approval's log entry by itself."""
    writers = re.compile(r"package_release\.(record_own|reopen_own)\(|record_event\([^)]*\"\w+_(approve|reopen)\"")
    found = [p.relative_to(JAV.parent).as_posix() for p in JAV.rglob("*.py")
             if "__pycache__" not in p.parts and p.name != "package_release.py" and writers.search(p.read_text(encoding="utf-8"))]
    assert found == []
