"""160 (review R-2): a step whose start was interrupted late reuses the package (and run) it made when started again.

A documents or statements step makes its package, then starts the package's live run, and only then notes both on the
step. When the process stopped in between (the service was stopped, the computer restarted), the step was released as
"interrupted" without its package, and starting it again made a second package and a second live run: every to-do
twice. The step now notes its package as soon as it exists, and a restart goes on with that package (starting its run
returns the run already made). Synthetic documents; the run is never processed."""

from __future__ import annotations

import pytest

from jav.app import parties, work_runs, workflows as wf
from jav.core import store
from tests.test_workflow_references_153 import MONTH, erste
from tests.test_workflows_146 import _steps, db  # noqa: F401 - the fixture is used by name


def _workflow(db, party: str) -> str:  # noqa: F811
    invoices = db / "inv"
    invoices.mkdir(parents=True, exist_ok=True)
    for i in range(2):
        (invoices / f"invoice-{i}.pdf").write_bytes(b"%PDF-1.4\n% synthetic invoice " + str(i).encode() + b"\n%%EOF\n")
    statements = db / "erste"
    erste._export(statements, "20260630", erste.JUNE, pdf=erste.PDF_JUNE)
    steps = {"invoices": {"source": {"kind": "folder", "folder": str(invoices)}, "budget": {"jev": "9", "openai": "9", "azure_di": "9"}},
             "statements": {"source": {"kind": "folder", "folder": str(statements)}},
             "reconcile": {"source": {"kind": "none"}}}
    return wf.create(template_id="monthly_reconciliation", party_id=party, period_start=MONTH[0], period_end=MONTH[1],
                     steps=steps, actor="tester", advance_now=False)["workflow"]["id"]


def _packages_and_runs(name: str) -> tuple[int, int]:
    """The step's packages and their runs; 231 (C3b5b): a step's package is a case's, whose container has its name too:
    one case, not counted as a package."""
    with store.connect() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM workpackages WHERE name=? AND source_kind != 'case'", (name,))]
        cases = c.execute("SELECT COUNT(*) FROM workpackages WHERE name=? AND source_kind = 'case'", (name,)).fetchone()[0]
        runs = c.execute(f"SELECT COUNT(*) FROM runs WHERE workpackage_id IN ({','.join('?' * len(ids))})", ids).fetchone()[0]
    assert cases == 1
    return len(ids), runs


@pytest.mark.parametrize("stop_after", ["package", "run"])
def test_a_restarted_step_goes_on_with_the_package_it_made(db, monkeypatch, stop_after):  # noqa: F811
    wf_id = _workflow(db, parties.create("Example R Kft.", identities=[], actor="t")["id"])
    name = _steps(wf.view(wf_id))["invoices"]["name"]
    original = work_runs.start_run

    def stopped(*args, **kwargs):  # the process stops before the run is made, or right after it
        if stop_after == "run":
            original(*args, **kwargs)
        raise KeyboardInterrupt

    monkeypatch.setattr(work_runs, "start_run", stopped)
    with pytest.raises(KeyboardInterrupt):
        wf.advance(wf_id, actor="t")
    monkeypatch.undo()
    assert _steps(wf.view(wf_id))["invoices"]["state"] == "failed"
    step = _steps(wf.start_step(wf_id, "invoices", actor="t"))["invoices"]  # a person starts it again
    assert step["state"] == "started" and step["run_id"]
    assert _packages_and_runs(name) == (1, 1)
