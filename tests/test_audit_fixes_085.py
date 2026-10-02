"""085: the fixes for the v1.1.2 security re-audit (A01-A05). Each test is the audit's witness turned around: it
failed on the code before the fix. Synthetic documents, a separate store and provider stand-ins only."""

import hashlib
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from typesafe_sdk import TypeSafeAPITimeoutError

from jav import api, backup, cfg, corrections, source_instances, store, work
from jav.adapters.jev import JevUnavailableError
from jav.runtime import calls, worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_api import BASE, HUMAN, _ready_wp, _start, env  # noqa: F401 - the shared service fixture (`service` below)


@pytest.fixture()
def service(request):
    """The local service over synthetic invoices (the `env` fixture of the service tests)."""
    return request.getfixturevalue("env")


def _reviewed_run(service) -> tuple[TestClient, dict, str]:
    """A finished live run whose to-dos are all resolved, so it can be approved."""
    client = service["client"]
    wp = _ready_wp(client, service["folder"])
    run_id = _start(client, wp["id"]).json()["run_id"]
    worker.run_worker(once=True)
    for item in work.get_run(run_id)["input"]["items"]:
        for reason in work.item_reasons(run_id, item["item_id"], item)["run"]:
            work.resolve_reason(reason["id"], actor="teszt.elek", resolution=None, note="synthetic review")
    return client, wp, run_id


# --- A01: approval and corrections ----------------------------------------------------------------------


def test_a01_correction_cannot_commit_after_a_concurrent_approval(service, monkeypatch):
    client, wp, run_id = _reviewed_run(service)
    item_id = wp["items"][0]["item_id"]
    insert = corrections._insert_revision

    def approve_in_between(*args, **kwargs):
        # another request approves the run after the correction's own approval check, before it writes
        assert work.approve_run(run_id, actor="teszt.elek")["approval"] == "approved"
        insert(*args, **kwargs)

    monkeypatch.setattr(corrections, "_insert_revision", approve_in_between)
    r = client.post(f"/api/runs/{run_id}/items/{item_id}/correction", headers=HUMAN,
                    json={"fields": {"invoice_number": "CHANGED-AFTER-APPROVAL"}, "expected_revision": 0})
    assert r.status_code == 409, r.text
    assert work.get_run(run_id)["approval"] == "approved"
    assert corrections.current(run_id, item_id)["fields"].get("invoice_number") != "CHANGED-AFTER-APPROVAL"


def test_a01_approval_is_bound_to_the_reviewed_version(service):
    client, wp, run_id = _reviewed_run(service)
    seen = client.get(f"/api/runs/{run_id}").json()["review_version"]
    item_id = wp["items"][0]["item_id"]
    r = client.post(f"/api/runs/{run_id}/items/{item_id}/correction", headers=HUMAN,
                    json={"fields": {"invoice_number": "CORRECTED-IN-ANOTHER-TAB"}, "expected_revision": 0})
    assert r.status_code == 200, r.text
    # the reviewer's page still shows the state before that correction: approving it is refused
    r = client.post(f"/api/runs/{run_id}/approve", headers=HUMAN, json={"review_version": seen})
    assert r.status_code == 409, r.text
    assert work.get_run(run_id)["approval"] is None
    now = client.get(f"/api/runs/{run_id}").json()["review_version"]
    assert now != seen
    r = client.post(f"/api/runs/{run_id}/approve", headers=HUMAN, json={"review_version": now})
    assert r.status_code == 200, r.text
    assert r.json()["run"]["approval"] == "approved"


def test_a01_approval_without_a_version_still_works(service):
    """The command line approves the current state (it shows no earlier view to compare with)."""
    client, _wp, run_id = _reviewed_run(service)
    assert client.post(f"/api/runs/{run_id}/approve", headers=HUMAN, json={}).status_code == 200
    assert work.get_run(run_id)["approval"] == "approved"


# --- A02: verified source copies in the backup ----------------------------------------------------------


def _backed_up_source(tmp_path: Path) -> tuple[dict, Path, Path]:
    original = tmp_path / "input.pdf"
    write_text_pdf(original, INVOICE_LINES)
    wp = work.create_from_files([original], name="Synthetic backup")
    item = wp["items"][0]
    dest = tmp_path / "backups"
    assert backup.backup(out_root=dest, keep=2)["ok"]
    return item, dest, dest / "sources" / item["instance"]


def _flip_first_byte(path: Path) -> None:
    data = path.read_bytes()
    path.write_bytes(bytes([data[0] ^ 1]) + data[1:])


def test_a02_equal_size_corruption_in_the_backup_is_found_and_repaired(tmp_path):
    with store.use_store(tmp_path / "store" / "jav.sqlite"):
        item, dest, saved = _backed_up_source(tmp_path)
        size = saved.stat().st_size
        _flip_first_byte(saved)
        assert saved.stat().st_size == size
        second = backup.backup(out_root=dest, keep=2)
        entry = next(f for f in second["files"] if f["file"] == "sources")
        assert second["ok"] and entry["integrity"] == "ok"
        assert entry["repaired"] == [saved.name] and entry["damaged"] == []
        assert hashlib.sha256(saved.read_bytes()).hexdigest() == item["sha256"]


def test_a02_a_damaged_copy_without_an_intact_source_fails_the_backup(tmp_path):
    with store.use_store(tmp_path / "store" / "jav.sqlite"):
        item, dest, saved = _backed_up_source(tmp_path)
        _flip_first_byte(saved)
        _flip_first_byte(source_instances.path_of(item["instance"]))  # the store's own instance is damaged as well
        second = backup.backup(out_root=dest, keep=2)
        entry = next(f for f in second["files"] if f["file"] == "sources")
        assert not second["ok"]
        assert entry["damaged"] == [saved.name] and entry["integrity"] != "ok"
        assert second["removed"] == []  # no pruning after a failed backup


# --- A03: no full copy of a document over the input limit -----------------------------------------------


def _tiny_input_limit(monkeypatch) -> None:
    load = cfg.load
    settings = {**load("service"), "input_limits": {**load("service")["input_limits"], "max_document_mb": 0.0001}}
    monkeypatch.setattr(cfg, "load", lambda name: settings if name == "service" else load(name))


def test_a03_document_over_the_input_limit_is_added_without_a_copy(tmp_path, monkeypatch):
    original = tmp_path / "larger_than_limit.pdf"
    write_text_pdf(original, INVOICE_LINES)
    _tiny_input_limit(monkeypatch)  # 100 bytes; the synthetic PDF is about 900
    db = tmp_path / "store" / "jav.sqlite"
    client = TestClient(api.create_app(store_path=db), base_url=BASE)
    r = client.post("/api/workpackages", headers=HUMAN, json={"paths": [str(original)], "name": "Synthetic over-limit input"})
    assert r.status_code == 201, r.text
    item = r.json()["workpackage"]["items"][0]
    with store.use_store(db):
        assert item["instance"] is None
        assert item["sha256"] == hashlib.sha256(original.read_bytes()).hexdigest()
        assert source_instances.files() == []  # nothing was copied into the store


def test_a03_the_copy_stops_at_the_byte_limit(tmp_path):
    original = tmp_path / "growing.pdf"
    write_text_pdf(original, INVOICE_LINES)
    with store.use_store(tmp_path / "store" / "jav.sqlite"):
        with pytest.raises(source_instances.InstanceTooLarge):
            source_instances.freeze(original, max_bytes=100)
        assert source_instances.files() == []
        assert not list(source_instances.root().glob(".incoming-*"))  # the partial copy is removed


# --- A04: a request sent without a response is uncertain ------------------------------------------------


def _invoke_twice(fn, **kw) -> list[BaseException]:
    errors = []
    for _ in range(2):
        try:
            calls.invoke(run_id="audit-run", step_id="same-step", provider="openai", model="synthetic",
                         max_cost_usd=Decimal("0.1"), budget_scope="budget", fn=fn, **kw)
        except BaseException as exc:  # noqa: BLE001 - the test collects what each attempt raised
            errors.append(exc)
    return errors


def test_a04_read_timeout_is_uncertain_and_not_repeated(tmp_path):
    attempts = []

    def response_lost():
        attempts.append(1)
        raise httpx2.ReadTimeout("synthetic response loss; no real request")

    with store.use_store(tmp_path / "jav.sqlite"):
        calls.set_budget("budget", "openai", Decimal("1"))
        first, second = _invoke_twice(response_lost)
        assert isinstance(first, httpx2.ReadTimeout)
        assert isinstance(second, calls.UncertainAttempt)  # no second paid request for the same step
        assert attempts == [1]
        assert [r["status"] for r in calls.journal("audit-run")] == ["uncertain"]
        assert [c["step_id"] for c in calls.uncertain_list()] == ["same-step"]
        assert calls.budget_usage("budget")["committed_usd"] == Decimal("0.1")  # the maximum stays reserved


def test_a04_a_timeout_wrapped_by_the_jev_adapter_is_uncertain(tmp_path):
    def wrapped():
        try:
            try:
                raise httpx2.ReadTimeout("synthetic")
            except httpx2.ReadTimeout as low:
                raise TypeSafeAPITimeoutError(30.0) from low
        except TypeSafeAPITimeoutError as sdk:
            raise JevUnavailableError("timeout") from sdk

    with store.use_store(tmp_path / "jav.sqlite"):
        calls.set_budget("budget", "openai", Decimal("1"))
        first, second = _invoke_twice(wrapped)
        assert isinstance(first, JevUnavailableError) and isinstance(second, calls.UncertainAttempt)
        row = calls.journal("audit-run")[0]
        assert row["status"] == "uncertain" and "ReadTimeout" in row["error"]


@pytest.mark.parametrize("error", [httpx2.ConnectTimeout("synthetic"), httpx2.ConnectError("synthetic"), ValueError("bad input")])
def test_a04_an_error_before_sending_stays_failed_and_can_be_retried(tmp_path, error):
    attempts = []

    def refused():
        attempts.append(1)
        raise error

    with store.use_store(tmp_path / "jav.sqlite"):
        calls.set_budget("budget", "openai", Decimal("1"))
        errors = _invoke_twice(refused)
        assert [type(e) for e in errors] == [type(error)] * 2
        assert attempts == [1, 1]
        assert [r["status"] for r in calls.journal("audit-run")] == ["failed", "failed"]
        assert calls.uncertain_list() == []


def test_a04_a_sidecar_that_never_answered_is_not_uncertain():
    """urllib wraps a failure while sending in URLError (connection refused, connect timeout): nothing was processed."""
    import urllib.error

    try:
        try:
            raise TimeoutError("timed out")
        except TimeoutError as low:
            raise urllib.error.URLError(low)  # noqa: B904 - urllib's own shape: the cause is only the context
    except urllib.error.URLError as exc:
        assert calls.outcome_unknown(exc) is False
    assert calls.outcome_unknown(TimeoutError("read timed out")) is True


# --- A05: recovery keeps the overrun lock ---------------------------------------------------------------


def test_a05_recovery_reinstates_the_overrun_lock(tmp_path):
    with store.use_store(tmp_path / "jav.sqlite"):
        calls.set_budget("budget", "openai", Decimal("1"))
        result = calls.invoke(run_id="audit-run", step_id="first", provider="openai", model="synthetic",
                              max_cost_usd=Decimal("0.1"), budget_scope="budget",
                              fn=lambda: calls.Outcome(response={}, cost_usd=Decimal("0.2")))
        # the durable state of a crash after the response was saved and before the call was marked succeeded
        with store.connect() as c:
            c.execute("UPDATE invocations SET status='reserved', cost_usd=NULL, cost_known=0, note=NULL WHERE id=?",
                      (result.invocation_id,))
        calls.release_holder()  # 092: the process stops; the operating system lets go of its holder lock
        calls.recover_uncertain()
        row = calls.journal("audit-run")[0]
        assert row["status"] == "succeeded" and row["note"] == calls.OVERRUN_NOTE
        with pytest.raises(calls.BudgetExceeded):
            calls.invoke(run_id="audit-run", step_id="after-recovery", provider="openai", model="synthetic",
                         max_cost_usd=Decimal("0.1"), budget_scope="budget",
                         fn=lambda: calls.Outcome(response={}, cost_usd=Decimal("0.01")))


def test_a05_recovery_within_the_reservation_is_noted_as_recovered(tmp_path):
    with store.use_store(tmp_path / "jav.sqlite"):
        calls.set_budget("budget", "openai", Decimal("1"))
        result = calls.invoke(run_id="audit-run", step_id="first", provider="openai", model="synthetic",
                              max_cost_usd=Decimal("0.1"), budget_scope="budget",
                              fn=lambda: calls.Outcome(response={}, cost_usd=Decimal("0.05")))
        with store.connect() as c:
            c.execute("UPDATE invocations SET status='reserved', cost_usd=NULL, cost_known=0, note=NULL WHERE id=?",
                      (result.invocation_id,))
        calls.release_holder()  # 092: the process stops; the operating system lets go of its holder lock
        calls.recover_uncertain()
        assert calls.journal("audit-run")[0]["note"] == "recovered_saved_response"
