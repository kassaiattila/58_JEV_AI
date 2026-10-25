"""The statement package's addresses of the local service (176, plan 170 L3: each logic pack its own).

Plain-language summary: the addresses the interface uses to survey more bank statements for an existing statement
package and to add the ticked ones. They moved here from `jav/service/api.py` as they were: the same paths, request
models and answers. `jav.service.api.create_app` adds them (231 C3b5a: as the finance domain's, `SERVICE`; its logic
pack's until then). The survey of a new package and its creation went with the package's own form (231 C3b5a): a
statement package is a bank statements case's, started from the new work wizard's general form.

Layer: UI/CLI (the local service) → `jav.domains.finance.statement_package`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI
from pydantic import Field

from jav.core import identity
from jav.app import work_views
from jav.domains.finance import statement_package
from jav.service.service_shared import In, WpId, checked_path, human_actor

class PackageStatementFiles(In):
    """160-C S2: more files for an existing statement package (its party and period are the package's own); 168: with
    `recursive`, a folder's subfolders too."""
    paths: Annotated[list[Annotated[str, Field(min_length=1, max_length=1024)]], Field(min_length=1, max_length=500)]
    recursive: bool = False


class AddPackageStatements(PackageStatementFiles):
    statements: Annotated[list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]], Field(max_length=2000)] = Field(default_factory=list)
    pdfs: Annotated[list[Annotated[str, Field(min_length=1, max_length=1024)]], Field(max_length=500)] = Field(default_factory=list)
    expected_revision: Annotated[int, Field(ge=0)]


def routes(app: FastAPI, r: str) -> None:
    """The statement package's addresses under the service's prefix `r`."""

    @app.post(r + "/workpackages/{wp_id}/statements/survey")
    def package_statement_survey(wp_id: WpId, body: PackageStatementFiles, _who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        """160-C S2: the survey of more files for an existing statement package, with its party and period; what the
        package already holds is marked (`in_package`). Nothing is written."""
        paths = [checked_path(p, want_dir=None) for p in body.paths]
        return work_views.jsonable(statement_package.survey_for(wp_id, paths, recursive=body.recursive))

    @app.post(r + "/workpackages/{wp_id}/statements/add")
    def add_package_statements(wp_id: WpId, body: AddPackageStatements, who: Annotated[identity.Actor, Depends(human_actor)]) -> dict[str, Any]:
        """160-C S2: the statements and PDFs ticked in the package's own survey, added to it and logged."""
        statement_package.add(wp_id, paths=[checked_path(p, want_dir=None) for p in body.paths], statements=body.statements,
                              pdfs=[str(checked_path(p, want_dir=False)) for p in body.pdfs], expected_revision=body.expected_revision,
                              actor=who, recursive=body.recursive)
        return work_views.workpackage_view(wp_id)


__all__ = ["routes"]
