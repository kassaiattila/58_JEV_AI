"""146 (backlog F-package-kind-chooser; DECISIONS 146): workflows - the work packages of one job, chained.

The owner's decisions of 2026-10-11: a step-by-step wizard over templates; a template of several steps makes a
workflow of one own party and a period whose next step starts by itself once the steps it waits for are approved, as a
live run, and a paid step only within the budget a person approved in the wizard (never raised by itself); three
workflows: the monthly reconciliation, from the mailbox to the reconciliation, and both invoice sources together.

No AI call: the invoices' run is started but never processed (its approval is set by hand in the test, as a person's
would be), the bank statements are a synthetic Erste export read by code, and the mailbox is a stand-in.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from jav import cfg, mailbox, parties, statement_table as st, store, work, workflows as wf
from jav.runtime import queue, worker
from tests import test_statement_erste_137 as erste

MONTH = ("2026-06-01", "2026-06-30")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "_pdf_lines", lambda path: Path(path).read_text(encoding="utf-8").splitlines())
    monkeypatch.setattr(wf, "_last_tick", 0.0)
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def _party() -> str:
    return parties.create("Example Kft.", identities=[], actor="tester")["id"]


def _invoices(folder: Path, n: int = 2) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for i in range(n):  # never processed: the test only makes the package and starts its run
        (folder / f"invoice-{i}.pdf").write_bytes(b"%PDF-1.4\n% synthetic invoice " + str(i).encode() + b"\n%%EOF\n")
    return folder


def _statements(folder: Path) -> Path:
    erste._export(folder, "20260630", erste.JUNE, pdf=erste.PDF_JUNE)
    return folder


def _process_all() -> None:
    while (job := queue.claim("workflow-test")) is not None:
        worker.process(job)


def _approve_by_hand(run_id: str) -> None:
    """A person's approval of the invoices' live run, which the test never processes (its items would call AI)."""
    with store.connect() as c:
        c.execute("UPDATE runs SET approval='approved', approved_by='tester', approved_at='2026-10-11T20:00:00+00:00'"
                  " WHERE run_id=?", (run_id,))


def _steps(view: dict) -> dict[str, dict]:
    return {s["id"]: s for s in view["steps"]}


# --- the templates ----------------------------------------------------------------------------------------------------------


def test_the_templates_are_the_four_kinds_and_three_workflows_each_waiting_only_for_earlier_steps():
    conf = cfg.load("workflows")
    kinds = set(conf["kinds"])
    assert kinds == {"documents", "emails", "statements", "reconcile"} == set(wf.PACKAGE_KINDS)
    groups = {g["id"] for g in conf["groups"]}
    singles = [t for t in conf["templates"] if not wf.is_workflow(t)]
    assert sorted(t["steps"][0]["kind"] for t in singles) == sorted(kinds)
    chains = {t["id"]: [s["kind"] for s in t["steps"]] for t in conf["templates"] if wf.is_workflow(t)}
    assert chains == {"monthly_reconciliation": ["documents", "statements", "reconcile"],
                      "mailbox_reconciliation": ["emails", "statements", "reconcile"],
                      "two_sources_reconciliation": ["documents", "emails", "statements", "reconcile"]}
    for t in conf["templates"]:
        assert t["group"] in groups
        seen: set[str] = set()
        for s in t["steps"]:
            assert s["kind"] in kinds and set(s.get("after", [])) <= seen, (t["id"], s["id"])
            seen.add(s["id"])


# --- making one ---------------------------------------------------------------------------------------------------------


def test_a_workflow_needs_a_template_of_several_steps_a_party_a_period_and_every_steps_source(db):
    party = _party()
    folder = _invoices(db / "inv")
    good = {"invoices": {"source": {"kind": "folder", "folder": str(folder)}},
            "statements": {"source": {"kind": "folder", "folder": str(folder)}}, "reconcile": {"source": {"kind": "none"}}}

    def make(**kw):
        args = {"template_id": "monthly_reconciliation", "party_id": party, "period_start": MONTH[0],
                "period_end": MONTH[1], "steps": good, "actor": "tester", "advance_now": False} | kw
        return wf.create(**args)

    for kw, message in (({"template_id": "documents"}, "one-step template"),
                        ({"template_id": "nothing"}, "unknown workflow template"),
                        ({"party_id": "party-000000000000"}, "unknown own party"),
                        ({"period_start": "2026-07-01"}, "ends before it starts"),
                        ({"steps": {k: v for k, v in good.items() if k != "statements"}}, "needs its source"),
                        ({"steps": good | {"extra": {}}}, "unknown step"),
                        ({"steps": good | {"reconcile": {"source": {"kind": "folder", "folder": str(folder)}}}}, "takes no 'folder'"),
                        ({"steps": good | {"invoices": {"source": {"kind": "folder", "folder": str(db / "nope")}}}}, "does not exist"),
                        ({"steps": good | {"invoices": {"source": good["invoices"]["source"], "budget": {"gpt": "1"}}}}, "unknown budget"),
                        ({"steps": good | {"invoices": {"source": good["invoices"]["source"], "budget": {"jev": "-1"}}}}, "between 0")):
        with pytest.raises(wf.WorkflowError, match=message):
            make(**kw)
    made = make(names={"invoices": "Example Kft. 2026-06 · Invoices"})
    steps = _steps(made)
    assert made["workflow"]["name"] == "Example Kft. 2026-06-01 – 2026-06-30" and made["total"] == 3 and made["done"] == 0
    assert [s["state"] for s in made["steps"]] == ["waiting", "waiting", "waiting"]
    assert [s["status"] for s in made["steps"]] == ["ready", "ready", "waiting"]  # the reconciliation waits for both
    assert steps["invoices"]["name"] == "Example Kft. 2026-06 · Invoices"
    assert steps["statements"]["name"] == "Example Kft. 2026-06-01 – 2026-06-30 · Bank statements"


def test_a_steps_package_must_be_of_its_kind_and_of_no_other_workflow(db):
    party = _party()
    docs = work.create_from_folder(_invoices(db / "inv"), name="Invoices", owner="tester")
    base = {"invoices": {"source": {"kind": "package", "workpackage_id": docs["id"]}},
            "statements": {"source": {"kind": "folder", "folder": str(db)}}, "reconcile": {"source": {"kind": "none"}}}
    with pytest.raises(wf.WorkflowError, match="not of a statements step's kind"):
        wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                  steps=base | {"statements": {"source": {"kind": "package", "workpackage_id": docs["id"]}}},
                  actor="tester", advance_now=False)
    made = wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                     steps=base, actor="tester", auto=False)
    assert _steps(made)["invoices"]["state"] == "linked" and wf.workflow_of(docs["id"])["id"] == made["workflow"]["id"]
    assert work.run_rows(docs["id"]) == []  # the chain starts no run on a package a person brought
    with pytest.raises(wf.WorkflowError, match="already belongs to a workflow"):
        wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                  steps=base, actor="tester", advance_now=False)


# --- the chain ----------------------------------------------------------------------------------------------------------------


def test_the_monthly_reconciliation_runs_its_steps_waits_for_a_budget_and_makes_the_reconciliation_last(db):
    party = _party()
    made = wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                     steps={"invoices": {"source": {"kind": "folder", "folder": str(_invoices(db / "inv"))}},
                            "statements": {"source": {"kind": "folder", "folder": str(_statements(db / "erste"))}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester")
    wf_id = made["workflow"]["id"]
    steps = _steps(made)
    # the invoices would cost money and no budget was approved: the package is made, its run waits for a person
    assert steps["invoices"]["state"] == steps["invoices"]["status"] == "needs_budget"
    assert steps["invoices"]["package"]["id"] and work.run_rows(steps["invoices"]["package"]["id"]) == []
    assert set(steps["invoices"]["note"]["over"]) and steps["invoices"]["note"]["budget"] == {}
    # the statements are read by code for free: their live run started at once
    assert steps["statements"]["state"] == "started" and steps["statements"]["status"] == "running"
    assert work.get_run(steps["statements"]["run_id"])["mode"] == "apply"
    assert made["next"] == {"step": "invoices", "status": "needs_budget"}
    _process_all()  # only the statements' items are queued
    view = wf.view(wf_id)
    assert _steps(view)["statements"]["status"] == "approve"
    work.approve_run(steps["statements"]["run_id"], actor="tester")
    assert wf.tick(now=1e9) == 1  # the reconciliation still waits for the invoices
    view = wf.view(wf_id)
    assert _steps(view)["statements"]["status"] == "approved" and _steps(view)["reconcile"]["status"] == "waiting"
    # a person approves a budget for the invoices: the run starts with the run's own estimate
    estimate = _steps(view)["invoices"]["note"]["estimate"]
    budget = {p: str(Decimal(v) + 1) for p, v in estimate.items()}
    view = wf.start_step(wf_id, "invoices", actor="Example Person", budget=budget)
    inv = _steps(view)["invoices"]
    assert inv["state"] == "started" and inv["budget"] == {p: str(Decimal(v)) for p, v in budget.items()}
    assert work.get_run(inv["run_id"])["actor"] == "Example Person"
    _approve_by_hand(inv["run_id"])
    assert wf.tick(now=1e9) == 0  # throttled
    assert wf.tick(now=2e9) == 1
    view = wf.view(wf_id)
    rec = _steps(view)["reconcile"]
    assert rec["state"] == "started" and rec["status"] == "pairing" and view["done"] == 2
    package = work.get(rec["package"]["id"])
    assert package["source_kind"] == "reconcile" and package["owner"] == "tester"
    assert wf.workflow_of(package["id"]) == {"id": wf_id, "name": view["workflow"]["name"], "step": "reconcile",
                                             "step_title": "Reconciliation"}
    actions = [(e["step"], e["action"]) for e in reversed(view["events"])]
    assert actions == [(None, "create"), ("invoices", "needs_budget"), ("statements", "run"), ("invoices", "budget"),
                       ("invoices", "run"), ("reconcile", "package")]
    assert next(e for e in view["events"] if e["action"] == "budget")["actor"] == "Example Person"


def test_a_step_with_nothing_new_is_done_and_leaves_no_empty_package(db):
    party = _party()
    (db / "empty").mkdir()
    statements = _statements(db / "erste")
    before = {w["id"] for w in work.list_workpackages()}
    made = wf.create(template_id="monthly_reconciliation", party_id=party, period_start="2025-01-01",
                     period_end="2025-01-31", steps={"invoices": {"source": {"kind": "folder", "folder": str(db / "empty")}},
                                                     "statements": {"source": {"kind": "folder", "folder": str(statements)}},
                                                     "reconcile": {"source": {"kind": "none"}}}, actor="tester")
    steps = _steps(made)
    assert steps["invoices"]["state"] == "nothing_new" and steps["invoices"]["done"]
    assert steps["statements"]["state"] == "nothing_new" and "outside the period" in steps["statements"]["note"]
    assert {w["id"] for w in work.list_workpackages()} == before
    # both done: the reconciliation starts, but the party has no account with a statement yet
    rec = steps["reconcile"]
    assert rec["state"] == "failed" and "no account" in rec["note"] and made["next"]["step"] == "reconcile"


def test_a_failed_step_shows_why_and_a_person_retries_it(db, monkeypatch):
    party = _party()
    folder = _invoices(db / "inv")
    calls = []

    def broken(*args, **kwargs):
        calls.append(1)
        raise OSError("the disk is gone")

    monkeypatch.setattr(work, "create_from_folder", broken)
    made = wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                     steps={"invoices": {"source": {"kind": "folder", "folder": str(folder)}, "budget": {"jev": "9", "openai": "9", "azure_di": "9"}},
                            "statements": {"source": {"kind": "folder", "folder": str(db)}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester", auto=False)
    assert _steps(made)["invoices"]["state"] == "waiting"  # the chain is off: nothing started
    view = wf.update(made["workflow"]["id"], actor="tester", auto=True)
    inv = _steps(view)["invoices"]
    assert inv["state"] == inv["status"] == "failed" and inv["note"] == "the disk is gone" and len(calls) == 1
    monkeypatch.undo()
    view = wf.start_step(view["workflow"]["id"], "invoices", actor="tester")
    assert _steps(view)["invoices"]["state"] == "started"
    with pytest.raises(wf.WorkflowError, match="cannot be started"):
        wf.start_step(view["workflow"]["id"], "invoices", actor="tester")


def test_the_mailbox_step_waits_for_its_download_then_runs_its_package(db, monkeypatch):
    party = _party()
    pulls = {"p1": {"id": "p1", "status": "running", "result": None}}
    monkeypatch.setattr(mailbox, "request_pull", lambda req, **kw: pulls["p1"] | {"request": req.model_dump(mode="json")})
    monkeypatch.setattr(mailbox, "pull", lambda pid: pulls[pid])
    request = {"accounts": ["someone@example.com"], "since_days": 31}
    made = wf.create(template_id="mailbox_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                     steps={"emails": {"source": {"kind": "mailbox", "request": request}, "budget": {"jev": "9", "openai": "9", "azure_di": "9"}},
                            "statements": {"source": {"kind": "folder", "folder": str(db)}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester")
    wf_id = made["workflow"]["id"]
    assert _steps(made)["emails"]["state"] == "pulling" and _steps(made)["emails"]["pull_id"] == "p1"
    assert _steps(made)["emails"]["source"] == {"kind": "mailbox", "accounts": ["someone@example.com"], "folders": ["Inbox"]}
    wf.advance(wf_id, actor="tester (auto)")
    assert _steps(wf.view(wf_id))["emails"]["state"] == "pulling"
    package = work.create_from_files(sorted(_invoices(db / "mail").iterdir()), name="Mail", owner="tester")
    pulls["p1"] = {"id": "p1", "status": "ok", "result": {"workpackage": package["id"]}}
    view = wf.advance(wf_id, actor="tester (auto)")
    emails = _steps(view)["emails"]
    assert emails["state"] == "started" and emails["package"]["id"] == package["id"]
    assert work.get_run(emails["run_id"])["actor"] == "tester (auto)"


def test_a_download_without_new_emails_is_nothing_new_and_a_failed_one_shows_its_error(db, monkeypatch):
    party = _party()
    results = iter([{"id": "a", "status": "ok", "result": {"workpackage": None}},
                    {"id": "b", "status": "error", "result": {"error": "Outlook is closed"}}])
    pulled = {}

    def request_pull(req, **kw):
        row = next(results)
        pulled[row["id"]] = row
        return row

    monkeypatch.setattr(mailbox, "request_pull", request_pull)
    monkeypatch.setattr(mailbox, "pull", lambda pid: pulled[pid])
    steps = {"emails": {"source": {"kind": "mailbox", "request": {"accounts": ["someone@example.com"]}}},
             "statements": {"source": {"kind": "folder", "folder": str(db)}}, "reconcile": {"source": {"kind": "none"}}}
    first = wf.create(template_id="mailbox_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                      steps=steps, actor="tester")
    view = wf.advance(first["workflow"]["id"], actor="tester")
    assert _steps(view)["emails"]["state"] == "nothing_new" and _steps(view)["emails"]["note"] == "no new emails"
    second = wf.create(template_id="mailbox_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                       steps=steps, actor="tester")
    view = wf.advance(second["workflow"]["id"], actor="tester")
    assert _steps(view)["emails"]["state"] == "failed" and _steps(view)["emails"]["note"] == "Outlook is closed"


def test_a_linked_package_counts_when_its_live_run_is_approved(db):
    party = _party()
    docs = work.create_from_folder(_invoices(db / "inv"), name="Invoices", owner="tester")
    made = wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                     steps={"invoices": {"source": {"kind": "folder", "folder": str(db / "inv")}},
                            "statements": {"source": {"kind": "folder", "folder": str(db)}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester", auto=False)
    wf_id = made["workflow"]["id"]
    view = wf.link(wf_id, "invoices", docs["id"], actor="tester")
    inv = _steps(view)["invoices"]
    assert inv["state"] == "linked" and inv["status"] == "attention" and not inv["done"]  # no run yet: a person starts it
    ready = work.readiness(docs["id"])
    run_id = work.start_run(docs["id"], mode="apply", expected_assignment_revision=ready["assignment_revision"],
                            input_hash=ready["input_hash"], actor="tester")["run_id"]
    _approve_by_hand(run_id)
    assert _steps(wf.view(wf_id))["invoices"]["done"]
    with pytest.raises(wf.WorkflowError, match="already belongs to a workflow"):
        wf.link(wf_id, "invoices", docs["id"], actor="tester")


def test_the_list_shows_each_workflow_with_its_steps_and_an_archived_one_only_on_request(db):
    party = _party()
    steps = {"invoices": {"source": {"kind": "folder", "folder": str(_invoices(db / "inv"))}},
             "statements": {"source": {"kind": "folder", "folder": str(db)}}, "reconcile": {"source": {"kind": "none"}}}
    a = wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                  steps=steps, actor="tester", auto=False, name="June")
    b = wf.create(template_id="monthly_reconciliation", party_id=party, period_start="2026-07-01", period_end="2026-07-31",
                  steps=steps, actor="tester", auto=False, name="July")
    wf.update(a["workflow"]["id"], actor="tester", archived=True)
    rows = wf.workflows()
    assert [r["name"] for r in rows] == ["July"] and rows[0]["party"] == "Example Kft."
    assert [s["status"] for s in rows[0]["steps"]] == ["ready", "ready", "waiting"] and rows[0]["next"]["step"] == "invoices"
    assert {r["name"] for r in wf.workflows(include_archived=True)} == {"June", "July"}
    with pytest.raises(wf.WorkflowError, match="archived"):
        wf.start_step(a["workflow"]["id"], "invoices", actor="tester")
    assert b["workflow"]["template_title"] == "Monthly reconciliation"


# --- the wizard's estimate ----------------------------------------------------------------------------------------------------


def test_the_estimate_is_the_recipes_item_budget_times_the_items(db):
    party = _party()
    folder = _invoices(db / "inv", n=3)
    per = wf._per_item("document")
    got = wf.estimate(kind="documents", source={"kind": "folder", "folder": str(folder)})
    assert got["items"] == 3 and got["usd"] == {p: str((v * 3).quantize(Decimal("0.0001"))) for p, v in per.items() if v}
    assert wf.estimate(kind="reconcile", source={"kind": "none"}) == {"items": None, "usd": {}, "note": None}
    statements = wf.estimate(kind="statements", source={"kind": "folder", "folder": str(_statements(db / "erste"))},
                             party_id=party, period_start=MONTH[0], period_end=MONTH[1])
    assert (statements["statements"], statements["pdfs"], statements["usd"]) == (1, 0, {})  # read by code: free
    mail = wf.estimate(kind="emails", source={"kind": "mailbox", "request": {"accounts": ["a@example.com"], "max_items": 10}})
    assert mail["items"] == 10 and mail["usd"] == wf._times(wf._per_item("email"), 10)
