"""Mailbox reading (048 T2): preview, download via a temporary email receiver, work package from fresh mail, recipe.

A fake runner stands in for the legacy Outlook script: for the download it imitates the real script (open a batch, send
each message to the given address with the given key, seal). Synthetic messages, fake JEV, no paid call.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from pydantic import ValidationError

from jav import emails, ingest_server, mailbox, store, work
from jav.adapters import jev as jev_mod
from jav.config import BRIDGE_ROOT, OLD_PROJECT_ROOT
from jav.runtime import worker
from tests.test_email_signals import FakeClient  # Choice + Noul + Score (the graded signals of the intent question)

REQ = mailbox.MailboxRequest(accounts=["iroda@minta.hu"], since_days=7)
MAILS = [
    {"message_id": "EID-0001", "account": "iroda@minta.hu", "from": "szamla@szolgaltato.hu", "sender": "Szolgáltató Kft.",
     "to": ["iroda@minta.hu"], "subject": "Számla 2026/09", "body_preview": "Mellékelten küldjük a szeptemberi számlát.",
     "received": "2026-09-27T10:00:00", "attachments": []},
    {"message_id": "EID-0002", "account": "iroda@minta.hu", "from": "ugyfel@pelda.hu", "sender": "Minta Ügyfél",
     "to": ["iroda@minta.hu"], "subject": "Kérdés", "body_preview": "Mikor érkezik a szerződés?",
     "received": "2026-09-27T11:00:00", "attachments": []},
]


def _arg(argv: list[str], name: str) -> str:
    return argv[argv.index(f"-{name}") + 1]


def _post(url: str, body: dict, token: str | None) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, {}


class FakeBridge:
    """The legacy script's download branch: batch, one send per message, seal. `unauthorized`: a keyless attempt too."""

    def __init__(self, mails: list[dict]) -> None:
        self.mails, self.argv, self.unauthorized = mails, [], None

    def __call__(self, argv: list[str], timeout: int) -> tuple[int, str, str]:
        self.argv = argv
        if _arg(argv, "Mode") == "count":
            return 0, 'naplósor\n{"count_only":true,"received_from":"2026-09-21T00:00:00","received_to":null,"eligible":2,' \
                      '"counts":{"scanned":5,"mail":3,"skippedSeen":1},"accounts":[{"account":"iroda@minta.hu","counts":{"mail":2}}]}\n', ""
        url, token = _arg(argv, "OrchUrl"), _arg(argv, "ApiToken")
        base = url.rsplit("/ingest/email", 1)[0]
        self.unauthorized = _post(url, self.mails[0], None)[0]
        _, batch = _post(base + "/api/intake-batches", {"name": "t"}, token)
        for m in self.mails:
            assert _post(url, {**m, "batch_id": batch["id"]}, token)[0] == 200
        _post(f"{base}/api/intake-batches/{batch['id']}/seal", {}, token)
        return 0, "=== TOTAL :: processed=2 ===\n", ""


@pytest.fixture()
def env(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ingest_server, "BRIDGE_DATA_ROOT", tmp_path / "bridge" / "data")
    monkeypatch.setattr(emails, "BRIDGE_DATA_ROOT", tmp_path / "bridge" / "data")
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        yield {"inbox": tmp_path / "inbox"}


def test_request_is_validated():
    with pytest.raises(ValidationError):
        mailbox.MailboxRequest(accounts=["nem cím"])
    with pytest.raises(ValidationError):
        mailbox.MailboxRequest(accounts=["a@b.hu"], received_from="2026-09-01")
    with pytest.raises(ValidationError):
        mailbox.MailboxRequest(accounts=["a@b.hu"], folders=["Inbox'; rm"])
    r = mailbox.MailboxRequest(accounts=["a@b.hu"], received_from="2026-09-01", received_to="2026-09-10")
    argv = mailbox._argv(r, "count")
    assert _arg(argv, "ReceivedTo") == "2026-09-10T23:59:59" and "-SinceDays" not in argv
    # the legacy script's project root is our own bridge root, not the (read-only) legacy project
    assert Path(_arg(argv, "RepoRoot")) == BRIDGE_ROOT and not Path(_arg(argv, "RepoRoot")).is_relative_to(OLD_PROJECT_ROOT)


def test_downloaded_package_owner_is_who_started_the_download(env):
    """065 decision: a downloaded package's owner is its starter; if scheduled, whoever saved the schedule."""
    res = mailbox.fetch(REQ, actor="Kiss Anna", runner=FakeBridge(MAILS), inbox_root=env["inbox"])
    assert work.get(res["workpackage"])["owner"] == "Kiss Anna"
    assert mailbox.owner_of("ütemezés (Nagy Béla)") == "Nagy Béla"
    assert mailbox.owner_of("Kiss Anna") == "Kiss Anna"


def test_count_preview_parses_the_bridge_result():
    out = mailbox.count(REQ, runner=FakeBridge(MAILS))
    assert out["eligible"] == 2 and out["already_read"] == 1 and out["accounts"] == [{"account": "iroda@minta.hu", "eligible": 2}]
    assert out["in_period"] == 3  # 065: all mail in the period (legacy `counts.mail`), not the 2 to download
    with pytest.raises(mailbox.BridgeError, match="Outlook must"):
        mailbox.count(REQ, runner=lambda argv, t: (1, "", "Outlook must already be running in the current interactive session."))


def test_fetch_creates_a_workpackage_of_fresh_mail_only(env):
    bridge = FakeBridge(MAILS)
    res = mailbox.fetch(REQ, actor="teszt", runner=bridge, inbox_root=env["inbox"])
    assert bridge.unauthorized == 401  # the temporary receiver accepts only the one-off key
    assert (res["new"], res["duplicate"]) == (2, 0) and res["workpackage"]
    wp = work.get(res["workpackage"])
    assert wp["source_kind"] == "mailbox" and {i["kind"] for i in wp["items"]} == {"email"} and len(wp["items"]) == 2
    assert wp["assignment"]["recipe_id"] == "processing" and wp["assignment"]["actor"] == "teszt"  # 080
    assert all(Path(i["source_path"]).name == "message.json" for i in wp["items"])

    again = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge(MAILS), inbox_root=env["inbox"])
    assert (again["new"], again["duplicate"], again["workpackage"]) == (0, 2, None)  # no new message: no package


def test_email_recipe_runs_in_the_worker(env):
    res = mailbox.fetch(REQ, actor="teszt", runner=FakeBridge(MAILS), inbox_root=env["inbox"])
    wp_id = res["workpackage"]
    ready = work.readiness(wp_id)
    assert ready["ready"], ready["blockers"]
    run_id = work.start_run(wp_id, mode="shadow", expected_assignment_revision=1, input_hash=ready["input_hash"], actor="t")["run_id"]
    info = worker.run_worker(once=True)
    assert info["results"] == {"done": 2}, info
    run = work.get_run(run_id)
    assert {i["status"] for i in run["items"]} == {"done"}
    with store.connect() as c:
        rows = c.execute("SELECT message_id, intent, run_id FROM emails").fetchall()
    assert len(rows) == 2 and all(r["intent"] for r in rows)
    assert {r["run_id"] for r in rows} == {work.flow_run_id(run_id, i["item_id"]) for i in work.get(wp_id)["items"]}


# --- scheduling (048 T2.2) -----------------------------------------------------------------------------------


def test_schedule_tick_enqueues_once_per_slot(tmp_path):
    from datetime import datetime, timedelta, timezone

    from jav.runtime import queue

    with store.use_store(tmp_path / "s.sqlite"):
        with pytest.raises(ValueError):  # a schedule only makes sense with "last N days"
            mailbox.create_schedule(mailbox.MailboxRequest(accounts=["a@b.hu"], received_from="2026-09-01", received_to="2026-09-02"), actor="t")
        sch = mailbox.create_schedule(mailbox.MailboxRequest(accounts=["a@b.hu"], since_days=3), actor="t")
        assert sch["interval_min"] == 60 and sch["enabled"]
        now = datetime.now(timezone.utc)
        assert len(mailbox.tick(now)) == 1
        assert mailbox.tick(now) == []  # no second job in the same time slot
        assert len(mailbox.tick(now + timedelta(minutes=61))) == 1
        mailbox.update_schedule(sch["id"], enabled=False)
        assert mailbox.tick(now + timedelta(days=1)) == []
        assert queue.counts() == {"queued": 2}


def test_scheduled_pull_runs_in_the_worker_and_records_the_outcome(env, monkeypatch):
    monkeypatch.setattr(ingest_server, "INBOX_ROOT", env["inbox"])
    monkeypatch.setattr(mailbox, "_subprocess_runner", FakeBridge(MAILS))
    sch = mailbox.create_schedule(REQ, actor="teszt")
    info = worker.run_worker(once=True)
    assert info["results"] == {"done": 1}
    after = mailbox.schedule(sch["id"])
    assert after["last_status"] == "ok" and after["last_result"]["new"] == 2 and after["last_result"]["workpackage"]
    wp = work.get(after["last_result"]["workpackage"])
    assert wp["assignment"]["actor"] == "ütemezés (teszt)" and not work.runs(wp["id"])  # no paid run started

    # Outlook not running: the error shows on the schedule, the worker does not stop, the job is not repeated
    monkeypatch.setattr(mailbox, "_subprocess_runner", lambda argv, t: (1, "", "Outlook must already be running."))
    mailbox.update_schedule(sch["id"], enabled=False)
    mailbox.update_schedule(sch["id"], enabled=True)  # switching on = due at once
    assert worker.run_worker(once=True)["results"] == {"done": 1}
    failed = mailbox.schedule(sch["id"])
    assert failed["last_status"] == "error" and "Outlook" in failed["last_result"]["error"]


def test_manual_pull_goes_through_the_worker(env, monkeypatch):
    monkeypatch.setattr(ingest_server, "INBOX_ROOT", env["inbox"])
    monkeypatch.setattr(mailbox, "_subprocess_runner", FakeBridge(MAILS))
    p = mailbox.request_pull(REQ, actor="teszt")
    assert p["status"] == "queued" and p["schedule_id"] is None
    worker.run_worker(once=True)
    done = mailbox.pull(p["id"])
    assert done["status"] == "ok" and done["result"]["new"] == 2 and done["finished_at"]
    assert [x["id"] for x in mailbox.pulls()] == [p["id"]]
    mailbox.request_pull(mailbox.MailboxRequest(accounts=["IRODA@minta.hu", "masik@minta.hu"], since_days=1), actor="teszt")
    assert mailbox.known_accounts() == ["iroda@minta.hu"]  # only a successful download's address; once, any case


def test_service_endpoints(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from jav import api

    db = tmp_path / "api.sqlite"
    monkeypatch.setattr(ingest_server, "INBOX_ROOT", tmp_path / "inbox")
    monkeypatch.setattr(ingest_server, "BRIDGE_DATA_ROOT", tmp_path / "bridge" / "data")
    monkeypatch.setattr(mailbox, "_subprocess_runner", FakeBridge(MAILS))
    c = TestClient(api.create_app(store_path=db), base_url="http://127.0.0.1:8930")
    human = {"X-Actor": "teszt.elek"}
    body = {"accounts": ["iroda@minta.hu"], "since_days": 7}

    assert c.post("/api/mailbox/count", json=body).json()["eligible"] == 2
    assert c.post("/api/mailbox/count", json={**body, "extra": 1}).status_code == 422
    assert c.post("/api/mailbox/pulls", json=body).status_code == 422  # no download without an author
    pull = c.post("/api/mailbox/pulls", json=body, headers=human).json()
    assert pull["status"] == "queued"

    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    with store.use_store(db), jev_mod.use_adapter(adapter):
        worker.run_worker(once=True)
        wp_id = mailbox.pull(pull["id"])["result"]["workpackage"]
        ready = work.readiness(wp_id)
        run_id = work.start_run(wp_id, mode="shadow", expected_assignment_revision=1, input_hash=ready["input_hash"], actor="t")["run_id"]
        worker.run_worker(once=True)
        item_id = work.get(wp_id)["items"][0]["item_id"]
    got = c.get(f"/api/mailbox/pulls/{pull['id']}").json()
    assert got["status"] == "ok" and got["result"]["new"] == 2
    item = c.get(f"/api/runs/{run_id}/items/{item_id}").json()
    assert item["kind"] == "email" and item["email"]["subject"] in ("Számla 2026/09", "Kérdés")
    assert item["email"]["result"]["intent"] and item["email"]["result"]["from_this_run"] is True

    sch = c.post("/api/mailbox/schedules", json={"request": {**body, "since_days": 3}}, headers=human)
    assert sch.status_code == 201 and sch.json()["interval_min"] == 60
    sid = sch.json()["id"]
    assert c.patch(f"/api/mailbox/schedules/{sid}", json={"enabled": False}, headers=human).json()["enabled"] is False
    assert c.patch(f"/api/mailbox/schedules/{sid}", json={"interval_min": 5}, headers=human).status_code == 422
    assert [s["id"] for s in c.get("/api/mailbox").json()["schedules"]] == [sid]
    assert c.get("/api/mailbox").json()["accounts"] == ["iroda@minta.hu"]  # 058: a used address is selectable
    assert c.post(f"/api/mailbox/schedules/{sid}/delete", json={}, headers=human).status_code == 200

    monkeypatch.setattr(mailbox, "_subprocess_runner", lambda argv, t: (1, "", "Outlook must already be running."))
    r = c.post("/api/mailbox/count", json=body)
    assert r.status_code == 503 and "Outlook" in r.text


def test_bookkeeping_files_are_not_attachments(tmp_path):
    from jav.emails import load_message_dir

    d = tmp_path / "abc"
    d.mkdir()
    (d / "message.json").write_text(json.dumps({"message_id": "abc", "subject": "x", "body": "y"}), encoding="utf-8")
    for name in ("receipt.json", "message.v1.json", "szamla.pdf"):
        (d / name).write_text("{}", encoding="utf-8")
    assert [a.filename for a in load_message_dir(d).attachments] == ["szamla.pdf"]
