"""265 (code review J4, R4 timing): a case's page and the list of scoped packages read in one store connection.

On a copy of the live store a mailbox routing case's page took about 1.3 s, 0.8 s of it opening 630 connections: the
routing element read every open package's scope, and each scope opened about nine. Both now run in one connection
(`store.one_connection`), and the page answers as before. Synthetic documents only, no AI call.
"""

from __future__ import annotations

import sqlite3

import pytest

from jav.app import case_views, package_scope, process_runtime, registrations, work
from jav.core import store
from tests.test_workflows_146 import _invoices

registrations.load_all()


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "one.sqlite"):
        yield tmp_path


def _opened(monkeypatch) -> list[int]:
    opened: list[int] = []
    real = sqlite3.connect

    def counting(*args, **kwargs):
        opened.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(store.sqlite3, "connect", counting)
    return opened


def test_a_case_page_opens_one_connection_and_answers_as_before(db, monkeypatch) -> None:
    folder = _invoices(db / "docs", n=2)
    case = process_runtime.start_case("documents", {"source": {"kind": "folder", "folder": str(folder)}}, name="Documents",
                                      actor="anna")
    before = case_views.view.__wrapped__(case)  # the page without the shared connection
    opened = _opened(monkeypatch)
    page = case_views.view(case)
    assert len(opened) == 1
    assert page == before


def test_the_scoped_packages_are_read_in_one_connection(db, monkeypatch) -> None:
    for n in range(3):
        source = db / f"p{n}" / "note.txt"
        source.parent.mkdir(parents=True)
        source.write_text(f"Synthetic note {n}", encoding="utf-8")
        wp = work.create_from_files([source], name=f"Package {n}")
        package_scope.set_scope(wp["id"], party_id=None, period_start="2026-03-01", period_end="2026-03-31",
                                role_name=None, actor="anna")
    before = package_scope.scoped_packages.__wrapped__()
    assert len(before) == 3
    opened = _opened(monkeypatch)
    assert package_scope.scoped_packages() == before
    assert len(opened) == 1


def test_a_case_page_reads_the_case_s_state_once(tmp_path, monkeypatch) -> None:
    """272 (K4, the rest of APPW-08): the page read the case's state again for its blockers element (and its partner
    link), and built every step's view twice; now once, and the page answers as before. A monthly reconciliation, whose
    page has the blockers element."""
    from jav.core.process import engine
    from tests import test_case_ui_unification_261 as u

    u.pdf_lines_as_text(monkeypatch)
    with store.use_store(tmp_path / "state.sqlite"):
        case = u._monthly(tmp_path)
        before = case_views.view(case)
        assert any(e["type"] == "blockers" for tab in before["tabs"] for e in tab["elements"])
        reads: list[str] = []
        real = engine.state
        monkeypatch.setattr(engine, "state", lambda case_id, *a, **k: reads.append(case_id) or real(case_id, *a, **k))
        assert case_views.view(case) == before
    assert reads.count(case) == 1  # (a sub-case element reads its own case)
