"""The finance domain's addresses of the local service beyond its logic packs' (185, plan G-full-move T1a).

Plain-language summary: the addresses for what the finance domain adds to a work package that processes its items:
- the bank files the system reads, and how (146);
- a bank's tabular export: its accounts surveyed, a new package of the chosen ones, or more of them added to a package
  (136);
- the utility cost of a run or of a package's current result (054, 172);
- a person's decision on a duplicate pair (126) and the choice between two statements of the same days (139).
They moved here from `jav/api.py` as they were: the same paths, request models and answers. The finance domain names
this module (`jav/domains/finance/__init__.py` `SERVICE`), and `jav.api.create_app` adds it. The reconciliation's and the
statement package's own addresses are their logic packs' (`jav/domains/finance/api_reconcile.py`, `jav/domains/finance/api_statement_package.py`).

Layer: UI/CLI (the local service) → `jav.domains.finance.bank_files`, `jav.domains.finance.statement_table`, `jav.domains.finance.statement_package`,
`jav.domains.finance.report_utility`, `jav.domains.finance.duplicates`, `jav.domains.finance.statement_months`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI
from pydantic import Field

from jav.app import corrections, datasets, work, work_runs, work_views
from jav.domains.finance import bank_files, duplicates, report_utility, statement_months, statement_package
from jav.service_shared import DecisionState, In, ItemId, RunId, Text, WpId, checked_path, human_actor


class StatementTableFile(In):
    """136: a bank's tabular statement export (a workbook or a CSV file)."""
    path: Annotated[str, Field(min_length=1, max_length=1024)]


class StatementTableAccounts(StatementTableFile):
    keys: Annotated[list[Annotated[str, Field(min_length=1, max_length=300)]], Field(min_length=1, max_length=100)]


class AddStatementTables(StatementTableAccounts):
    expected_revision: Annotated[int, Field(ge=0)]


class CreateFromStatementTable(StatementTableAccounts):
    name: Annotated[str, Field(min_length=1, max_length=200)]


class DuplicateDecision(In):
    decision: Literal[duplicates.DECISIONS]  # type: ignore[valid-type]  # 126: copy, modified version, not the same invoice
    note: Text | None = None
    expected_state: DecisionState | None = None  # 187: the pair's `decision_state` as the page read it


class StatementChoice(In):
    keep: Literal["this", "other", "rule"]  # 139: which of two statements of the same days stays valid; rule: as ranked
    note: Text | None = None
    expected_state: DecisionState | None = None


def routes(app: FastAPI, r: str) -> None:
    """The finance domain's addresses under the service's prefix `r`."""

    @app.get(r + "/bank-files")
    def bank_files_catalogue() -> dict[str, Any]:
        # 146: which bank files the system reads, and how (configs/bank_files.json with the readers' own configuration)
        return {**bank_files.catalogue(), "labels": bank_files.labels()}

    @app.post(r + "/statement-tables/survey")
    def statement_table_survey(body: StatementTableFile, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """136 (E4): the accounts of a bank's tabular export with their line counts, dates and checks, for a person to
        choose from; no lines or balances, nothing is stored. 137: or of every export in a folder (the Erste XML files
        with their PDF statements), one statement per account and month."""
        from jav.domains.finance import statement_table

        return statement_table.survey(statement_table.read(checked_path(body.path, want_dir=None)))

    @app.post(r + "/statement-tables/workpackage", status_code=201)
    def create_from_statement_table(body: CreateFromStatementTable, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """136 (E4): a new package of the chosen accounts of the export; the creator is its owner (065)."""
        wp = statement_package.create_from_statement_table(checked_path(body.path, want_dir=None), body.keys, name=body.name,
                                                           owner=who)
        return work_views.workpackage_view(wp["id"])

    @app.post(r + "/workpackages/{wp_id}/statement-tables")
    def add_statement_tables(wp_id: WpId, body: AddStatementTables, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """136 (E4, DECISIONS 136): the chosen accounts of the export as the package's items, one statement each."""
        statement_package.add_statement_tables(wp_id, checked_path(body.path, want_dir=None), body.keys,
                                               expected_revision=body.expected_revision)
        return work_views.workpackage_view(wp_id)

    @app.get(r + "/workpackages/{wp_id}/result/utility-cost")
    def package_utility_cost(wp_id: WpId) -> dict[str, Any]:
        """172: the utility-cost time series of the package's current result (as the run's report, 054 K4)."""
        work.get(wp_id)
        return work_views.jsonable({"workpackage_id": wp_id,
                                    **report_utility.build(datasets.result_records({"workpackage_id": wp_id}))})

    @app.get(r + "/runs/{run_id}/reports/utility-cost")
    def utility_cost(run_id: RunId) -> dict[str, Any]:
        """054 K4: utility-cost time series (consumption point + utility, monthly grid, with sources)."""
        work_runs.get_run(run_id)
        return work_views.jsonable({"run_id": run_id, **report_utility.build(datasets.run_records(run_id))})

    @app.post(r + "/runs/{run_id}/items/{item_id}/duplicates/{other_doc_id}/decision")
    def duplicate_decision(run_id: RunId, item_id: ItemId, other_doc_id: ItemId, body: DuplicateDecision,
                           who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """126: only a human decides whether two documents are the same invoice; the pair's to-dos close."""
        duplicates.decide(run_id, item_id, other_doc_id, decision=body.decision, actor=who, note=body.note,
                          expected_state=body.expected_state)
        return work_views.jsonable(corrections.item_result(run_id, item_id))

    @app.post(r + "/runs/{run_id}/items/{item_id}/statements/{other_doc_id}/choice")
    def statement_choice(run_id: RunId, item_id: ItemId, other_doc_id: ItemId, body: StatementChoice,
                         who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """139: a person chooses which of two statements of the same days stays valid; the pair's to-dos close."""
        keep = {"this": item_id, "other": other_doc_id, "rule": None}[body.keep]
        statement_months.decide(run_id, item_id, other_doc_id, keep=keep, actor=who, note=body.note,
                                expected_state=body.expected_state)
        return work_views.jsonable(corrections.item_result(run_id, item_id))


__all__ = ["routes"]
