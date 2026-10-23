"""154: the workflow's package pickers get a brief list.

The new-workflow wizard and a workflow step's "Use an existing package…" asked for the full package list, which works
out every package's to-dos and next step (a reconciliation package builds its whole pairing workspace); after the
workspaces' two-minute window the first request took 5.8 s live. The pickers need only the name and the kind, so
`brief=true` returns the packages as stored, without the to-dos and the next step. Synthetic PDFs, no model calls.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav import api, store, work_views
from jav.domains.finance import reconcile_package
from tests.pdfgen import INVOICE_LINES, write_text_pdf

BASE = "http://127.0.0.1:8930"
HUMAN = {"X-Actor": "teszt.elek"}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    root = tmp_path / "root"
    folder = root / "incoming"
    folder.mkdir(parents=True)
    write_text_pdf(folder / "invoice_1.pdf", INVOICE_LINES)
    monkeypatch.setenv("JAV_API_ROOTS", str(root))
    db = tmp_path / "w.sqlite"
    client = TestClient(api.create_app(store_path=db), base_url=BASE)
    with store.use_store(db):
        yield {"client": client, "folder": folder}


def test_the_brief_list_has_the_name_and_the_kind_without_the_next_step(env, monkeypatch):
    c = env["client"]
    r = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(env["folder"]), "name": "Example invoices"})
    assert r.status_code == 201, r.text
    wp = r.json()["workpackage"]

    def expensive(*_a, **_k):
        raise AssertionError("the brief list must not work out the next step")

    monkeypatch.setattr(work_views, "next_step", expensive)
    monkeypatch.setattr(reconcile_package, "package_view", expensive)
    rows = c.get("/api/workpackages", params={"brief": "true"}).json()["workpackages"]
    assert [(w["id"], w["name"], w["source_kind"], w["items"]) for w in rows] == [(wp["id"], "Example invoices", "folder", 1)]
    assert "next" not in rows[0] and "open_reasons" not in rows[0]


def test_the_brief_list_leaves_out_hidden_packages_unless_asked(env):
    c = env["client"]
    wp = c.post("/api/workpackages", headers=HUMAN, json={"folder": str(env["folder"]), "name": "Hidden"}).json()["workpackage"]
    assert c.post(f"/api/workpackages/{wp['id']}/archive", json={}, headers=HUMAN).status_code == 200
    assert c.get("/api/workpackages", params={"brief": "true"}).json()["workpackages"] == []
    rows = c.get("/api/workpackages", params={"brief": "true", "include_archived": "true"}).json()["workpackages"]
    assert [w["id"] for w in rows] == [wp["id"]]


def test_the_full_list_is_unchanged(env):
    c = env["client"]
    c.post("/api/workpackages", headers=HUMAN, json={"folder": str(env["folder"]), "name": "Example invoices"})
    row = c.get("/api/workpackages").json()["workpackages"][0]
    assert {"next", "open_reasons", "open_reasons_all", "older_runs"} <= set(row)
