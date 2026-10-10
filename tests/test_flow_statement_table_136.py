"""136 (backlog F-revolut-csv, E4): the chosen accounts of a bank's tabular export as work package items, processed by
code only and approved like any run, so the reconciliation reads their lines (DECISIONS 132, 136).

Synthetic exports only (`tests/test_statement_table_136.py`); no model is called.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jav import reconcile, reconcile_package, statement_table as st, store, work
from jav.runtime import queue, worker
from tests.test_statement_table_136 import IBAN_EUR, IBAN_HUF, _records, _workbook

HUF = IBAN_HUF.replace(" ", "") + ":HUF"
EUR = IBAN_EUR.replace(" ", "") + ":EUR"


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "s.sqlite"):
        yield tmp_path


def _package(export: Path, keys: list[str]) -> dict:
    wp = work.create_workpackage(name="Statements", source_kind="manual", source_ref=None)
    return work.add_statement_tables(wp["id"], export, keys, expected_revision=wp["revision"])


def _run_all(wp_id: str, mode: str = "apply") -> str:
    ready = work.readiness(wp_id)
    assert ready["ready"], ready["blockers"]
    run_id = work.start_run(wp_id, mode=mode, expected_assignment_revision=ready["assignment_revision"],
                            input_hash=ready["input_hash"], actor="tester")["run_id"]
    while (job := queue.claim("statement-test")) is not None:
        worker.process(job)
    return run_id


def test_only_the_chosen_accounts_are_written_once_each(db):
    reading = st.read(_workbook(db))
    paths = st.derive(reading, [HUF, EUR, HUF])
    assert len(paths) == 2 and all(p.parent.parent == st.derived_dir() for p in paths)
    first = [p.read_bytes() for p in paths]
    assert [p.read_bytes() for p in st.derive(st.read(_workbook(db)), [HUF, EUR])] == first  # canonical: the same items
    content = st.load_derived(first[0])
    assert content["account"] == {"key": HUF, "title": "Személyes számla", "currency": "HUF", "occurrence": 1}
    assert content["source"]["file"].endswith(".xlsx") and len(content["statement"]["transactions"]) == 4
    with pytest.raises(st.StatementTableError, match="unknown: 1"):
        st.derive(reading, [HUF, "XX00 unknown"])
    with pytest.raises(st.StatementTableError):
        st.load_derived(b'{"format": "something else"}')


def test_the_package_runs_free_and_its_statements_are_read_like_extracted_ones(db):
    wp = _package(_workbook(db), [HUF, EUR])
    assert [i["kind"] for i in wp["items"]] == ["statement_table", "statement_table"]
    ready = work.readiness(wp["id"])
    assert ready["plan"]["statement_tables"] == 2 and not any(ready["budget"].values())
    run_id = _run_all(wp["id"])
    run = work.get_run(run_id)
    assert run["status"] == "done" and {i["final_status"] for i in run["items"]} == {"done"}
    with store.connect() as c:
        rows = c.execute("SELECT d.doc_type, d.arm, d.datapoints, o.doc_type AS coarse FROM datapoints d"
                         " JOIN documents o ON o.doc_id = d.doc_id").fetchall()
    assert {(r["doc_type"], r["arm"], r["coarse"]) for r in rows} == {("statement_table", "code", "bank_statement")}
    huf = next(json.loads(r["datapoints"]) for r in rows if json.loads(r["datapoints"])["currency"] == "HUF")
    assert huf["opening_balance"] == "10000" and len(huf["transactions"]) == 4  # the store's money form
    work.approve_run(run_id, actor="tester")
    package = reconcile_package.create(name="Pairing", accounts=[reconcile.account_key(IBAN_HUF.replace(" ", ""))],
                                       period_start="2026-01-01", period_end="2026-03-31", actor="tester")["workpackage_id"]
    ws = reconcile_package.workspace(package)
    assert len(ws["lines"]) == 4  # the HUF account's lines; the EUR account has its own number here
    assert not [b for b in ws["blockers"] if b.get("code", "").startswith(("source_", "statement_"))]


def test_a_failed_check_and_an_unreadable_line_are_to_dos(db):
    rows = _records()
    for r in rows:
        if r and r[0] == "2026. febr. 10.":
            r[4] = "10 900,00"
        if r and r[0] == "2026. márc. 1.":
            r[3] = "n/a"
    wp = _package(_workbook(db, rows), [HUF])
    run_id = _run_all(wp["id"])
    item = work.get_run(run_id)["items"][0]
    assert item["final_status"] == "needs_review"
    reasons = {r["reason"] for r in work.item_reasons(run_id, item["item_id"])["run"]}
    assert "statement_table:unreadable_lines:1" in reasons
    assert any(r.startswith("validator:balance.") or r.startswith("validator:closing.") for r in reasons)


def test_a_statement_file_changed_after_it_was_added_fails(db):
    wp = _package(_workbook(db), [HUF])
    item = wp["items"][0]
    copy = work.source_file(item)
    copy.write_bytes(copy.read_bytes().replace(b"10000.00", b"10001.00"))
    ready = work.readiness(wp["id"])
    assert not ready["ready"] and {b["code"] for b in ready["blockers"]} == {"instance_damaged"}


def test_the_service_surveys_an_export_and_adds_the_chosen_accounts(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from jav import api
    from tests.test_api import BASE, HUMAN, restrict_paths

    root = tmp_path / "root"
    (root / "package").mkdir(parents=True)
    export = _workbook(root)
    monkeypatch.setenv("JAV_API_ROOTS", str(root))
    restrict_paths(monkeypatch)  # a file outside the allowed roots is refused
    db = tmp_path / "w.sqlite"
    client = TestClient(api.create_app(store_path=db), base_url=BASE)
    with store.use_store(db):
        survey = client.post("/api/statement-tables/survey", headers=HUMAN, json={"path": str(export)})
        assert survey.status_code == 200, survey.text
        assert [a["lines"] for a in survey.json()["accounts"]] == [4, 2, 1, 0] and "Example Market" not in survey.text
        r = client.post("/api/workpackages", headers=HUMAN, json={"folder": str(root / "package"), "name": "Revolut"})
        assert r.status_code == 201, r.text
        wp = r.json()["workpackage"]
        r = client.post(f"/api/workpackages/{wp['id']}/statement-tables", headers=HUMAN,
                        json={"path": str(export), "keys": [HUF], "expected_revision": wp["revision"]})
        assert r.status_code == 200, r.text
        assert [i["kind"] for i in r.json()["workpackage"]["items"]] == ["statement_table"]
        outside = _workbook(tmp_path, name="outside_2026-01-01_2026-03-31.xlsx")
        assert client.post("/api/statement-tables/survey", headers=HUMAN, json={"path": str(outside)}).status_code == 403
        created = client.post("/api/statement-tables/workpackage", headers=HUMAN,
                              json={"path": str(export), "keys": [HUF, EUR], "name": "Revolut 2026"})
        assert created.status_code == 201, created.text
        new = created.json()["workpackage"]
        assert new["owner"] == "teszt.elek" and len(new["items"]) == 2 and created.json()["readiness"]["ready"]
        bad = client.post(f"/api/workpackages/{wp['id']}/statement-tables", headers=HUMAN,
                          json={"path": str(export), "keys": ["unknown"], "expected_revision": r.json()["workpackage"]["revision"]})
        assert bad.status_code == 422
