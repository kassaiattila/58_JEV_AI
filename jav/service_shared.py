"""The local service's shared request handling (204, plan G-process-core R1g): what every module of addresses uses.

Plain-language summary: the local service is put together from one gateway module (`jav/api.py`) and modules of
addresses by theme (`jav/api_*.py`). They all check a request the same way: the same rules for an id in the address,
for a request body (an unknown field is refused), for the person named in the `X-Actor` header and for a folder or file
given by path, and they answer an error in the same JSON shape. Those rules live here, so the modules of addresses no
longer import the gateway that loads them, and nothing here imports a module of addresses.

They moved here from `jav/api.py` as they were; the names other modules use lost their leading underscore (`_In` is
`In`, `_error` is `error`). The service's settings (`configs/service.json`) are read here too, because the folder
restriction depends on them.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, unquote

from fastapi import Header, HTTPException
from fastapi import Path as PathParam
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jav.app import app_settings
from jav.core import cfg
from jav.core.config import OLD_DATA_ROOT, PROJECT_ROOT
from jav.core.user_messages import explained


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


class JavJSONResponse(JSONResponse):
    """The same JSON shape as the command line (`work_views.jsonable`): money as `Decimal` text, not floating point."""

    def render(self, content: Any) -> bytes:
        return json.dumps(content, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")


def error(status: int, code: str, message: str, **extra: Any) -> JavJSONResponse:
    return JavJSONResponse({"error": code, "message": message, **extra}, status_code=status)


# --- input schemas --------------------------------------------------------------------------------------

WpId = Annotated[str, PathParam(pattern=r"^wp-[0-9a-f]{12}$")]
RunId = Annotated[str, PathParam(pattern=r"^run-[0-9a-f]{12}$")]
ItemId = Annotated[str, PathParam(pattern=r"^[0-9a-f]{64}$")]
Text = Annotated[str, Field(max_length=2000)]
# 187: a decision's state as its page read it (`jav/core/decisions.py`); a change on a stale page is a 409
DecisionState = Annotated[int, Field(ge=0)]


# every request body: an unknown field is refused
class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Revision(In):
    expected_revision: Annotated[int, Field(ge=0)]


class Empty(In):
    pass


IsoDay = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]


PartyId = Annotated[str, Field(pattern=r"^party-[0-9a-f]{12}$")]  # 133: an own party (`jav/app/parties.py`)


# --- actor and download header --------------------------------------------------------------------------

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
