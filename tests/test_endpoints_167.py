"""167 (review T-2): the six service endpoints no test called, each once through the service.

Each operation behind them has its own tests; these show that the endpoint reaches it with the person's name, answers
with the view the interface reads, and turns the operation's refusal into its status code: the reconciliation's scope and
its rate refresh, linking a package to a workflow step, scanning a watched folder now, adding the emails' attachments to
a package, and choosing between two statements of the same days. Synthetic documents and emails, made-up accounts,
invented rates; no AI call, no network.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav.service import api
from jav.app import app_settings, work, work_runs
from jav.core import store
from jav.domains.finance import fx
from jav.domains.email import mailbox
from jav.domains.finance import reconcile_package as rp
from jav.app import workflows as wf
from tests import test_reconcile_k2_129 as k2
from tests import test_statement_months_store_139 as months
from tests import test_workflows_146 as flows
from tests.test_api import BASE, HUMAN
from tests.test_email_results import _mail_with_pdf
from tests.test_fx_130 import Service
from tests.test_guards_167 import RATES, _package
from tests.test_mailbox import MAILS, REQ, FakeBridge, env  # noqa: F401 - `env` is a fixture
from tests.test_reconcile_package_131 import OWN_KEY, _stmt
from tests.test_reconcile_package_131 import _line as _pkg_line
from tests.pdfgen import INVOICE_LINES, write_text_pdf


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "w.sqlite"
    with store.use_store(db):
        rp.clear_cache()
        yield TestClient(api.create_app(store_path=db), base_url=BASE)
        rp.clear_cache()


def _ok(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


# --- every one of them is a person's action ------------------------------------------------------------------------------

ITEM = "a" * 64
ENDPOINTS = [
    ("/api/workpackages/wp-000000000001/reconcile/scope",
     {"accounts": [OWN_KEY], "period_start": "2026-04-01", "period_end": "2026-04-30", "expected_revision": 1}),
    ("/api/workpackages/wp-000000000001/reconcile/refresh", {}),
    ("/api/workflows/wf-000000000001/steps/invoices/link", {"workpackage_id": "wp-000000000001"}),
    ("/api/settings/folders/wf-0000000001/scan", {}),
    ("/api/workpackages/wp-000000000001/attachments", {"expected_revision": 1}),
    (f"/api/runs/run-000000000001/items/{ITEM}/statements/{'b' * 64}/choice", {"keep": "this"}),
]


@pytest.mark.parametrize("path, body", ENDPOINTS, ids=[p.split("/")[-1] for p, _ in ENDPOINTS])
def test_the_endpoint_needs_the_persons_name(client, path, body):
    r = client.post(path, json=body)  # no X-Actor header
    assert r.status_code == 422 and "x-actor" in r.text.lower()


# --- the reconciliation: its scope and its rates -------------------------------------------------------------------------


def test_the_reconciliation_scope_changes_at_its_revision(client):
    _stmt("stmt", _pkg_line())
    wp = rp.create(name="April", accounts=[OWN_KEY], period_start="2026-04-01", period_end="2026-04-30",
                   actor="reviewer")["workpackage_id"]
    body = {"accounts": [OWN_KEY], "period_start": "2026-04-01", "period_end": "2026-05-31", "expected_revision": 1}
    scope = _ok(client.post(f"/api/workpackages/{wp}/reconcile/scope", headers=HUMAN, json=body))["scope"]
    assert (scope["period_end"], scope["revision"]) == ("2026-05-31", 2)
    stale = client.post(f"/api/workpackages/{wp}/reconcile/scope", headers=HUMAN, json=body)
    assert stale.status_code == 409 and stale.json()["error"] == "revision_conflict"
    bad = client.post(f"/api/workpackages/{wp}/reconcile/scope", headers=HUMAN, json=body | {
        "period_start": "2026-06-01", "expected_revision": 2})
    assert bad.status_code == 422 and "ends before it starts" in bad.text


def test_the_refresh_fetches_the_missing_rates(client):
    pkg = _package(invoices={"OUT-1": "CHF"}, rates=False)
    service = Service(RATES)
    with fx.use_transport(service):
        ws = _ok(client.post(f"/api/workpackages/{pkg['wp']}/reconcile/refresh", headers=HUMAN, json={}))
    assert [call["codes"] for call in service.calls] == [["CHF"]]  # only the currency code and the days left
    assert ws["scope"]["workpackage_id"] == pkg["wp"]
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM fx_rates WHERE currency='CHF'").fetchone()[0] > 0


# --- a workflow step's package -------------------------------------------------------------------------------------------


def test_a_package_is_linked_to_a_workflow_step_of_its_kind(client, tmp_path):
    party = flows._party()
    made = wf.create(template_id="monthly_reconciliation", party_id=party, period_start=flows.MONTH[0],
                     period_end=flows.MONTH[1], actor="tester", auto=False, advance_now=False,
                     steps={"invoices": {"source": {"kind": "folder", "folder": str(flows._invoices(tmp_path / "a"))}},
                            "statements": {"source": {"kind": "folder", "folder": str(tmp_path)}},
                            "reconcile": {"source": {"kind": "none"}}})
    wf_id = made["workflow"]["id"]
    docs = work.create_from_folder(flows._invoices(tmp_path / "b"), name="Invoices", owner="tester")
    wrong = client.post(f"/api/workflows/{wf_id}/steps/statements/link", headers=HUMAN, json={"workpackage_id": docs["id"]})
    assert wrong.status_code == 422 and "not of a statements step's kind" in wrong.text
    view = _ok(client.post(f"/api/workflows/{wf_id}/steps/invoices/link", headers=HUMAN, json={"workpackage_id": docs["id"]}))
    step = next(s for s in view["steps"] if s["id"] == "invoices")
    assert (step["state"], step["package"]["id"]) == ("linked", docs["id"])
    assert wf.workflow_of(docs["id"])["id"] == wf_id and work_runs.run_rows(docs["id"]) == []  # linking starts no run
    again = client.post(f"/api/workflows/{wf_id}/steps/invoices/link", headers=HUMAN, json={"workpackage_id": docs["id"]})
    assert again.status_code == 422


# --- a watched folder, scanned now ---------------------------------------------------------------------------------------


def test_scanning_a_watched_folder_now_makes_the_scanners_package(client, tmp_path):
    folder = tmp_path / "watched"
    folder.mkdir()
    for n in (1, 2):
        pdf = write_text_pdf(folder / f"invoice_{n}.pdf", [ln.replace("MINTA-2026-001", f"MINTA-2026-00{n}") for ln in INVOICE_LINES])
        hour_ago = time.time() - 3600  # written long enough ago to have settled
        os.utime(pdf, (hour_ago, hour_ago))
    [f] = app_settings.save_folders([app_settings.WatchedFolder(path=str(folder))], check_dir=lambda raw: Path(raw).resolve())
    result = _ok(client.post(f"/api/settings/folders/{f['id']}/scan", headers=HUMAN, json={}))
    assert (result["status"], result["new"]) == ("ok", 2)
    assert work.get(result["workpackage"])["owner"] == "teszt.elek"  # 065: the "now" button's person owns it
    assert client.post("/api/settings/folders/wf-0000000000/scan", headers=HUMAN, json={}).status_code == 404


# --- the emails' attachments ---------------------------------------------------------------------------------------------


def test_the_emails_pdf_attachments_are_added_to_their_package(env):  # noqa: F811
    c = TestClient(api.create_app(store_path=store.current_path()), base_url=BASE)
    wp_id = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge([_mail_with_pdf(env)]), inbox_root=env["inbox"])["workpackage"]
    wp = work.get(wp_id)
    doc = next(i for i in wp["items"] if i["kind"] == "document")
    wp = work.remove_item(wp_id, doc["item_id"], expected_revision=wp["revision"], actor="test", reason="pre-058 package")
    stale = c.post(f"/api/workpackages/{wp_id}/attachments", headers=HUMAN, json={"expected_revision": wp["revision"] - 1})
    assert stale.status_code == 409
    view = _ok(c.post(f"/api/workpackages/{wp_id}/attachments", headers=HUMAN, json={"expected_revision": wp["revision"]}))
    added = [i for i in view["workpackage"]["items"] if i["kind"] == "document" and not i.get("removed_at")]
    assert [Path(i["source_path"]).name for i in added] == ["szamla.pdf"] and added[0]["parent_item_id"]
    assert mailbox.missing_attachments(work.get(wp_id)) == []


# --- two statements of the same days ------------------------------------------------------------------------------------


def test_a_person_chooses_the_valid_statement_and_its_to_dos_close(client):
    a, b = months._pair_in_run()
    url = f"/api/runs/{k2.RUN}/items/{b}/statements/{a}/choice"
    assert client.post(url, headers=HUMAN, json={"keep": "neither"}).status_code == 422
    _ok(client.post(url, headers=HUMAN, json={"keep": "other", "note": "the export is complete"}))
    assert store.review_open_reasons("document", b) == []
    with store.connect() as c:
        row = c.execute("SELECT keep_doc_id, actor FROM statement_choices").fetchone()
        c.execute("UPDATE runs SET approval='approved' WHERE run_id=?", (k2.RUN,))
    assert (row["keep_doc_id"], row["actor"]) == (a, "teszt.elek")
    assert client.post(url, headers=HUMAN, json={"keep": "rule"}).status_code == 409  # frozen after the approval
