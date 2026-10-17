"""The email receiver does not let a slow client hold a connection open (076, the repeated audit's hardening point).

Every socket read is bounded (`READ_TIMEOUT_S`) and the whole body must arrive within `BODY_DEADLINE_S`. The limits
are shortened here so the test runs in about a second.

167 (review T-4): no test measures the elapsed time against a fixed limit any more, which a busy machine could break.
The client waits up to `CLIENT_PATIENCE_S` (25 times the shortened deadline, below the real 30 s read limit) and the
test asks who ended the connection: the server, or the client giving up. The trickled body counts the bytes sent.
"""

import json
import socket
import threading
import time

import pytest

from jav import ingest_server

CLIENT_PATIENCE_S = 20.0


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_server, "READ_TIMEOUT_S", 0.4)
    monkeypatch.setattr(ingest_server, "BODY_DEADLINE_S", 0.8)
    httpd = ingest_server.make_server(0, inbox_root=tmp_path / "inbox", token="secret-key")
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield {"port": httpd.server_address[1], "inbox": tmp_path / "inbox"}
    httpd.shutdown()
    httpd.server_close()


def _headers(length: int) -> bytes:
    return (f"POST /ingest/email HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer secret-key\r\n"
            f"Content-Type: application/json\r\nContent-Length: {length}\r\n\r\n").encode("ascii")


def _response(sock: socket.socket) -> tuple[bytes, bool]:
    """The bytes the server sent, and whether the server ended the connection (False: the client gave up waiting)."""
    sock.settimeout(CLIENT_PATIENCE_S)
    data = b""
    while True:
        try:
            chunk = sock.recv(4096)
        except (ConnectionResetError, ConnectionAbortedError):
            return data, True
        except TimeoutError:
            return data, False
        if not chunk:
            return data, True
        data += chunk


def test_a_body_that_never_arrives_gets_408(server):
    with socket.create_connection(("127.0.0.1", server["port"])) as s:
        s.sendall(_headers(100) + b'{"message_id": ')  # 15 of the promised 100 bytes, then silence
        reply, closed_by_server = _response(s)
    assert closed_by_server, f"the server kept a silent connection open for {CLIENT_PATIENCE_S} s"
    assert reply.startswith(b"HTTP/1.0 408") or reply.startswith(b"HTTP/1.1 408")
    assert not server["inbox"].exists()


def test_a_trickling_body_is_cut_off_at_the_deadline(server):
    body = json.dumps({"message_id": "m1", "account": "a", "subject": "x" * 200}).encode("utf-8")
    with socket.create_connection(("127.0.0.1", server["port"])) as s:
        s.sendall(_headers(len(body)))
        s.setblocking(False)
        reply, cut, sent = b"", False, 0
        for i in range(len(body)):  # one byte every 0.1 s: each read is fast, the whole body is not
            try:
                reply += s.recv(4096)  # the server answered (408) or closed (b"")
                cut = True
                break
            except BlockingIOError:
                pass
            except OSError:  # reset: the server closed with our unread bytes in its buffer (Windows)
                cut = True
                break
            try:
                s.send(body[i:i + 1])
                sent += 1
            except OSError:
                cut = True
                break
            time.sleep(0.1)
    assert cut, "the server kept reading the trickled body to the end"
    # the deadline (0.8 s) passes after about 8 bytes; half the body takes 12 s at this pace, and a busy machine only
    # slows the trickle down, so it sends fewer bytes before the deadline, never more
    assert sent < len(body) // 2, (sent, len(body))
    assert reply == b"" or b" 408 " in reply.split(b"\r\n", 1)[0]
    assert not server["inbox"].exists()


def test_silent_headers_close_the_connection(server):
    with socket.create_connection(("127.0.0.1", server["port"])) as s:
        s.sendall(b"POST /ingest/email HTTP/1.1\r\nHost: 127.0.0.1\r\n")  # the header block never ends
        reply, closed_by_server = _response(s)
    assert closed_by_server, f"the server waited for the rest of the headers for {CLIENT_PATIENCE_S} s"
    assert b"200" not in reply


def test_a_normal_request_is_unaffected(server):
    body = json.dumps({"message_id": "m2", "account": "box", "subject": "hello", "body_preview": "text"}).encode()
    with socket.create_connection(("127.0.0.1", server["port"])) as s:
        s.sendall(_headers(len(body)) + body)
        reply, _ = _response(s)
    assert b" 200 " in reply.split(b"\r\n", 1)[0]
