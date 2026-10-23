"""The statement package's addresses of the local service (176, plan 170 L3: each logic pack its own).

Plain-language summary: the addresses the interface uses to survey a folder's bank statements for a party and a
period, to create a statement package of the ticked ones, and to survey and add more to an existing one. They moved
here from `jav/service/api.py` as they were: the same paths, request models and answers. `jav.service.api.create_app` adds them
(185: by its logic pack's `service`, `jav.service.api.service_modules`).

Layer: UI/CLI (the local service) → `jav.domains.finance.statement_package`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI
from pydantic import Field

from jav.app import work_views
from jav.domains.finance import statement_package
from jav.service.service_shared import In, IsoDay, PartyId, WpId, checked_path, human_actor

class StatementPackageSources(In):
    """140: a statement package's party, period and files (one folder, or files: exports and PDFs)."""
    paths: Annotated[list[Annotated[str, Field(min_length=1, max_length=1024)]], Field(min_length=1, max_length=500)]
    party_id: PartyId
    period_start: IsoDay
    period_end: IsoDay


class CreateStatementPackage(StatementPackageSources):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    statements: Annotated[list[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]], Field(max_length=2000)] = Field(default_factory=list)
    pdfs: Annotated[list[Annotated[str, Field(min_length=1, max_length=1024)]], Field(max_length=500)] = Field(default_factory=list)


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

    @app.post(r + "/statement-packages/survey")
    def statement_package_survey(body: StatementPackageSources, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """140: what a folder or the given files hold for a party and a period, before anything is written: every
        statement with its account's last four characters, month, checks, what it would replace and whose account it
        is; the PDFs no export uses. No line, partner or balance leaves."""
        paths = [checked_path(p, want_dir=None) for p in body.paths]
        return work_views.jsonable(statement_package.survey(paths, party_id=body.party_id, period_start=body.period_start,
                                                            period_end=body.period_end))

    @app.post(r + "/statement-packages", status_code=201)
    def create_statement_package(body: CreateStatementPackage, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """140: a new statement package of the statements and PDFs ticked in the survey; the creator is its owner."""
        sc = statement_package.create(name=body.name, party_id=body.party_id, period_start=body.period_start,
                                      period_end=body.period_end, paths=[checked_path(p, want_dir=None) for p in body.paths],
                                      statements=body.statements, pdfs=[str(checked_path(p, want_dir=False)) for p in body.pdfs],
                                      actor=who)
        return work_views.workpackage_view(sc["workpackage_id"])

    @app.post(r + "/workpackages/{wp_id}/statements/survey")
    def package_statement_survey(wp_id: WpId, body: PackageStatementFiles, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """160-C S2: the survey of more files for an existing statement package, with its party and period; what the
        package already holds is marked (`in_package`). Nothing is written."""
        paths = [checked_path(p, want_dir=None) for p in body.paths]
        return work_views.jsonable(statement_package.survey_for(wp_id, paths, recursive=body.recursive))

    @app.post(r + "/workpackages/{wp_id}/statements/add")
    def add_package_statements(wp_id: WpId, body: AddPackageStatements, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """160-C S2: the statements and PDFs ticked in the package's own survey, added to it and logged."""
        statement_package.add(wp_id, paths=[checked_path(p, want_dir=None) for p in body.paths], statements=body.statements,
                              pdfs=[str(checked_path(p, want_dir=False)) for p in body.pdfs], expected_revision=body.expected_revision,
                              actor=who, recursive=body.recursive)
        return work_views.workpackage_view(wp_id)


__all__ = ["routes"]
