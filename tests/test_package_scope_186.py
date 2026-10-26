"""The shared scope of a work package (186, plan G-full-move T2b; DECISIONS 185: the owner chose the full move).

Guarantees tested:
- what each logic pack shows of its package's scope stays as it was: a statement package's party and period, a
  reconciliation package's accounts, period, party and revision, a routing package's email packages;
- each one is kept in the shared scope store (`package_scope.stored`): the party, the period and the role in their
  columns, a logic pack's further parts (a reconciliation's accounts, a routing's email packages) beside them, and one
  revision step per change;
- the shared store's one party reference keeps a party in use from being deleted and moves every scope in a merge; a
  deleted package's scope goes with it;
- an older store's three own scope tables (statement, reconciliation, routing) are copied into the shared one once,
  with their rows left as they were; a scope deleted afterwards does not come back, and a package found in two of them
  stops the copy instead of losing one.
Synthetic names and made-up accounts only; no AI call.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from jav.domains.email import email_routing
from jav.app import package_scope, parties, registrations, work
from jav.core import store
from jav.domains.finance import reconcile_package as rp, statement_package as sp
from tests import test_email_routing_181 as routing_base
from tests.test_email_routing_181 import _routing
from tests import test_reconcile_package_131 as p131
from tests import test_statement_package_140 as sp140
from tests.statement_pdf import pdf_lines_as_text

OWN_KEY = p131.OWN_KEY


@pytest.fixture
def db(tmp_path, monkeypatch):
    # the synthetic statement PDFs hold their lines as plain text (`tests/test_statement_package_140.py`)
    pdf_lines_as_text(monkeypatch)
    registrations.load_all()
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def _party(name: str = "Example Kft.") -> str:
    return parties.create(name, identities=[], actor="tester")["id"]


def _reconciliation(party: str | None = None) -> str:
    p131._stmt("stmt", p131._line())
    return rp.create(name="April", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30", actor="reviewer",
                     party_id=party)["workpackage_id"]


def _stored(wp_id: str) -> dict | None:
    """The shared store's scope without its time."""
    found = package_scope.stored(wp_id)
    return None if found is None else {k: v for k, v in found.items() if k != "set_at"}


# --- what each logic pack shows stays as it was ------------------------------------------------------------------------


def test_a_statement_packages_scope_shows_as_before_and_is_in_the_shared_store(db) -> None:
    party = _party()
    wp = sp140._package(db, party)
    shown = sp.scope(wp)
    assert shown.pop("updated_at")
    assert shown == {"workpackage_id": wp, "party_id": party, "party": {"id": party, "name": "Example Kft."},
                     "period_start": "2026-05-01", "period_end": "2026-06-30", "revision": 2}  # 231 C3b4: its case binds it
    assert package_scope.scope_of(wp) == {"party_id": party, "party": "Example Kft.", "period_start": "2026-05-01",
                                          "period_end": "2026-06-30", "role": "statements", "role_title": "Bank statements",
                                          "from": "logic_pack"}
    stored = _stored(wp)  # 231 (C3b4): its case's step names it, with its rule
    parts = stored.pop("parts")
    assert parts["rule"] == "statements" and parts["owner_step"].endswith(":process")
    assert stored == {"party_id": party, "period_start": "2026-05-01", "period_end": "2026-06-30", "role": "statements",
                      "revision": 2, "set_by": "tester"}
    # a person cannot take it away: the package keeps its own scope
    assert package_scope.clear_scope(wp, actor="tester")["from"] == "logic_pack"
    assert _stored(wp)["party_id"] == party


def test_a_reconciliation_packages_scope_shows_as_before_and_changes_with_its_revision(db) -> None:
    party = _party()
    wp = _reconciliation(party)
    shown = rp.scope(wp)
    assert shown.pop("updated_at")
    assert shown == {"workpackage_id": wp, "accounts": [OWN_KEY], "period_start": "2026-04-01", "period_end": "2026-04-30",
                     "revision": 1, "party_id": party, "party": {"id": party, "name": "Example Kft."}}
    assert package_scope.scope_of(wp) is None  # a reconciliation collects no documents for a role
    assert _stored(wp) == {"party_id": party, "period_start": "2026-04-01", "period_end": "2026-04-30", "role": None,
                           "parts": {"party": party, "period": ["2026-04-01", "2026-04-30"], "accounts": [OWN_KEY]},
                           "revision": 1, "set_by": "reviewer"}  # 231 (C2d, C3a-2): a case keeps its party and period as parts too
    rp.set_scope(wp, accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-05-31", expected_revision=1,
                 actor="other reviewer", party_id=None)
    with pytest.raises(work.RevisionConflict, match="revision 2, not 1"):
        rp.set_scope(wp, accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-06-30", expected_revision=1,
                     actor="tester")
    assert (rp.scope(wp)["revision"], rp.scope(wp)["party"]) == (2, None)
    assert work.get(wp)["source_ref"].startswith("pack:reconciliation@")  # 231 (C3a-2): a case's reference names its pack
    assert _stored(wp) == {"party_id": None, "period_start": "2026-04-01", "period_end": "2026-05-31", "role": None,
                           "parts": {"period": ["2026-04-01", "2026-05-31"], "accounts": [OWN_KEY]}, "revision": 2,
                           "set_by": "other reviewer"}
    assert [e["action"] for e in work.workpackage_events(wp)].count("reconcile_scope") == 2


def test_a_routing_packages_email_packages_show_as_before_and_are_in_the_shared_store(db) -> None:
    from jav.app import work_views

    mails, _ = routing_base._mailbox(db, {"m1": ("invoice.pdf", "inbox")})
    routing = _routing(mails, "June routing")
    assert email_routing.sources_of(routing) == [mails]
    assert work_views.workpackage_view(mails)["intake"][0]["cases"] == [{"id": routing, "name": "June routing"}]
    assert _stored(routing) == {"party_id": None, "period_start": None, "period_end": None, "role": None,
                                "parts": {"sources": [mails]}, "revision": 1, "set_by": "tester"}  # 231 (C1c): a case's


def test_a_persons_scope_is_in_the_shared_store_and_steps_its_revision(db) -> None:
    party = _party()
    docs = work.create_workpackage(name="June invoices", source_kind="folder", source_ref=None, owner="tester")["id"]
    package_scope.set_scope(docs, party_id=party, period_start=None, period_end=None, role_name="incoming_invoices",
                            actor="tester")
    package_scope.set_scope(docs, party_id=party, period_start="2026-06-01", period_end="2026-06-30",
                            role_name="incoming_invoices", actor="Example Person")
    assert package_scope.scope_of(docs)["from"] == "own"
    assert _stored(docs) == {"party_id": party, "period_start": "2026-06-01", "period_end": "2026-06-30",
                             "role": "incoming_invoices", "parts": {}, "revision": 2, "set_by": "Example Person"}
    assert package_scope.clear_scope(docs, actor="tester") is None and package_scope.stored(docs) is None


# --- one party reference, and the deletion ---------------------------------------------------------------------------


def test_one_reference_keeps_a_party_in_use_and_a_merge_moves_every_scope(db) -> None:
    party, other = _party(), _party("Other Home")
    statements = sp140._package(db, party)
    reconciliation = _reconciliation(party)
    docs = work.create_workpackage(name="Invoices", source_kind="folder", source_ref=None, owner="tester")["id"]
    package_scope.set_scope(docs, party_id=party, period_start=None, period_end=None, role_name="incoming_invoices",
                            actor="tester")
    with pytest.raises(parties.PartyError):
        parties.delete(party, actor="tester")
    parties.merge(party, other, actor="tester")
    assert sp.scope(statements)["party"]["id"] == other
    assert rp.scope(reconciliation)["party"]["id"] == other
    assert package_scope.scope_of(docs)["party_id"] == other


def test_a_deleted_packages_scope_goes_with_it(db) -> None:
    party = _party()
    statements = sp140._package(db, party)
    reconciliation = _reconciliation(party)
    work.delete_workpackage(statements, actor="tester")  # 231 (C1c): a routing is a case now, not deleted while it runs
    assert package_scope.stored(statements) is None
    with pytest.raises(work.NotReady):  # (C3a-2) a reconciliation too: its case's container stays, hidden if need be
        work.delete_workpackage(reconciliation, actor="tester")
    with store.connect() as c:  # the reconciliation's scope is left (231 C3b4: and the statements' case's own)
        left = [r[0] for r in c.execute("SELECT workpackage_id FROM workpackage_scopes")]
    assert reconciliation in left and statements not in left and len(left) == 2


# --- an older store's own scope tables -------------------------------------------------------------------------------

# the four scope tables as 133-185 made them
_OLD = """
CREATE TABLE workpackage_scopes (workpackage_id TEXT PRIMARY KEY, party_id TEXT, period_start TEXT, period_end TEXT,
    role TEXT, set_by TEXT NOT NULL, set_at TEXT NOT NULL);
CREATE TABLE statement_scopes (workpackage_id TEXT PRIMARY KEY, party_id TEXT NOT NULL, period_start TEXT NOT NULL,
    period_end TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, actor TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE reconcile_scopes (workpackage_id TEXT PRIMARY KEY, accounts TEXT NOT NULL, period_start TEXT NOT NULL,
    period_end TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, actor TEXT NOT NULL, updated_at TEXT NOT NULL,
    party_id TEXT);
CREATE TABLE email_routing_scopes (workpackage_id TEXT PRIMARY KEY, sources TEXT NOT NULL, actor TEXT NOT NULL,
    created_at TEXT NOT NULL);
INSERT INTO workpackage_scopes VALUES ('wp-docs', 'party-1', NULL, NULL, 'incoming_invoices', 'Example Person', 't1');
INSERT INTO statement_scopes VALUES ('wp-statements', 'party-1', '2026-05-01', '2026-06-30', 1, 'tester', 't2');
INSERT INTO reconcile_scopes VALUES ('wp-reconcile', '["acct-1", "acct-2"]', '2026-04-01', '2026-04-30', 3, 'reviewer',
    't3', NULL);
INSERT INTO email_routing_scopes VALUES ('wp-routing', '["wp-mails"]', 'tester', 't4');
"""


def _old_store(path: Path, extra: str = "") -> None:
    with sqlite3.connect(path) as c:
        c.executescript(_OLD + extra)


def _rows(path: Path, table: str) -> list[tuple]:
    with sqlite3.connect(path) as c:
        return c.execute(f"SELECT * FROM {table} ORDER BY workpackage_id").fetchall()


def test_an_older_stores_own_scope_tables_are_copied_into_the_shared_one_once(tmp_path) -> None:
    registrations.load_all()
    path = tmp_path / "old.sqlite"
    _old_store(path)
    before = {t: _rows(path, t) for t in ("statement_scopes", "reconcile_scopes", "email_routing_scopes")}
    with store.use_store(path):
        stored = {wp: package_scope.stored(wp) for wp in ("wp-docs", "wp-statements", "wp-reconcile", "wp-routing")}
    assert stored == {
        "wp-docs": {"party_id": "party-1", "period_start": None, "period_end": None, "role": "incoming_invoices",
                    "parts": {}, "revision": 1, "set_by": "Example Person", "set_at": "t1"},
        "wp-statements": {"party_id": "party-1", "period_start": "2026-05-01", "period_end": "2026-06-30",
                          "role": "statements", "parts": {}, "revision": 1, "set_by": "tester", "set_at": "t2"},
        "wp-reconcile": {"party_id": None, "period_start": "2026-04-01", "period_end": "2026-04-30", "role": None,
                         "parts": {"accounts": ["acct-1", "acct-2"]}, "revision": 3, "set_by": "reviewer", "set_at": "t3"},
        "wp-routing": {"party_id": None, "period_start": None, "period_end": None, "role": None,
                       "parts": {"emails": ["wp-mails"]}, "revision": 1, "set_by": "tester", "set_at": "t4"},
    }
    # the older tables keep their rows as they were (read by nothing; left for one release)
    assert {t: _rows(path, t) for t in before} == before
    # a scope deleted afterwards does not come back when the store is checked again
    with sqlite3.connect(path) as c:
        c.execute("DELETE FROM workpackage_scopes WHERE workpackage_id='wp-reconcile'")
    store._initialized.clear()
    with store.use_store(path):
        assert package_scope.stored("wp-reconcile") is None and package_scope.stored("wp-routing") is not None


def test_a_package_in_two_older_scope_tables_stops_the_copy(tmp_path) -> None:
    registrations.load_all()
    path = tmp_path / "old.sqlite"
    _old_store(path, "INSERT INTO statement_scopes VALUES ('wp-docs', 'party-2', '2026-01-01', '2026-01-31', 1, 't', 't');")
    with pytest.raises(package_scope.ScopeCopyError, match="wp-docs"), store.use_store(path), store.connect():
        pass
    with sqlite3.connect(path) as c:  # nothing of that table was copied, and the person's scope is as it was
        rows = dict(c.execute("SELECT workpackage_id, party_id FROM workpackage_scopes").fetchall())
        marks = [r[0] for r in c.execute("SELECT key FROM meta WHERE key LIKE 'scope_copy:%' ORDER BY key")]
    assert rows["wp-docs"] == "party-1" and "wp-statements" not in rows
    assert "scope_copy:statement_scopes" not in marks  # it is tried again until the two rows are settled


def test_a_new_store_has_only_the_shared_scope_table(db) -> None:
    with store.connect() as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "workpackage_scopes" in tables
    assert not tables & {"statement_scopes", "reconcile_scopes", "email_routing_scopes"}


def test_the_stored_parts_are_json(db) -> None:
    mails, _ = routing_base._mailbox(db, {"m1": ("invoice.pdf", "inbox")})
    routing = _routing(mails, "Routing")
    with store.connect() as c:
        raw = c.execute("SELECT parts FROM workpackage_scopes WHERE workpackage_id=?", (routing,)).fetchone()[0]
    assert json.loads(raw) == {"sources": [mails]}  # 231 (C1c): a routing case's scope part
