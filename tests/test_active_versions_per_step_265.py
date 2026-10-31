"""265 (code review APPW-13): every approving step's active version holds, not only the latest one.

A case holds one own version per approving step (D0-b). The active versions were read one per package, so a later
step's version (a letter, which locks nothing) hid the pairing's version and its locked statement lines became free.
Now each (package, step) keeps its version and the package locks the lines of every one of them. Invented data; no AI.
"""

from __future__ import annotations

from jav.app import package_release
from jav.core import store
from jav.domains.finance import reconcile_package as rp
from tests.test_own_approval_224 import db  # noqa: F401 (the fixture)
from tests.test_reconcile_statement_145 import _world


def _approve(wp_id: str, step: str, locks: list[str]) -> int:
    with store.connect() as c:
        store.begin_immediate(c)
        return package_release.approve_own(c, wp_id, event="reconcile" if step == "pairing" else step, content={"step": step}, fingerprint=f"f-{step}",
                                           locks=locks, actor="Reviewer", files=lambda c, n: None, details={},
                                           step=step)


def test_a_later_steps_version_keeps_the_pairings_locks(db) -> None:  # noqa: F811
    wp_id, _inv, _ids = _world()
    _approve(wp_id, "pairing", ["line-1", "line-2"])
    later = _approve(wp_id, "letter", [])

    active = package_release.active_own()
    assert set(active) == {(wp_id, "pairing"), (wp_id, "letter")}
    assert set(rp.locks()) == {"line-1", "line-2"}
    assert rp.active_versions()[wp_id]["version"] == later  # the package shows its latest version
