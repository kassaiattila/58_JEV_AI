"""The settings' addresses of the local service (195, plan G-tidy R4; 057: until then in `jav/service/api.py` `create_app`).

Plain-language summary: the addresses of the settings pages: the user list, the watched work folders (and scanning one
now), the output folder of the named copies, and the application's AI engine. A folder is checked like any typed
path. They moved here from `jav/service/api.py` as they were: the same paths, request models and answers, in the same order.
`jav.service.api.create_app` adds this module last, before the unknown address's answer.

Layer: UI/CLI (the local service) → `jav.app.app_settings`.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI
from fastapi import Path as PathParam
from pydantic import Field

from jav.core import identity
from jav.app import app_settings, work_views
from jav.service.service_shared import Empty, In, actor_unless_first_users, allowed_roots, checked_path, human_actor

log = logging.getLogger("jav.service.api")


class SaveUsers(In):
    users: Annotated[list[Annotated[str, Field(max_length=64)]], Field(max_length=200)]


class SaveFolders(In):
    folders: Annotated[list[app_settings.WatchedFolder], Field(max_length=50)]


class SaveOutputFolder(In):
    path: str | None = Field(default=None, max_length=1024)  # empty: no output folder


class SaveEngine(In):
    engine: Literal["jev", "gpt"]  # 160-D: JEV and GPT | GPT only (app_settings.ENGINES)


def routes(app: FastAPI, r: str) -> None:
    """The settings' addresses under the service's prefix `r`."""

    # --- settings (057): users, watched work folders ---

    @app.get(r + "/settings/users")
    def settings_users() -> dict[str, Any]:
        return {"users": app_settings.users()}

    @app.put(r + "/settings/users")
    def settings_save_users(body: SaveUsers, who: Annotated[identity.Actor | None, Depends(actor_unless_first_users)]) -> dict[str, Any]:
        saved = app_settings.save_users(body.users)
        log.info("user list saved by %s: %d names", who.name if who else "(first setup)", len(saved))  # 066 Á35
        return {"users": saved}

    @app.get(r + "/settings/folders")
    def settings_folders() -> dict[str, Any]:
        return work_views.jsonable({"folders": app_settings.folders(), "roots": [str(p) for p in allowed_roots()]})

    @app.put(r + "/settings/folders")
    def settings_save_folders(body: SaveFolders, _who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        """Replaces the whole list; every path must be an existing folder (under the allowed roots when restricted)."""
        saved = app_settings.save_folders(body.folders, check_dir=lambda raw: checked_path(raw, want_dir=True))
        return work_views.jsonable({"folders": saved, "roots": [str(p) for p in allowed_roots()]})

    @app.get(r + "/settings/output-folder")
    def settings_output_folder() -> dict[str, Any]:
        """078: where the content-named copies of a run are written."""
        return {"path": app_settings.output_folder()}

    @app.put(r + "/settings/output-folder")
    def settings_save_output_folder(body: SaveOutputFolder, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        """An existing folder that does not overlap a watched folder (the watcher would take the copies in again)."""
        return {"path": app_settings.save_output_folder(body.path, check_dir=lambda raw: checked_path(raw, want_dir=True), actor=who)}

    @app.get(r + "/settings/engine")
    def settings_engine() -> dict[str, Any]:
        """160-D: the application's AI engine, the default of every new processing setting that does not name one."""
        return app_settings.engine_setting()

    @app.put(r + "/settings/engine")
    def settings_save_engine(body: SaveEngine, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        """Saved settings and started runs keep their own engine; only new settings follow."""
        return app_settings.save_engine_default(body.engine, actor=who)

    @app.post(r + "/settings/folders/{folder_id}/scan")
    def settings_scan_folder(folder_id: Annotated[str, PathParam(pattern=r"^wf-[0-9a-f]{10}$")], body: Empty,
                             who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        """Scan now (without waiting for the schedule)."""
        return work_views.jsonable(app_settings.scan(folder_id, actor=who))
