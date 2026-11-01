"""272 (K2, the check of SEC-02): the email receiver's flows run under the command's budget in the request's thread.

265 (SEC-02) gave the receiver a budget (`email-ingest-server --run --jev-budget-usd`) and handed the command's context
to the server, whose request threads would otherwise run without one, so every paid call would be refused. The
hand-over itself was not tried: here a real server on a free port takes one message, and the flow (a stand-in) sees
the budget's scope in the request's thread. Synthetic message; no AI is asked.
"""

from __future__ import annotations

import contextvars
import http.client
import json
import threading
from decimal import Decimal

from jav.core import calls, store
from jav.domains.email import ingest_server


def _payload() -> dict:
    return {"message_id": "ENTRY-272", "account": "box@example.com", "from": "a@example.com", "subject": "Invoice",
            "body_preview": "An invented body.", "received": "2026-11-01T10:00:00", "to": [], "cc": [],
            "attachments": []}


def test_a_request_s_flow_runs_under_the_command_s_budget(tmp_path, monkeypatch):
    seen: list[object] = []

    def flow(folder):
        seen.append((threading.current_thread().name, calls.current()))
        return {"run_id": "r-272", "intent": None, "next_flow": None}

    monkeypatch.setattr(ingest_server, "_run_flow", flow)
    monkeypatch.setattr(ingest_server, "record_run", lambda *_a, **_k: None)
    with store.use_store(tmp_path / "t.sqlite"):
        calls.set_budget("ingest-272", "jev", Decimal("0.10"))
        with calls.use_run(budget_scope="ingest-272"):
            context = contextvars.copy_context()  # as `serve` takes it inside the command's budget
        httpd = ingest_server.make_server(0, run_flow=True, inbox_root=tmp_path / "inbox", token="t-272",
                                          flow_context=context)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            c = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
            c.request("POST", "/ingest/email", body=json.dumps(_payload()).encode("utf-8"),
                      headers={"Content-Type": "application/json", "Authorization": "Bearer t-272"})
            assert c.getresponse().status == 200
        finally:
            httpd.shutdown()
            httpd.server_close()
    assert len(seen) == 1
    thread, ctx = seen[0]
    assert thread != threading.current_thread().name  # the request's own thread
    assert ctx is not None and ctx.budget_scope == "ingest-272"
