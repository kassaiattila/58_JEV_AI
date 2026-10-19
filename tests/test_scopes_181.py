"""The scope of a workflow and of a work package (181, plan 170 L5; DECISIONS 181: the owner chose a general scope now).

Guarantees tested:
- a workflow's scope is what its template's steps need: the monthly reconciliation needs a party and a period as before,
  a template whose steps need neither is made without them, and its repeat keeps no period;
- an older store's workflows table is rebuilt with the party and the period optional, its rows kept;
- a package's scope comes from a person, else its logic pack (a statement package), else its workflow step (the
  workflow's party and period, the step's role); a person cannot give one to a package whose logic pack has its own;
- the roles are the finance domain's three, each with the package kinds that can hold it; the email routing's targets
  are the open packages whose scope fits; a merge of parties moves a package's scope, a deleted package's scope goes.
Synthetic names only; no AI call.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from jav import package_scope, parties, registrations, scopes, statement_table as st, store, work, workflow_steps
from jav import workflows as wf
from tests import test_workflows_146 as base

MONTH = base.MONTH


@pytest.fixture
def db(tmp_path, monkeypatch):
    # the synthetic Erste PDF is text (`tests/test_statement_erste_137.py`), as in the workflow tests
    monkeypatch.setattr(st, "_pdf_lines", lambda path: Path(path).read_text(encoding="utf-8").splitlines())
    monkeypatch.setattr(wf, "_last_tick", 0.0)
    registrations.load_all()
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def _party(name: str = "Example Kft.") -> str:
    return parties.create(name, identities=[], actor="tester")["id"]


# --- the parts of a scope ---------------------------------------------------------------------------------------------


def test_a_scope_is_checked_part_by_part_with_the_callers_error(db) -> None:
    party = _party()
    assert scopes.check(["party", "period"], {"period": MONTH, "party": party}) == {"party": party, "period": MONTH}
    assert scopes.check([], {"party": None, "period": None}) == {}
    with pytest.raises(wf.WorkflowError, match="needs an own party"):
        scopes.check(["party", "period"], {"period": MONTH}, error=wf.WorkflowError)
    with pytest.raises(wf.WorkflowError, match="needs a period"):
        scopes.check(["period"], {}, error=wf.WorkflowError)
    with pytest.raises(scopes.ScopeError, match="unknown scope part 'client'"):
        scopes.check([], {"client": "x"})
    with pytest.raises(scopes.ScopeError, match="ends before it starts"):
        scopes.check([], {"period": ("2026-07-01", "2026-06-30")})
    assert scopes.label({"party": party, "period": MONTH}) == "Example Kft. 2026-06-01 – 2026-06-30"
    assert [p.name for p in scopes.parts()] == ["party", "period"]


# --- a workflow's scope -------------------------------------------------------------------------------------------------


def test_the_monthly_reconciliation_needs_a_party_and_a_period_as_before(db) -> None:
    folder = base._invoices(db / "inv")
    steps = {"invoices": {"source": {"kind": "folder", "folder": str(folder)}},
             "statements": {"source": {"kind": "folder", "folder": str(folder)}}, "reconcile": {"source": {"kind": "none"}}}
    assert wf.template_needs(wf.template("monthly_reconciliation")) == ["party", "period"]
    with pytest.raises(wf.WorkflowError, match="needs an own party"):
        wf.create(template_id="monthly_reconciliation", party_id=None, period_start=MONTH[0], period_end=MONTH[1],
                  steps=steps, actor="tester", advance_now=False)
    with pytest.raises(wf.WorkflowError, match="needs a period"):
        wf.create(template_id="monthly_reconciliation", party_id=_party(), period_start=None, period_end=None,
                  steps=steps, actor="tester", advance_now=False)


def _documents_and_emails(monkeypatch) -> None:
    """A template of two steps that need no party and no period (a made-up one; the email routing brings a real one)."""
    conf = wf.config()
    extra = {"id": "inbox_and_folder", "group": "documents", "title": "Inbox and folder", "description": "Test only.",
             "steps": [{"id": "documents", "kind": "documents"}, {"id": "emails", "kind": "emails"}]}
    monkeypatch.setattr(wf, "config", lambda: conf | {"templates": [*conf["templates"], extra]})


def test_a_template_whose_steps_need_nothing_makes_a_workflow_without_party_or_period(db, monkeypatch) -> None:
    _documents_and_emails(monkeypatch)
    folder = base._invoices(db / "inv")
    steps = {"documents": {"source": {"kind": "folder", "folder": str(folder)}},
             "emails": {"source": {"kind": "mailbox", "request": {"accounts": ["office@example.com"], "since_days": 7}}}}
    assert wf.template_needs(wf.template("inbox_and_folder")) == []
    made = wf.create(template_id="inbox_and_folder", party_id=None, period_start=None, period_end=None, steps=steps,
                     actor="tester", advance_now=False, name="Inbox")
    w = made["workflow"]
    assert (w["party_id"], w["party"], w["period_start"], w["period_end"]) == (None, None, None, None)
    unnamed = wf.create(template_id="inbox_and_folder", party_id=None, period_start=None, period_end=None,
                        steps=steps, actor="tester", advance_now=False)
    assert unnamed["workflow"]["name"] == "Inbox and folder"  # without a scope, the template's title
    draft = wf.repeat_draft(w["id"])
    assert (draft["party_id"], draft["period_start"], draft["period_end"], draft["name"]) == (None, None, None, "Inbox")
    # a party given to a workflow that does not need it is kept
    party = _party()
    kept = wf.create(template_id="inbox_and_folder", party_id=party, period_start=None, period_end=None, steps=steps,
                     actor="tester", advance_now=False)
    assert kept["workflow"]["party_id"] == party and kept["workflow"]["name"] == "Example Kft."


def test_an_older_store_gets_its_workflows_table_rebuilt_with_its_rows(tmp_path) -> None:
    path = tmp_path / "old.sqlite"
    with sqlite3.connect(path) as c:  # the workflows table as 146-180 made it
        c.execute("""CREATE TABLE workflows (id TEXT PRIMARY KEY, template TEXT NOT NULL, definition TEXT NOT NULL,
                     name TEXT NOT NULL, party_id TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
                     auto INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'open', actor TEXT NOT NULL,
                     created_at TEXT NOT NULL, updated_at TEXT NOT NULL, previous_id TEXT)""")
        c.execute("INSERT INTO workflows VALUES ('wf-000000000001', 'monthly_reconciliation', '{}', 'June', 'party-1',"
                  " '2026-06-01', '2026-06-30', 0, 'open', 'tester', 't0', 't1', NULL)")
    with store.use_store(path), store.connect() as c:
        cols = {r[1]: r for r in c.execute("PRAGMA table_info(workflows)")}
        row = dict(c.execute("SELECT * FROM workflows").fetchone())
    assert not cols["party_id"][3] and not cols["period_start"][3] and not cols["period_end"][3]  # NOT NULL no more
    assert row["name"] == "June" and row["party_id"] == "party-1" and row["auto"] == 0 and row["updated_at"] == "t1"
    assert row["scope"] == "{}"


# --- a package's scope -----------------------------------------------------------------------------------------------------


def test_the_roles_are_the_finance_domains_three() -> None:
    registrations.load_all()
    roles = {r.name: r for r in package_scope.roles()}
    assert list(roles) == ["incoming_invoices", "outgoing_invoices", "statements"]
    assert {r.module for r in roles.values()} == {"jav.domains.finance"}
    assert roles["statements"].package_kinds == ("statements",)
    assert set(roles["incoming_invoices"].package_kinds) == set(wf.DOCUMENT_PACKAGES)
    assert roles["incoming_invoices"].fits("invoice_hu", "incoming") and not roles["incoming_invoices"].fits("invoice_hu", "outgoing")
    assert roles["outgoing_invoices"].fits("invoice_out", "outgoing") and roles["outgoing_invoices"].fits("invoice_hu", "outgoing")
    assert not roles["outgoing_invoices"].fits("invoice_hu", "incoming")
    assert roles["statements"].fits("statement_erste", None) and not roles["statements"].fits("invoice_hu", "incoming")


def test_a_person_gives_a_package_its_scope_and_the_routing_finds_it(db) -> None:
    party = _party()
    docs = work.create_from_folder(base._invoices(db / "inv"), name="June invoices", owner="tester")
    assert package_scope.scope_of(docs["id"]) is None
    with pytest.raises(package_scope.ScopeRefused, match="cannot collect"):
        package_scope.set_scope(docs["id"], party_id=party, period_start=None, period_end=None, role_name="statements",
                                actor="tester")
    with pytest.raises(package_scope.ScopeRefused, match="a party, a period or a role"):
        package_scope.set_scope(docs["id"], party_id=None, period_start=None, period_end=None, role_name=None, actor="tester")
    scope = package_scope.set_scope(docs["id"], party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                                    role_name="incoming_invoices", actor="Example Person")
    assert scope | {"set_at": None} == {"party_id": party, "party": "Example Kft.", "period_start": MONTH[0],
                                        "period_end": MONTH[1], "role": "incoming_invoices", "role_title": "Incoming invoices",
                                        "from": "own", "set_by": "Example Person", "set_at": None}
    assert work.workpackage_events(docs["id"])[-1]["action"] == "scope_set"
    assert [p["id"] for p in package_scope.fitting("incoming_invoices", party, "2026-06-15")] == [docs["id"]]
    assert package_scope.fitting("incoming_invoices", party, "2026-07-01") == []
    assert package_scope.fitting("outgoing_invoices", party, "2026-06-15") == []
    # a merge of the party moves the package's scope; its deletion takes it away
    other = _party("Example Kft (2)")
    parties.merge(party, other, actor="tester")
    assert package_scope.scope_of(docs["id"])["party_id"] == other
    assert package_scope.clear_scope(docs["id"], actor="Example Person") is None
    work.delete_workpackage(docs["id"], actor="tester")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM workpackage_scopes").fetchone()[0] == 0


def test_a_workflow_steps_package_takes_its_workflows_party_period_and_the_steps_role(db) -> None:
    party = _party()
    docs = work.create_from_folder(base._invoices(db / "inv"), name="Invoices", owner="tester")
    made = wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                     steps={"invoices": {"source": {"kind": "package", "workpackage_id": docs["id"]}},
                            "statements": {"source": {"kind": "folder", "folder": str(base._statements(db / "erste"))}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester", auto=False)
    assert made["workflow"]["id"]
    scope = package_scope.scope_of(docs["id"])
    assert (scope["party_id"], scope["period_start"], scope["period_end"], scope["role"], scope["from"]) == (
        party, MONTH[0], MONTH[1], "incoming_invoices", "workflow")
    # a person's scope wins over the workflow's
    package_scope.set_scope(docs["id"], party_id=party, period_start=None, period_end=None, role_name="outgoing_invoices",
                            actor="tester")
    assert package_scope.scope_of(docs["id"])["role"] == "outgoing_invoices"


def test_a_statement_packages_scope_is_its_own(db) -> None:
    party = _party()
    from jav import statement_package

    found = statement_package.survey([base._statements(db / "erste")], party_id=party, period_start="2026-01-01",
                                     period_end="2026-12-31")
    made = statement_package.create(name="Statements", party_id=party, period_start="2026-01-01", period_end="2026-12-31",
                                    paths=[db / "erste"], statements=[s["id"] for s in found["statements"] if s["chosen"]],
                                    pdfs=[], actor="tester")
    scope = package_scope.scope_of(made["workpackage_id"])
    assert (scope["party_id"], scope["role"], scope["from"]) == (party, "statements", "logic_pack")
    with pytest.raises(package_scope.ScopeRefused, match="its own"):
        package_scope.set_scope(made["workpackage_id"], party_id=party, period_start=None, period_end=None,
                                role_name=None, actor="tester")


def test_every_step_kind_states_what_it_needs() -> None:
    registrations.load_all()
    assert {k.kind: k.needs for k in workflow_steps.kinds()} == {
        "documents": (), "emails": (), "statements": ("party", "period"), "reconcile": ("party", "period"),
        "routing": ()}
