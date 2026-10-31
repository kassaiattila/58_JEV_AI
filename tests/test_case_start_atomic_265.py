"""265 (code review APPW-12): a case's container is made in the start's own transaction.

The container (a work package) was made before the transaction that starts the case; a start that failed after it
left a container with no case behind, shown on the lists. Now both are in one transaction. Invented process; no AI.
"""

from __future__ import annotations

import pytest

from jav.app import process_runtime
from jav.core import store
from jav.core.process import cases
from tests.test_case_list_263 import _started
from tests.test_sub_case_231 import db  # noqa: F401 (the fixture)


def _containers() -> int:
    with store.connect() as c:
        return c.execute("SELECT COUNT(*) FROM workpackages WHERE source_kind=?", (process_runtime.CONTAINER,)).fetchone()[0]


def test_a_failed_start_leaves_no_container(db, monkeypatch) -> None:  # noqa: F811
    before = _containers()

    def broken(*a, **k):
        raise RuntimeError("the case could not start")

    monkeypatch.setattr(cases, "start_in", broken)
    with pytest.raises(RuntimeError):
        _started(db, "Invented March")
    assert _containers() == before
