"""The work packages' addresses of the local service (195, plan G-tidy R4; until then in `jav/api.py` `create_app`).

Plain-language summary: the addresses the package pages use for the packages themselves and their documents: the
recipes, the package list, creating a package from a folder or from files, the system's folder and file pickers, one
package's view, hiding, restoring, renaming and deleting it, its scope and owner, adding documents (with a preview first)
and removing or restoring them, a document's page images and source file, and the package's to-dos. They moved here
from `jav/api.py` as they were: the same paths, request models and answers, in the same order. `jav.api.create_app`
adds this module first among the shared ones.

Layer: UI/CLI (the local service) → `jav.work`, `jav.work_views`, `jav.package_scope`, `jav.local_picker`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query
from fastapi import Path as PathParam
from fastapi.responses import Response
from pydantic import Field

from jav import app_settings, local_picker, package_scope, work, work_views
from jav.api import Empty, IsoDay, ItemId, PartyId, Revision, WpId, _In, checked_path, human_actor
from jav.user_messages import explained


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


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


class RemoveItem(Revision):
    """160-C S1 (decision 163 D2): the reason is required; the person is the request's actor."""
    reason: Annotated[str, Field(min_length=1, max_length=500)]


class ItemIds(Revision):
    """168: several of the package's items at once."""
    item_ids: Annotated[list[Digest], Field(min_length=1, max_length=2000)]


class RemoveItems(ItemIds):
    reason: Annotated[str, Field(min_length=1, max_length=500)]


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


def _max_source_bytes() -> int:
    """075: a source larger than the input limit is never read into memory (it could not have been added anyway)."""
    return work.max_source_bytes()


def routes(app: FastAPI, r: str) -> None:
    """The work packages' addresses under the service's prefix `r`."""

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
