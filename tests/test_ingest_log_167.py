"""167 (review S-6): the email receiver's log lines do not carry the email's subject.

The receiver printed each message's subject; in a mailbox download it runs inside the worker, whose output the
development script keeps in `runs/dev/worker.log` (not rotated, not filtered). A log line now names the message's
folder (a hash of the mailbox's message id), its version and status, and on a failure the error's type only.
Synthetic messages only.
"""

import json
import threading
import urllib.request

import pytest

from jav import ingest_server

SUBJECT = "Private matter 4417 about Someone"


@pytest.fixture()
def receiver(tmp_path, monkeypatch):
    def start(run_flow: bool):
        httpd = ingest_server.make_server(0, run_flow=run_flow, inbox_root=tmp_path / "inbox", token="k" * 24)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return httpd.server_address[1]

    servers: list = []
    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


def _send(port: int, message_id: str) -> dict:
    body = json.dumps({"message_id": message_id, "account": "box@example.com", "subject": SUBJECT,
                       "body_preview": "text"}).encode("utf-8")
    req = urllib.request.Request(f"http://127.0.0.1:{port}/ingest/email", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + "k" * 24})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def test_a_stored_message_is_logged_without_its_subject(receiver, capfd):
    port = receiver(run_flow=False)
    first = _send(port, "ENTRY-1")
    again = _send(port, "ENTRY-1")
    out = capfd.readouterr().out
    folder = ingest_server.short_hash("ENTRY-1")
    assert out.count(f"[mail] {folder}") == 2 and "unchanged" in out
    assert not first["deduped"] and again["deduped"]
    assert "Private" not in out and "Someone" not in out


def test_a_failed_flow_is_logged_with_the_error_type_only(receiver, capfd, monkeypatch):
    def failing(folder):
        raise ValueError(f"could not read the subject {SUBJECT!r}")

    monkeypatch.setattr(ingest_server, "_run_flow", failing)
    port = receiver(run_flow=True)
    resp = _send(port, "ENTRY-2")
    out = capfd.readouterr().out
    assert "ValueError" in out and "Private" not in out and "Someone" not in out
    assert resp["error"].startswith("ValueError")  # the bridge still gets the whole message
