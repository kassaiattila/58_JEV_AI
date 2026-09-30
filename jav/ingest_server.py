"""Local receiver for the LEGACY `10_AIFLOW_V4/scripts/outlook_bridge.ps1` - the bridge runs unchanged.

The bridge (desktop Outlook COM, read-only) POSTs each message to the legacy orchestrator's `/ingest/email` endpoint and
saves the document attachments under the legacy `data/inbox/email/<acct>/<eid>/`. This small stdlib HTTP server offers
the same three endpoints the bridge calls (open batch, ingest per message, seal) and writes the message into the M3
inbox model: `inbox/<mailbox>/<message_id>/message.json` (body = `body_preview`, which the bridge sends up to 20,000
characters; the attachments point to the host files the bridge has already saved). Afterwards `email-inbox inbox/` runs
the M3 graph, or with `--run` it runs immediately and synchronously.

Input protection (040 K1, findings F01–F03 of 038):
- F01: the server derives the mailbox folder name (only `[A-Za-z0-9._-]`), and every computed path must stay inside the
  root after resolution (`..`, absolute, UNC, or a link pointing outside the root never writes/reads outside).
- F02: `Content-Length` is required, 0..`MAX_BODY_BYTES`; the body is a JSON object with typed fields and item-count
  limits; on error 400/411/413, with no file written and no process started. `Authorization: Bearer <key>` is always
  required (sent by the bridge's `-ApiToken` switch); the key is `JAV_INGEST_TOKEN` or `--token`, failing that a random
  key made at startup, which the receiver prints (066 Á14). A request from a browser (Origin header, non-JSON body,
  foreign host name) is refused with 403.
- F03: mailbox + message id + content hash: an unchanged repeat is not overwritten and starts no new run (the original
  receipt is returned); changed content is an explicit new version (`message.v<n>.json` keeps the old one).
  An in-process lock guards against concurrent repeats.
- Read time limits (076): every socket read waits at most `READ_TIMEOUT_S`, and the whole body must arrive within
  `BODY_DEADLINE_S`; a client that sends slowly or not at all gets 408 (or, while still sending its headers, a closed
  connection) instead of holding a thread open.

Start:    python -m jav.cli email-ingest-server [--port 8931] [--run]
Bridge:   powershell -File <legacy-root>\\scripts\\outlook_bridge.ps1 -Accounts <smtp> -SinceDays 30
              -MaxItems 50 -AllEmails -ManualRun -NoArchive -WorkflowId email-intent -WorkflowVersion 1 [-ApiToken <key>]
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from jav.config import BRIDGE_DATA_ROOT, OLD_DATA_ROOT, PROJECT_ROOT

INBOX_ROOT = PROJECT_ROOT / "inbox"
WORKFLOW_HASH = "jav-m3-email-intent"
TOKEN_ENV = "JAV_INGEST_TOKEN"
MAX_BODY_BYTES = 2 * 1024 * 1024
READ_TIMEOUT_S = 30.0  # per socket read (headers and body); the bridge sends each message in one go on 127.0.0.1
BODY_DEADLINE_S = 60.0  # the whole body; 2 MB on the local machine takes milliseconds
_READ_CHUNK = 64 * 1024
MAX_TEXT = 200_000
MAX_LIST = 200
MAX_ATTACHMENTS = 100
_CONTAINER_DATA = re.compile(r"^/data/(.*)$")
_SAFE = re.compile(r"[^A-Za-z0-9._-]")
_LOCK = threading.Lock()
_STR_FIELDS = ("message_id", "account", "from", "sender", "subject", "body_preview", "received", "batch_id", "ocr_policy")
_LIST_FIELDS = ("to", "cc")


class BadPayload(ValueError):
    """The request structure is invalid; nothing is written and no process starts."""


def short_hash(entry_id: str, n: int = 16) -> str:
    """The bridge's `Get-ShortHash`: the first 16 hex digits of md5(UTF-8 EntryID) = the folder name."""
    return hashlib.md5(entry_id.encode("utf-8")).hexdigest()[:n]


def safe_mailbox_dir(account: str) -> str:
    """Server-derived folder name from the mailbox: `a@b.hu` -> `a_b.hu`; no separator, `..` or drive colon survives."""
    name = _SAFE.sub("_", account.replace("@", "_")).strip("._")[:100]
    return name or "unknown"


def _inside(path: Path, root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def _inside_lexical(path: Path, root: Path) -> bool:
    """Containment by path text (`..` resolved, without touching the file system)."""
    p, r = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    return os.path.commonpath([p, r]) == r


def host_path(container_path: str) -> Path | None:
    """`/data/inbox/email/<acct>/<eid>/<file>` (container path) -> host file under a bridge `data/` root: first our own
    bridge root (048 T2, a download started from the local service), then the legacy project's `data/` folder (a bridge
    running with the legacy settings). Only if the resolved path is inside the root and exists."""
    m = _CONTAINER_DATA.match(container_path.replace("\\", "/"))
    if not m:
        return None
    for root in (BRIDGE_DATA_ROOT, OLD_DATA_ROOT):
        p = (root / m.group(1)).resolve()
        if _inside(p, root) and p.is_file():
            return p
    return None


def validate_payload(payload: Any) -> dict[str, Any]:
    """Typed structure check of the bridge payload (F02); raises `BadPayload` on error."""
    if not isinstance(payload, dict):
        raise BadPayload("payload must be a JSON object")
    for key in _STR_FIELDS:
        v = payload.get(key)
        if v is not None and (not isinstance(v, str) or len(v) > MAX_TEXT):
            raise BadPayload(f"{key} must be a string of at most {MAX_TEXT} characters")
    for key in _LIST_FIELDS:
        v = payload.get(key)
        if v is not None and (not isinstance(v, list) or len(v) > MAX_LIST or not all(isinstance(x, str) and len(x) < 1000 for x in v)):
            raise BadPayload(f"{key} must be a list of strings")
    atts = payload.get("attachments")
    if atts is not None:
        if not isinstance(atts, list) or len(atts) > MAX_ATTACHMENTS:
            raise BadPayload("attachments must be a list")
        for a in atts:
            if not isinstance(a, dict) or any(a.get(k) is not None and (not isinstance(a.get(k), str) or len(a[k]) > 1000)
                                              for k in ("path", "filename")):
                raise BadPayload("attachment entries must be objects with string path/filename")
    return payload


def _record(payload: dict[str, Any], msg_id: str, mailbox: str) -> dict[str, Any]:
    atts = []
    for a in payload.get("attachments") or []:
        p = host_path(str(a.get("path") or ""))
        atts.append({"filename": a.get("filename") or Path(str(a.get("path"))).name, "path": str(p) if p else None,
                     "container_path": a.get("path")})
    return {
        "message_id": msg_id,
        "entry_id": str(payload.get("message_id") or ""),
        "mailbox": mailbox,
        "sender": payload.get("from"),
        "sender_name": payload.get("sender"),
        "to": payload.get("to") or [],
        "cc": payload.get("cc") or [],
        "subject": payload.get("subject") or "",
        "received_at": payload.get("received"),
        "body": payload.get("body_preview") or "",
        "attachments": atts,
        "attachments_failed": payload.get("attachments_failed"),
    }


def _content_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8"))
    os.replace(tmp, path)


def ingest_message(payload: dict[str, Any], inbox_root: Path = INBOX_ROOT) -> dict[str, Any]:
    """Bridge payload -> `inbox/<mailbox>/<message>/`. Result: folder, `status` (new | duplicate | changed), version
    number and the receipt (on a repeat the earlier one, e.g. with the run identifier)."""
    validate_payload(payload)
    entry_id = str(payload.get("message_id") or "")
    msg_id = short_hash(entry_id) if entry_id else uuid.uuid4().hex[:16]
    mailbox = str(payload.get("account") or "unknown")
    folder = Path(inbox_root) / safe_mailbox_dir(mailbox) / msg_id
    # a textual check first (on a folder that does not exist yet, `resolve()` can fail on Windows during concurrent
    # creation, which wrongly reported "escapes the root" - Q-flaky, 048); after creation, under the lock, a second
    # check that also follows links
    if not _inside_lexical(folder, Path(inbox_root)):
        raise BadPayload("computed folder escapes the inbox root")
    record = _record(payload, msg_id, mailbox)
    digest = _content_hash(record)
    with _LOCK:
        folder.mkdir(parents=True, exist_ok=True)
        if not _inside(folder, Path(inbox_root)):
            raise BadPayload("computed folder escapes the inbox root")
        receipt_path = folder / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else None
        if receipt is None and (folder / "message.json").exists():  # pre-040 folder: the existing content is version 1
            old = json.loads((folder / "message.json").read_text(encoding="utf-8"))
            receipt = {"version": 1, "content_sha256": _content_hash({k: old.get(k) for k in record}), "run_id": None}
        if receipt is not None and receipt["content_sha256"] == digest:
            return {"folder": folder, "status": "duplicate", "version": receipt["version"], "receipt": receipt}
        version = 1 if receipt is None else receipt["version"] + 1
        if receipt is not None:
            os.replace(folder / "message.json", folder / f"message.v{receipt['version']}.json")
        _write_json(folder / "message.json", {**record, "batch_id": payload.get("batch_id"),
                                              "pulled_at": datetime.now().isoformat(timespec="seconds"), "version": version})
        new_receipt = {"version": version, "content_sha256": digest, "run_id": None}
        _write_json(receipt_path, new_receipt)
    return {"folder": folder, "status": "new" if version == 1 else "changed", "version": version, "receipt": new_receipt}


def write_message(payload: dict[str, Any], inbox_root: Path = INBOX_ROOT) -> tuple[Path, bool]:
    """Legacy interface: (folder, whether it already existed unchanged)."""
    res = ingest_message(payload, inbox_root)
    return res["folder"], res["status"] == "duplicate"


def record_run(folder: Path, run_id: str | None) -> None:
    with _LOCK:
        path = folder / "receipt.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["run_id"] = run_id
        _write_json(path, receipt)


def _run_flow(folder: Path) -> dict[str, Any]:
    from jav.flow_email import run_email

    st = run_email(str(folder))
    r = st.result
    return {"run_id": st.run_id, "intent": r.intent if r else None, "confidence": r.confidence if r else None, "next_flow": st.next_flow}


class _Handler(BaseHTTPRequestHandler):
    server_version = "jav-ingest/0.2"
    run_flow = False
    inbox_root = INBOX_ROOT
    token: str | None = None
    on_ingest = None  # 048 T2: the code that starts the download collects the stored messages (set as a staticmethod)

    def _json(self, code: int, body: dict[str, Any]) -> None:
        raw = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        if not self.token:  # 066 Á14: nothing without a key (`make_server` always provides one)
            return False
        got = self.headers.get("Authorization") or ""
        return hmac.compare_digest(got.encode("utf-8"), f"Bearer {self.token}".encode("utf-8"))

    def _from_browser(self) -> bool:
        """066 Á14: a request coming from a browser (Origin header, non-JSON body, or a foreign host name: DNS
        rebinding). The legacy bridge and the download send from PowerShell, with JSON, to 127.0.0.1, without an Origin
        header; sealing a batch goes without a body or content-type header, so the type is checked only with a body."""
        if self.headers.get("Origin") is not None:
            return True
        has_body = (self.headers.get("Content-Length") or "0").strip() not in ("", "0") or "Transfer-Encoding" in self.headers
        if has_body and (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower() != "application/json":
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
        return host not in ("127.0.0.1", "localhost", "::1")

    def _read(self) -> Any:
        """Size-limited read; errors are raised as a (code, message) exception."""
        length = self.headers.get("Content-Length")
        if length is None:
            raise _HttpError(411, "Content-Length required")
        try:
            n = int(length)
        except ValueError:
            raise _HttpError(400, "invalid Content-Length") from None
        if n < 0:
            raise _HttpError(400, "negative Content-Length")
        if n > MAX_BODY_BYTES:
            raise _HttpError(413, f"body exceeds {MAX_BODY_BYTES} bytes")
        raw = self._read_body(n)
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError) as exc:
            raise _HttpError(400, f"bad json: {exc}") from None

    def _read_body(self, n: int) -> bytes:
        """Reads `n` bytes in chunks; each read is bounded by the socket timeout (`READ_TIMEOUT_S`) and the whole body by
        `BODY_DEADLINE_S` (076), so a client trickling a byte at a time cannot keep the connection open."""
        deadline = time.monotonic() + BODY_DEADLINE_S
        parts: list[bytes] = []
        got = 0
        try:
            while got < n:
                if time.monotonic() > deadline:
                    raise _HttpError(408, "request body not received in time")
                chunk = self.rfile.read1(min(_READ_CHUNK, n - got))
                if not chunk:
                    raise _HttpError(400, "incomplete body")
                parts.append(chunk)
                got += len(chunk)
        except TimeoutError:
            raise _HttpError(408, "request body not received in time") from None
        return b"".join(parts)

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter default log
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in ("", "/health"):
            self._json(200, {"ok": True, "service": "jav-m3-ingest", "auth": bool(self.token)})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        refused = (403, "browser requests are not accepted") if self._from_browser() else \
            (401, "unauthorized") if not self._authorized() else None
        if refused:
            try:  # drain a bounded body so that the client gets a proper response (not a connection reset)
                n = int(self.headers.get("Content-Length") or 0)
                if 0 < n <= MAX_BODY_BYTES:
                    self._read_body(n)  # under the same time limits as an accepted body (076)
            except (_HttpError, ValueError, OSError):
                pass
            self.close_connection = True
            self._json(refused[0], {"error": refused[1]})
            return
        try:
            payload = self._read()
        except _HttpError as exc:
            self.close_connection = True
            self._json(exc.code, {"error": exc.message})
            return
        if path == "/api/intake-batches":
            if not isinstance(payload, dict):
                self._json(400, {"error": "payload must be a JSON object"})
                return
            batch_id = f"jav-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
            print(f"[batch] {batch_id} {str(payload.get('name'))[:80]}")
            self._json(200, {
                "id": batch_id, "workflow_id": payload.get("workflow_id") or "", "workflow_version": payload.get("workflow_version") or 0,
                "workflow_hash": WORKFLOW_HASH, "workflow_active_hash": WORKFLOW_HASH, "workflow_compatible_hashes": [WORKFLOW_HASH],
            })
            return
        if path.startswith("/api/intake-batches/") and path.endswith("/seal"):
            print(f"[seal] {path.split('/')[-2][:80]}")
            self._json(200, {"ok": True})
            return
        if path == "/ingest/email":
            try:
                res = ingest_message(payload, self.inbox_root)
            except BadPayload as exc:
                self._json(400, {"error": str(exc)})
                return
            folder = res["folder"]
            if self.on_ingest is not None:
                self.on_ingest(res, payload)
            resp: dict[str, Any] = {"run_id": res["receipt"].get("run_id"), "deduped": res["status"] == "duplicate",
                                    "version": res["version"], "ocr_policy": payload.get("ocr_policy") or "auto",
                                    "message_dir": str(folder)}
            subj = str(payload.get("subject") or "")[:60]
            if self.run_flow and res["status"] != "duplicate":
                try:
                    out = _run_flow(folder)
                    record_run(folder, out.get("run_id"))
                    resp.update(out)
                    print(f"[mail] {folder.name}  {subj!r} v{res['version']} -> {out.get('intent')} -> {out.get('next_flow')}")
                except Exception as exc:  # noqa: BLE001 - the bridge must not get a 500 because of one bad message
                    resp["error"] = f"{type(exc).__name__}: {exc}"
                    print(f"[mail] {folder.name}  {subj!r} HIBA: {resp['error']}")
            else:
                print(f"[mail] {folder.name}  {subj!r}  v{res['version']}{'  (már volt, változatlan)' if resp['deduped'] else ''}")
            self._json(200, resp)
            return
        self._json(404, {"error": "not found", "path": path[:200]})


class _HttpError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def make_server(port: int = 8901, *, run_flow: bool = False, inbox_root: Path = INBOX_ROOT, token: str | None = None,
                on_ingest=None) -> ThreadingHTTPServer:
    """`port=0`: a free port (the actual one is in `server_address`). `on_ingest(res, payload)`: after every stored
    message. 066 Á14 (decision of 2026-09-29): the receiver works only with a key; if neither the caller nor the
    environment provides one, it gets a one-off random key (`serve` prints it for the bridge's `-ApiToken` switch)."""
    key = token or os.environ.get(TOKEN_ENV) or secrets.token_urlsafe(24)
    # `timeout`: the socket timeout of every read on the connection, headers included (StreamRequestHandler); a
    # timed-out request line or header closes the connection (076)
    handler = type("Handler", (_Handler,), {"run_flow": run_flow, "inbox_root": Path(inbox_root), "token": key,
                                            "on_ingest": staticmethod(on_ingest) if on_ingest else None,
                                            "timeout": READ_TIMEOUT_S})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve(port: int = 8901, *, run_flow: bool = False, inbox_root: Path = INBOX_ROOT, token: str | None = None) -> None:
    configured = token or os.environ.get(TOKEN_ENV)
    httpd = make_server(port, run_flow=run_flow, inbox_root=inbox_root, token=token)
    auth = "kulccsal (Authorization: Bearer)" if configured else \
        (f"egyszeri kulccsal: a híd -ApiToken kapcsolójának értéke {httpd.RequestHandlerClass.token} "
         f"(állandó kulcs: a {TOKEN_ENV} környezeti változó)")
    print(f"jav M3 ingest-fogadó: http://127.0.0.1:{port}/ingest/email  ->  {inbox_root}  (run_flow={run_flow}; {auth}; Ctrl+C: leállítás)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nleállítva")
    finally:
        httpd.server_close()
