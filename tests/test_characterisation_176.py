"""Characterisation before the logic pack registry (176, plan 170 L3): what the move must keep as it is.

Plain-language summary: the reconciliation package and the statement package are about to be described in one
registry instead of being named in the shared code. Before that, these tests record what a person and the interface
see today: every address of the local service and that each one is reached (none is hidden behind another), the parts
of a package's page and of its list row for each kind of package, and the fingerprint a reconciliation's approval
records. The move may change none of them.

Synthetic documents and made-up accounts only; no AI call, no network.
"""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Match

from jav.service import api
from jav.app import datasets, work, work_views
from jav.core import store
from jav.domains.finance import reconcile_statement as rs
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_package_131 import _line, _package as _reconcile_package, _stmt
from tests.test_statement_package_140 import _package as _statement_package, _party
from tests.statement_pdf import pdf_lines_as_text


@pytest.fixture(autouse=True)
def pdf_text(monkeypatch):
    """The synthetic 'PDF' statements hold their lines as plain text (as in `tests/test_statement_package_140.py`)."""
    pdf_lines_as_text(monkeypatch)


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "c.sqlite"):
        yield tmp_path


def _routes() -> list[APIRoute]:
    app = api.create_app(store_path=Path(tempfile.mkdtemp()) / "routes.sqlite")
    return [r for r in app.routes if isinstance(r, APIRoute)]


# --- the addresses of the local service ---------------------------------------------------------------------------------

ROUTE_COUNT = 211  # (method, path) pairs of 176 routes: the unknown-address answer has five methods
# 178 (plan 170 L4): nine new addresses on purpose - the own output templates (list, upload, activate, retire, file,
# preview), a package's choice of them (read, choose) and the utility cost's workbook (jav/service/api_outputs.py)
# 181 (plan 170 L5): three more on purpose - the package roles, and a package's scope given and taken away
# (`GET /api/package-roles`, `POST /api/workpackages/{wp_id}/scope`, `POST /api/workpackages/{wp_id}/scope/clear`), and
# the email routing's five in its own module (`jav/domains/email/api_email_routing.py`: a routing package; accept, every clear one,
# reject, undo)
# 191 (plan F-quote-package B2): seven more on purpose - the price lists in their own module (`jav/domains/quotes/api_price_lists.py`:
# list, upload, a version, its settings, activate, retire, its file); B3: two more, the quote package's
# (`jav/domains/quotes/api_quote_package.py`: the requests a quote can start from, a quote package); B4c: one more, a quote's
# proposal queued for the worker
# 192 (plan F-quote-package B5): five more on purpose - a quote's draft started and saved, its approval, its reopening
# and an approved version (`jav/domains/quotes/api_quote_package.py`)
# 196 (plan F-Word-output W2, W3): seven more on purpose - a Word template's preview (`jav/service/api_outputs.py`), the quote's
# Word document of the draft and of a version, and its reply letter: read, GPT's paragraph queued, the body accepted,
# the letter file (`jav/domains/quotes/api_quote_package.py`)
# 200 (the pinned JEV version): one more on purpose - the JEV version's last look (`GET /api/system/jev-version`,
# `jav/service/api_system.py`)
# 231 (plan stage A, A6): three more on purpose - a process pack's case started, its page and a step's start
# (`jav/service/api_cases.py`); one fewer - the quote package's creation (`POST /api/quote-packages`, A6c: a quote
# starts as a case); A7d: one more, a person's action on a case's step (`POST /api/cases/{case_id}/steps/{step_id}/actions/{name}`)
# 231 (plan stage B, B1): seven more, the partner register (`jav/service/api_partners.py`: the list, the suggestions, one
# partner, a new one, a new version, retire, restore); and one more, a partner linked to a case
# (`POST /api/cases/{case_id}/partners`); B2: five more, a process pack's own settings (`jav/service/api_processes.py`:
# the processes, one's settings, a value saved, a version made active, the process's own value set aside); B3: three
# more, the same for a rule value (saved, a version made active, set aside), and one, a rule value's preview
# 231 (plan stage C, C1c): one fewer, a routing package's creation (`POST /api/email-routing/packages`: a routing is the
# email routing process pack's case, `POST /api/cases` with its sources); C3b5a: two fewer, the statement package's own
# form's survey and creation (`POST /api/statement-packages/survey`, `POST /api/statement-packages`: a statement package
# is a bank statements case's, `POST /api/cases` with its source); C3c: one more, the records a pack's case may start from
# (`GET /api/processes/{pack_id}/records`, the general form's record chooser), and one fewer, the quote's own search of
# them (`GET /api/quote-requests`); C3e: one fewer, the reconciliation's own creation (`POST /api/reconcile/packages`: a
# reconciliation is its pack's case, `POST /api/cases`)
# 231 (stage D0, D0-d): two more, a case's approving step's approval state and a person's return of its result
# (`GET /api/cases/{case_id}/steps/{step_id}/approval`, `POST .../approval/return`)
# 231 (stage D, D-c6): three more, the product registry (`jav/service/api_products.py`: the products, documents, rules and
# tariffs; a version made active; a thing retired)
# 231 (stage D, D-c7f): six more, the rule proposals (`jav/service/api_products.py`: the runs, one run, a run
# started, a proposal accepted, corrected or rejected)
# 231 (stage D, D-f7): one more, the document a case's step printed and stored with its version
# (`GET /api/cases/{case_id}/steps/{step_id}/file`)
# 231 (stage U, U0): four more, a process's example material (`jav/service/api_processes.py`: the material, its
# installation and removal, a packet's documents written as files)
# 231 (stage U, the walkthrough): one more, a follow-up case started from a closed one
# (`POST /api/cases/{case_id}/follow-ups`, `jav/service/api_cases.py`)
ROUTE_TABLE = "889a221edc9c6aa731811987b84907b0c9f2df4f7b262a8a632638c143764e43"


def test_the_service_has_these_addresses() -> None:
    rows = sorted(f"{m} {r.path}" for r in _routes() for m in r.methods)
    assert (len(rows), hashlib.sha256(json.dumps(rows).encode("utf-8")).hexdigest()) == (ROUTE_COUNT, ROUTE_TABLE), rows


def test_the_reconciliation_and_the_statement_package_have_these_addresses() -> None:
    own = sorted(f"{m} {r.path}" for r in _routes() for m in r.methods
                 if "/reconcile" in r.path or "/statement-packages" in r.path or "/statements/" in r.path)
    assert own == [
        "GET /api/reconcile/accounts",
        "GET /api/workpackages/{wp_id}/reconcile",
        "GET /api/workpackages/{wp_id}/reconcile/locate",
        "GET /api/workpackages/{wp_id}/reconcile/matches",
        "GET /api/workpackages/{wp_id}/reconcile/original/pages/{page}.png",
        "GET /api/workpackages/{wp_id}/reconcile/quick-review",
        "GET /api/workpackages/{wp_id}/reconcile/statement",
        "GET /api/workpackages/{wp_id}/reconcile/statement.xlsx",
        "GET /api/workpackages/{wp_id}/reconcile/targets",
        "POST /api/runs/{run_id}/items/{item_id}/statements/{other_doc_id}/choice",
        "POST /api/workpackages/{wp_id}/reconcile/accept-proposed",
        "POST /api/workpackages/{wp_id}/reconcile/accept-sources",
        "POST /api/workpackages/{wp_id}/reconcile/allocate",
        "POST /api/workpackages/{wp_id}/reconcile/approve",
        "POST /api/workpackages/{wp_id}/reconcile/leave-out",
        "POST /api/workpackages/{wp_id}/reconcile/mark",
        "POST /api/workpackages/{wp_id}/reconcile/quick-review/accept",
        "POST /api/workpackages/{wp_id}/reconcile/refresh",
        "POST /api/workpackages/{wp_id}/reconcile/reject",
        "POST /api/workpackages/{wp_id}/reconcile/reopen",
        "POST /api/workpackages/{wp_id}/reconcile/restore-left-out",
        "POST /api/workpackages/{wp_id}/reconcile/revoke",
        "POST /api/workpackages/{wp_id}/reconcile/scope",
        "POST /api/workpackages/{wp_id}/reconcile/unmark",
        "POST /api/workpackages/{wp_id}/statements/add",
        "POST /api/workpackages/{wp_id}/statements/survey",
    ]


def test_every_address_is_the_first_to_match_its_own_path() -> None:
    """No address hides another: for each one, a concrete path of its shape is matched first by that address."""
    routes = _routes()
    for route in routes:
        path = re.sub(r"\{[^}]+\}", "x1", route.path)
        for method in route.methods:
            scope = {"type": "http", "path": path, "method": method, "root_path": ""}
            first = next(r for r in routes if r.matches(scope)[0] == Match.FULL)
            assert first is route, f"{method} {route.path} is reached as {first.path}"


# --- a package's page and its list row, per kind --------------------------------------------------------------------------


def _keys(view: dict) -> list[str]:
    return sorted(view)


def test_the_page_of_a_folder_package_has_these_parts(db) -> None:
    folder = db / "docs"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(b"%PDF-1.4 synthetic")
    wp = work.create_from_folder(folder, name="Folder")
    view = work_views.workpackage_view(wp["id"])
    assert _keys(view) == ["current_run", "item_counts", "last_run", "next", "open_runs", "readiness", "runs",
                           "supersedable", "titles", "workflow", "workpackage"]
    assert view["next"]["code"] == "start"


def test_the_page_of_a_statement_package_has_these_parts(db) -> None:
    wp_id = _statement_package(db, _party())
    view = work_views.workpackage_view(wp_id)
    # 181: its scope (its own party and period, collecting bank statements) on purpose
    # 231 C3b5a: rule; U2a: the case step it belongs to (its page leads back to the case)
    assert _keys(view) == ["current_run", "item_counts", "last_run", "next", "open_runs", "owner_case", "readiness", "rule",
                           "runs", "scope", "statements", "supersedable", "titles", "workflow", "workpackage"]
    assert _keys(view["statements"]) == ["scope", "statements"]
    assert (view["scope"]["role"], view["scope"]["from"]) == ("statements", "logic_pack")
    assert view["workpackage"]["source_kind"] == "manual"  # 231 (C3b5a): a plain package of the statements rule
    assert view["rule"] == {"name": "statements", "adds": "own", "parts": ["statements"]}


def _reconciliation(db) -> str:
    k2._run(k2.RUN, ["inv", "stmt"], approved=True)
    k2._save("inv", k2._invoice(number="INV-0001"), run_id=k2.RUN)
    _stmt("stmt", _line(), run_id=k2.RUN)
    return _reconcile_package()


def test_the_page_of_a_reconciliation_package_has_these_parts(db) -> None:
    wp_id = _reconciliation(db)
    view = work_views.workpackage_view(wp_id)  # 231 (C3a-2): a reconciliation is its process pack's case: its page names it
    assert _keys(view) == ["case", "last_run", "next", "runs", "titles", "workflow", "workpackage"]
    assert view["case"]["pack"] == "reconciliation"
    assert (view["last_run"], view["runs"], view["titles"]) == (None, 0, {})
    assert view["next"]["code"] == "reconcile_pair"


def test_a_reconciliation_package_in_the_list(db) -> None:
    wp_id = _reconciliation(db)
    row = next(r for r in work_views.workpackage_list() if r["id"] == wp_id)
    assert (row["next"]["code"], row["older_runs"], row["open_reasons"]) == ("reconcile_pair", 0, 0)
    _cols, rows = datasets.rows("workpackages", {})
    # U2a (the owner's decision of 2026-10-28: one work list): a reconciliation is a case, listed among the cases only
    assert wp_id not in {r["id"] for r in rows}


def test_a_reconciliation_package_is_released_in_its_own_statement(db) -> None:
    from jav.app import package_release

    wp_id = _reconciliation(db)
    view = package_release.view(wp_id)
    assert (view["blockers"], view["open_live_runs"]) == ([{"code": "own_approval"}], [])
    with pytest.raises(package_release.ReleaseError, match="approved on its own page"):  # 231 (C3a-2): a case's rule
        package_release.release(wp_id, actor="t", expected_mark=view["mark"])


def test_neither_kind_takes_documents_the_shared_way(db) -> None:
    pdf = db / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 synthetic")
    reconciliation = _reconciliation(db)
    with pytest.raises(ValueError, match="^a case's documents are in the packages its scope names$"):  # 231 (C3a-2)
        work.add_to_package(reconciliation, [pdf], expected_revision=work.get(reconciliation)["revision"], actor="t")
    statements = _statement_package(db, _party())
    with pytest.raises(ValueError, match="^add statements to a statement package through its survey$"):
        work.add_to_package(statements, [pdf], expected_revision=work.get(statements)["revision"], actor="t")


# --- the fingerprint a reconciliation's approval records -------------------------------------------------------------------

APPROVAL_FINGERPRINT = "60e7c20bbd733e5c279373b003dbb9a61d677ce2799dfe2b43fa6779746b9455"


def test_the_statement_a_reconciliation_approves_has_this_fingerprint(db) -> None:
    """The statement's content with the package's random id replaced; the fingerprint is the content's sorted JSON."""
    wp_id = _reconciliation(db)
    content = rs.current(wp_id)["statement"]
    assert rs.fingerprint(content) == hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                                                default=str).encode("utf-8")).hexdigest()
    content["package"]["id"] = "wp-000000000000"
    assert rs.fingerprint(content) == APPROVAL_FINGERPRINT, json.dumps(content, ensure_ascii=False, indent=1)
