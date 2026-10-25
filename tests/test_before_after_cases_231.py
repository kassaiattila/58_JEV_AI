"""231 (plan stage C, C3a-1): the before/after comparison reads a reconciliation taken over as a case like the package it
was.

The release takes the reconciliation packages over as the reconciliation process's cases (`cases-adopt --write`); the
comparison of the store before and after reads such a case's reconciliation views under the keys the package's were,
so the pairing, the quick review, the targets and the statement are compared like for like. Synthetic statements and
invoices; no AI call.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from jav.app import parties, process_runtime
from jav.core import store
from jav.domains.finance import reconcile, reconcile_package
from jav.evals import before_after
from tests import test_reconcile_ai_134 as ai134
from tests import test_reconcile_k2_129 as k2


def _backup(folder: Path) -> str:
    folder.mkdir(parents=True)
    with store.use_store(folder / "jav.sqlite"):
        party = parties.create("Example Home", identities=[("account", reconcile.account_key(k2.OWN), k2.OWN)], actor="t")["id"]
        k2._save_statement("stmt", *ai134.LINES)
        k2._save("tel", ai134.TELECOM)
        # with its party: a package without one takes the party its accounts imply, which its statement then names
        return reconcile_package.create(name="April", accounts=[reconcile.account_key(k2.OWN)], period_start="2026-04-01",
                                        period_end="2026-04-30", actor="anna", party_id=party)["workpackage_id"]


def test_a_reconciliation_taken_over_keeps_its_reconciliation_views(tmp_path) -> None:
    before_folder = tmp_path / "before"
    wp = _backup(before_folder)
    after_folder = tmp_path / "after"
    shutil.copytree(before_folder, after_folder)
    with store.use_store(after_folder / "jav.sqlite"):
        assert [r["result"] for r in process_runtime.adopt_all(actor="tester", write=True)] == ["adopted"]
    before_after.static_snapshot(before_folder, tmp_path / "work-before", tmp_path / "before.jsonl")
    before_after.static_snapshot(after_folder, tmp_path / "work-after", tmp_path / "after.jsonl")
    _, before = before_after.load(tmp_path / "before.jsonl")
    _, after = before_after.load(tmp_path / "after.jsonl")
    keys = [f"reconcile/{wp}", f"reconcile/{wp}/quick-review", f"reconcile/{wp}/targets", f"reconcile/{wp}/statement"]
    assert all(before[k]["status"] == 200 and after[k]["status"] == 200 for k in keys)
    assert [before[k] for k in keys[1:]] == [after[k] for k in keys[1:]]  # the same reconciliation, read as a case
    assert before[f"reconcile/{wp}"]["body"]["lines"] == after[f"reconcile/{wp}"]["body"]["lines"]
