"""Invented outside registers on this machine, for the tests and the trial (231, stage D, D-d5).

Plain-language summary: a case's outside checks ask a company register with the policyholder's tax number and a
sanctions list with its name and tax number. No real register is asked in the tests or the trial: these two invented
ones answer from `configs/golden_registers.json` (every name and number invented), as a local web service on this
machine (`python -m jav.cli invented-services`, port 8941, the address the connectors `invented_company_register` and
`invented_sanctions_list` name) or, in the tests, inside the process (`transport`). Both answer JSON to a JSON question.

- `answer(path, body)`: the status and the answer of one question (`/company`: {"tax_number"} -> {"found", "company"};
  `/sanctions`: {"name", "tax_number"} -> {"listed", "entries"}: an entry matches by its tax number, or by its name
  written the same way, case, spaces and punctuation aside).
- `transport(down=)`: a connector transport answering in this process; a path in `down` is not reached.
- `server(port)`, `serve(port)`: the local web service (127.0.0.1 only).

Layer: development tool; the runtime never imports it.
"""

from __future__ import annotations

import http.server
import json
import logging
import re
import urllib.error
import urllib.parse
from typing import Any, Callable

from jav.core import cfg

__all__ = ["DATA", "PORT", "answer", "serve", "server", "transport"]

log = logging.getLogger(__name__)

DATA = "golden_registers"
PORT = 8941
MAX_QUESTION = 10_000


def _normal(name: str) -> str:
    return re.sub(r"[\W_]+", "", name.casefold())


def _company(question: dict[str, Any]) -> dict[str, Any]:
    tax = str(question.get("tax_number") or "").strip()
    found = cfg.load(DATA)["companies"].get(tax)
    return {"found": True, "company": {"tax_number": tax, **found}} if found else {"found": False}


def _sanctions(question: dict[str, Any]) -> dict[str, Any]:
    tax = str(question.get("tax_number") or "").strip()
    name = _normal(str(question.get("name") or ""))
    entries = []
    for entry in cfg.load(DATA)["sanctions"]:
        on = ("tax_number" if tax and entry.get("tax_number") == tax
              else "name" if name and _normal(entry.get("name") or "") == name else None)
        if on:
            entries.append({**entry, "matched_on": on})
    return {"listed": bool(entries), "entries": entries}


_ROUTES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {"/company": _company, "/sanctions": _sanctions}


def _json(data: dict[str, Any]) -> bytes:
    return json.dumps(data, ensure_ascii=False).encode("utf-8")


def answer(path: str, body: bytes | None) -> tuple[int, bytes]:
    """One question's status and answer (404: no such register; 400: not a JSON object)."""
    route = _ROUTES.get(urllib.parse.urlsplit(path).path)
    if route is None:
        return 404, _json({"error": "no such register"})
    try:
        question = json.loads(body or b"{}")
    except ValueError:
        question = None
    if not isinstance(question, dict):
        return 400, _json({"error": "the question is a JSON object"})
    return 200, _json(route(question))


def transport(*, down: frozenset[str] = frozenset()) -> Callable[[str, bytes | None, dict[str, str], float], bytes]:
    """A connector transport (`connectors.use_transport`) answering the invented registers in this process; a path in
    `down` (e.g. "/sanctions") is not reached, as a service that is down."""
    def send(url: str, body: bytes | None, _headers: dict[str, str], _timeout: float) -> bytes:
        path = urllib.parse.urlsplit(url).path
        if path in down:
            raise urllib.error.URLError("the invented register is down")
        status, data = answer(path, body)
        if status != 200:
            raise urllib.error.HTTPError(url, status, data.decode("utf-8"), None, None)  # type: ignore[arg-type]
        return data

    return send


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - the standard library's name
        length = int(self.headers.get("Content-Length") or 0)
        status, data = answer(self.path, self.rfile.read(min(length, MAX_QUESTION)))
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the standard library's name
        log.info("invented register: " + format, *args)


def server(port: int = PORT) -> http.server.ThreadingHTTPServer:
    """The local web service of the invented registers on 127.0.0.1 (port 0: any free port)."""
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), _Handler)


def serve(port: int = PORT) -> None:
    """Runs the local web service until stopped."""
    with server(port) as running:
        log.info("invented registers on http://127.0.0.1:%d (company, sanctions)", running.server_address[1])
        running.serve_forever()
