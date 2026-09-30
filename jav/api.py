"""Helyi szolgáltatás (040 K2): a felület és a parancssor közös kapuja a kerethez.

Csak a saját gépről érhető el: loopback címre köt, és minden kérésnél ellenőrzi a `Host` fejlécet (DNS-átkötés ellen)
és a böngésző `Origin` fejlécét (idegen weboldal ne indíthasson műveletet). Író kérés csak JSON-törzzsel jöhet
(egyszerű űrlap-hamisítás ellen), a törzs mérete korlátos, a bemenet szerkezetét Pydantic-séma ellenőrzi
(ismeretlen mező = elutasítás). A határok a `configs/service.json`-ban vannak.

A végpontok nevei a V4 `businessWorkflowApi.ts` hívásait követik (`workflow`, `readiness`, `start`, `runs`). Az üzleti
szabályok a `jav.work`-ben és a `jav.corrections`-ben vannak; itt csak fordítás HTTP-re:

  404 ismeretlen azonosító · 409 verzióütközés / nem indítható / nem jóváhagyható · 413 túl nagy törzs ·
  415 nem JSON · 422 hibás bemenet · 403 idegen eredet vagy nem engedélyezett mappa

A hosszú feldolgozás nem itt fut: a futás a munkasorba kerül, és a különálló feldolgozó (`python -m jav.cli worker`)
viszi végig, így a böngésző vagy a szolgáltatás bezárása nem állítja le.
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import quote, unquote, urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from jav import app_settings, backup, cfg, corrections, mailbox, store, work, work_views
from jav.config import OLD_DATA_ROOT, PROJECT_ROOT
from jav.runtime import worker
from jav.tablequery import Query as TableQuery

API_VERSION = "1"
UI_DIST = PROJECT_ROOT / "ui" / "dist"  # a felület buildje (040 K3); ha megvan, a szolgáltatás a gyökéren kiszolgálja
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
log = logging.getLogger("jav.api")


def settings() -> dict[str, Any]:
    return cfg.load("service")


class UnknownUser(PermissionError):
    """061: a névlista nem üres, és a megadott szerző nincs rajta."""


class ForbiddenPath(PermissionError):
    """A kért mappa vagy fájl nem az engedélyezett gyökérmappák alatt van."""


def paths_restricted() -> bool:
    """061 döntés: alapból nincs mappakorlát (bármely létező helyi mappa / fájl megadható); `restrict_paths: true` esetén
    csak az engedélyezett gyökerek alatt."""
    return bool(settings().get("restrict_paths", True))


def allowed_roots() -> list[Path]:
    """Az engedélyezett gyökerek; korlát nélkül üres lista (a felület ekkor nem sorol fel helyeket)."""
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
    """Az útvonal feloldva (hivatkozások követésével) létező mappa / fájl; korláttal az engedélyezett gyökerek egyike alatt."""
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


# --- válasz és hibák -----------------------------------------------------------------------------------


class _UiFiles(StaticFiles):
    """A felület fájljai; a belépő HTML-t a böngésző mindig újrakéri (új build azonnal látszik), a hash-nevű
    fájlok gyorsítótárazhatók."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        response = super().file_response(full_path, stat_result, scope, status_code)
        if str(full_path).endswith(".html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


class JavJSONResponse(JSONResponse):
    """A parancssorral azonos JSON-alak (`work_views.jsonable`): a pénz `Decimal` szövegként, nem lebegőpontosan."""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")


def _error(status: int, code: str, message: str, **extra: Any) -> JavJSONResponse:
    return JavJSONResponse({"error": code, "message": message, **extra}, status_code=status)


def _origin(value: str) -> str:
    """Összevethető eredet: `séma://gép:port` kisbetűvel, alapértelmezett porttal kiegészítve; értelmezhetetlen = üres."""
    try:
        u = urlsplit(value.strip())
        port = u.port or {"http": 80, "https": 443}.get(u.scheme)
    except ValueError:
        return ""
    return f"{u.scheme}://{u.hostname}:{port}" if u.scheme and u.hostname else ""


class _Guard:
    """Tiszta ASGI-köztes réteg: Host, Origin, tartalomtípus és törzsméret, még az útválasztás előtt."""

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
        # 066 Á34: pontos egyezés (séma, gép, port): a saját cím, vagy a beállított fejlesztői felület; más helyi port nem
        if origin is not None and _origin(origin) not in self.dev_origins | {_origin("http://" + headers.get("host", ""))}:
            return await _error(403, "forbidden_origin", "requests from other sites are refused")(scope, receive, send)
        if scope["method"] in ("POST", "PUT", "PATCH", "DELETE"):
            ctype = headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype != "application/json":
                return await _error(415, "unsupported_media_type", "the request body must be JSON")(scope, receive, send)
            length = headers.get("content-length")
            if length is not None and (not length.isdigit() or int(length) > self.max_body):
                return await _error(413, "too_large", f"the request body is limited to {self.max_body} bytes")(scope, receive, send)
        # A törzs előre, korláttal beolvasva (darabolt küldésnél sincs Content-Length); utána visszajátszva.
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


# --- bemeneti sémák -------------------------------------------------------------------------------------

WpId = Annotated[str, PathParam(pattern=r"^wp-[0-9a-f]{12}$")]
RunId = Annotated[str, PathParam(pattern=r"^run-[0-9a-f]{12}$")]
ItemId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{64}$")]
DatasetName = Annotated[str, PathParam(pattern=r"^[a-z_]{1,40}$")]
Text = Annotated[str, Field(max_length=2000)]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateWorkpackage(_In):
    """Pontosan az egyik: `folder` (a mappa PDF-jei) vagy `paths` (megadott fájlok, több mappából is; ekkor `name` kell)."""
    folder: Annotated[str, Field(min_length=1, max_length=1024)] | None = None
    paths: Annotated[list[Annotated[str, Field(min_length=1, max_length=1024)]], Field(min_length=1, max_length=500)] | None = None
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None


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
    rerun_of: Annotated[str, Field(pattern=r"^run-[0-9a-f]{12}$")] | None = None  # 057: újrafuttatás


class Empty(_In):
    pass


class TaskDecision(_In):
    decision: Literal["accepted", "rejected"]
    note: Text | None = None


class TaskDone(_In):
    done: bool


class RenameWorkpackage(_In):
    name: Annotated[str, Field(min_length=1, max_length=200)]


class SetOwner(_In):
    """061: a csomag felelőse (a névlista egy neve); None: nincs felelős."""
    owner: Annotated[str, Field(min_length=1, max_length=64)] | None


class SaveUsers(_In):
    users: Annotated[list[Annotated[str, Field(max_length=64)]], Field(max_length=200)]


class SaveFolders(_In):
    folders: Annotated[list[app_settings.WatchedFolder], Field(max_length=50)]


_ScopeMap = Annotated[dict[Annotated[str, Field(max_length=64)], Annotated[str, Field(max_length=200)]], Field(max_length=5)]


class DatasetQuery(_In):
    """056 U1: egységes lista-kérés (hatókör + keresés, szűrők, rendezés, lapozás)."""
    scope: _ScopeMap = Field(default_factory=dict)
    query: TableQuery = Field(default_factory=TableQuery)


class DatasetExport(DatasetQuery):
    format: Literal["csv", "xlsx", "json"] = "xlsx"
    rows: Literal["all", "filtered", "selected"] = "filtered"
    columns: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=500)] | None = None


_Cell = Annotated[str, Field(max_length=500)] | int | None
_Row = Annotated[dict[Annotated[str, Field(max_length=64)], _Cell], Field(max_length=50)]


class SaveCorrection(_In):
    # 048: tételes lista = sorok listája (tétel-mező -> érték) vagy egyszerű értékek listája; a fajta szerinti ellenőrzés
    # a `jav.corrections`-ben (a sorok tartalmát ott vetjük össze a csomag tétel-leírásával)
    fields: dict[Annotated[str, Field(max_length=64)], _Cell | Annotated[list[_Row | _Cell], Field(max_length=2000)]] = Field(max_length=100)
    expected_revision: Annotated[int, Field(ge=0)]
    note: Text | None = None
    # 045: mezőnként a képen kijelölt szavak azonosítói (a tétel szórétegéből)
    sources: dict[Annotated[str, Field(max_length=64)], Annotated[list[Annotated[int, Field(ge=0)]], Field(min_length=1, max_length=200)]] | None = Field(
        default=None, max_length=100)


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


_ACTOR_RE = app_settings.ACTOR_RE  # 066 Á25: közös szabály a névlistával


def _decode_actor(raw: str) -> str:
    """A szerző neve URL-kódolva jön (a HTTP-fejléc nem hordoz tetszőleges ékezetet, pl. „ő”); dekódolva ellenőrizzük."""
    name = unquote(raw).strip()
    if not _ACTOR_RE.match(name):
        raise HTTPException(status_code=422, detail="X-Actor: 1-64 letters, digits, space, dot, @ or hyphen")
    return name


def attachment_header(filename: str) -> str:
    """Letöltési fejléc bármilyen fájlnévre (066 Á22): ASCII-tartalék (ékezet nélkül, a nem biztonságos jel `_`) és a
    pontos név UTF-8-ban (RFC 5987). A fejléc Latin-1-es, ezért az ékezetes név eddig hibát (422) adott."""
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name) or "export"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def human_actor(x_actor: Annotated[str, Header(max_length=256)]) -> str:
    """Emberi döntésnél (jóváhagyás, javítás, teendő zárása, futás indítása, recept, csomag módosítása) a szerző
    kötelező: `X-Actor` fejléc. 061: ha a névlista nem üres, a névnek rajta kell lennie (a lista alakjában rögzítjük)."""
    name = app_settings.canonical_user(_decode_actor(x_actor))
    if name is None:
        raise UnknownUser("the actor is not in the user list (Settings > Users)")
    return name


def actor_unless_first_users(x_actor: Annotated[str | None, Header(max_length=256)] = None) -> str | None:
    """066 Á35: a névlista írásához szerző kell, a listán szereplő; az első kitöltés (üres lista) szerző nélkül is mehet."""
    if not app_settings.users():
        return app_settings.canonical_user(_decode_actor(x_actor)) if x_actor else None
    if x_actor is None:
        raise ValueError("X-Actor header is required to change the user list")
    return human_actor(x_actor)


# --- alkalmazás -----------------------------------------------------------------------------------------


def create_app(*, store_path: Path | None = None) -> FastAPI:
    """`store_path`: futáshelyi adattár (tesztekhez); nélküle az alapértelmezett `store/jav.sqlite`."""
    s = settings()
    app = FastAPI(title="JAV helyi szolgáltatás", version=API_VERSION, default_response_class=JavJSONResponse,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)

    if store_path is not None:
        @app.middleware("http")
        async def scoped_store(request: Request, call_next):
            with store.use_store(store_path):
                return await call_next(request)

    # 063: a 404 / 422 válaszra fordított hiba a naplóba is bekerül a hibanyommal — egy belső hiba (pl. hiányzó kulcs
    # egy szótárban) különben „ismeretlen azonosítónak” látszana, nyom nélkül
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

    @app.exception_handler(mailbox.BridgeError)
    async def bridge_failed(_request: Request, exc: mailbox.BridgeError):
        return _error(503, "mailbox_unavailable", str(exc))

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        log.warning("422 %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        return _error(422, "invalid", str(exc))

    @app.exception_handler(OSError)
    async def unreadable(request: Request, exc: OSError):
        # 063: pl. egy mappa zárolt vagy közben eltűnt fájlja — érthető válasz 500 helyett, a hibanyom a naplóban
        log.warning("OSError %s %s: %s", request.method, request.url.path, exc, exc_info=exc)
        name = Path(exc.filename).name if getattr(exc, "filename", None) else ""
        return _error(422, "unreadable", f"A fájl nem olvasható{': ' + name if name else ''} ({type(exc).__name__}).")

    r = "/api"

    @app.get(r + "/settings")
    def ui_settings() -> dict[str, Any]:
        """A felület megjelenítési beállításai (045): bizonyosság-sávok."""
        return {"confidence_bands": settings().get("confidence_bands", {"confident": 0.9, "check": 0.5})}

    @app.post(r + "/normalize")
    def normalize(body: NormalizeValue) -> dict[str, Any]:
        """Kijelölt szöveg → a mező fajtája szerinti érték (045: kijelölés a képen). A formátumot kód dönti el, nem a
        böngésző; értelmezhetetlen szövegnél `ok=false` és az ok, a felület ekkor nem ajánlja fel a mentést."""
        from jav import typepack
        from jav.models import normalize_value

        pack = typepack.get(body.doc_type)
        if body.field not in pack.fields:
            raise ValueError(f"not a field of {pack.key}: {body.field}")
        reasons: list[str] = []
        text = body.text.strip()
        if pack.kind(body.field) == "money":  # a kijelölésben természetes a pénznem-jel („1 071 880 Ft”, „650 000,-”)
            text = re.sub(r"(?i)\s*(?:ft\.?|huf|eur|usd|€|\$|,-)\s*$", "", re.sub(r"(?i)^\s*(?:huf|eur|usd|€|\$)\s*", "", text))
        value = normalize_value(pack.kind(body.field), text, body.field, reasons)
        return work_views.jsonable({"ok": value is not None and not reasons, "value": value, "reasons": reasons,
                                    "kind": pack.kind(body.field)})

    @app.get(r + "/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "api_version": API_VERSION, "service_config": cfg.version("service")}

    # --- receptek és munkacsomagok ---

    @app.get(r + "/recipes")
    def recipes() -> dict[str, Any]:
        return {"recipes": work_views.recipe_catalog(), "help": work_views.recipe_help()}  # 063: a receptek magyarázata

    @app.get(r + "/workpackages")
    def workpackages(include_archived: bool = False) -> dict[str, Any]:
        return {"workpackages": work_views.workpackage_list(include_archived=include_archived)}

    @app.post(r + "/workpackages", status_code=201)
    def create_workpackage(body: CreateWorkpackage, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        if (body.folder is None) == (body.paths is None):
            raise ValueError("give exactly one of folder or paths")
        if body.folder is not None:  # 065: a létrehozó a felelős
            wp = work.create_from_folder(checked_path(body.folder, want_dir=True), name=body.name, owner=who)
        else:
            if not body.name:
                raise ValueError("name is required when creating from files")
            wp = work.create_from_files([checked_path(p, want_dir=False) for p in body.paths], name=body.name, owner=who)
        return work_views.workpackage_view(wp["id"])

    @app.get(r + "/workpackages/{wp_id}")
    def workpackage(wp_id: WpId) -> dict[str, Any]:
        return work_views.workpackage_view(wp_id)

    # 058: elrejtés (a futások és az eredmények megmaradnak), visszahozás, átnevezés; törlés csak futás nélküli csomagon

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
        """061: a csomag felelőse; csak a névlista egy neve (üres listánál bármely név)."""
        owner = None
        if body.owner is not None:
            owner = app_settings.canonical_user(body.owner)
            if owner is None:
                raise ValueError("unknown user: the owner must be in the user list")
        work.set_owner(wp_id, owner, actor=who)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/delete")  # a többi törléshez hasonlóan JSON-törzses POST
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
        """058 K5.2: a levelek PDF-csatolmányai iratként a csomagba, a levélre mutatva."""
        mailbox.add_attachments(wp_id, expected_revision=body.expected_revision)
        return work_views.workpackage_view(wp_id)

    @app.post(r + "/workpackages/{wp_id}/items/{item_id}/remove")
    def remove_item(wp_id: WpId, item_id: ItemId, body: Revision, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.remove_item(wp_id, item_id, expected_revision=body.expected_revision)
        return work_views.workpackage_view(wp_id)

    def _item_file(wp_id: str, item_id: str) -> Path:
        """A csomag élő tételének forrásfájlja, csak ha a tartalma azonos a felvételkorival — más fájl ezen az úton
        nem olvasható ki. Az ujjlenyomat méret + módosítási idő szerint megjegyzett (058): oldalképenként nem hasheljük
        újra a teljes iratot."""
        item = next((i for i in work.get(wp_id)["items"] if i["item_id"] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        p = Path(item["source_path"])
        if not p.is_file() or work.fingerprint(p) != item["sha256"]:
            raise work.RevisionConflict("the source file changed or disappeared since it was added")
        return p

    @app.get(r + "/workpackages/{wp_id}/items/{item_id}/pages/{page}.png")
    def item_page(wp_id: WpId, item_id: ItemId, page: Annotated[int, PathParam(ge=1, le=500)],
                  dpi: Annotated[int, Query(ge=72, le=200)] = 144) -> Response:
        """Egy oldal képe (045 K3b) — a keretek erre kerülnek. A tartalom a hash-hez kötött, ezért gyorsítótárazható."""
        from jav import page_image

        png = page_image.render(_item_file(wp_id, item_id), page, dpi=dpi)
        return Response(png, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=86400, immutable", "X-Content-Type-Options": "nosniff"})

    @app.get(r + "/workpackages/{wp_id}/items/{item_id}/source")
    def item_source(wp_id: WpId, item_id: ItemId) -> FileResponse:
        """A tétel forrásirata (böngészőben megjelenítve vagy letöltve)."""
        p = _item_file(wp_id, item_id)
        return FileResponse(p, media_type="application/pdf" if p.suffix.lower() == ".pdf" else "application/octet-stream",
                            headers={"Content-Disposition": "inline", "Cache-Control": "no-store",
                                     "X-Content-Type-Options": "nosniff"})

    @app.get(r + "/workpackages/{wp_id}/reviews")
    def reviews(wp_id: WpId) -> dict[str, Any]:
        return work_views.workpackage_reviews(wp_id)

    # --- folyamat (recept) és készenlét ---

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

    # --- futtatás ---

    @app.get(r + "/runs")
    def all_runs(limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict[str, Any]:
        return {"runs": work_views.run_list(None, limit=limit)}

    @app.get(r + "/runs/{run_id}")
    def run(run_id: RunId) -> dict[str, Any]:
        return work_views.run_view(run_id)

    @app.get(r + "/runs/{run_id}/journal")
    def journal(run_id: RunId) -> dict[str, Any]:
        return work_views.run_journal(run_id)

    @app.post(r + "/runs/{run_id}/cancel")
    def cancel(run_id: RunId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.get_run(run_id)
        return {"run_id": run_id, "jobs": work.cancel_run(run_id, actor=who), "status": work.get_run(run_id)["status"]}

    @app.post(r + "/runs/{run_id}/approve")
    def approve(run_id: RunId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        work.approve_run(run_id, actor=who)
        return work_views.run_view(run_id)

    @app.get(r + "/runs/{run_id}/results")
    def results(run_id: RunId) -> dict[str, Any]:
        """A futás eredménye tételenként (gépi adat, javítás, összefésült érték) — a riportok alapja (K4)."""
        items = work.get_run(run_id)["input"]["items"]
        return work_views.jsonable({"run_id": run_id, "items": [corrections.item_result(run_id, i["item_id"]) for i in items]})

    @app.get(r + "/datasets")
    def dataset_catalog() -> dict[str, Any]:
        """056 U1: a lekérdezhető adatkészletek (lista és eredménytábla) nevei és hatókörei."""
        from jav import datasets

        return {"datasets": datasets.catalog()}

    @app.post(r + "/datasets/{name}/query")
    def dataset_query(name: DatasetName, body: DatasetQuery) -> dict[str, Any]:
        """056 U1: egy lap az adatkészletből; a szűrés, a rendezés és a lapozás itt, a szolgáltatásban fut."""
        from jav import datasets

        return datasets.query(name, body.scope, body.query)

    @app.post(r + "/datasets/{name}/export")
    def dataset_export(name: DatasetName, body: DatasetExport) -> Response:
        """056 U1: letöltés az adatkészletből (minden / szűrt / kijelölt sor, választott oszlopok)."""
        from jav import datasets

        data, media, fname, n = datasets.export_file(name, body.scope, body.query, body.rows, body.format, body.columns)
        return Response(data, media_type=media, headers={"Content-Disposition": attachment_header(fname),
                                                         "X-Export-Rows": str(n), "Cache-Control": "no-store",
                                                         "X-Content-Type-Options": "nosniff"})

    @app.get(r + "/runs/{run_id}/export")
    def run_export(run_id: RunId, format: Literal["csv", "xlsx", "json"] = "xlsx",  # noqa: A002 - a régi végpont paramétere
                   table: Literal["documents", "datapoints", "line_items"] = "documents") -> Response:
        """054 K4: a futás érvényes adata letöltésre (a régi V4 export-végpont mintájára: attachment + sorszám-fejléc)."""
        from jav import export

        work.get_run(run_id)  # ismeretlen futás: 404
        data, media, name, rows = export.render(run_id, format, table)
        return Response(data, media_type=media, headers={"Content-Disposition": attachment_header(name),
                                                         "X-Export-Rows": str(rows), "Cache-Control": "no-store",
                                                         "X-Content-Type-Options": "nosniff"})

    @app.get(r + "/runs/{run_id}/reports/utility-cost")
    def utility_cost(run_id: RunId) -> dict[str, Any]:
        """054 K4: közmű-költség idősor (fogyasztási hely + közmű, havi rács, forrásokkal)."""
        from jav import datasets, report_utility

        work.get_run(run_id)
        return work_views.jsonable({"run_id": run_id, **report_utility.build(datasets.run_records(run_id))})

    @app.get(r + "/runs/{run_id}/items/{item_id}")
    def item(run_id: RunId, item_id: ItemId) -> dict[str, Any]:
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    @app.get(r + "/runs/{run_id}/items/{item_id}/words")
    def item_words(run_id: RunId, item_id: ItemId) -> dict[str, Any]:
        """A tétel szórétege (045): oldalak és szavak 0–1 keretekkel — a képen való kijelöléshez."""
        corrections.item_result(run_id, item_id)  # ismeretlen futás/tétel → 404
        layer = corrections.layer_for(corrections.datapoints_row(run_id, item_id))
        if layer is None:
            raise KeyError(f"no source layer for {item_id[:12]}")
        return work_views.jsonable({"layer_id": layer.layer_id, "text_source": layer.text_source,
                                    "pages": [p.model_dump() for p in layer.pages],
                                    "words": [w.model_dump() for w in layer.words]})

    @app.post(r + "/runs/{run_id}/items/{item_id}/correction")
    def save_correction(run_id: RunId, item_id: ItemId, body: SaveCorrection,
                        who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        corrections.item_result(run_id, item_id)  # ismeretlen tétel → 404
        corrections.save(run_id, item_id, fields=dict(body.fields), expected_revision=body.expected_revision,
                         actor=who, note=body.note, sources=dict(body.sources) if body.sources else None)
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    @app.post(r + "/runs/{run_id}/items/{item_id}/tasks/{index}/decision")
    def task_decision(run_id: RunId, item_id: ItemId, index: Annotated[int, PathParam(ge=0, le=100)], body: TaskDecision,
                      who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """058 K5.3: a feladatjavaslatot csak ember fogadja el vagy veti el."""
        mailbox.decide_task(run_id, item_id, index, decision=body.decision, actor=who, note=body.note)
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    @app.post(r + "/runs/{run_id}/items/{item_id}/tasks/{index}/done")
    def task_done(run_id: RunId, item_id: ItemId, index: Annotated[int, PathParam(ge=0, le=100)], body: TaskDone,
                  who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """062: az elfogadott feladat kézzel elvégezve (vagy vissza)."""
        mailbox.mark_task_done(run_id, item_id, index, done=body.done, actor=who)
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    # --- teendők ---

    @app.post(r + "/review-reasons/{reason_id}/resolve")
    def resolve_reason(reason_id: Annotated[int, PathParam(ge=1)], body: ResolveReason,
                       who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        return work.resolve_reason(reason_id, actor=who, resolution=body.resolution, note=body.note)

    # --- feldolgozó ---

    @app.get(r + "/worker")
    def worker_status() -> dict[str, Any]:
        return work_views.worker_status()

    @app.post(r + "/worker/stop")
    def worker_stop(body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        log.info("worker stop requested by %s", who)  # 066 Á35: ki kérte (üzemi napló)
        worker.request_stop()
        return work_views.worker_status()

    # --- adattár-mentés (064): a legutóbbi mentés állapota és a mentés most ---

    @app.get(r + "/system/backup")
    def backup_status() -> dict[str, Any]:
        c = settings().get("backup", {})
        conf = {k: c.get(k) for k in ("schedule", "keep", "copy_to", "with_burr", "with_docs", "max_age_hours")}
        return work_views.jsonable({"status": backup.status(backup.default_root()), "config": conf})

    @app.post(r + "/system/backup")
    def backup_now(body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Mentés most, a napi mentés beállításával (helyben és a második helyre). A hiba az állapotban is látszik."""
        log.info("backup requested by %s", who)
        return work_views.jsonable(backup.scheduled())

    # --- beállítások (057): felhasználók, figyelt munkamappák ---

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
        """A teljes lista cseréje; minden útvonal az engedélyezett gyökerek alatt létező mappa kell legyen."""
        saved = app_settings.save_folders(body.folders, check_dir=lambda raw: checked_path(raw, want_dir=True))
        return work_views.jsonable({"folders": saved, "roots": [str(p) for p in allowed_roots()]})

    @app.post(r + "/settings/folders/{folder_id}/scan")
    def settings_scan_folder(folder_id: Annotated[str, PathParam(pattern=r"^wf-[0-9a-f]{10}$")], body: Empty,
                             who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Átnézés most (nem vár az ütemezésre)."""
        return work_views.jsonable(app_settings.scan(folder_id, actor=who))

    # --- postafiók (048 T2): előnézet, letöltés (a feldolgozó futtatja), ütemezés ---

    @app.get(r + "/mailbox")
    def mailbox_overview() -> dict[str, Any]:
        from jav.config import OUTLOOK_BRIDGE_SCRIPT

        return work_views.jsonable({"schedules": mailbox.schedules(), "pulls": mailbox.pulls(), "accounts": mailbox.known_accounts(),
                                    "bridge_available": OUTLOOK_BRIDGE_SCRIPT.is_file(),
                                    "defaults": {"interval_min": mailbox.DEFAULT_INTERVAL_MIN,
                                                 "lookback_days": mailbox.DEFAULT_LOOKBACK_DAYS}})

    @app.post(r + "/mailbox/count")
    def mailbox_count(body: mailbox.MailboxRequest) -> dict[str, Any]:
        """Ingyenes darabszám-előnézet (a régi szkript `-CountOnly` ága); az Outlooknak futnia kell."""
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

    @app.post(r + "/mailbox/schedules/{schedule_id}/delete")  # a többi törléshez hasonlóan JSON-törzses POST
    def mailbox_schedule_delete(schedule_id: ScheduleId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        mailbox.delete_schedule(schedule_id)
        return {"deleted": schedule_id}

    @app.api_route(r + "/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def unknown_api(rest: str):
        return _error(404, "not_found", "unknown endpoint")

    if UI_DIST.is_dir():  # a felület: ugyanazon a címen, így nincs külön szerver és nincs kereszt-eredetű hívás
        app.mount("/", _UiFiles(directory=UI_DIST, html=True), name="ui")

    # utoljára hozzáadva = legkülső réteg: a kérés még az útválasztás és az adattár előtt ellenőrződik
    app.add_middleware(_Guard, allowed_hosts=set(s["allowed_hosts"]) & LOOPBACK, max_body=int(s["max_body_bytes"]),
                       dev_origins=set(s.get("dev_origins", [])))
    return app


def serve(*, host: str | None = None, port: int | None = None) -> None:
    """A szolgáltatás indítása (uvicorn). Csak loopback címre köt; más címet elutasít."""
    import uvicorn

    s = settings()
    host = host or s["host"]
    if host not in LOOPBACK:
        raise ValueError(f"the local service binds only to a loopback address, not {host!r}")
    from jav.runtime import applog

    # 063: a szolgáltatás naplója állandó, forgó fájlba is kerül (runs/logs/api.log), az 500-as hibák hibanyomával
    uvicorn.run(create_app(), host=host, port=port or int(s["port"]), log_level="info", access_log=False,
                log_config=applog.uvicorn_config("api"))
