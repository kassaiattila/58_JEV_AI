"""Local service (040 K2): the shared gateway of the UI and the command line to the framework.

Reachable only from the local machine: it binds to a loopback address and on every request checks the `Host` header
(against DNS rebinding) and the browser's `Origin` header (so that a foreign website cannot trigger an operation). A
writing request must carry a JSON body (against simple form forgery), the body size is limited, and a Pydantic schema
checks the input's structure (unknown field = rejection). The limits are in `configs/service.json`.

The endpoint names follow the calls of V4's `businessWorkflowApi.ts` (`workflow`, `readiness`, `start`, `runs`). The
business rules live in `jav.work` and `jav.corrections`; the service only translates them to HTTP. This module holds
the gateway itself: the request checks, the error translation, and `create_app`. The endpoints live in modules by theme
(195, plan G-tidy R4: `jav/api_workpackages.py`, `api_runs.py`, `api_results.py`, `api_items.py`, `api_workflows.py`,
`api_system.py`, `api_settings.py`) and in the logic packs' and domains' own modules; each has a `routes(app, prefix)`,
and `create_app` adds them in a fixed order (`route_modules`). 204 (R1g): the shared input types, the actor rules, the
path check and the error answer's shape are in `jav/service_shared.py`, which every module of addresses imports instead
of this one. The status codes:

  404 unknown id · 409 revision conflict / cannot be started / cannot be approved · 413 body too large ·
  415 not JSON · 422 invalid input · 403 foreign origin or folder not allowed

Long processing does not run here: the run goes into the work queue and the separate worker
(`python -m jav.cli worker`) carries it through, so closing the browser or the service does not stop it.
"""

from __future__ import annotations

import importlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.routing import BaseRoute

from jav import (app_settings, cfg, corrections, dates, isolated_pdf, local_picker, numbers, policy, package_release, store,
                 version, work, work_views)
from jav.config import PROJECT_ROOT
from jav.runtime import lock, pdf_status, worker
from jav.service_shared import ForbiddenPath, In, JavJSONResponse, UnknownUser, error, settings
from jav.user_messages import explained, message_fields

API_VERSION = "1"
UI_DIST = PROJECT_ROOT / "ui" / "dist"  # the UI build (040 K3); if present, the service serves it at the root
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
log = logging.getLogger("jav.api")


# --- responses and errors ------------------------------------------------------------------------------


class _UiFiles(StaticFiles):
    """The UI files; the browser always re-requests the entry HTML (a new build shows up at once), while the
    hash-named files may be cached."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        if str(full_path).endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


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
            return await error(403, "forbidden_host", "requests are accepted only for the local host")(scope, receive, send)
        origin = headers.get("origin")
        # 066 Á34: exact match (scheme, host, port): our own address or the configured dev UI; no other local port
        if origin is not None and _origin(origin) not in self.dev_origins | {_origin("http://" + headers.get("host", ""))}:
            return await error(403, "forbidden_origin", "requests from other sites are refused")(scope, receive, send)
        if scope["method"] in ("POST", "PUT", "PATCH", "DELETE"):
            ctype = headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return await error(415, "unsupported_media_type", "the request body must be JSON")(scope, receive, send)
            length = headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > self.max_body):
                return await error(413, "too_large", f"the request body is limited to {self.max_body} bytes")(scope, receive, send)
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
                return await error(413, "too_large", f"the request body is limited to {self.max_body} bytes")(scope, receive, send)
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


class NormalizeValue(In):
    doc_type: Annotated[str, Field(min_length=1, max_length=64)]
    field: Annotated[str, Field(min_length=1, max_length=64)]
    text: Annotated[str, Field(max_length=1000)]


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


# 203: the theme modules' finished routes and the error answers they add, per module list and prefix. FastAPI analyses
# every endpoint's signature when it is added (about 4 ms each, some 170 of them); the service builds its app once, but
# the test suite built one per test, about 450 times. An endpoint never refers to the app it was added to (a test
# checks), so the same route objects serve every app, and each app keeps its own store, settings and start-up state.
_THEME_ROUTES: dict[tuple[tuple[str, ...], str], tuple[list[BaseRoute], dict[Any, Any]]] = {}


def _new_app() -> FastAPI:
    # 071 decision (2026-09-30): the clickable endpoint list (/api/docs) would load program code from an external host
    # onto the local address, so it is switched off; the machine-readable endpoint list (/api/openapi.json) stays
    return FastAPI(title="JAV helyi szolgáltatás", version=API_VERSION, default_response_class=JavJSONResponse,
                   docs_url=None, openapi_url="/api/openapi.json", redoc_url=None)


def _add_theme_routes(app: FastAPI, prefix: str) -> None:
    """Adds every `route_modules` module's routes and error answers to `app`, built on a throwaway app of the same
    settings the first time. The routes keep that app as their dependency-override source, so `app.dependency_overrides`
    does not reach them (nothing uses it)."""
    key = (tuple(route_modules()), prefix)
    if key not in _THEME_ROUTES:
        scratch = _new_app()
        start, handlers = len(scratch.router.routes), dict(scratch.exception_handlers)
        for name in key[0]:
            importlib.import_module(name).routes(scratch, prefix)
        added = {exc: h for exc, h in scratch.exception_handlers.items() if handlers.get(exc) is not h}
        _THEME_ROUTES[key] = (scratch.router.routes[start:], added)
    routes, added = _THEME_ROUTES[key]
    app.router.routes.extend(routes)
    for exc, handler in added.items():
        app.add_exception_handler(exc, handler)


def _add_error_handlers(app: FastAPI) -> None:
    """The named errors of the business modules translated into answers (the status codes in the module's docstring)."""

    # 063: an error translated into a 404 / 422 response is also logged with its traceback — otherwise an internal error
    # (e.g. a missing key in a dict) would look like an "unknown id", leaving no trace
    @app.exception_handler(KeyError)
    async def not_found(request: Request, exc: KeyError):
        log.warning("404 %s %s: %r", request.method, request.url.path, exc, exc_info=exc)
        return error(404, "not_found", f"unknown id: {exc.args[0] if exc.args else ''}")

    @app.exception_handler(work.RevisionConflict)
    async def conflict(_request: Request, exc: work.RevisionConflict):
        return error(409, "revision_conflict", str(exc), **message_fields(exc))

    @app.exception_handler(work.NotReady)
    async def not_ready(_request: Request, exc: work.NotReady):
        return error(409, "not_ready", str(exc), blockers=exc.blockers, **message_fields(exc))

    @app.exception_handler(package_release.ReleaseError)
    async def release_refused(_request: Request, exc: package_release.ReleaseError):
        return error(422, "release_refused", str(exc), **message_fields(exc))  # 171: named in the display language

    @app.exception_handler(UnknownUser)
    async def unknown_user(_request: Request, exc: UnknownUser):
        return error(403, "unknown_user", str(exc))

    @app.exception_handler(ForbiddenPath)
    async def forbidden_path(_request: Request, exc: ForbiddenPath):
        return error(403, "forbidden_path", str(exc))

    @app.exception_handler(app_settings.FolderOverlap)
    async def folder_overlap(_request: Request, exc: app_settings.FolderOverlap):
        return error(422, "folder_overlap", str(exc), **message_fields(exc))  # 078: the UI names it in the display language

    @app.exception_handler(app_settings.NoOutputFolder)
    async def no_output_folder(_request: Request, exc: app_settings.NoOutputFolder):
        return error(422, "no_output_folder", str(exc), **message_fields(exc))

    @app.exception_handler(numbers.AmbiguousNumber)
    async def ambiguous_number(_request: Request, exc: numbers.AmbiguousNumber):
        # 081: the UI asks for the Hungarian form ("28,50"); 153: and names the field
        return error(422, "ambiguous_number", str(exc), field=getattr(exc, "field", None), **message_fields(exc))

    @app.exception_handler(dates.AmbiguousDate)
    async def ambiguous_date(_request: Request, exc: dates.AmbiguousDate):
        # 084: the UI asks for the year first ("2022-12-04"); 153: and names the field
        return error(422, "ambiguous_date", str(exc), field=getattr(exc, "field", None), **message_fields(exc))

    @app.exception_handler(corrections.InvalidValue)
    async def invalid_value(_request: Request, exc: corrections.InvalidValue):
        return error(422, "invalid_value", str(exc), field=exc.field, kind=exc.kind, **message_fields(exc))  # 153: the UI names the field

    @app.exception_handler(local_picker.PickerBusy)
    async def picker_busy(_request: Request, exc: local_picker.PickerBusy):
        return error(409, "picker_busy", str(exc), **message_fields(exc))

    @app.exception_handler(local_picker.PickerUnavailable)
    async def picker_unavailable(_request: Request, exc: local_picker.PickerUnavailable):
        return error(503, "picker_unavailable", str(exc), **message_fields(exc))

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        log.warning("422 %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        extra = {"reason": exc.reason} if isinstance(exc, isolated_pdf.PdfReaderLimit) else {}
        return error(422, "invalid", str(exc), **extra, **message_fields(exc))

    @app.exception_handler(OSError)
    async def unreadable(request: Request, exc: OSError):
        # 063: e.g. a locked file in a folder, or one that vanished meanwhile — a clear response instead of 500, the
        # traceback goes to the log
        log.warning("OSError %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        name = Path(exc.filename).name if getattr(exc, "filename", None) else ""
        return error(422, "unreadable", f"A fájl nem olvasható{': ' + name if name else ''} ({type(exc).__name__}).")


def create_app(*, store_path: Path | None = None) -> FastAPI:
    """`store_path`: a store for this app instance (for tests); without it, the default `store/jav.sqlite`."""
    from jav import registrations

    registrations.load_all()  # 173 (plan 170 E2): the package rules, delete guards and party references
    s = settings()
    app = _new_app()

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

    _add_theme_routes(app, r)  # 195 (plan G-tidy R4): every other address, by theme; 203: built once per process

    @app.api_route(r + "/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unknown_api(rest: str):
        return error(404, "not_found", "unknown endpoint")

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
