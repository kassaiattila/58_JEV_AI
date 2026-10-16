"""160 (review R-1): an interrupted mailbox download in a workflow keeps the package made from the emails that arrived.

When the download stopped midway (a timeout, a stopped script), the emails that had arrived became a package and the
download was marked as an error. The workflow step saw only the error: it failed without noting the package, and when
started again the download found "no new emails" and counted as done, so the package never ran and stayed out of the
reconciliation. The step now takes the package and starts its run; the error stays visible in the step's events.
Synthetic documents, stand-in downloads."""

from __future__ import annotations

from jav import mailbox, work, workflows as wf
from tests.test_workflows_146 import MONTH, _invoices, _party, _steps, db  # noqa: F401 - the fixture is used by name


def test_an_interrupted_download_still_runs_the_package_of_the_emails_that_arrived(db, monkeypatch):  # noqa: F811
    party = _party()
    pulls = {"p1": {"id": "p1", "status": "running", "result": None}}
    monkeypatch.setattr(mailbox, "request_pull", lambda req, **kw: pulls["p1"] | {"request": req.model_dump(mode="json")})
    monkeypatch.setattr(mailbox, "pull", lambda pid: pulls[pid])
    made = wf.create(template_id="mailbox_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                     steps={"emails": {"source": {"kind": "mailbox", "request": {"accounts": ["someone@example.com"]}},
                                       "budget": {"jev": "9", "openai": "9", "azure_di": "9"}},
                            "statements": {"source": {"kind": "folder", "folder": str(db)}},
                            "reconcile": {"source": {"kind": "none"}}}, actor="tester")
    wf_id = made["workflow"]["id"]
    package = work.create_from_files(sorted(_invoices(db / "mail").iterdir()), name="Mail", owner="tester")
    error = "The download was interrupted (TimeoutExpired); the emails that arrived were packaged."
    pulls["p1"] = {"id": "p1", "status": "error", "result": {"error": error, "workpackage": package["id"]}}
    view = wf.advance(wf_id, actor="tester (auto)")
    emails = _steps(view)["emails"]
    assert emails["state"] == "started" and emails["package"]["id"] == package["id"] and emails["run_id"]
    assert any(e["step"] == "emails" and e["action"] == "pull_interrupted" and e["detail"]["note"] == error for e in view["events"])
