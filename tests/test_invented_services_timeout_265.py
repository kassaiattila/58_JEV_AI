"""265 (code review X-01): the invented registers the live start runs close a connection that sends nothing.

`dev.ps1 start` runs the invented company register and sanctions list beside the service, because the insurance
cases ask them (their connectors point there), so they stay in the live start; but their handler had no read timeout,
and a connection that sent nothing held a thread for good. Now each socket read waits at most `READ_TIMEOUT_S`.
"""

from __future__ import annotations

import socket
import threading

from jav.devtools import invented_services


def test_a_silent_connection_is_closed(monkeypatch) -> None:
    monkeypatch.setattr(invented_services._Handler, "timeout", 0.5)
    running = invented_services.server(0)
    threading.Thread(target=running.serve_forever, daemon=True).start()
    try:
        with socket.create_connection(running.server_address, timeout=5) as conn:
            conn.settimeout(5)
            assert conn.recv(1024) == b""  # the register closed it; the reader did not hang
    finally:
        running.shutdown()
        running.server_close()
