"""The reconciliation package's addresses of the local service (176, plan 170 L3: each logic pack its own).

Plain-language summary: the addresses the interface uses to build a reconciliation package, pair its lines with
invoices, mark and revoke, and approve, reopen and download its statement. They moved here from `jav/api.py` as they
were: the same paths, request models and answers. `jav.api.create_app` adds them (185: by its logic pack's
`service`, `jav.api.service_modules`).

Layer: UI/CLI (the local service) → `jav.reconcile_package`, `jav.reconcile_review`, `jav.reconcile_statement`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import Response
from pydantic import Field

from jav import reconcile_package, reconcile_review, reconcile_statement, work_views
from jav.api import Empty, IsoDay, PartyId, Text, WpId, _error, _In, attachment_header, human_actor
from jav.user_messages import message_fields

# 131 (F-reconciliation E1): the reconciliation package (`jav/reconcile_package.py`)
DocId = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
LINE_ID = r"^[0-9A-Za-z_-]{1,16}:[0-9a-f]{12}:\d{1,5}$"
LineId = Annotated[str, Field(pattern=LINE_ID)]  # the statement line's stable id
Money = Annotated[str, Field(pattern=r"^\d{1,12}(\.\d{1,2})?$")]  # a canonical amount, never a guessed separator


class ReconcileScope(_In):
    accounts: Annotated[list[Annotated[str, Field(min_length=1, max_length=80)]], Field(min_length=1, max_length=50)]
    period_start: IsoDay
    period_end: IsoDay
    party_id: PartyId | None = None  # 133: the package's own party; None: every invoice is its own


class CreateReconcilePackage(ReconcileScope):
    name: Annotated[str, Field(min_length=1, max_length=200)]


class SetReconcileScope(ReconcileScope):
    expected_revision: Annotated[int, Field(ge=1)]


class AllocationPair(_In):
    invoice_doc_id: DocId
    line_id: LineId
    line_amount: Money | None = None  # None: what both sides have left (one currency) or both whole (two currencies)
    invoice_amount: Money | None = None


class ReconcileAllocate(_In):
    pairs: Annotated[list[AllocationPair], Field(min_length=1, max_length=200)]
    note: Text | None = None  # required for a split or a converted pair outside the card band


class ReconcileReject(_In):
    invoice_doc_id: DocId
    line_id: LineId
    note: Annotated[str, Field(min_length=1, max_length=2000)]


class ReconcileMark(_In):
    line_ids: Annotated[list[LineId], Field(min_length=1, max_length=5000)]  # 132: several lines in one step
    category: Annotated[str, Field(min_length=1, max_length=40)]  # configs/reconcile.json line_marks
    note: Text | None = None


class QuickReviewAccept(_In):
    """147: a person accepts a quick review group's suggestion for these of its lines."""
    group: Annotated[str, Field(pattern=r"^[a-z_]{1,40}$")]
    line_ids: Annotated[list[LineId], Field(min_length=1, max_length=5000)]


class ReconcileUnmark(_In):
    line_ids: Annotated[list[LineId], Field(min_length=1, max_length=5000)]  # 135: a partner's lines undone in one step


class ReconcileRevoke(_In):
    kind: Literal["allocation", "mark", "decision"]
    ref: Annotated[str, Field(min_length=1, max_length=200)]  # an allocation's or a mark's id, or a decision's pair key
    note: Text | None = None


# 145 (F-reconciliation E3b): the result (`jav/reconcile_statement.py`)
class ReconcileApprove(_In):
    fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]  # the statement the person saw


class ReconcileReopen(_In):
    note: Annotated[str, Field(min_length=1, max_length=2000)]


class ReconcileAcceptSources(_In):
    doc_ids: Annotated[list[DocId], Field(min_length=1, max_length=5000)]


# 169 (DECISIONS 169): documents left out of a reconciliation package with a reason, and restored
class ReconcileRestoreLeftOut(_In):
    doc_ids: Annotated[list[DocId], Field(min_length=1, max_length=5000)]


class ReconcileLeaveOut(ReconcileRestoreLeftOut):
    reason: Annotated[str, Field(min_length=1, max_length=500)]


def routes(app: FastAPI, r: str) -> None:
    """The reconciliation package's addresses under the service's prefix `r`, and the answer to a locked line."""

    @app.exception_handler(reconcile_package.Locked)
    async def reconcile_locked(_request: Request, exc: reconcile_package.Locked):
        return _error(422, "reconcile_locked", str(exc), **message_fields(exc))  # 145: the UI names it in the display language

    # --- 131: the reconciliation package (jav/reconcile_package.py): a scope, two lists, decisions per pair ---

    @app.get(r + "/reconcile/accounts")
    def reconcile_accounts() -> dict[str, Any]:
        return work_views.jsonable({"accounts": reconcile_package.accounts()})

    @app.post(r + "/reconcile/packages", status_code=201)
    def create_reconcile_package(body: CreateReconcilePackage, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        sc = reconcile_package.create(name=body.name, accounts=body.accounts, period_start=body.period_start,
                                      period_end=body.period_end, actor=who, party_id=body.party_id)
        return work_views.workpackage_view(sc["workpackage_id"])

    @app.get(r + "/workpackages/{wp_id}/reconcile")
    def reconcile_workspace(wp_id: WpId) -> dict[str, Any]:
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/scope")
    def reconcile_scope(wp_id: WpId, body: SetReconcileScope, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        reconcile_package.set_scope(wp_id, accounts=body.accounts, period_start=body.period_start, period_end=body.period_end,
                                    expected_revision=body.expected_revision, actor=who, party_id=body.party_id)
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/refresh")
    def reconcile_refresh(wp_id: WpId, body: Empty, _who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Recomputes with the missing MNB rates fetched (only dates and currency codes leave the machine)."""
        reconcile_package.refresh(wp_id)
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/allocate")
    def reconcile_allocate(wp_id: WpId, body: ReconcileAllocate, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        reconcile_package.allocate(wp_id, [p.model_dump() for p in body.pairs], note=body.note, actor=who)
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/accept-proposed")
    def reconcile_accept_proposed(wp_id: WpId, body: Empty, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """Every unambiguous proposal at once (proposed, the only candidate, a statement whose balances check out)."""
        reconcile_package.accept_proposed(wp_id, actor=who)
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/reject")
    def reconcile_reject(wp_id: WpId, body: ReconcileReject, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        reconcile_package.reject(wp_id, body.invoice_doc_id, body.line_id, note=body.note, actor=who)
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/mark")
    def reconcile_mark(wp_id: WpId, body: ReconcileMark, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        reconcile_package.mark(wp_id, body.line_ids, category=body.category, note=body.note, actor=who)
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    @app.get(r + "/workpackages/{wp_id}/reconcile/quick-review")
    def reconcile_quick_review(wp_id: WpId) -> dict[str, Any]:
        """147: the lines to decide in groups by what is known of them (jav/reconcile_review.py)."""
        return work_views.jsonable(reconcile_review.review(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/quick-review/accept")
    def reconcile_quick_review_accept(wp_id: WpId, body: QuickReviewAccept,
                                      who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """147: a group's suggestion accepted for the given lines (only those still in the group, all or none); the
        review and the workspace after it."""
        n = reconcile_review.accept(wp_id, body.group, body.line_ids, actor=who)
        return {"accepted": n, "review": work_views.jsonable(reconcile_review.review(wp_id)),
                "workspace": work_views.jsonable(reconcile_package.kept_workspace(wp_id))}

    @app.post(r + "/workpackages/{wp_id}/reconcile/unmark")
    def reconcile_unmark(wp_id: WpId, body: ReconcileUnmark, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """135: the needs-no-invoice marks of several lines undone in one step."""
        reconcile_package.unmark(wp_id, body.line_ids, actor=who)
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    @app.get(r + "/workpackages/{wp_id}/reconcile/locate")
    def reconcile_locate(wp_id: WpId, line_id: Annotated[str, Query(pattern=LINE_ID)]) -> dict[str, Any]:
        """132: where a line stands on its statement page (found in the word layer by its amount and date); 144: with the
        statement as read and, for a statement read by code, whether the bank's PDF behind it was found."""
        return work_views.jsonable(reconcile_package.locate(wp_id, line_id))

    @app.get(r + "/workpackages/{wp_id}/reconcile/original/pages/{page}.png")
    def reconcile_original_page(wp_id: WpId, page: Annotated[int, PathParam(ge=1, le=500)],
                                line_id: Annotated[str, Query(pattern=LINE_ID)],
                                dpi: Annotated[int, Query(ge=72, le=200)] = 144) -> Response:
        """144: a page of the bank's PDF behind a statement read by code (the line says which; its verified bytes, 075)."""
        return Response(reconcile_package.original_page(wp_id, line_id, page, dpi=dpi), media_type="image/png")

    @app.get(r + "/workpackages/{wp_id}/reconcile/matches")
    def reconcile_matches(wp_id: WpId, line_id: Annotated[str, Query(pattern=LINE_ID)]) -> dict[str, Any]:
        """143: every invoice of the page compared with one line, the fitting ones first (the two lists' finder)."""
        return work_views.jsonable(reconcile_package.matches(wp_id, line_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/revoke")
    def reconcile_revoke(wp_id: WpId, body: ReconcileRevoke, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        reconcile_package.revoke(wp_id, kind=body.kind, ref=body.ref, actor=who, note=body.note)
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    # --- 145: the result - the statement, its approval as a version that locks its lines, its download ---

    @app.get(r + "/workpackages/{wp_id}/reconcile/statement")
    def reconcile_statement_view(wp_id: WpId, version: Annotated[int | None, Query(ge=1, le=100000)] = None) -> dict[str, Any]:
        """The statement as it stands now (with its fingerprint, blockers, warnings and the approval), or an approved
        version as it was approved."""
        if version is not None:
            return work_views.jsonable(reconcile_statement.approved_version(wp_id, version))
        return work_views.jsonable(reconcile_statement.current(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/accept-sources")
    def reconcile_accept_sources(wp_id: WpId, body: ReconcileAcceptSources,
                                 who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """DECISIONS 132: a person accepts command-line results as sources (who and when is recorded)."""
        reconcile_statement.accept_sources(wp_id, body.doc_ids, actor=who)
        return work_views.jsonable(reconcile_statement.current(wp_id))

    @app.get(r + "/workpackages/{wp_id}/reconcile/targets")
    def reconcile_targets(wp_id: WpId) -> dict[str, Any]:
        """169: the documents and statement packages files for this reconciliation can be added to (and processed in)."""
        return work_views.jsonable(reconcile_package.targets(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/leave-out")
    def reconcile_leave_out(wp_id: WpId, body: ReconcileLeaveOut, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        """169: statements or invoices left out of this package only, with a reason (they stay in their own packages)."""
        reconcile_package.leave_out(wp_id, body.doc_ids, reason=body.reason, actor=who)
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/restore-left-out")
    def reconcile_restore_left_out(wp_id: WpId, body: ReconcileRestoreLeftOut,
                                   who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        reconcile_package.restore_left_out(wp_id, body.doc_ids, actor=who)
        return work_views.jsonable(reconcile_package.kept_workspace(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/approve")
    def reconcile_approve(wp_id: WpId, body: ReconcileApprove, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        reconcile_statement.approve(wp_id, fingerprint=body.fingerprint, actor=who)
        return work_views.jsonable(reconcile_statement.current(wp_id))

    @app.post(r + "/workpackages/{wp_id}/reconcile/reopen")
    def reconcile_reopen(wp_id: WpId, body: ReconcileReopen, who: Annotated[str, Depends(human_actor)]) -> dict[str, Any]:
        reconcile_statement.reopen(wp_id, note=body.note, actor=who)
        return work_views.jsonable(reconcile_statement.current(wp_id))

    @app.get(r + "/workpackages/{wp_id}/reconcile/statement.xlsx")
    def reconcile_statement_xlsx(wp_id: WpId, version: Annotated[int | None, Query(ge=1, le=100000)] = None) -> Response:
        """DECISIONS 145: the statement as an Excel workbook (invoices and lines): the draft, or an approved version."""
        data, name = reconcile_statement.xlsx(wp_id, version=version)
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": attachment_header(name), "Cache-Control": "no-store",
                                 "X-Content-Type-Options": "nosniff"})


__all__ = ["routes"]
