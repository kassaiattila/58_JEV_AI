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

from jav import api, datasets, reconcile_statement as rs, statement_table as st, store, work, work_views
from tests import test_reconcile_k2_129 as k2
from tests.test_reconcile_package_131 import _line, _package as _reconcile_package, _stmt
from tests.test_statement_package_140 import _package as _statement_package, _party


@pytest.fixture(autouse=True)
def pdf_text(monkeypatch):
    """The synthetic 'PDF' statements hold their lines as plain text (as in `tests/test_statement_package_140.py`)."""
    monkeypatch.setattr(st, "_pdf_lines", lambda path: Path(path).read_text(encoding="utf-8").splitlines())


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "c.sqlite"):
        yield tmp_path


def _routes() -> list[APIRoute]:
    app = api.create_app(store_path=Path(tempfile.mkdtemp()) / "routes.sqlite")
    return [r for r in app.routes if isinstance(r, APIRoute)]


# --- the addresses of the local service ---------------------------------------------------------------------------------

ROUTE_COUNT = 178  # (method, path) pairs of 174 routes: the unknown-address answer has five methods
# 178 (plan 170 L4): nine new addresses on purpose - the own output templates (list, upload, activate, retire, file,
# preview), a package's choice of them (read, choose) and the utility cost's workbook (jav/api_outputs.py)
# 181 (plan 170 L5): three more on purpose - the package roles, and a package's scope given and taken away
# (`GET /api/package-roles`, `POST /api/workpackages/{wp_id}/scope`, `POST /api/workpackages/{wp_id}/scope/clear`), and
# the email routing's five in its own module (`jav/domains/email/api_email_routing.py`: a routing package; accept, every clear one,
# reject, undo)
# 191 (plan F-quote-package B2): seven more on purpose - the price lists in their own module (`jav/api_price_lists.py`:
# list, upload, a version, its settings, activate, retire, its file); B3: two more, the quote package's
# (`jav/api_quote_package.py`: the requests a quote can start from, a quote package); B4c: one more, a quote's
# proposal queued for the worker
# 192 (plan F-quote-package B5): five more on purpose - a quote's draft started and saved, its approval, its reopening
# and an approved version (`jav/api_quote_package.py`)
# 196 (plan F-Word-output W2, W3): seven more on purpose - a Word template's preview (`jav/api_outputs.py`), the quote's
# Word document of the draft and of a version, and its reply letter: read, GPT's paragraph queued, the body accepted,
# the letter file (`jav/api_quote_package.py`)
# 200 (the pinned JEV version): one more on purpose - the JEV version's last look (`GET /api/system/jev-version`,
# `jav/api_system.py`)
ROUTE_TABLE = "41cc565ef01319a4aa6e0c1f10a406a25c69424e6c4a3587ed769339463fb228"


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
        "POST /api/reconcile/packages",
        "POST /api/runs/{run_id}/items/{item_id}/statements/{other_doc_id}/choice",
        "POST /api/statement-packages",
        "POST /api/statement-packages/survey",
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
    assert _keys(view) == ["current_run", "item_counts", "last_run", "next", "open_runs", "readiness", "runs", "scope",
                           "statements", "supersedable", "titles", "workflow", "workpackage"]
    assert _keys(view["statements"]) == ["scope", "statements"]
    assert (view["scope"]["role"], view["scope"]["from"]) == ("statements", "logic_pack")
    assert view["workpackage"]["source_kind"] == "statements"


def _reconciliation(db) -> str:
    k2._run(k2.RUN, ["inv", "stmt"], approved=True)
    k2._save("inv", k2._invoice(number="INV-0001"), run_id=k2.RUN)
    _stmt("stmt", _line(), run_id=k2.RUN)
    return _reconcile_package()


def test_the_page_of_a_reconciliation_package_has_these_parts(db) -> None:
    wp_id = _reconciliation(db)
    view = work_views.workpackage_view(wp_id)
    assert _keys(view) == ["last_run", "next", "readiness", "reconcile", "runs", "titles", "workflow", "workpackage"]
    assert _keys(view["reconcile"]) == ["approval", "counts", "coverage", "scope"]
    assert (view["last_run"], view["runs"], view["titles"]) == (None, 0, {})
    assert view["next"]["code"] == "reconcile_pair"
    assert view["readiness"]["counts"] == {"items": 0, "lines": 1, "invoices": 1}


def test_a_reconciliation_package_in_the_list(db) -> None:
    wp_id = _reconciliation(db)
    row = next(r for r in work_views.workpackage_list() if r["id"] == wp_id)
    assert (row["next"]["code"], row["older_runs"], row["open_reasons"]) == ("reconcile_pair", 0, 0)
    _cols, rows = datasets.rows("workpackages", {})
    shown = next(r for r in rows if r["id"] == wp_id)
    assert shown["items"] is None  # its lines are not items: an empty cell, not "0"


def test_a_reconciliation_package_is_released_in_its_own_statement(db) -> None:
    from jav import package_release

    wp_id = _reconciliation(db)
    view = package_release.view(wp_id)
    assert (view["blockers"], view["open_live_runs"]) == ([{"code": "own_approval"}], [])
    with pytest.raises(package_release.ReleaseError, match="approved in its own statement"):
        package_release.release(wp_id, actor="t", expected_mark=view["mark"])


def test_neither_kind_takes_documents_the_shared_way(db) -> None:
    pdf = db / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 synthetic")
    reconciliation = _reconciliation(db)
    with pytest.raises(ValueError, match="^a reconciliation package has no documents$"):
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
