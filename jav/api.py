"""Local service (040 K2): the shared gateway of the UI and the command line to the framework.

Reachable only from the local machine: it binds to a loopback address and on every request checks the `Host` header
(against DNS rebinding) and the browser's `Origin` header (so that a foreign website cannot trigger an operation). A
writing request must carry a JSON body (against simple form forgery), the body size is limited, and a Pydantic schema
checks the input's structure (unknown field = rejection). The limits are in `configs/service.json`.

The endpoint names follow the calls of V4's `businessWorkflowApi.ts` (`workflow`, `readiness`, `start`, `runs`). The
business rules live in `jav.work` and `jav.corrections`; the service only translates them to HTTP. This module holds
the gateway itself: the request checks, the shared input types and actor rules, the error translation, and
`create_app`. The endpoints live in modules by theme (195, plan G-tidy R4: `jav/api_workpackages.py`, `api_runs.py`,
`api_results.py`, `api_items.py`, `api_workflows.py`, `api_system.py`, `api_settings.py`) and in the logic packs' and
domains' own modules; each has a `routes(app, prefix)`, and `create_app` adds them in a fixed order (`route_modules`).
The status codes:

  404 unknown id · 409 revision conflict / cannot be started / cannot be approved · 413 body too large ·
  415 not JSON · 422 invalid input · 403 foreign origin or folder not allowed

Long processing does not run here: the run goes into the work queue and the separate worker
(`python -m jav.cli worker`) carries it through, so closing the browser or the service does not stop it.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, unquote, urlsplit

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from jav import (app_settings, cfg, corrections, dates, isolated_pdf, local_picker, numbers, policy, package_release, store,
                 version, work, work_views)
from jav.config import OLD_DATA_ROOT, PROJECT_ROOT
from jav.runtime import lock, pdf_status, worker
from jav.user_messages import explained, message_fields

API_VERSION = "1"
UI_DIST = PROJECT_ROOT / "ui" / "dist"  # the UI build (040 K3); if present, the service serves it at the root
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
log = logging.getLogger("jav.api")


def settings() -> dict[str, Any]:
    return cfg.load("service")


class UnknownUser(PermissionError):
    """061: the user list is not empty and the given actor is not on it."""


class ForbiddenPath(PermissionError):
    """The requested folder or file is not under the allowed root folders."""


def paths_restricted() -> bool:
    """061 decision: by default (`configs/service.json`) there is no folder restriction (any existing local folder /
    file may be given); with `restrict_paths: true`, or if the key is missing, only under the allowed roots."""
    return bool(settings().get("restrict_paths", True))


def allowed_roots() -> list[Path]:
    """The allowed roots; an empty list when unrestricted (the UI then lists no locations)."""
    s = settings()
    if not paths_restricted():
        return []
    roots = [PROJECT_ROOT / r for r in s["allowed_roots"]]
    if s.get("allow_legacy_data_root"):
        roots.append(OLD_DATA_ROOT)
    extra = os.environ.get(s.get("extra_roots_env", ""), "")
    roots += [Path(p) for p in extra.split(os.pathsep) if p.strip()]
    return [r.resolve() for r in roots if r.exists()]


def checked_path(raw: str, *, want_dir: bool | None) -> Path:
    """The path, resolved (following links), is an existing folder / file (`want_dir` None: either); when restricted,
    under one of the allowed roots."""
    try:
        p = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise explained(ValueError, "path does not exist: {{name}}", name=Path(raw).name) from exc
    if paths_restricted() and not any(p == r or p.is_relative_to(r) for r in allowed_roots()):
        raise explained(ForbiddenPath, "path is outside the allowed roots (configs/service.json)")
    if want_dir and not p.is_dir():
        raise explained(ValueError, "not a folder: {{name}}", name=p.name)
    if want_dir is False and not p.is_file():
        raise explained(ValueError, "not a file: {{name}}", name=p.name)
    return p


# --- responses and errors ------------------------------------------------------------------------------


class _UiFiles(StaticFiles):
    """The UI files; the browser always re-requests the entry HTML (a new build shows up at once), while the
    hash-named files may be cached."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        if str(full_path).endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


class JavJSONResponse(JSONResponse):
    """The same JSON shape as the command line (`work_views.jsonable`): money as `Decimal` text, not floating point."""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")


def _error(status: int, code: str, message: str, **extra: Any) -> JavJSONResponse:
    return JavJSONResponse({"error": code, "message": message, **extra}, status_code=status)


def _origin(value: str) -> str:
    """Comparable origin: `scheme://host:port` in lower case, with the default port filled in; unparsable = empty."""
    try:
        u = urlsplit(value.strip())
        port = u.port or {"http": 80, "https": 443}.get(u.scheme)
    except ValueError:
        return ""
    return f"{u.scheme}://{u.hostname}:{port}" if u.scheme and u.hostname else ""


# 071 S-fejlécek (070 plan 2.1, audit A07): browser security headers on every response, a second layer behind the
# existing protections. The UI may load only its own files; Vite inlines the small font files into the stylesheet
# (`data:`), the favicon is `data:`, downloads are `blob:`. The browser must not store `/api/` responses (document data,
# page image, source document, download). The source document opens in a new tab, in the browser's built-in PDF viewer:
# there only embedding is forbidden.
UI_CSP = "; ".join((
    "default-src 'self'", "script-src 'self'", "style-src 'self'", "img-src 'self' data: blob:", "font-src 'self' data:",
    "connect-src 'self'", "object-src 'none'", "base-uri 'none'", "form-action 'self'", "frame-ancestors 'none'",
))
API_CSP = "default-src 'none'; frame-ancestors 'none'"
DOCUMENT_CSP = "frame-ancestors 'none'"
_COMMON_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
)
_SET_HERE = {k for k, _ in _COMMON_HEADERS} | {b"content-security-policy"}


class _SecurityHeaders:
    """Pure ASGI middleware, the outermost: the security headers are added to the responses of failed and rejected
    requests too."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_api = scope["path"] == "/api" or scope["path"].startswith("/api/")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                drop = _SET_HERE | ({b"cache-control"} if is_api else set())
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in drop]
                ctype = next((v for k, v in headers if k.lower() == b"content-type"), b"")
                if not is_api:
                    csp = UI_CSP
                elif ctype.startswith(b"application/pdf"):
                    csp = DOCUMENT_CSP
                else:
                    csp = API_CSP
                headers += [*_COMMON_HEADERS, (b"content-security-policy", csp.encode("ascii"))]
                if is_api:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class _Guard:
    """Pure ASGI middleware: Host, Origin, content type and body size, checked before routing."""

    def __init__(self, app, *, allowed_hosts: set[str], max_body: int, dev_origins: set[str] = frozenset()) -> None:
        self.app = app
        self.allowed_hosts = allowed_hosts
        self.dev_origins = {_origin(o) for o in dev_origins}
        self.max_body = max_body

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = urlsplit("//" + headers.get("host", "")).hostname or ""
        if host not in self.allowed_hosts:
            return await _error(403, "forbidden_host", "requests are accepted only for the local host")(scope, receive, send)
        origin = headers.get("origin")
        # 066 Á34: exact match (scheme, host, port): our own address or the configured dev UI; no other local port
        if origin is not None and _origin(origin) not in self.dev_origins | {_origin("http://" + headers.get("host", ""))}:
            return await _error(403, "forbidden_origin", "requests from other sites are refused")(scope, receive, send)
        if scope["method"] in ("POST", "PUT", "PATCH", "DELETE"):
            ctype = headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return await _error(415, "unsupported_media_type", "the request body must be JSON")(scope, receive, send)
            length = headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > self.max_body):
                return await _error(413, "too_large", f"the request body is limited to {self.max_body} bytes")(scope, receive, send)
        # The body is read up front, with a limit (chunked transfer has no Content-Length either), then replayed.
        chunks: list[bytes] = []
        size = 0
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                return
            chunks.append(message.get("body", b""))
            size += len(chunks[-1])
            if size > self.max_body:
                return await _error(413, "too_large", f"the request body is limited to {self.max_body} bytes")(scope, receive, send)
            more = message.get("more_body", False)
        body = b"".join(chunks)
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


# --- input schemas --------------------------------------------------------------------------------------

WpId = Annotated[str, PathParam(pattern=r"^wp-[0-9a-f]{12}$")]
RunId = Annotated[str, PathParam(pattern=r"^run-[0-9a-f]{12}$")]
ItemId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(max_length=2000)]
# 187: a decision's state as its page read it (`jav/decisions.py`); a change on a stale page is a 409
DecisionState = Annotated[int, Field(ge=0)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Revision(_In):
    expected_revision: Annotated[int, Field(ge=0)]


class Empty(_In):
    pass


IsoDay = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


PartyId = Annotated[str, Field(pattern=r"^party-[0-9a-f]{12}$")]  # 133: an own party (`jav/parties.py`)


class NormalizeValue(_In):
    doc_type: Annotated[str, Field(min_length=1, max_length=64)]
    field: Annotated[str, Field(min_length=1, max_length=64)]
    text: Annotated[str, Field(max_length=1000)]


_ACTOR_RE = app_settings.ACTOR_RE  # 066 Á25: the same rule as the user list


def _decode_actor(raw: str) -> str:
    """The actor's name arrives URL-encoded (an HTTP header cannot carry arbitrary accented letters, e.g. "ő"); it is
    checked after decoding."""
    name = unquote(raw).strip()
    if not _ACTOR_RE.match(name):
        raise HTTPException(status_code=422, detail="X-Actor: 1-64 letters, digits, space, dot, @ or hyphen")
    return name


def attachment_header(filename: str) -> str:
    """Download header for any file name (066 Á22): an ASCII fallback (accents stripped, unsafe characters as `_`) and
    the exact name in UTF-8 (RFC 5987). The header is Latin-1, so an accented name used to cause an error (422)."""
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name) or "export"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def human_actor(x_actor: Annotated[str, Header(max_length=256)]) -> str:
    """For a human decision (approval, correction, closing a to-do, starting a run, recipe, changing a package) the
    actor is mandatory: the `X-Actor` header. 061: if the user list is not empty, the name must be on it (it is
    recorded in the list's spelling)."""
    name = app_settings.canonical_user(_decode_actor(x_actor))
    if name is None:
        raise explained(UnknownUser, "the actor is not in the user list (Settings > Users)")
    return name


def actor_unless_first_users(x_actor: Annotated[str | None, Header(max_length=256)] = None) -> str | None:
    """066 Á35: writing the user list requires an actor who is on the list; the first fill-in (empty list) may be done
    without an actor."""
    if not app_settings.users():
        return app_settings.canonical_user(_decode_actor(x_actor)) if x_actor else None
    if x_actor is None:
        raise explained(ValueError, "X-Actor header is required to change the user list")
    return human_actor(x_actor)


# --- application ----------------------------------------------------------------------------------------


def service_modules() -> list[str]:
    """176 (plan 170 L3): the modules of each logic pack's own addresses (`LogicPack.service`), in the order the packs
    are registered; 185 (plan G-full-move T1a): then the modules of each domain's other addresses (its domain module's
    `SERVICE`). Each has a `routes(app, prefix)`; `create_app` adds them in this order, before the unknown address's
    answer. A test checks that every registered logic pack names its own."""
    from jav import logic_packs, registrations
    from jav.domains import DOMAINS

    registrations.load_all()
    own = [pack.service for pack in logic_packs.packs() if pack.service]
    return [*own, *(name for domain in DOMAINS for name in importlib.import_module(domain).SERVICE)]


# 195 (plan G-tidy R4): the shared addresses, split by theme out of `create_app`. Before the logic packs' and domains'
# modules: the work packages, the runs, the results and one item's; after them: the output layer (178), the workflows
# (146), the to-dos and the system, and the settings (057).
SHARED_BEFORE = ("jav.api_workpackages", "jav.api_runs", "jav.api_results", "jav.api_items")
SHARED_AFTER = ("jav.api_outputs", "jav.api_workflows", "jav.api_system", "jav.api_settings")


def route_modules() -> list[str]:
    """195: every module whose `routes(app, prefix)` `create_app` adds, in this order. The order is the routing order
    (the first matching address answers) and the order of the endpoint list (`/api/openapi.json`); it is the order the
    addresses had when they were written inside `create_app`. The unknown address's answer comes after all of them."""
    return [*SHARED_BEFORE, *service_modules(), *SHARED_AFTER]


def _add_error_handlers(app: FastAPI) -> None:
    """The named errors of the business modules translated into answers (the status codes in the module's docstring)."""

    # 063: an error translated into a 404 / 422 response is also logged with its traceback — otherwise an internal error
    # (e.g. a missing key in a dict) would look like an "unknown id", leaving no trace
    @app.exception_handler(KeyError)
    async def not_found(request: Request, exc: KeyError):
        log.warning("404 %s %s: %r", request.method, request.url.path, exc, exc_info=exc)
        return _error(404, "not_found", f"unknown id: {exc.args[0] if exc.args else ''}")

    @app.exception_handler(work.RevisionConflict)
    async def conflict(_request: Request, exc: work.RevisionConflict):
        return _error(409, "revision_conflict", str(exc), **message_fields(exc))

    @app.exception_handler(work.NotReady)
    async def not_ready(_request: Request, exc: work.NotReady):
        return _error(409, "not_ready", str(exc), blockers=exc.blockers, **message_fields(exc))

    @app.exception_handler(package_release.ReleaseError)
    async def release_refused(_request: Request, exc: package_release.ReleaseError):
        return _error(422, "release_refused", str(exc), **message_fields(exc))  # 171: named in the display language

    @app.exception_handler(UnknownUser)
    async def unknown_user(_request: Request, exc: UnknownUser):
        return _error(403, "unknown_user", str(exc))

    @app.exception_handler(ForbiddenPath)
    async def forbidden_path(_request: Request, exc: ForbiddenPath):
        return _error(403, "forbidden_path", str(exc))

    @app.exception_handler(app_settings.FolderOverlap)
    async def folder_overlap(_request: Request, exc: app_settings.FolderOverlap):
        return _error(422, "folder_overlap", str(exc), **message_fields(exc))  # 078: the UI names it in the display language

    @app.exception_handler(app_settings.NoOutputFolder)
    async def no_output_folder(_request: Request, exc: app_settings.NoOutputFolder):
        return _error(422, "no_output_folder", str(exc), **message_fields(exc))

    @app.exception_handler(numbers.AmbiguousNumber)
    async def ambiguous_number(_request: Request, exc: numbers.AmbiguousNumber):
        # 081: the UI asks for the Hungarian form ("28,50"); 153: and names the field
        return _error(422, "ambiguous_number", str(exc), field=getattr(exc, "field", None), **message_fields(exc))

    @app.exception_handler(dates.AmbiguousDate)
    async def ambiguous_date(_request: Request, exc: dates.AmbiguousDate):
        # 084: the UI asks for the year first ("2022-12-04"); 153: and names the field
        return _error(422, "ambiguous_date", str(exc), field=getattr(exc, "field", None), **message_fields(exc))

    @app.exception_handler(corrections.InvalidValue)
    async def invalid_value(_request: Request, exc: corrections.InvalidValue):
        return _error(422, "invalid_value", str(exc), field=exc.field, kind=exc.kind, **message_fields(exc))  # 153: the UI names the field

    @app.exception_handler(local_picker.PickerBusy)
    async def picker_busy(_request: Request, exc: local_picker.PickerBusy):
        return _error(409, "picker_busy", str(exc), **message_fields(exc))

    @app.exception_handler(local_picker.PickerUnavailable)
    async def picker_unavailable(_request: Request, exc: local_picker.PickerUnavailable):
        return _error(503, "picker_unavailable", str(exc), **message_fields(exc))

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        log.warning("422 %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        extra = {"reason": exc.reason} if isinstance(exc, isolated_pdf.PdfReaderLimit) else {}
        return _error(422, "invalid", str(exc), **extra, **message_fields(exc))

    @app.exception_handler(OSError)
    async def unreadable(request: Request, exc: OSError):
        # 063: e.g. a locked file in a folder, or one that vanished meanwhile — a clear response instead of 500, the
        # traceback goes to the log
        log.warning("OSError %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        name = Path(exc.filename).name if getattr(exc, "filename", None) else ""
        return _error(422, "unreadable", f"A fájl nem olvasható{': ' + name if name else ''} ({type(exc).__name__}).")


def create_app(*, store_path: Path | None = None) -> FastAPI:
    """`store_path`: a store for this app instance (for tests); without it, the default `store/jav.sqlite`."""
    from jav import registrations

    registrations.load_all()  # 173 (plan 170 E2): the package rules, delete guards and party references
    s = settings()
    # 071 decision (2026-09-30): the clickable endpoint list (/api/docs) would load program code from an external host
    # onto the local address, so it is switched off; the machine-readable endpoint list (/api/openapi.json) stays
    app = FastAPI(title="JAV helyi szolgáltatás", version=API_VERSION, default_response_class=JavJSONResponse,
                  docs_url=None, openapi_url="/api/openapi.json", redoc_url=None)

    if store_path is not None:
        @app.middleware("http")
        async def scoped_store(request: Request, call_next):
            with store.use_store(store_path):
                return await call_next(request)

    _add_error_handlers(app)

    r = "/api"

    @app.get(r + "/settings")
    def ui_settings() -> dict[str, Any]:
        """The UI's display settings (045): confidence bands."""
        bands = dict(settings().get("confidence_bands", {"confident": 0.9, "check": 0.5}))
        # 091: a GPT field's confidence (path without JEV) has its own display band
        return {"confidence_bands": {**bands, "gpt": dict(policy.GPT_FIELD_CONFIDENCE["bands"])}}

    @app.post(r + "/normalize")
    def normalize(body: NormalizeValue) -> dict[str, Any]:
        """Selected text → a value according to the field's kind (045: selection on the image). Code decides the format,
        not the browser; for unparsable text, `ok=false` plus the reason, and the UI then does not offer saving."""
        from jav import typepack
        from jav.models import normalize_value

        pack = typepack.get(body.doc_type)
        if body.field not in pack.fields:
            raise explained(ValueError, "not a field of {{key}}: {{field}}", key=pack.key, field=body.field)
        reasons: list[str] = []
        text = body.text.strip()
        if pack.kind(body.field) == "money":  # a currency sign is natural in a selection ("1 071 880 Ft", "650 000,-")
            text = re.sub(r"(?i)\s*(?:ft\.?|huf|eur|usd|€|\$|,-)\s*$", "", re.sub(r"(?i)^\s*(?:huf|eur|usd|€|\$)\s*", "", text))
        value = normalize_value(pack.kind(body.field), text, body.field, reasons, origin="printed")
        return work_views.jsonable({"ok": value is not None and not reasons, "value": value, "reasons": reasons,
                                    "kind": pack.kind(body.field)})

    # 071 S-verzió: the version and the commit are fixed at start-up — this is the code actually running in the process
    running = {"version": version.VERSION, **version.commit_info(),
               "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    @app.get(r + "/health")
    def health() -> dict[str, Any]:
        # 091: the UI build is read on every request (a new build is served at once, even without a restart)
        return {"ok": True, "api_version": API_VERSION, "service_config": cfg.version("service"), **running,
                "ui_build": version.ui_build(UI_DIST),
                "pdf_protection": {
                    "service": isolated_pdf.protection_status(),
                    "worker": pdf_status.worker_status(store.current_path(), running=lock.is_held(worker.lock_path())),
                }}

    for name in route_modules():  # 195 (plan G-tidy R4): every other address, by theme
        importlib.import_module(name).routes(app, r)

    @app.api_route(r + "/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unknown_api(rest: str):
        return _error(404, "not_found", "unknown endpoint")

    if UI_DIST.is_dir():  # the UI: on the same address, so there is no separate server and no cross-origin call
        app.mount("/", _UiFiles(directory=UI_DIST, html=True), name="ui")

    # added last = outermost layer: the request is checked before routing and before the store
    app.add_middleware(_Guard, allowed_hosts=set(s["allowed_hosts"]) & LOOPBACK, max_body=int(s["max_body_bytes"]),
                       dev_origins=set(s.get("dev_origins", [])))
    app.add_middleware(_SecurityHeaders)  # 071: even on the _Guard's rejection responses
    return app


def serve(*, host: str | None = None, port: int | None = None) -> None:
    """Start the service (uvicorn). It binds only to a loopback address and refuses any other address."""
    import uvicorn

    s = settings()
    host = host or s["host"]
    if host not in LOOPBACK:
        raise ValueError(f"the local service binds only to a loopback address, not {host!r}")
    from jav import datasets
    from jav.runtime import applog, preload

    preload.preload()  # 091: all the code now, so later changes on disk cannot mix into the running service
    datasets.warm_up()  # 158: the package list is built in the background, so its first request does not wait 5-8 s
    # 063: the service log also goes to a persistent rotating file (runs/logs/api.log), with tracebacks for 500 errors
    uvicorn.run(create_app(), host=host, port=port or int(s["port"]), log_level="info", access_log=False,
                log_config=applog.uvicorn_config("api"))
