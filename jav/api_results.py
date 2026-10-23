"""The results' addresses of the local service (195, plan G-tidy R4; until then in `jav/api.py` `create_app`).

Plain-language summary: the addresses for what processing produced: a package's current result, its workbook, its
release and a released version's files; a run's results per item; the datasets behind every table (their list, one
page of a dataset, a download from it); a run's data for download and the copies of its documents under content-based
names. They moved here from `jav/api.py` as they were: the same paths, request models and answers, in the same order.
`jav.api.create_app` adds this module after the runs' one.

Layer: UI/CLI (the local service) → `jav.app.package_release`, `jav.app.datasets`, `jav.app.export`, `jav.app.naming`,
`jav.app.corrections`, `jav.app.work`.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI
from fastapi import Path as PathParam
from fastapi.responses import Response, StreamingResponse
from pydantic import Field

from jav.app import app_settings, corrections, package_release, work_runs, work_views
from jav.core import store
from jav.service_shared import Empty, In, RunId, WpId, attachment_header, human_actor
from jav.app.tablequery import Query as TableQuery
from jav.core.user_messages import explained

log = logging.getLogger("jav.api")


DatasetName = Annotated[str, PathParam(pattern=r"^[a-z_]{1,40}$")]


class ReleasePackage(In):
    """171 (plan 170 L1): `expected_mark` is the package result view's `mark` the person saw; if the result changed
    since, 409. `confirm_removed`: the view's `removed_items`, as for a run's approval."""
    expected_mark: str = Field(min_length=1, max_length=64)
    confirm_removed: int | None = Field(default=None, ge=0)


_ScopeMap = Annotated[dict[Annotated[str, Field(max_length=64)], Annotated[str, Field(max_length=200)]], Field(max_length=5)]


class DatasetQuery(In):
    """056 U1: uniform list request (scope + search, filters, sorting, paging)."""
    scope: _ScopeMap = Field(default_factory=dict)
    query: TableQuery = Field(default_factory=TableQuery)


class DatasetExport(DatasetQuery):
    format: Literal["csv", "xlsx", "json"] = "xlsx"
    rows: Literal["all", "filtered", "selected"] = "filtered"
    columns: Annotated[list[Annotated[str, Field(max_length=200)]], Field(max_length=500)] | None = None


def routes(app: FastAPI, r: str) -> None:
    """The results' addresses under the service's prefix `r`."""

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
            items = work_runs.get_run(run_id)["input"]["items"]
            return work_views.jsonable({"run_id": run_id, "items": [corrections.item_result(run_id, i["item_id"]) for i in items]})

    @app.get(r + "/datasets")
    def dataset_catalog() -> dict[str, Any]:
        """056 U1: names and scopes of the queryable datasets (lists and result tables)."""
        from jav.app import datasets

        return {"datasets": datasets.catalog()}

    @app.post(r + "/datasets/{name}/query")
    def dataset_query(name: DatasetName, body: DatasetQuery) -> dict[str, Any]:
        """056 U1: one page of the dataset; filtering, sorting and paging run here, in the service."""
        from jav.app import datasets

        return datasets.query(name, body.scope, body.query)

    @app.post(r + "/datasets/{name}/export")
    def dataset_export(name: DatasetName, body: DatasetExport) -> Response:
        """056 U1: download from the dataset (all / filtered / selected rows, chosen columns)."""
        from jav.app import datasets

        data, media, fname, n = datasets.export_file(name, body.scope, body.query, body.rows, body.format, body.columns)
        return Response(data, media_type=media, headers={"Content-Disposition": attachment_header(fname),
                                                         "X-Export-Rows": str(n), "Cache-Control": "no-store",
                                                         "X-Content-Type-Options": "nosniff"})

    @app.get(r + "/runs/{run_id}/export")
    def run_export(run_id: RunId, format: Literal["csv", "xlsx", "json"] = "xlsx",  # noqa: A002 - legacy endpoint parameter
                   table: Literal["documents", "datapoints", "line_items", "native_facts"] = "documents") -> Response:
        """054 K4: the run's valid data for download (modelled on the legacy V4 export endpoint: attachment + row-count
        header)."""
        from jav.app import export

        work_runs.get_run(run_id)  # unknown run: 404
        data, media, name, rows = export.render(run_id, format, table)
        return Response(data, media_type=media, headers={"Content-Disposition": attachment_header(name),
                                                         "X-Export-Rows": str(rows), "Cache-Control": "no-store",
                                                         "X-Content-Type-Options": "nosniff"})

    @app.get(r + "/runs/{run_id}/named-copies.zip")
    def named_copies_zip(run_id: RunId) -> StreamingResponse:
        """078: copies of the run's documents under content-based names, with the manifest (`jav/app/naming.py`); the
        originals are only read. Built into a temporary file first (large packages do not sit in memory)."""
        from jav.app import naming

        work_runs.get_run(run_id)  # unknown run: 404
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
        from jav.app import naming

        work_runs.get_run(run_id)
        folder = app_settings.output_folder()
        if not folder:
            raise explained(app_settings.NoOutputFolder, "no output folder is set (Settings > Work folders)")
        res = naming.write_to_folder(run_id, Path(folder))
        log.info("named copies of %s written by %s", run_id, who)
        return res
