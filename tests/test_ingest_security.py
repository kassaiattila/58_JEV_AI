"""Input protection of the email receiver (040 K1; findings F01, F02, F03 of 038). Synthetic data, no live call, no
real email."""

import http.client
import json
import threading

import pytest

from jav import ingest_server
from jav.emails import load_message_dir


def _payload(**over):
    base = {"message_id": "ENTRY-1", "account": "box@example.com", "from": "a@example.com", "subject": "Számla",
            "body_preview": "Mesterséges törzs.", "received": "2026-09-27T10:00:00", "to": [], "cc": [], "attachments": []}
    base.update(over)
    return base


# --- F01: paths ----------------------------------------------------------------------------------


@pytest.mark.parametrize("account", ["C:/Windows/Temp/x", "/etc/passwd", "..\\..\\kint", "../kint", "\\\\server\\share\\x", ""])
def test_account_cannot_escape_inbox(tmp_path, account):
    root = tmp_path / "inbox"
    res = ingest_server.ingest_message(_payload(account=account), root)
    assert res["folder"].resolve().is_relative_to(root.resolve())
    assert res["folder"].parent.parent == root


def test_container_path_cannot_escape_old_data_root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "inbox").mkdir(parents=True)
    secret = tmp_path / "titok.pdf"
    secret.write_bytes(b"%PDF")
    inside = data / "inbox" / "ok.pdf"
    inside.write_bytes(b"%PDF")
    monkeypatch.setattr(ingest_server, "OLD_DATA_ROOT", data)
    assert ingest_server.host_path("/data/inbox/ok.pdf") == inside.resolve()
    assert ingest_server.host_path("/data/../titok.pdf") is None
    assert ingest_server.host_path("/data/inbox/../../titok.pdf") is None


def test_message_loader_refuses_external_attachment_paths(tmp_path, monkeypatch):
    from jav import emails
    outside = tmp_path / "kint.pdf"
    outside.write_bytes(b"%PDF")
    folder = tmp_path / "inbox" / "box" / "m1"
    folder.mkdir(parents=True)
    (folder / "helyi.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(emails, "OLD_DATA_ROOT", tmp_path / "data")
    meta = {"message_id": "m1", "attachments": [{"filename": "kint.pdf", "path": str(outside)},
                                                {"filename": "ki.pdf", "path": "../../../kint.pdf"},
                                                {"filename": "helyi.pdf"}]}
    (folder / "message.json").write_text(json.dumps(meta), encoding="utf-8")
    msg = load_message_dir(folder)
    assert [a.path is not None for a in msg.attachments] == [False, False, True]


# --- F03: repeats ----------------------------------------------------------------------------------


def test_identical_repeat_is_not_rewritten(tmp_path):
    root = tmp_path / "inbox"
    first = ingest_server.ingest_message(_payload(), root)
    stamp = (first["folder"] / "message.json").stat().st_mtime_ns
    again = ingest_server.ingest_message(_payload(batch_id="masik-batch"), root)  # only the batch differs
    assert first["status"] == "new" and again["status"] == "duplicate" and again["version"] == 1
    assert (first["folder"] / "message.json").stat().st_mtime_ns == stamp


def test_changed_content_becomes_explicit_new_version(tmp_path):
    root = tmp_path / "inbox"
    ingest_server.ingest_message(_payload(), root)
    changed = ingest_server.ingest_message(_payload(body_preview="MÁS törzs"), root)
    assert changed["status"] == "changed" and changed["version"] == 2
    folder = changed["folder"]
    assert json.loads((folder / "message.v1.json").read_text(encoding="utf-8"))["body"] == "Mesterséges törzs."
    assert json.loads((folder / "message.json").read_text(encoding="utf-8"))["body"] == "MÁS törzs"


# --- HTTP: F02 + F03 through the server ------------------------------------------------------------


@pytest.fixture()
def server(tmp_path, monkeypatch):
    runs = []

    def fake_run(folder):
        runs.append(folder)
        return {"run_id": f"r{len(runs)}", "intent": "szamla_erkezett", "confidence": 0.9, "next_flow": "m2:invoice_hu"}

    monkeypatch.setattr(ingest_server, "_run_flow", fake_run)
    httpd = ingest_server.make_server(0, run_flow=True, inbox_root=tmp_path / "inbox", token="titkos")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield {"port": httpd.server_address[1], "runs": runs, "root": tmp_path / "inbox"}
    httpd.shutdown()
    httpd.server_close()


def _post(port, body: bytes, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    h = {"Content-Type": "application/json", "Authorization": "Bearer titkos"}
    h.update(headers or {})
    c.request("POST", "/ingest/email", body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    return r.status, (json.loads(data) if data else {})


def test_unauthorized_request_refused(server):
    status, _ = _post(server["port"], json.dumps(_payload()).encode(), {"Authorization": "Bearer rossz"})
    assert status == 401 and not server["root"].exists() and server["runs"] == []


def test_oversized_request_refused_without_reading(server):
    try:
        status, _ = _post(server["port"], b"{}", {"Content-Length": str(ingest_server.MAX_BODY_BYTES + 1)})
    except ConnectionResetError:  # the server closes without reading: on Windows the client may see a reset
        status = 413
    assert status == 413 and not server["root"].exists() and server["runs"] == []


@pytest.mark.parametrize("body", [b"[1,2]", b"null", b"\"szoveg\"", b"{rossz json",
                                  json.dumps(_payload(attachments="nem lista")).encode(),
                                  json.dumps(_payload(attachments=[{"path": 5}])).encode(),
                                  json.dumps(_payload(subject=["lista"])).encode(),
                                  json.dumps(_payload(to=[1, 2])).encode()])
def test_malformed_payload_refused_before_write(server, body):
    status, _ = _post(server["port"], body)
    assert status == 400 and not server["root"].exists() and server["runs"] == []


def test_negative_length_refused(server):
    c = http.client.HTTPConnection("127.0.0.1", server["port"], timeout=5)
    c.putrequest("POST", "/ingest/email")
    c.putheader("Authorization", "Bearer titkos")
    c.putheader("Content-Type", "application/json")  # 066: without the JSON type it is refused earlier as browser-like
    c.putheader("Content-Length", "-5")
    c.endheaders()
    assert c.getresponse().status == 400


def test_repeat_post_does_not_run_flow_twice(server):
    body = json.dumps(_payload()).encode()
    s1, r1 = _post(server["port"], body)
    s2, r2 = _post(server["port"], body)
    assert (s1, s2) == (200, 200) and not r1["deduped"] and r2["deduped"]
    assert r2["run_id"] == r1["run_id"] == "r1" and len(server["runs"]) == 1


def test_changed_post_runs_again_as_new_version(server):
    _post(server["port"], json.dumps(_payload()).encode())
    s, r = _post(server["port"], json.dumps(_payload(body_preview="módosított")).encode())
    assert s == 200 and r["version"] == 2 and len(server["runs"]) == 2


def test_concurrent_identical_posts_run_once(server):
    body = json.dumps(_payload(message_id="PAR-1")).encode()
    results = []
    threads = [threading.Thread(target=lambda: results.append(_post(server["port"], body))) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(s == 200 for s, _ in results) and len(server["runs"]) == 1
    assert sum(not r["deduped"] for _, r in results) == 1


# --- 066 Á14: key only, never from a browser ---------------------------------------------------------------------


def test_server_without_a_configured_key_generates_one_and_refuses_keyless_requests(tmp_path, monkeypatch):
    monkeypatch.delenv(ingest_server.TOKEN_ENV, raising=False)
    httpd = ingest_server.make_server(0, inbox_root=tmp_path / "inbox")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        token = httpd.RequestHandlerClass.token
        assert token and len(token) >= 24
        c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=5)
        c.request("POST", "/ingest/email", body=json.dumps(_payload()).encode(), headers={"Content-Type": "application/json"})
        r = c.getresponse()
        r.read()
        assert r.status == 401 and not (tmp_path / "inbox").exists()
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize("headers", [
    {"Origin": "https://pelda.example"},                 # request sent from a browser
    {"Content-Type": "text/plain"},                       # "simple" browser request without a preflight
    {"Host": "tamado.example:8901"},                      # DNS rebinding: foreign host name
])
def test_browser_style_requests_are_refused_before_write(server, headers):
    status, _ = _post(server["port"], json.dumps(_payload()).encode(), headers)
    assert status == 403 and not server["root"].exists() and server["runs"] == []


def test_bodyless_seal_from_the_old_bridge_is_accepted(server):
    """The legacy bridge sends the batch seal without a body or content-type header (PowerShell
    `Invoke-RestMethod -Method Post`)."""
    c = http.client.HTTPConnection("127.0.0.1", server["port"], timeout=5)
    c.request("POST", "/api/intake-batches/jav-1/seal", headers={"Authorization": "Bearer titkos", "X-Actor": "outlook-bridge",
                                                                  "Content-Length": "0"})
    r = c.getresponse()
    r.read()
    assert r.status == 200


# --- 067: protective branches without a test, per the coverage run --------------------------------------------------


def _raw_post(port, path, headers):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest("POST", path)
    for k, v in headers.items():
        c.putheader(k, v)
    c.endheaders()
    r = c.getresponse()
    r.read()
    return r.status


def test_request_without_length_is_refused(server):
    # a body without a length (e.g. chunked) is not read: the size limit can only be checked against a given length
    headers = {"Authorization": "Bearer titkos", "Content-Type": "application/json"}
    assert _raw_post(server["port"], "/ingest/email", headers) == 411
    assert _raw_post(server["port"], "/ingest/email", {**headers, "Transfer-Encoding": "chunked"}) == 411
    assert not server["root"].exists() and server["runs"] == []


def test_non_numeric_length_is_refused(server):
    headers = {"Authorization": "Bearer titkos", "Content-Type": "application/json", "Content-Length": "abc"}
    assert _raw_post(server["port"], "/ingest/email", headers) == 400
    assert not server["root"].exists()


def test_batch_open_needs_a_json_object(server):
    c = http.client.HTTPConnection("127.0.0.1", server["port"], timeout=5)
    c.request("POST", "/api/intake-batches", body=b"[1]",
              headers={"Content-Type": "application/json", "Authorization": "Bearer titkos"})
    r = c.getresponse()
    r.read()
    assert r.status == 400


def test_unknown_paths_are_not_found(server):
    c = http.client.HTTPConnection("127.0.0.1", server["port"], timeout=5)
    c.request("GET", "/../store/jav.sqlite")
    r = c.getresponse()
    r.read()
    assert r.status == 404
    c = http.client.HTTPConnection("127.0.0.1", server["port"], timeout=5)
    c.request("POST", "/ingest/other", body=b"{}", headers={"Content-Type": "application/json", "Authorization": "Bearer titkos"})
    r = c.getresponse()
    r.read()
    assert r.status == 404


def test_folder_guard_holds_even_if_the_mailbox_name_is_not_sanitized(tmp_path, monkeypatch):
    # second line of defence: even if the mailbox-name sanitising failed, the computed folder stays inside the inbox
    root = tmp_path / "inbox"
    monkeypatch.setattr(ingest_server, "safe_mailbox_dir", lambda _name: "../../kint")
    with pytest.raises(ingest_server.BadPayload):
        ingest_server.ingest_message(_payload(), root)
    assert not (tmp_path / "kint").exists() and not tmp_path.parent.joinpath("kint").exists()


def test_failing_flow_is_reported_not_crashed(server, monkeypatch):
    def boom(folder):
        raise RuntimeError("kitalált hiba")

    monkeypatch.setattr(ingest_server, "_run_flow", boom)
    status, body = _post(server["port"], json.dumps(_payload(message_id="ENTRY-HIBA")).encode())
    assert status == 200 and body["error"].startswith("RuntimeError") and body["version"] == 1
