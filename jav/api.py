"""Local service (040 K2): the shared gateway of the UI and the command line to the framework.

Reachable only from the local machine: it binds to a loopback address and on every request checks the `Host` header
(against DNS rebinding) and the browser's `Origin` header (so that a foreign website cannot trigger an operation). A
writing request must carry a JSON body (against simple form forgery), the body size is limited, and a Pydantic schema
checks the input's structure (unknown field = rejection). The limits are in `configs/service.json`.

The endpoint names follow the calls of V4's `businessWorkflowApi.ts` (`workflow`, `readiness`, `start`, `runs`). The
business rules live in `jav.work` and `jav.corrections`; this module only translates them to HTTP:

  404 unknown id · 409 revision conflict / cannot be started / cannot be approved · 413 body too large ·
  415 not JSON · 422 invalid input · 403 foreign origin or folder not allowed

Long processing does not run here: the run goes into the work queue and the separate worker
(`python -m jav.cli worker`) carries it through, so closing the browser or the service does not stop it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import unicodedata
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote, unquote, urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from jav import (app_settings, backup, cfg, corrections, dates, deps_audit, local_picker, mailbox, numbers, store, version,
                 work, work_views)
from jav.config import OLD_DATA_ROOT, PROJECT_ROOT
from jav.runtime import calls, worker
from jav.tablequery import Query as TableQuery

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


def checked_path(raw: str, *, want_dir: bool) -> Path:
    """The path, resolved (following links), is an existing folder / file; when restricted, under one of the allowed
    roots."""
    try:
        p = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"path does not exist: {Path(raw).name}") from exc
    if paths_restricted() and not any(p == r or p.is_relative_to(r) for r in allowed_roots()):
        raise ForbiddenPath("path is outside the allowed roots (configs/service.json)")
    if want_dir and not p.is_dir():
        raise ValueError(f"not a folder: {p.name}")
    if not want_dir and not p.is_file():
        raise ValueError(f"not a file: {p.name}")
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
DatasetName = Annotated[str, PathParam(pattern=r"^[a-z_]{1,40}$")]
Text = Annotated[str, Field(max_length=2000)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateWorkpackage(_In):
    """Exactly one of: `folder` (the folder's PDFs; with `recursive`, 081, those of its subfolders too) or `paths`
    (given files, possibly from several folders; then `name` is required)."""
    folder: Annotated[str, Field(min_length=1, max_length=1024)] | None = None
    paths: Annotated[list[Annotated[str, Field(min_length=1, max_length=1024)]], Field(min_length=1, max_length=500)] | None = None
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    recursive: bool = False


class PickRequest(_In):
    """081: the picker's window title (in the display language) and where it opens (a folder, or a file's folder)."""
    title: Annotated[str, Field(max_length=200)] | None = None
    initial: Annotated[str, Field(max_length=1024)] | None = None


class AddItems(_In):
    paths: Annotated[list[Annotated[str, Field(min_length=1, max_length=1024)]], Field(min_length=1, max_length=500)]
    expected_revision: Annotated[int, Field(ge=0)]


class Revision(_In):
    expected_revision: Annotated[int, Field(ge=0)]


class SaveWorkflow(_In):
    recipe_id: Annotated[str, Field(min_length=1, max_length=100)]
    params: dict[Annotated[str, Field(max_length=64)], Annotated[str, Field(max_length=200)]] = Field(default_factory=dict, max_length=20)
    expected_revision: Annotated[int, Field(ge=0)]
    note: Text | None = None


class StartRun(_In):
    mode: Literal["shadow", "apply"] = "shadow"
    expected_revision: Annotated[int, Field(ge=0)]
    input_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{16}$")]
    rerun_of: Annotated[str, Field(pattern=r"^run-[0-9a-f]{12}$")] | None = None  # 057: rerun


class Empty(_In):
    pass


class Approve(_In):
    """085 (re-audit A01): `review_version` is the run view's `review_version` the approver saw; if a correction changed
    the result since, 409. Without it (the command line) the current result is approved."""
    review_version: str | None = Field(default=None, max_length=64)


class ResolveCall(_In):
    """076: settling a paid call with an uncertain outcome by hand, as `calls-resolve` does."""

    cost_usd: Decimal | None = Field(default=None, ge=0, le=Decimal("100"))  # None: unknown, the maximum stays committed
    note: str = Field(min_length=3, max_length=500)


class TaskDecision(_In):
    decision: Literal["accepted", "rejected"]
    note: Text | None = None


class TaskDone(_In):
    done: bool


class RenameWorkpackage(_In):
    name: Annotated[str, Field(min_length=1, max_length=200)]


class SetOwner(_In):
    """061: the package's owner (a name from the user list); None: no owner."""
    owner: Annotated[str, Field(min_length=1, max_length=64)] | None


class SaveUsers(_In):
    users: Annotated[list[Annotated[str, Field(max_length=64)]], Field(max_length=200)]


class SaveFolders(_In):
    folders: Annotated[list[app_settings.WatchedFolder], Field(max_length=50)]


class SaveOutputFolder(_In):
    path: str | None = Field(default=None, max_length=1024)  # empty: no output folder


_ScopeMap = Annotated[dict[Annotated[str, Field(max_length=64)], Annotated[str, Field(max_length=200)]], Field(max_length=5)]


class DatasetQuery(_In):
    """056 U1: uniform list request (scope + search, filters, sorting, paging)."""
    scope: _ScopeMap = Field(default_factory=dict)
    query: TableQuery = Field(default_factory=TableQuery)


class DatasetExport(DatasetQuery):
    format: Literal["csv", "xlsx", "json"] = "xlsx"
    rows: Literal["all", "filtered", "selected"] = "filtered"
    columns: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=500)] | None = None


_Cell = Annotated[str, Field(max_length=500)] | int | None
_Row = Annotated[dict[Annotated[str, Field(max_length=64)], _Cell], Field(max_length=50)]


class SaveCorrection(_In):
    # 048: an itemised list = a list of rows (item field -> value) or a list of plain values; the kind-based check is in
    # `jav.corrections` (that is where the rows' content is compared with the pack's item description)
    fields: dict[Annotated[str, Field(max_length=64)], _Cell | Annotated[list[_Row | _Cell], Field(max_length=2000)]] = Field(max_length=100)
    expected_revision: Annotated[int, Field(ge=0)]
    note: Text | None = None
    # 045: per field, the ids of the words selected on the image (from the item's word layer)
    sources: dict[Annotated[str, Field(max_length=64)], Annotated[list[Annotated[int, Field(ge=0)]], Field(min_length=1, max_length=200)]] | None = Field(
        default=None, max_length=100)
    # 083: the simple fields a person checked (the tick next to the field): recorded as confirmed, their to-dos resolved
    confirm: list[Annotated[str, Field(max_length=64)]] | None = Field(default=None, max_length=100)


ScheduleId = Annotated[str, PathParam(pattern=r"^mbx-[0-9a-f]{10}$")]
PullId = Annotated[str, PathParam(pattern=r"^pull-[0-9a-f]{10}$")]


class CreateSchedule(_In):
    request: mailbox.MailboxRequest
    interval_min: Annotated[int, Field(ge=15, le=7 * 24 * 60)] = mailbox.DEFAULT_INTERVAL_MIN


class UpdateSchedule(_In):
    enabled: bool | None = None
    interval_min: Annotated[int, Field(ge=15, le=7 * 24 * 60)] | None = None


class NormalizeValue(_In):
    doc_type: Annotated[str, Field(min_length=1, max_length=64)]
    field: Annotated[str, Field(min_length=1, max_length=64)]
    text: Annotated[str, Field(max_length=1000)]


class ResolveReason(_In):
    resolution: dict[Annotated[str, Field(max_length=64)], Any] | None = Field(default=None, max_length=50)
    note: Text | None = None


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
        raise UnknownUser("the actor is not in the user list (Settings > Users)")
    return name


def actor_unless_first_users(x_actor: Annotated[str | None, Header(max_length=256)] = None) -> str | None:
    """066 Á35: writing the user list requires an actor who is on the list; the first fill-in (empty list) may be done
    without an actor."""
    if not app_settings.users():
        return app_settings.canonical_user(_decode_actor(x_actor)) if x_actor else None
    if x_actor is None:
        raise ValueError("X-Actor header is required to change the user list")
    return human_actor(x_actor)


# --- application ----------------------------------------------------------------------------------------


def _max_source_bytes() -> int:
    """075: a source larger than the input limit is never read into memory (it could not have been added anyway)."""
    return work.max_source_bytes()


def create_app(*, store_path: Path | None = None) -> FastAPI:
    """`store_path`: a store for this app instance (for tests); without it, the default `store/jav.sqlite`."""
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

    # 063: an error translated into a 404 / 422 response is also logged with its traceback — otherwise an internal error
    # (e.g. a missing key in a dict) would look like an "unknown id", leaving no trace
    @app.exception_handler(KeyError)
    async def not_found(request: Request, exc: KeyError):
        log.warning("404 %s %s: %r", request.method, request.url.path, exc, exc_info=exc)
        return _error(404, "not_found", f"unknown id: {exc.args[0] if exc.args else ''}")

    @app.exception_handler(work.RevisionConflict)
    async def conflict(_request: Request, exc: work.RevisionConflict):
        return _error(409, "revision_conflict", str(exc))

    @app.exception_handler(work.NotReady)
    async def not_ready(_request: Request, exc: work.NotReady):
        return _error(409, "not_ready", str(exc), blockers=exc.blockers)

    @app.exception_handler(UnknownUser)
    async def unknown_user(_request: Request, exc: UnknownUser):
        return _error(403, "unknown_user", str(exc))

    @app.exception_handler(ForbiddenPath)
    async def forbidden_path(_request: Request, exc: ForbiddenPath):
        return _error(403, "forbidden_path", str(exc))

    @app.exception_handler(app_settings.FolderOverlap)
    async def folder_overlap(_request: Request, exc: app_settings.FolderOverlap):
        return _error(422, "folder_overlap", str(exc))  # 078: the UI names it in the display language

    @app.exception_handler(app_settings.NoOutputFolder)
    async def no_output_folder(_request: Request, exc: app_settings.NoOutputFolder):
        return _error(422, "no_output_folder", str(exc))

    @app.exception_handler(numbers.AmbiguousNumber)
    async def ambiguous_number(_request: Request, exc: numbers.AmbiguousNumber):
        return _error(422, "ambiguous_number", str(exc))  # 081: the UI asks for the Hungarian form ("28,50")

    @app.exception_handler(dates.AmbiguousDate)
    async def ambiguous_date(_request: Request, exc: dates.AmbiguousDate):
        return _error(422, "ambiguous_date", str(exc))  # 084: the UI asks for the year first ("2022-12-04")

    @app.exception_handler(local_picker.PickerBusy)
    async def picker_busy(_request: Request, exc: local_picker.PickerBusy):
        return _error(409, "picker_busy", str(exc))

    @app.exception_handler(local_picker.PickerUnavailable)
    async def picker_unavailable(_request: Request, exc: local_picker.PickerUnavailable):
        return _error(503, "picker_unavailable", str(exc))

    @app.exception_handler(mailbox.BridgeError)
    async def bridge_failed(_request: Request, exc: mailbox.BridgeError):
        return _error(503, "mailbox_unavailable", str(exc))

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        log.warning("422 %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        return _error(422, "invalid", str(exc))

    @app.exception_handler(OSError)
    async def unreadable(request: Request, exc: OSError):
        # 063: e.g. a locked file in a folder, or one that vanished meanwhile — a clear response instead of 500, the
        # traceback goes to the log
        log.warning("OSError %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        name = Path(exc.filename).name if getattr(exc, "filename", None) else ""
        return _error(422, "unreadable", f"A fájl nem olvasható{': ' + name if name else ''} ({type(exc).__name__}).")

    r = "/api"

    @app.get(r + "/settings")
    def ui_settings() -> dict[str, Any]:
        """The UI's display settings (045): confidence bands."""
        return {"confidence_bands": settings().get("confidence_bands", {"confident": 0.9, "check": 0.5})}

    @app.post(r + "/normalize")
    def normalize(body: NormalizeValue) -> dict[str, Any]:
        """Selected text → a value according to the field's kind (045: selection on the image). Code decides the format,
        not the browser; for unparsable text, `ok=false` plus the reason, and the UI then does not offer saving."""
        from jav import typepack
        from jav.models import normalize_value

        pack = typepack.get(body.doc_type)
        if body.field not in pack.fields:
            raise ValueError(f"not a field of {pack.key}: {body.field}")
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
                "ui_build": version.ui_build(UI_DIST)}

    # --- recipes and work packages ---

    @app.get(r + "/recipes")
    def recipes() -> dict[str, Any]:
        # 063: recipe explanations; 080: the titles of every recipe (an old run or a package not yet migrated shows its
        # recipe's title, although only the active processing is offered)
        return {"recipes": work_views.recipe_catalog(), "help": work_views.recipe_help(),
                "titles": {r["id"]: r["title"] for r in work.recipes()}}

    @app.get(r + "/workpackages")
    def workpackages(include_archived: bool = False) -> dict[str, Any]:
        return {"workpackages": work_views.workpackage_list(include_archived=include_archived)}

    @app.post(r + "/workpackages", status_code=201)
    def create_workpackage(body: CreateWorkpackage, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        if (body.folder is None) == (body.paths is None):
            raise ValueError("give exactly one of folder or paths")
        if body.folder is not None:  # 065: the creator is the owner
            # 081: with the subfolders, the output folder of the named copies is left out
            out = app_settings.output_folder() if body.recursive else None
            wp = work.create_from_folder(checked_path(body.folder, want_dir=True), name=body.name, owner=who,
                                         recursive=body.recursive, exclude=[Path(out)] if out else [])
        else:
            if not body.name:
                raise ValueError("name is required when creating from files")
            wp = work.create_from_files([checked_path(p, want_dir=False) for p in body.paths], name=body.name, owner=who)
        return work_views.workpackage_view(wp["id"])

    # 081: the system's own folder and file pickers. The service and the browser run on the same machine, so the dialog
    # opens on the user's desktop; the chosen path is checked like a typed one.

    @app.post(r + "/local/pick-folder")
    def pick_folder(body: PickRequest) -> dict[str, Any]:
        path = local_picker.pick_folder(title=body.title or "Choose a folder", initial=body.initial)
        if path:
            checked_path(path, want_dir=True)
        return {"path": path}

    @app.post(r + "/local/pick-files")
    def pick_files(body: PickRequest) -> dict[str, Any]:
        paths = local_picker.pick_files(title=body.title or "Choose files", initial=body.initial)
        for p in paths:
            checked_path(p, want_dir=False)
        return {"paths": paths}

    @app.get(r + "/workpackages/{wp_id}")
    def workpackage(wp_id: WpId) -> dict[str, Any]:
        return work_views.workpackage_view(wp_id)

    # 058: hiding (runs and results are kept), restoring, renaming; deletion only for a package without runs

    @app.post(r + "/workpackages/{wp_id}/archive")
    def archive_workpackage(wp_id: WpId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.archive_workpackage(wp_id, actor=who)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/restore")
    def restore_workpackage(wp_id: WpId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.restore_workpackage(wp_id, actor=who)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/rename")
    def rename_workpackage(wp_id: WpId, body: RenameWorkpackage, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.rename_workpackage(wp_id, body.name, actor=who)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/owner")
    def set_owner(wp_id: WpId, body: SetOwner, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """061: the package's owner; only a name from the user list (any name when the list is empty)."""
        owner = None
        if body.owner is not None:
            owner = app_settings.canonical_user(body.owner)
            if owner is None:
                raise ValueError("unknown user: the owner must be in the user list")
        work.set_owner(wp_id, owner, actor=who)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/delete")  # a POST with a JSON body, like the other deletions
    def delete_workpackage(wp_id: WpId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.delete_workpackage(wp_id, actor=who)
        return {"deleted": wp_id}

    @app.post(r + "/workpackages/{wp_id}/items")
    def add_items(wp_id: WpId, body: AddItems, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        paths = [checked_path(p, want_dir=False) for p in body.paths]
        work.add_documents(wp_id, paths, expected_revision=body.expected_revision)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/attachments")
    def add_attachments(wp_id: WpId, body: Revision, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """058 K5.2: the emails' PDF attachments go into the package as documents, pointing back to the email."""
        mailbox.add_attachments(wp_id, expected_revision=body.expected_revision)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/items/{item_id}/remove")
    def remove_item(wp_id: WpId, item_id: ItemId, body: Revision, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.remove_item(wp_id, item_id, expected_revision=body.expected_revision)
        return work_views.workpackage_view(wp_id)

    def _item_source(wp_id: str, item_id: str) -> tuple[Path, bytes]:
        """The source file of a live item in the package and its bytes, only if their content is the same as when it
        was added — no other file can be read out through this route. 075 (repeated security audit, S03): the file is
        read once and hashed in full on every request, and exactly the verified bytes are served or rendered, so a file
        changed in place (even with the same size and modification time) or swapped after the check cannot be served.
        Before 075 a fingerprint memoised by size + modification time was trusted here (058). An item with a source
        instance is served from the instance, so a later change to the original does not hide the document; the returned
        path is the original one (its suffix decides the media type)."""
        item = next((i for i in work.get(wp_id)["items"] if i["item_id"] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        return Path(item["source_path"]), work.read_verified(work.source_file(item), item["sha256"], max_bytes=_max_source_bytes())

    @app.get(r + "/workpackages/{wp_id}/items/{item_id}/pages/{page}.png")
    def item_page(wp_id: WpId, item_id: ItemId, page: Annotated[int, PathParam(ge=1, le=500)],
                  dpi: Annotated[int, Query(ge=72, le=200)] = 144) -> Response:
        """The image of one page (045 K3b) — the boxes are drawn on it. 071: document content, so the browser does not
        store it (`no-store`, added by the security-header layer; previously it stayed in the disk cache for a day)."""
        from jav import page_image

        path, data = _item_source(wp_id, item_id)
        png = page_image.render(path, page, dpi=dpi, data=data)
        return Response(png, media_type="image/png")

    @app.get(r + "/workpackages/{wp_id}/items/{item_id}/source")
    def item_source(wp_id: WpId, item_id: ItemId) -> Response:
        """The item's source document (shown in the browser or downloaded): the verified bytes (075)."""
        p, data = _item_source(wp_id, item_id)
        return Response(data, media_type="application/pdf" if p.suffix.lower() == ".pdf" else "application/octet-stream",
                        headers={"Content-Disposition": "inline", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.get(r + "/workpackages/{wp_id}/reviews")
    def reviews(wp_id: WpId) -> dict[str, Any]:
        return work_views.workpackage_reviews(wp_id)

    # --- workflow (recipe) and readiness ---

    @app.get(r + "/workpackages/{wp_id}/workflow")
    def workflow(wp_id: WpId) -> dict[str, Any]:
        return work_views.assignment_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/workflow")
    def save_workflow(wp_id: WpId, body: SaveWorkflow, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.assign_recipe(wp_id, body.recipe_id, params=dict(body.params), expected_revision=body.expected_revision,
                           actor=who, note=body.note)
        return work_views.assignment_view(wp_id)

    @app.get(r + "/workpackages/{wp_id}/workflow/readiness")
    def readiness(wp_id: WpId) -> dict[str, Any]:
        return work_views.jsonable(work.readiness(wp_id))

    @app.post(r + "/workpackages/{wp_id}/workflow/start")
    def start(wp_id: WpId, body: StartRun, who: Annotated[str, Depends(human_actor)]) -> JavJSONResponse:
        res = work.start_run(wp_id, mode=body.mode, expected_assignment_revision=body.expected_revision,
                             input_hash=body.input_hash, actor=who, rerun_of=body.rerun_of)
        run = work.get_run(res["run_id"])
        return JavJSONResponse({**res, "status": run["status"]}, status_code=200 if res["deduped"] else 201)

    @app.get(r + "/workpackages/{wp_id}/runs")
    def wp_runs(wp_id: WpId) -> dict[str, Any]:
        return {"runs": work_views.run_list(wp_id)}

    # --- runs ---

    @app.get(r + "/runs")
    def all_runs(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict[str, Any]:
        return {"runs": work_views.run_list(None, limit=limit)}

    @app.get(r + "/runs/{run_id}")
    def run(run_id: RunId, names: Literal["original", "unified"] = "original") -> dict[str, Any]:
        """082: `names=unified` adds the items' unified names (the review queue shows them instead of the originals)."""
        return work_views.run_view(run_id, names=names == "unified")

    @app.get(r + "/runs/{run_id}/journal")
    def journal(run_id: RunId) -> dict[str, Any]:
        return work_views.run_journal(run_id)

    @app.post(r + "/runs/{run_id}/cancel")
    def cancel(run_id: RunId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.get_run(run_id)
        return {"run_id": run_id, "jobs": work.cancel_run(run_id, actor=who), "status": work.get_run(run_id)["status"]}

    @app.post(r + "/runs/{run_id}/approve")
    def approve(run_id: RunId, body: Approve, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.approve_run(run_id, actor=who, review_version=body.review_version)
        return work_views.run_view(run_id)

    @app.get(r + "/runs/{run_id}/results")
    def results(run_id: RunId) -> dict[str, Any]:
        """The run's result per item (machine data, correction, merged value) — the basis of the reports (K4)."""
        items = work.get_run(run_id)["input"]["items"]
        return work_views.jsonable({"run_id": run_id, "items": [corrections.item_result(run_id, i["item_id"]) for i in items]})

    @app.get(r + "/datasets")
    def dataset_catalog() -> dict[str, Any]:
        """056 U1: names and scopes of the queryable datasets (lists and result tables)."""
        from jav import datasets

        return {"datasets": datasets.catalog()}

    @app.post(r + "/datasets/{name}/query")
    def dataset_query(name: DatasetName, body: DatasetQuery) -> dict[str, Any]:
        """056 U1: one page of the dataset; filtering, sorting and paging run here, in the service."""
        from jav import datasets

        return datasets.query(name, body.scope, body.query)

    @app.post(r + "/datasets/{name}/export")
    def dataset_export(name: DatasetName, body: DatasetExport) -> Response:
        """056 U1: download from the dataset (all / filtered / selected rows, chosen columns)."""
        from jav import datasets

        data, media, fname, n = datasets.export_file(name, body.scope, body.query, body.rows, body.format, body.columns)
        return Response(data, media_type=media, headers={"Content-Disposition": attachment_header(fname),
                                                         "X-Export-Rows": str(n), "Cache-Control": "no-store",
                                                         "X-Content-Type-Options": "nosniff"})

    @app.get(r + "/runs/{run_id}/export")
    def run_export(run_id: RunId, format: Literal["csv", "xlsx", "json"] = "xlsx",  # noqa: A002 - legacy endpoint parameter
                   table: Literal["documents", "datapoints", "line_items"] = "documents") -> Response:
        """054 K4: the run's valid data for download (modelled on the legacy V4 export endpoint: attachment + row-count
        header)."""
        from jav import export

        work.get_run(run_id)  # unknown run: 404
        data, media, name, rows = export.render(run_id, format, table)
        return Response(data, media_type=media, headers={"Content-Disposition": attachment_header(name),
                                                         "X-Export-Rows": str(rows), "Cache-Control": "no-store",
                                                         "X-Content-Type-Options": "nosniff"})

    @app.get(r + "/runs/{run_id}/named-copies.zip")
    def named_copies_zip(run_id: RunId) -> StreamingResponse:
        """078: copies of the run's documents under content-based names, with the manifest (`jav/naming.py`); the
        originals are only read. Built into a temporary file first (large packages do not sit in memory)."""
        from jav import naming

        work.get_run(run_id)  # unknown run: 404
        fh = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)  # noqa: SIM115 - closed by the stream below
        try:
            counts = naming.write_zip(run_id, fh)
        except BaseException:
            fh.close()
            raise
        fh.seek(0)

        def chunks():
            try:
                while data := fh.read(1 << 20):
                    yield data
            finally:
                fh.close()

        return StreamingResponse(chunks(), media_type="application/zip", headers={
            "Content-Disposition": attachment_header(naming.zip_name(run_id)), "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff", "X-Named-Ready": str(counts["ready"]), "X-Named-Review": str(counts["review"]),
            "X-Named-Skipped": str(counts["skipped"])})

    @app.post(r + "/runs/{run_id}/named-copies")
    def named_copies_write(run_id: RunId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """078: writes the named copies and the manifest into a new subfolder of the output folder (Settings)."""
        from jav import naming

        work.get_run(run_id)
        folder = app_settings.output_folder()
        if not folder:
            raise app_settings.NoOutputFolder("no output folder is set (Settings > Work folders)")
        res = naming.write_to_folder(run_id, Path(folder))
        log.info("named copies of %s written by %s", run_id, who)
        return res

    @app.get(r + "/runs/{run_id}/reports/utility-cost")
    def utility_cost(run_id: RunId) -> dict[str, Any]:
        """054 K4: utility-cost time series (consumption point + utility, monthly grid, with sources)."""
        from jav import datasets, report_utility

        work.get_run(run_id)
        return work_views.jsonable({"run_id": run_id, **report_utility.build(datasets.run_records(run_id))})

    @app.get(r + "/runs/{run_id}/items/{item_id}")
    def item(run_id: RunId, item_id: ItemId) -> dict[str, Any]:
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    @app.get(r + "/runs/{run_id}/items/{item_id}/words")
    def item_words(run_id: RunId, item_id: ItemId) -> dict[str, Any]:
        """The item's word layer (045): pages and words with 0–1 boxes — for selecting on the image."""
        corrections.item_result(run_id, item_id)  # unknown run/item → 404
        layer = corrections.layer_for(corrections.datapoints_row(run_id, item_id))
        if layer is None:
            raise KeyError(f"no source layer for {item_id[:12]}")
        return work_views.jsonable({"layer_id": layer.layer_id, "text_source": layer.text_source,
                                    "pages": [p.model_dump() for p in layer.pages],
                                    "words": [w.model_dump() for w in layer.words]})

    @app.post(r + "/runs/{run_id}/items/{item_id}/correction")
    def save_correction(run_id: RunId, item_id: ItemId, body: SaveCorrection,
                        who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        corrections.item_result(run_id, item_id)  # unknown item → 404
        corrections.save(run_id, item_id, fields=dict(body.fields), expected_revision=body.expected_revision,
                         actor=who, note=body.note, sources=dict(body.sources) if body.sources else None, confirm=body.confirm)
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    @app.post(r + "/runs/{run_id}/items/{item_id}/tasks/{index}/decision")
    def task_decision(run_id: RunId, item_id: ItemId, index: Annotated[int, PathParam(ge=0, le=100)], body: TaskDecision,
                      who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """058 K5.3: only a human accepts or rejects a task proposal."""
        mailbox.decide_task(run_id, item_id, index, decision=body.decision, actor=who, note=body.note)
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    @app.post(r + "/runs/{run_id}/items/{item_id}/tasks/{index}/done")
    def task_done(run_id: RunId, item_id: ItemId, index: Annotated[int, PathParam(ge=0, le=100)], body: TaskDone,
                  who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """062: mark an accepted task as done by hand (or undo that)."""
        mailbox.mark_task_done(run_id, item_id, index, done=body.done, actor=who)
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    # --- to-dos ---

    @app.post(r + "/review-reasons/{reason_id}/resolve")
    def resolve_reason(reason_id: Annotated[int, PathParam(ge=1)], body: ResolveReason,
                       who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work.resolve_reason(reason_id, actor=who, resolution=body.resolution, note=body.note)

    # --- worker ---

    @app.get(r + "/worker")
    def worker_status() -> dict[str, Any]:
        return work_views.worker_status()

    @app.post(r + "/worker/stop")
    def worker_stop(body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        log.info("worker stop requested by %s", who)  # 066 Á35: who asked (operational log)
        worker.request_stop()
        return work_views.worker_status()

    # --- dependency audit (075): the last result; the audit itself runs from the CLI or the daily backup ---

    @app.get(r + "/system/deps-audit")
    def deps_audit_status() -> dict[str, Any]:
        return work_views.jsonable({"status": deps_audit.status(), "max_age_days": deps_audit.MAX_AGE_DAYS})

    # --- store backup (064): status of the latest backup, and backup now ---

    @app.get(r + "/system/backup")
    def backup_status() -> dict[str, Any]:
        c = settings().get("backup", {})
        conf = {k: c.get(k) for k in ("schedule", "keep", "copy_to", "with_burr", "with_docs", "max_age_hours")}
        conf["copy_to"] = backup.configured_copy_to()  # 076: the config or the local environment
        return work_views.jsonable({"status": backup.status(backup.default_root()), "config": conf})

    @app.post(r + "/system/backup")
    def backup_now(body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Back up now, with the daily backup's settings (locally and to the second location). A failure also shows in
        the status."""
        log.info("backup requested by %s", who)
        return work_views.jsonable(backup.scheduled())

    # --- paid calls with an uncertain outcome (076): listed and settled by hand, as `calls-uncertain` / `calls-resolve` ---

    @app.get(r + "/system/uncertain-calls")
    def uncertain_calls() -> dict[str, Any]:
        return work_views.jsonable({"calls": calls.uncertain_list()})

    @app.post(r + "/system/uncertain-calls/{invocation_id}/resolve")
    def resolve_uncertain_call(invocation_id: int, body: ResolveCall,
                               who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """The attempt becomes `failed` with the given cost (or with the maximum still committed when the cost is
        unknown); the step may then run again. The note records who settled it."""
        try:
            calls.resolve_uncertain(invocation_id, cost_usd=body.cost_usd, note=f"{who}: {body.note}")
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        log.info("uncertain call %d settled by %s", invocation_id, who)
        return {"ok": True}

    # --- settings (057): users, watched work folders ---

    @app.get(r + "/settings/users")
    def settings_users() -> dict[str, Any]:
        return {"users": app_settings.users()}

    @app.put(r + "/settings/users")
    def settings_save_users(body: SaveUsers, who: Annotated[str | None, Depends(actor_unless_first_users)]) -> dict[str, Any]:
        saved = app_settings.save_users(body.users)
        log.info("user list saved by %s: %d names", who or "(first setup)", len(saved))  # 066 Á35
        return {"users": saved}

    @app.get(r + "/settings/folders")
    def settings_folders() -> dict[str, Any]:
        return work_views.jsonable({"folders": app_settings.folders(), "roots": [str(p) for p in allowed_roots()]})

    @app.put(r + "/settings/folders")
    def settings_save_folders(body: SaveFolders, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Replaces the whole list; every path must be an existing folder (under the allowed roots when restricted)."""
        saved = app_settings.save_folders(body.folders, check_dir=lambda raw: checked_path(raw, want_dir=True))
        return work_views.jsonable({"folders": saved, "roots": [str(p) for p in allowed_roots()]})

    @app.get(r + "/settings/output-folder")
    def settings_output_folder() -> dict[str, Any]:
        """078: where the content-named copies of a run are written."""
        return {"path": app_settings.output_folder()}

    @app.put(r + "/settings/output-folder")
    def settings_save_output_folder(body: SaveOutputFolder, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """An existing folder that does not overlap a watched folder (the watcher would take the copies in again)."""
        return {"path": app_settings.save_output_folder(body.path, check_dir=lambda raw: checked_path(raw, want_dir=True), actor=who)}

    @app.post(r + "/settings/folders/{folder_id}/scan")
    def settings_scan_folder(folder_id: Annotated[str, PathParam(pattern=r"^wf-[0-9a-f]{10}$")], body: Empty,
                             who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Scan now (without waiting for the schedule)."""
        return work_views.jsonable(app_settings.scan(folder_id, actor=who))

    # --- mailbox (048 T2): preview, download (run by the worker), schedule ---

    @app.get(r + "/mailbox")
    def mailbox_overview() -> dict[str, Any]:
        from jav.config import OUTLOOK_BRIDGE_SCRIPT

        return work_views.jsonable({"schedules": mailbox.schedules(), "pulls": mailbox.pulls(), "accounts": mailbox.known_accounts(),
                                    "bridge_available": OUTLOOK_BRIDGE_SCRIPT.is_file(),
                                    "defaults": {"interval_min": mailbox.DEFAULT_INTERVAL_MIN,
                                                 "lookback_days": mailbox.DEFAULT_LOOKBACK_DAYS}})

    @app.post(r + "/mailbox/count")
    def mailbox_count(body: mailbox.MailboxRequest) -> dict[str, Any]:
        """Free count preview (the legacy script's `-CountOnly` branch); Outlook must be running."""
        return work_views.jsonable(mailbox.count(body))

    @app.post(r + "/mailbox/pulls", status_code=202)
    def mailbox_pull(body: mailbox.MailboxRequest, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(mailbox.request_pull(body, actor=who))

    @app.get(r + "/mailbox/pulls/{pull_id}")
    def mailbox_pull_status(pull_id: PullId) -> dict[str, Any]:
        return work_views.jsonable(mailbox.pull(pull_id))

    @app.post(r + "/mailbox/schedules", status_code=201)
    def mailbox_schedule_create(body: CreateSchedule, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(mailbox.create_schedule(body.request, actor=who, interval_min=body.interval_min))

    @app.patch(r + "/mailbox/schedules/{schedule_id}")
    def mailbox_schedule_update(schedule_id: ScheduleId, body: UpdateSchedule,
                                who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(mailbox.update_schedule(schedule_id, enabled=body.enabled, interval_min=body.interval_min))

    @app.post(r + "/mailbox/schedules/{schedule_id}/delete")  # a POST with a JSON body, like the other deletions
    def mailbox_schedule_delete(schedule_id: ScheduleId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        mailbox.delete_schedule(schedule_id)
        return {"deleted": schedule_id}

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
    from jav.runtime import applog

    # 063: the service log also goes to a persistent rotating file (runs/logs/api.log), with tracebacks for 500 errors
    uvicorn.run(create_app(), host=host, port=port or int(s["port"]), log_level="info", access_log=False,
                log_config=applog.uvicorn_config("api"))
