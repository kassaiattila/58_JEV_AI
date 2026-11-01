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
