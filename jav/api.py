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

import importlib
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

from jav import (app_settings, backup, cfg, corrections, dates, deps_audit, isolated_pdf, local_picker, numbers, policy, package_release,
                 package_scope, store, version, work, work_views, workflows)
from jav.config import OLD_DATA_ROOT, PROJECT_ROOT
from jav.runtime import calls, lock, pdf_status, worker
from jav.tablequery import Query as TableQuery
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
DatasetName = Annotated[str, PathParam(pattern=r"^[a-z_]{1,40}$")]
WfId = Annotated[str, PathParam(pattern=r"^wf-[0-9a-f]{12}$")]  # 146: a workflow
StepId = Annotated[str, PathParam(pattern=r"^[a-z_]{1,40}$")]  # 146: a workflow step
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


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ItemSources(_In):
    """168 (plan F-item-list-and-adding): exactly one of the given files (`paths`) or a folder's documents (`folder`;
    with `recursive` its subfolders' too, without the output folder of the named copies)."""
    paths: Annotated[list[Annotated[str, Field(min_length=1, max_length=1024)]], Field(min_length=1, max_length=500)] | None = None
    folder: Annotated[str, Field(min_length=1, max_length=1024)] | None = None
    recursive: bool = False


class AddItems(ItemSources):
    """160-C S2; 168: what the person unticked in the preview stays out: the new documents in `exclude`, and, when
    `restore` is given, every removed one not in it."""
    exclude: Annotated[list[Digest], Field(max_length=2000)] = Field(default_factory=list)
    restore: Annotated[list[Digest], Field(max_length=2000)] | None = None
    expected_revision: Annotated[int, Field(ge=0)]


class Revision(_In):
    expected_revision: Annotated[int, Field(ge=0)]


class RemoveItem(Revision):
    """160-C S1 (decision 163 D2): the reason is required; the person is the request's actor."""
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class ItemIds(Revision):
    """168: several of the package's items at once."""
    item_ids: Annotated[list[Digest], Field(min_length=1, max_length=2000)]


class RemoveItems(ItemIds):
    reason: Annotated[str, Field(min_length=1, max_length=500)]


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
    scope: Literal["all", "pending"] = "all"  # 160-C S3: "pending" = only the package's pending items


class Empty(_In):
    pass


class ReleasePackage(_In):
    """171 (plan 170 L1): `expected_mark` is the package result view's `mark` the person saw; if the result changed
    since, 409. `confirm_removed`: the view's `removed_items`, as for a run's approval."""
    expected_mark: str = Field(min_length=1, max_length=64)
    confirm_removed: int | None = Field(default=None, ge=0)


class Approve(_In):
    """085 (re-audit A01): `review_version` is the run view's `review_version` the approver saw; if a correction changed
    the result since, 409. Without it (the command line) the current result is approved."""
    review_version: str | None = Field(default=None, max_length=64)
    # 160-C (decision 163 D7): how many removed items the approver saw (the run view's `removed_items`)
    confirm_removed: int | None = Field(default=None, ge=0)


class ResolveCall(_In):
    """076: settling a paid call with an uncertain outcome by hand, as `calls-resolve` does."""

    # None: unknown, the maximum stays committed; 167 (review R-9): the same cap as the settlement itself
    cost_usd: Decimal | None = Field(default=None, ge=0, le=calls.MAX_SETTLED_COST_USD, allow_inf_nan=False)
    note: str = Field(min_length=3, max_length=500)


IsoDay = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


PartyId = Annotated[str, Field(pattern=r"^party-[0-9a-f]{12}$")]  # 133: an own party (`jav/parties.py`)


StepKey = Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]
Budget = dict[Literal["jev", "openai", "azure_di"], Annotated[str, Field(pattern=r"^\d{1,4}(\.\d{1,6})?$")]]


class WorkflowSource(_In):
    """146: a workflow step's source: a folder or files, a mailbox request, an existing work package, or none."""
    kind: Literal["folder", "files", "mailbox", "package", "none"]
    folder: Annotated[str, Field(min_length=1, max_length=1024)] | None = None
    recursive: bool = False
    paths: Annotated[list[Annotated[str, Field(min_length=1, max_length=1024)]], Field(max_length=500)] | None = None
    request: dict[str, Any] | None = None  # checked as a mailbox.MailboxRequest
    workpackage_id: Annotated[str, Field(pattern=r"^wp-[0-9a-f]{12}$")] | None = None
    only_new: bool = False  # 147: a documents step takes only the documents no live run has processed yet


class WorkflowStepInput(_In):
    source: WorkflowSource
    budget: Budget | None = None  # 146: the most an automatic start may reserve, per provider (USD)
    engine: Literal["jev", "gpt"] | None = None  # 160-D: the step's own AI engine; None: the application's


class CreateWorkflow(_In):
    template: Annotated[str, Field(pattern=r"^[a-z_]{1,60}$")]
    # 181: the party and the period are needed only when the template's steps need them (`workflows.template_needs`)
    party_id: PartyId | None = None
    period_start: IsoDay | None = None
    period_end: IsoDay | None = None
    name: Annotated[str, Field(max_length=200)] | None = None
    names: dict[StepKey, Annotated[str, Field(min_length=1, max_length=200)]] | None = None  # the steps' package names
    auto: bool = True
    steps: Annotated[dict[StepKey, WorkflowStepInput], Field(min_length=1, max_length=10)]
    previous: Annotated[str, Field(pattern=r"^wf-[0-9a-f]{12}$")] | None = None  # 147: the workflow this one repeats


class WorkflowEstimate(_In):
    kind: Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]  # 181: a registered step kind (`jav/workflow_steps.py`)
    source: WorkflowSource
    party_id: PartyId | None = None
    period_start: IsoDay | None = None
    period_end: IsoDay | None = None
    engine: Literal["jev", "gpt"] | None = None  # 160-D: the step's own AI engine; None: the application's


class StartWorkflowStep(_In):
    budget: Budget | None = None  # a person's new budget for the step (recorded)


class LinkWorkflowStep(_In):
    workpackage_id: Annotated[str, Field(pattern=r"^wp-[0-9a-f]{12}$")]


class UpdateWorkflow(_In):
    auto: bool | None = None
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    archived: bool | None = None


class RenameWorkpackage(_In):
    name: Annotated[str, Field(min_length=1, max_length=200)]


class SetPackageScope(_In):
    """181: the party, the period and the role a person gives a package (`jav/package_scope.py`); any may be left out."""
    party_id: PartyId | None = None
    period_start: IsoDay | None = None
    period_end: IsoDay | None = None
    role: Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")] | None = None


class SetOwner(_In):
    """061: the package's owner (a name from the user list); None: no owner."""
    owner: Annotated[str, Field(min_length=1, max_length=64)] | None


class SaveUsers(_In):
    users: Annotated[list[Annotated[str, Field(max_length=64)]], Field(max_length=200)]


class SaveFolders(_In):
    folders: Annotated[list[app_settings.WatchedFolder], Field(max_length=50)]


class SaveOutputFolder(_In):
    path: str | None = Field(default=None, max_length=1024)  # empty: no output folder


class SaveEngine(_In):
    engine: Literal["jev", "gpt"]  # 160-D: JEV and GPT | GPT only (app_settings.ENGINES)


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


class NativeCitationRequest(_In):
    occurrence_id: str = Field(min_length=1, max_length=256)
    element_id: str = Field(min_length=1, max_length=256)
    quote: str = Field(min_length=1, max_length=10000)


class SaveNativeCorrection(_In):
    kind: Literal["native"]
    values: dict[Annotated[str, Field(max_length=256)], Annotated[str, Field(max_length=100000)] | None] = Field(max_length=200)
    native_sources: dict[Annotated[str, Field(max_length=256)], Annotated[list[NativeCitationRequest], Field(max_length=20)]] = Field(default_factory=dict, max_length=200)
    expected_revision: Annotated[int, Field(ge=0)]
    expected_result_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    confirm: list[Annotated[str, Field(max_length=256)]] = Field(default_factory=list, max_length=200)
    note: Text | None = None


class ResolveNativeCitations(_In):
    expected_result_version: str = Field(pattern=r"^[0-9a-f]{64}$")
    citations: list[NativeCitationRequest] = Field(max_length=20)


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


def _max_source_bytes() -> int:
    """075: a source larger than the input limit is never read into memory (it could not have been added anyway)."""
    return work.max_source_bytes()


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

    # --- recipes and work packages ---

    @app.get(r + "/recipes")
    def recipes() -> dict[str, Any]:
        # 063: recipe explanations; 080: the titles of every recipe (an old run or a package not yet migrated shows its
        # recipe's title, although only the active processing is offered)
        return {"recipes": work_views.recipe_catalog(), "help": work_views.recipe_help(),
                "titles": {r["id"]: r["title"] for r in work.recipes()}}

    @app.get(r + "/workpackages")
    def workpackages(include_archived: bool = False, brief: bool = False) -> dict[str, Any]:
        """154: `brief` gives the packages as stored, without their to-dos and next step (the workflow pickers need
        only the name and the kind; the full list builds every reconciliation workspace)."""
        if brief:
            return {"workpackages": work_views.jsonable(work.list_workpackages(include_archived=include_archived))}
        return {"workpackages": work_views.workpackage_list(include_archived=include_archived)}

    @app.post(r + "/workpackages", status_code=201)
    def create_workpackage(body: CreateWorkpackage, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        if (body.folder is None) == (body.paths is None):
            raise explained(ValueError, "give exactly one of folder or paths")
        if body.folder is not None:  # 065: the creator is the owner
            # 081: with the subfolders, the output folder of the named copies is left out
            out = app_settings.output_folder() if body.recursive else None
            wp = work.create_from_folder(checked_path(body.folder, want_dir=True), name=body.name, owner=who,
                                         recursive=body.recursive, exclude=[Path(out)] if out else [])
        else:
            if not body.name:
                raise explained(ValueError, "name is required when creating from files")
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

    @app.get(r + "/package-roles")
    def package_roles() -> dict[str, Any]:
        """181: the roles a package's scope can name, with the package kinds that can hold each."""
        return {"roles": [{"name": x.name, "title": x.title, "package_kinds": list(x.package_kinds)}
                          for x in package_scope.roles()]}

    @app.post(r + "/workpackages/{wp_id}/scope")
    def set_package_scope(wp_id: WpId, body: SetPackageScope, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """181: a person gives the package its party, period and role (recorded in its log)."""
        package_scope.set_scope(wp_id, party_id=body.party_id, period_start=body.period_start, period_end=body.period_end,
                                role_name=body.role, actor=who)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/scope/clear")
    def clear_package_scope(wp_id: WpId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """181: a person takes the package's own scope away (a scope of its workflow shows again)."""
        package_scope.clear_scope(wp_id, actor=who)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/owner")
    def set_owner(wp_id: WpId, body: SetOwner, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """061: the package's owner; only a name from the user list (any name when the list is empty)."""
        owner = None
        if body.owner is not None:
            owner = app_settings.canonical_user(body.owner)
            if owner is None:
                raise explained(ValueError, "unknown user: the owner must be in the user list")
        work.set_owner(wp_id, owner, actor=who)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/delete")  # a POST with a JSON body, like the other deletions
    def delete_workpackage(wp_id: WpId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.delete_workpackage(wp_id, actor=who)
        return {"deleted": wp_id}

    def _sources(body: ItemSources) -> tuple[list[Path], list[Path], Path | None]:
        """168: the documents of the given files or of the folder, the folder's other files, and the folder."""
        if (body.folder is None) == (body.paths is None):
            raise explained(ValueError, "give exactly one of folder or paths")
        if body.paths is not None:
            return [checked_path(p, want_dir=False) for p in body.paths], [], None
        root = checked_path(body.folder, want_dir=True)
        out = app_settings.output_folder() if body.recursive else None  # 081: not the named copies
        docs, others = work.folder_contents(root, recursive=body.recursive, exclude=[Path(out)] if out else [])
        return docs, others, root

    @app.post(r + "/workpackages/{wp_id}/items/preview")
    def preview_items(wp_id: WpId, body: ItemSources, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """168: what adding the files or the folder would do, file by file; nothing is written."""
        docs, others, root = _sources(body)
        return work.preview_additions(wp_id, docs, others=others, root=root)

    @app.post(r + "/workpackages/{wp_id}/items")
    def add_items(wp_id: WpId, body: AddItems, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """160-C S2: documents added to an existing package, with what happened (`added`: added, already in the
        package, restored, left out as unticked (168), and those processed live in another package)."""
        docs, _others, _root = _sources(body)
        _wp, summary = work.add_to_package(wp_id, docs, expected_revision=body.expected_revision, actor=who,
                                           exclude=body.exclude, restore=body.restore)
        return {**work_views.workpackage_view(wp_id), "added": summary}

    @app.post(r + "/workpackages/{wp_id}/items/remove")
    def remove_items(wp_id: WpId, body: RemoveItems, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """168: several items removed with one reason, in one step."""
        work.remove_items(wp_id, body.item_ids, expected_revision=body.expected_revision, actor=who, reason=body.reason)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/items/restore")
    def restore_items(wp_id: WpId, body: ItemIds, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """168: several removed items back in the package, in one step."""
        work.restore_items(wp_id, body.item_ids, expected_revision=body.expected_revision, actor=who)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/items/{item_id}/remove")
    def remove_item(wp_id: WpId, item_id: ItemId, body: RemoveItem, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.remove_item(wp_id, item_id, expected_revision=body.expected_revision, actor=who, reason=body.reason)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/items/{item_id}/restore")
    def restore_item(wp_id: WpId, item_id: ItemId, body: Revision, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """160-C S1: a removed item back in the package (it takes part in the next run)."""
        work.restore_item(wp_id, item_id, expected_revision=body.expected_revision, actor=who)
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
                             input_hash=body.input_hash, actor=who, rerun_of=body.rerun_of,
                             scope=body.scope)
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

    @app.post(r + "/runs/{run_id}/supersede")
    def supersede(run_id: RunId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """151: a person supersedes an older live run that a later live run has repeated (`work.supersede_run`)."""
        out = work.supersede_run(run_id, actor=who)
        return {**out, "status": work.get_run(run_id)["status"]}

    @app.post(r + "/runs/{run_id}/approve")
    def approve(run_id: RunId, body: Approve, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.approve_run(run_id, actor=who, review_version=body.review_version, confirm_removed=body.confirm_removed)
        return work_views.run_view(run_id)

    @app.get(r + "/workpackages/{wp_id}/result")
    def package_result_view(wp_id: WpId) -> dict[str, Any]:
        """171 (plan 170 L1): the package's current result per item, its mark, the open live runs and what blocks a
        release, the release state and the released versions. 172: and its meaningful result views (`tables`)."""
        with store.session():
            return work_views.jsonable({**package_release.view(wp_id),
                                        "tables": work_views.result_tables(workpackage_id=wp_id)})

    @app.get(r + "/workpackages/{wp_id}/result/export.xlsx")
    def package_result_export(wp_id: WpId) -> Response:
        """172: the package's current result as a workbook (each item from its counted run; a release stores its own)."""
        content, filename = package_release.current_workbook(wp_id)
        return Response(content, media_type=package_release.MEDIA["result.xlsx"],
                        headers={"Content-Disposition": attachment_header(filename), "Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff"})

    @app.post(r + "/workpackages/{wp_id}/release")
    def release_package(wp_id: WpId, body: ReleasePackage, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """171 (plan 170 L1): Approve and release: the open live runs are approved and the next version recorded."""
        version = package_release.release(wp_id, actor=who, expected_mark=body.expected_mark,
                                          confirm_removed=body.confirm_removed)
        return work_views.jsonable({"version": version, "result": package_release.view(wp_id)})

    @app.get(r + "/workpackages/{wp_id}/versions/{version}/files/{name}")
    def package_version_file(wp_id: WpId, version: Annotated[int, PathParam(ge=1, le=100000)],
                             name: Literal["result.xlsx", "result.json", "documents.csv", "datapoints.csv",
                                           "line_items.csv", "native_facts.csv", "utility_cost.xlsx"]) -> Response:
        """171: a released version's download, the stored file itself (it never changes)."""
        content, media, filename = package_release.version_file(wp_id, version, name)
        return Response(content, media_type=media, headers={"Content-Disposition": attachment_header(filename),
                                                            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.get(r + "/runs/{run_id}/results")
    def results(run_id: RunId) -> dict[str, Any]:
        """The run's result per item (machine data, correction, merged value) — the basis of the reports (K4)."""
        with store.session():  # 153 (review B6): one connection for every item
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
                   table: Literal["documents", "datapoints", "line_items", "native_facts"] = "documents") -> Response:
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
            raise explained(app_settings.NoOutputFolder, "no output folder is set (Settings > Work folders)")
        res = naming.write_to_folder(run_id, Path(folder))
        log.info("named copies of %s written by %s", run_id, who)
        return res

    @app.get(r + "/runs/{run_id}/items/{item_id}")
    def item(run_id: RunId, item_id: ItemId) -> dict[str, Any]:
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    @app.get(r + "/document-formats")
    def document_formats() -> dict[str, Any]:
        from jav.native_contracts import DOCUMENT_FORMATS
        from jav.native_processing import estimate_limits

        limits = estimate_limits({"jev": "off"})
        return {"formats": [item.model_dump(mode="json") for item in DOCUMENT_FORMATS],
                "native_limits": limits.model_dump(mode="json", exclude={"provider_limits_usd"})}

    @app.get(r + "/runs/{run_id}/items/{item_id}/sources")
    def native_sources(run_id: RunId, item_id: ItemId, offset: Annotated[int, Query(ge=0)] = 0,
                       limit: Annotated[int, Query(ge=1, le=500)] = 100,
                       occurrence_id: Annotated[str | None, Query(max_length=256)] = None,
                       expected_result_version: Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")] = None) -> dict[str, Any]:
        from jav import native_results

        publication = corrections.native_publication(run_id, item_id, expected_result_version=expected_result_version)
        return native_results.source_elements(publication, offset=offset, limit=limit,
                                              occurrence_id=occurrence_id).model_dump(mode="json")

    @app.post(r + "/runs/{run_id}/items/{item_id}/citations/resolve")
    def resolve_native_citations(run_id: RunId, item_id: ItemId, body: ResolveNativeCitations) -> dict[str, Any]:
        from jav import native_results

        publication = corrections.native_publication(run_id, item_id, expected_result_version=body.expected_result_version)
        return {"result_version": publication.result_version,
                "citations": [cite.model_dump(mode="json") for cite in native_results.resolve_citations(
                    publication, [citation.model_dump() for citation in body.citations])]}

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
    def save_correction(run_id: RunId, item_id: ItemId, body: SaveCorrection | SaveNativeCorrection,
                        who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        corrections.item_result(run_id, item_id)  # unknown item → 404
        if isinstance(body, SaveNativeCorrection):
            citations = {key: [cite.model_dump() for cite in refs] for key, refs in body.native_sources.items()}
            corrections.save_native(run_id, item_id, values=body.values, native_sources=citations,
                                     expected_revision=body.expected_revision, expected_result_version=body.expected_result_version,
                                     actor=who, note=body.note, confirm=body.confirm)
        else:
            corrections.save(run_id, item_id, fields=dict(body.fields), expected_revision=body.expected_revision,
                             actor=who, note=body.note, sources=dict(body.sources) if body.sources else None, confirm=body.confirm)
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    # --- 176 (plan 170 L3): each logic pack's own addresses; 185 (plan G-full-move T1a): and each domain's others
    # (`service_modules`) ---

    for name in service_modules():
        importlib.import_module(name).routes(app, r)

    # --- 178 (plan 170 L4): own output templates and a package's choice of them (jav/api_outputs.py) ---

    from jav import api_outputs

    api_outputs.routes(app, r)

    # --- 146: workflows (the work packages of one job, chained; jav/workflows.py) ---

    def workflow_source(src: WorkflowSource) -> dict[str, Any]:
        """A step's source with its paths checked like a typed path (existing, under the allowed roots)."""
        out = src.model_dump(exclude_none=True)
        if src.kind == "folder":
            out["folder"] = str(checked_path(src.folder or "", want_dir=True))
        elif src.kind == "files":
            out["paths"] = [str(checked_path(p, want_dir=False)) for p in src.paths or []]
        return out

    @app.get(r + "/workflow-templates")
    def workflow_templates() -> dict[str, Any]:
        return workflows.templates_view()  # 181: each kind with its registered step kind

    @app.post(r + "/workflows/estimate")
    def workflow_estimate(body: WorkflowEstimate) -> dict[str, Any]:
        return work_views.jsonable(workflows.estimate(kind=body.kind, source=workflow_source(body.source),
                                                      party_id=body.party_id, period_start=body.period_start,
                                                      period_end=body.period_end, engine=body.engine))

    @app.get(r + "/workflows")
    def workflow_list(include_archived: bool = False) -> dict[str, Any]:
        return {"workflows": work_views.jsonable(workflows.workflows(include_archived=include_archived))}

    @app.post(r + "/workflows", status_code=201)
    def create_workflow(body: CreateWorkflow, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        steps = {sid: {"source": workflow_source(s.source), "budget": s.budget or {}, "engine": s.engine}
                 for sid, s in body.steps.items()}
        return work_views.jsonable(workflows.create(template_id=body.template, party_id=body.party_id,
                                                    period_start=body.period_start, period_end=body.period_end,
                                                    steps=steps, actor=who, name=body.name, names=body.names,
                                                    auto=body.auto, previous=body.previous))

    @app.get(r + "/workflows/{wf_id}")
    def workflow_view(wf_id: WfId) -> dict[str, Any]:
        return work_views.jsonable(workflows.view(wf_id))

    @app.get(r + "/workflows/{wf_id}/repeat")
    def workflow_repeat(wf_id: WfId) -> dict[str, Any]:
        """147: the workflow for the next period, as the wizard shows it filled in (nothing is written)."""
        return work_views.jsonable(workflows.repeat_draft(wf_id))

    @app.patch(r + "/workflows/{wf_id}")
    def update_workflow(wf_id: WfId, body: UpdateWorkflow, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(workflows.update(wf_id, actor=who, auto=body.auto, name=body.name,
                                                    archived=body.archived))

    @app.post(r + "/workflows/{wf_id}/steps/{step}/start")
    def start_workflow_step(wf_id: WfId, step: StepId, body: StartWorkflowStep,
                            who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(workflows.start_step(wf_id, step, actor=who, budget=body.budget))

    @app.post(r + "/workflows/{wf_id}/steps/{step}/link")
    def link_workflow_step(wf_id: WfId, step: StepId, body: LinkWorkflowStep,
                           who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work_views.jsonable(workflows.link(wf_id, step, body.workpackage_id, actor=who))

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
        the status. 160 (review R-6): it counts with the manual backups, so it never pushes out a daily one."""
        log.info("backup requested by %s", who)
        return work_views.jsonable(backup.scheduled(kind="manual"))

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

    @app.get(r + "/settings/engine")
    def settings_engine() -> dict[str, Any]:
        """160-D: the application's AI engine, the default of every new processing setting that does not name one."""
        return app_settings.engine_setting()

    @app.put(r + "/settings/engine")
    def settings_save_engine(body: SaveEngine, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Saved settings and started runs keep their own engine; only new settings follow."""
        return app_settings.save_engine_default(body.engine, actor=who)

    @app.post(r + "/settings/folders/{folder_id}/scan")
    def settings_scan_folder(folder_id: Annotated[str, PathParam(pattern=r"^wf-[0-9a-f]{10}$")], body: Empty,
                             who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Scan now (without waiting for the schedule)."""
        return work_views.jsonable(app_settings.scan(folder_id, actor=who))

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
