"""A logic pack's own released version in the shared version store (186, plan G-full-move T2d; DECISIONS 185).

Guarantees tested:
- a reconciliation's approval is a version of the shared version store (`package_release`): its statement as the
  content, its fingerprint, who approved it and when, the lines it locks, and its file in the shared file store in its
  state (approved; earlier once reopened); what the reconciliation shows of its approval stays as it was, and the
  shared release view of the package does not list it (a logic pack without runs is approved its own way);
- an older store's own version tables of the reconciliation are copied into the shared ones once, the stored files
  byte for byte; the shared file table is rebuilt with each file's state, its rows kept; the older tables keep their
  rows, read by nothing.
Synthetic data only; no AI call, no network.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from jav import package_release, reconcile_package as rp, reconcile_statement as rs, registrations, store
from tests.test_reconcile_statement_145 import _world


@pytest.fixture
def db(tmp_path):
    registrations.load_all()
    with store.use_store(tmp_path / "r186.sqlite"):
        yield


def _meta(v: dict) -> dict:
    return {k: v[k] for k in ("version", "approved_by", "reopened_by", "reopen_note")}


def test_a_reconciliations_approval_is_a_version_in_the_shared_version_store(db) -> None:
    wp_id, _inv, ids = _world()
    shown = rs.current(wp_id)
    rs.approve(wp_id, fingerprint=shown["fingerprint"], actor="Reviewer")
    [v] = package_release.own_versions(wp_id)
    assert _meta(v) == {"version": 1, "approved_by": "Reviewer", "reopened_by": None, "reopen_note": None}
    assert v["fingerprint"] == shown["fingerprint"] and v["approved_at"]
    assert package_release.own_version(wp_id, 1)["content"] == rs.approved_version(wp_id, 1)["statement"]
    assert package_release.active_own()[wp_id]["locks"] == [ln["id"] for ln in shown["statement"]["lines"]]
    assert set(ids) <= set(rp.locks())
    # what the reconciliation shows stays as it was
    approval = rp.approval(wp_id)
    assert approval["active"]["version"] == 1 and [x["version"] for x in approval["versions"]] == [1]
    # the shared release view of a logic pack without runs does not list its own versions
    view = package_release.view(wp_id)
    assert view["versions"] == [] and view["state"] == "not_released"
    assert {b["code"] for b in view["blockers"]} == {"own_approval"}
    assert package_release.release_summary(wp_id) is None
    # its file in the shared file store, in its state
    stored, name = rs.xlsx(wp_id, version=1)
    [f] = package_release.own_files(wp_id, 1)
    assert (f["state"], f["name"], f["sha256"]) == ("approved", name, hashlib.sha256(stored).hexdigest())
    rs.reopen(wp_id, note="a payment was missed", actor="Reviewer")
    assert [f["state"] for f in package_release.own_files(wp_id, 1)] == ["approved", "earlier"]
    assert package_release.active_own() == {} and rp.locks() == {}
    assert _meta(package_release.own_versions(wp_id)[0]) == {"version": 1, "approved_by": "Reviewer",
                                                             "reopened_by": "Reviewer", "reopen_note": "a payment was missed"}


def test_a_second_approval_after_a_reopening_is_the_next_version(db) -> None:
    wp_id, _inv, _ids = _world()
    rs.approve(wp_id, fingerprint=rs.current(wp_id)["fingerprint"], actor="Reviewer")
    rs.reopen(wp_id, note="checked again", actor="Reviewer")
    rs.approve(wp_id, fingerprint=rs.current(wp_id)["fingerprint"], actor="Other Reviewer")
    assert [(v["version"], v["approved_by"], v["reopened_at"] is None) for v in package_release.own_versions(wp_id)] == [
        (2, "Other Reviewer", True), (1, "Reviewer", False)]
    assert [f["state"] for f in package_release.own_files(wp_id, 2)] == ["approved"]


# --- an older store ----------------------------------------------------------------------------------------------------

# the version tables as 171-185 (shared) and 145-185 (the reconciliation's own) made them
_OLD = """
CREATE TABLE package_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, workpackage_id TEXT NOT NULL, version INTEGER NOT NULL,
    mark TEXT NOT NULL, items TEXT NOT NULL, runs TEXT NOT NULL, released_by TEXT NOT NULL, released_at TEXT NOT NULL,
    backfilled_at TEXT, UNIQUE (workpackage_id, version));
CREATE TABLE package_version_files (version_id INTEGER NOT NULL, name TEXT NOT NULL, media TEXT NOT NULL,
    rows INTEGER NOT NULL, sha256 TEXT NOT NULL, content BLOB NOT NULL, template TEXT, template_version TEXT,
    PRIMARY KEY (version_id, name));
CREATE TABLE reconcile_versions (id INTEGER PRIMARY KEY AUTOINCREMENT, workpackage_id TEXT NOT NULL, version INTEGER NOT NULL,
    content TEXT NOT NULL, fingerprint TEXT NOT NULL, line_ids TEXT NOT NULL, approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL, reopened_by TEXT, reopened_at TEXT, reopen_note TEXT, UNIQUE (workpackage_id, version));
CREATE TABLE reconcile_version_files (version_id INTEGER NOT NULL, state TEXT NOT NULL, name TEXT NOT NULL,
    template TEXT NOT NULL, template_version TEXT NOT NULL, sha256 TEXT NOT NULL, content BLOB NOT NULL,
    created_at TEXT NOT NULL, backfilled_at TEXT, PRIMARY KEY (version_id, state));
INSERT INTO package_versions VALUES (1, 'wp-docs', 1, 'mark-1', '[["item-1", "run-1"]]', '["run-1"]', 'Releaser', 't1', NULL);
INSERT INTO package_version_files VALUES (1, 'result.json', 'application/json', 1, 'sha-json', X'7B7D', NULL, NULL);
INSERT INTO package_version_files VALUES (1, 'result.xlsx', 'xlsx', 1, 'sha-xlsx', X'504B', 'builtin', '1.0.0');
INSERT INTO reconcile_versions VALUES (7, 'wp-reconcile', 1, '{"lines": []}', 'fp-1', '["line-1"]', 'Reviewer', 't2',
    'Reviewer', 't3', 'checked again');
INSERT INTO reconcile_versions VALUES (8, 'wp-reconcile', 2, '{"lines": [1]}', 'fp-2', '["line-1", "line-2"]', 'Reviewer',
    't4', NULL, NULL, NULL);
INSERT INTO reconcile_version_files VALUES (7, 'approved', 'statement-v1.xlsx', 'builtin', '1.1.0', 'sha-a', X'0102', 't2', NULL);
INSERT INTO reconcile_version_files VALUES (7, 'earlier', 'statement-v1.xlsx', 'builtin', '1.1.0', 'sha-e', X'0304', 't3', NULL);
INSERT INTO reconcile_version_files VALUES (8, 'approved', 'statement-v2.xlsx', 'own-1', '3', 'sha-b', X'0506', 't4', 't5');
"""


def _rows(path: Path, table: str) -> list[tuple]:
    with sqlite3.connect(path) as c:
        return c.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()


def test_an_older_stores_own_versions_and_files_are_copied_into_the_shared_ones_once(tmp_path) -> None:
    registrations.load_all()
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as c:
        c.executescript(_OLD)
    older = {t: _rows(path, t) for t in ("reconcile_versions", "reconcile_version_files")}
    with store.use_store(path):
        versions = package_release.own_versions("wp-reconcile")
        assert [(v["version"], v["fingerprint"], v["reopen_note"]) for v in versions] == [(2, "fp-2", None),
                                                                                            (1, "fp-1", "checked again")]
        assert package_release.own_version("wp-reconcile", 2)["content"] == {"lines": [1]}
        assert package_release.active_own() == {"wp-reconcile": {**versions[0], "locks": ["line-1", "line-2"]}}
        assert [(f["state"], f["name"], f["template"], f["created_at"], f["backfilled_at"])
                for f in package_release.own_files("wp-reconcile", 1)] == [
            ("approved", "statement-v1.xlsx", "builtin", "t2", None), ("earlier", "statement-v1.xlsx", "builtin", "t3", None)]
        assert package_release.own_file("wp-reconcile", 1, "earlier")["content"] == b"\x03\x04"
        assert package_release.own_file("wp-reconcile", 2, "approved")["template"] == "own-1"
        # the shared release of a processing package is as it was, its files with their state
        assert package_release.version_file("wp-docs", 1, "result.xlsx")[0] == b"PK"
        with store.connect() as c:
            files = c.execute("SELECT version_id, state, name, sha256 FROM package_version_files ORDER BY version_id, state,"
                              " name").fetchall()
        assert [tuple(r) for r in files][:2] == [(1, "released", "result.json", "sha-json"),
                                                 (1, "released", "result.xlsx", "sha-xlsx")]
        assert len(files) == 5
    assert {t: _rows(path, t) for t in older} == older  # the older tables keep their rows
    store._initialized.clear()
    with store.use_store(path):  # checked again: nothing copied twice
        assert len(package_release.own_versions("wp-reconcile")) == 2
        with store.connect() as c:
            assert c.execute("SELECT COUNT(*) FROM package_version_files").fetchone()[0] == 5


def test_a_new_store_has_only_the_shared_version_tables(db) -> None:
    with store.connect() as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"package_versions", "package_version_files"} <= tables
    assert not tables & {"reconcile_versions", "reconcile_version_files"}
