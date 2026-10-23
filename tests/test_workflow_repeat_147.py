"""147 (backlog F-workflow-repeat; DECISIONS 147): a workflow repeated for the next period.

The owner's decision of 2026-10-12: a finished monthly workflow is repeated for the next month in one go. The repeat is
a draft the wizard shows filled in (the template, the party, the sources, the budgets and the name, the period moved
on); a person checks it and makes the new workflow, so the budgets are approved again. A documents step from a folder
takes only the documents no live run has processed yet: the folder of a year's invoices does not bring last month's
invoices back, while a document only a trial run has seen is still new.

No AI call: runs are started but never processed; a processed item is set by hand, as the worker would leave it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jav import parties, work, work_readiness, work_runs, workflows as wf
from jav.core import store

SEPT = ("2026-09-01", "2026-09-30")


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(wf, "_last_tick", 0.0)
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def _party(name: str = "Example Kft.") -> str:
    return parties.create(name, identities=[], actor="tester")["id"]


def _pdf(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(b"%PDF-1.4\n% synthetic " + name.encode() + b"\n%%EOF\n")
    return p


def _processed(paths: list[Path], *, mode: str = "apply", status: str = "done") -> str:
    """A run of `mode` over the files whose items the worker has finished (no AI: their results are recorded by hand,
    as the worker records them)."""
    wp = work.create_from_files(paths, name="Earlier", owner="tester")
    ready = work_readiness.readiness(wp["id"])
    run_id = work_runs.start_run(wp["id"], mode=mode, expected_assignment_revision=ready["assignment_revision"],
                            input_hash=ready["input_hash"], actor="tester")["run_id"]
    for item in work.get(wp["id"])["items"]:
        work_runs.record_item_result(run_id, item["item_id"], status=status)
    return run_id


def _steps(view: dict) -> dict[str, dict]:
    return {s["id"]: s for s in view["steps"]}


def _monthly(party: str, invoices: Path, statements: Path, **kw) -> dict:
    args = {"template_id": "monthly_reconciliation", "party_id": party, "period_start": SEPT[0], "period_end": SEPT[1],
            "steps": {"invoices": {"source": {"kind": "folder", "folder": str(invoices)}, "budget": {"jev": "0.5"}},
                      "statements": {"source": {"kind": "folder", "folder": str(statements)}},
                      "reconcile": {"source": {"kind": "none"}}},
            "actor": "tester", "auto": False} | kw
    return wf.create(**args)


# --- the next period ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("period, following", [
    (("2026-09-01", "2026-09-30"), ("2026-10-01", "2026-10-31")),
    (("2026-02-01", "2026-02-28"), ("2026-03-01", "2026-03-31")),
    (("2026-12-01", "2026-12-31"), ("2027-01-01", "2027-01-31")),
    (("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30")),  # a quarter: the next quarter
    (("2026-06-10", "2026-06-19"), ("2026-06-20", "2026-06-29")),  # not whole months: as long, right after
    (("2026-01-31", "2026-01-31"), ("2026-02-01", "2026-02-01")),
])
def test_the_next_period_is_the_next_whole_months_or_as_long_right_after(period, following):
    assert wf.next_period(*period) == following


# --- the draft ---------------------------------------------------------------------------------------------------------------


def test_a_repeat_draft_carries_the_sources_budgets_and_name_into_the_next_period(db):
    party = _party()
    invoices, statements = db / "inv", db / "stm"
    _pdf(invoices, "a.pdf")
    statements.mkdir()
    made = _monthly(party, invoices, statements, name="Example Kft. 2026-09-01 – 2026-09-30")
    draft = wf.repeat_draft(made["workflow"]["id"])
    assert (draft["template"], draft["party_id"], draft["period_start"], draft["period_end"], draft["auto"]) == (
        "monthly_reconciliation", party, "2026-10-01", "2026-10-31", False)
    assert draft["name"] == "Example Kft. 2026-10-01 – 2026-10-31" and draft["previous"] == made["workflow"]["id"]
    steps = draft["steps"]
    assert steps["invoices"] == {"source": {"kind": "folder", "folder": str(invoices), "recursive": False, "only_new": True},
                                 "budget": {"jev": "0.5"}, "engine": None}  # 160-D: the application's engine
    assert steps["statements"]["source"] == {"kind": "folder", "folder": str(statements), "recursive": False}
    assert steps["reconcile"] == {"source": {"kind": "none"}, "budget": {}, "engine": None}
    # a name of the person's own, without the period in it, is not guessed: the wizard proposes one
    other = _monthly(party, invoices, statements, name="Club accounts")
    assert wf.repeat_draft(other["workflow"]["id"])["name"] is None
    with pytest.raises(KeyError):
        wf.repeat_draft("wf-000000000000")


def test_a_mailbox_period_moves_with_the_workflow_and_a_number_of_days_stays(db, monkeypatch):
    from jav.domains.email import mailbox

    monkeypatch.setattr(mailbox, "request_pull", lambda req, **kw: {"id": "p1", "status": "queued"})
    party = _party()
    (db / "stm").mkdir()

    def made(request: dict) -> dict:
        return wf.create(template_id="mailbox_reconciliation", party_id=party, period_start=SEPT[0], period_end=SEPT[1],
                         steps={"emails": {"source": {"kind": "mailbox", "request": request}},
                                "statements": {"source": {"kind": "folder", "folder": str(db / "stm")}},
                                "reconcile": {"source": {"kind": "none"}}}, actor="tester", auto=False)

    ranged = made({"accounts": ["someone@example.com"], "received_from": SEPT[0], "received_to": SEPT[1], "max_items": 50})
    request = wf.repeat_draft(ranged["workflow"]["id"])["steps"]["emails"]["source"]["request"]
    assert (request["received_from"], request["received_to"], request["max_items"]) == ("2026-10-01", "2026-10-31", 50)
    days = made({"accounts": ["someone@example.com"], "since_days": 31})
    request = wf.repeat_draft(days["workflow"]["id"])["steps"]["emails"]["source"]["request"]
    assert request["since_days"] == 31 and request.get("received_from") is None


def test_a_linked_steps_draft_takes_its_packages_folder_or_asks_for_a_source(db, monkeypatch):
    from jav.domains.email import mailbox

    party = _party()
    invoices = db / "inv"
    _pdf(invoices, "a.pdf")
    (db / "stm").mkdir()
    docs = work.create_from_folder(invoices, name="September invoices", owner="tester")
    made = _monthly(party, invoices, db / "stm", steps={
        "invoices": {"source": {"kind": "package", "workpackage_id": docs["id"]}},
        "statements": {"source": {"kind": "folder", "folder": str(db / "stm")}}, "reconcile": {"source": {"kind": "none"}}})
    draft = wf.repeat_draft(made["workflow"]["id"])
    assert draft["steps"]["invoices"]["source"] == {"kind": "folder", "folder": str(invoices.resolve()), "recursive": False,
                                                    "only_new": True}
    monkeypatch.setattr(mailbox, "request_pull", lambda req, **kw: {"id": "p1", "status": "queued"})
    mail = work.create_workpackage(name="Mail", source_kind="mailbox", source_ref="someone@example.com", owner="tester")
    linked = wf.create(template_id="mailbox_reconciliation", party_id=party, period_start=SEPT[0], period_end=SEPT[1],
                       steps={"emails": {"source": {"kind": "package", "workpackage_id": mail["id"]}},
                              "statements": {"source": {"kind": "folder", "folder": str(db / "stm")}},
                              "reconcile": {"source": {"kind": "none"}}}, actor="tester", auto=False)
    assert wf.repeat_draft(linked["workflow"]["id"])["steps"]["emails"]["source"] is None  # the wizard asks for it


# --- only the new documents --------------------------------------------------------------------------------------------------


def test_only_new_leaves_out_the_documents_a_live_run_has_processed_and_keeps_what_only_a_trial_saw(db):
    folder = db / "inv"
    old, trial, failed = _pdf(folder, "1-old.pdf"), _pdf(folder, "2-trial.pdf"), _pdf(folder, "3-failed.pdf")
    _pdf(folder, "4-new.pdf")
    _processed([old])
    _processed([trial], mode="shadow")
    _processed([failed], status="failed")
    new, seen = work.unprocessed(work.folder_documents(folder))
    assert [p.name for p in new] == ["2-trial.pdf", "3-failed.pdf", "4-new.pdf"] and [p.name for p in seen] == ["1-old.pdf"]
    got = wf.estimate(kind="documents", source={"kind": "folder", "folder": str(folder), "only_new": True})
    assert (got["items"], got["left_out"]) == (3, 1)
    assert wf.estimate(kind="documents", source={"kind": "folder", "folder": str(folder)})["items"] == 4


def test_a_documents_step_with_only_new_makes_its_package_of_the_new_documents(db):
    party = _party()
    folder = db / "inv"
    old = _pdf(folder, "1-old.pdf")
    _pdf(folder, "2-new.pdf")
    _processed([old])
    (db / "stm").mkdir()
    made = _monthly(party, folder, db / "stm", steps={
        "invoices": {"source": {"kind": "folder", "folder": str(folder), "only_new": True},
                     "budget": {"jev": "9", "openai": "9", "azure_di": "9"}},
        "statements": {"source": {"kind": "folder", "folder": str(db / "stm")}}, "reconcile": {"source": {"kind": "none"}}})
    view = wf.start_step(made["workflow"]["id"], "invoices", actor="tester")
    inv = _steps(view)["invoices"]
    assert inv["state"] == "started"
    assert [Path(i["source_path"]).name for i in work.get(inv["package"]["id"])["items"]] == ["2-new.pdf"]
    left = next(e for e in view["events"] if e["action"] == "left_out")
    assert left["detail"] == {"new": 1, "left_out": 1}


def test_a_folder_of_processed_documents_only_is_nothing_new(db):
    party = _party()
    folder = db / "inv"
    _processed([_pdf(folder, "1-old.pdf"), _pdf(folder, "2-old.pdf")])
    (db / "stm").mkdir()
    before = {w["id"] for w in work.list_workpackages()}
    made = _monthly(party, folder, db / "stm", steps={
        "invoices": {"source": {"kind": "folder", "folder": str(folder), "only_new": True}},
        "statements": {"source": {"kind": "folder", "folder": str(db / "stm")}}, "reconcile": {"source": {"kind": "none"}}})
    view = wf.start_step(made["workflow"]["id"], "invoices", actor="tester")
    inv = _steps(view)["invoices"]
    assert inv["state"] == "nothing_new" and inv["done"] and inv["note"] == "no new documents: 2 already processed"
    assert {w["id"] for w in work.list_workpackages()} == before


def test_only_new_is_a_documents_steps_choice(db):
    party = _party()
    (db / "stm").mkdir()
    with pytest.raises(wf.WorkflowError, match="only a documents step"):
        _monthly(party, db / "stm", db / "stm", steps={
            "invoices": {"source": {"kind": "folder", "folder": str(db / "stm")}},
            "statements": {"source": {"kind": "folder", "folder": str(db / "stm"), "only_new": True}},
            "reconcile": {"source": {"kind": "none"}}})


# --- the two workflows linked ------------------------------------------------------------------------------------------------


def test_a_repeat_links_the_two_workflows_both_ways(db):
    party = _party()
    _pdf(db / "inv", "a.pdf")
    (db / "stm").mkdir()
    sept = _monthly(party, db / "inv", db / "stm")
    draft = wf.repeat_draft(sept["workflow"]["id"])
    octo = wf.create(template_id=draft["template"], party_id=draft["party_id"], period_start=draft["period_start"],
                     period_end=draft["period_end"], steps=draft["steps"], actor="tester", auto=False,
                     previous=draft["previous"])
    assert octo["repeat_of"] == {"id": sept["workflow"]["id"], "name": sept["workflow"]["name"],
                                 "period_start": SEPT[0], "period_end": SEPT[1]}
    assert wf.view(sept["workflow"]["id"])["repeated_as"] == [{"id": octo["workflow"]["id"], "name": octo["workflow"]["name"],
                                                               "period_start": "2026-10-01", "period_end": "2026-10-31"}]
    assert sept["repeat_of"] is None
    with pytest.raises(wf.WorkflowError, match="no workflow"):
        _monthly(party, db / "inv", db / "stm", previous="wf-000000000000")


# --- the service ---------------------------------------------------------------------------------------------------------------


def test_the_service_gives_the_draft_and_makes_the_repeat(db):
    from fastapi.testclient import TestClient

    from jav import api
    from tests.test_api import BASE, HUMAN

    client = TestClient(api.create_app(store_path=db / "s.sqlite"), base_url=BASE)
    party = _party()
    folder = db / "inv"
    _pdf(folder, "a.pdf")
    (db / "stm").mkdir()
    sept = _monthly(party, folder, db / "stm")
    got = client.get(f"/api/workflows/{sept['workflow']['id']}/repeat")
    assert got.status_code == 200, got.text
    draft = got.json()
    assert draft["period_start"] == "2026-10-01" and draft["steps"]["invoices"]["source"]["only_new"] is True
    assert client.get("/api/workflows/wf-000000000000/repeat").status_code == 404
    est = client.post("/api/workflows/estimate", json={"kind": "documents", "source": draft["steps"]["invoices"]["source"]})
    assert est.status_code == 200 and (est.json()["items"], est.json()["left_out"]) == (1, 0)
    body = {"template": draft["template"], "party_id": draft["party_id"], "period_start": draft["period_start"],
            "period_end": draft["period_end"], "auto": False, "previous": draft["previous"], "steps": draft["steps"]}
    made = client.post("/api/workflows", headers=HUMAN, json=body)
    assert made.status_code == 201, made.text
    assert made.json()["repeat_of"]["id"] == sept["workflow"]["id"]
    assert _steps(made.json())["invoices"]["source"]["only_new"] is True
