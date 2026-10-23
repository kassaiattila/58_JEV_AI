"""218 (plan G-process-core P3a): what a calculation snapshot is linked to. A run keeps the snapshot it started with and
each finished item the one of the process that processed it; when an item was processed with other rules or code
(a release during the run), the run's view says how many items and which files with their versions - the owner's
decision of 2026-10-23: shown at the approval, nothing stops. A case and a person's approval of a package's own version
keep theirs too. Synthetic PDFs, a fake JEV client, no paid calls."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from jav.ai import jev as jev_mod
from jav.app import package_release, work, work_readiness, work_recipes, work_runs, work_views
from jav.core import cfg, queue, rulebook, store
from jav.core.process import actor as actors
from jav.core.process import cases, kinds
from jav.core.process.definition import ProcessDef, StepDef
from jav.runtime import worker
from tests.pdfgen import INVOICE_LINES, write_text_pdf
from tests.test_runtime_worker import FakeClient

kinds.register(kinds.StepKind("snapshot_note_218", __name__, lambda ctx: kinds.DONE))


@pytest.fixture()
def env(tmp_path: Path):
    adapter = jev_mod.JevAdapter(client=FakeClient(), cache_dir=tmp_path / "cache", model="jev-1.13.0")
    folder = tmp_path / "incoming"
    folder.mkdir()
    for n in (1, 2):
        write_text_pdf(folder / f"invoice_{n}.pdf", [line.replace("MINTA-2026-001", f"MINTA-2026-00{n}") for line in INVOICE_LINES])
    with store.use_store(tmp_path / "w.sqlite"), jev_mod.use_adapter(adapter):
        wp = work.create_from_folder(folder, name="Synthetic invoices")
        work_recipes.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S", "doc_type": "invoice_hu"},
                                   expected_revision=0, actor="t")
        ready = work_readiness.readiness(wp["id"])
        run_id = work_runs.start_run(wp["id"], mode="shadow", expected_assignment_revision=1,
                                     input_hash=ready["input_hash"], actor="t")["run_id"]
        yield {"run_id": run_id, "wp_id": wp["id"]}


def _released(snapshot: rulebook.Snapshot) -> rulebook.Snapshot:
    """The same process after a release that changed one rule file."""
    policy = snapshot.files["policy.json"]
    return dataclasses.replace(snapshot, files={**snapshot.files, "policy.json": dataclasses.replace(
        policy, sha256="f" * 64, version="9.9.9", content=b'{"meta": {"version": "9.9.9"}}')})


def test_a_run_and_its_items_keep_the_snapshot_they_were_made_with(env) -> None:
    run_id, current = env["run_id"], rulebook.current().snapshot_id
    with store.connect() as c:
        assert rulebook.of_run_in(c, run_id) == {"start": current, "items": {}}
    assert worker.process(queue.claim("w1")) == "done"
    with store.connect() as c:
        assert list(rulebook.of_run_in(c, run_id)["items"].values()) == [current]
    assert work_runs.rule_changes(run_id) is None
    assert "rule_changes" not in work_views.run_view(run_id)  # one snapshot: the view is as before


def test_an_item_processed_after_a_release_is_shown_at_the_run_s_approval(env, monkeypatch) -> None:
    run_id = env["run_id"]
    assert worker.process(queue.claim("w1")) == "done"
    monkeypatch.setattr(rulebook, "_CURRENT", _released(rulebook.current()))
    assert worker.process(queue.claim("w1")) == "done"
    changed = work_runs.rule_changes(run_id)
    assert changed == {"items": 1, "snapshots": 2, "code_changed": False,
                       "files": [{"path": "policy.json", "before": cfg.version("policy"), "after": "9.9.9"}]}
    assert work_views.run_view(run_id)["rule_changes"] == changed


def test_a_case_and_an_own_approval_keep_their_snapshot(env) -> None:
    definition = ProcessDef(id="snapshot_218", version="1", title="A synthetic process",
                            steps=(StepDef(id="note", kind="snapshot_note_218"),))
    cases.start("case-218", definition, {}, actors.person("Reviewer One"))
    with store.connect() as c:
        store.begin_immediate(c)
        package_release.record_own(c, env["wp_id"], content={}, fingerprint="x", locks=[], actor="Reviewer One")
    with store.connect() as c:
        version_id = c.execute("SELECT id FROM package_versions WHERE workpackage_id=?", (env["wp_id"],)).fetchone()[0]
        assert rulebook.of_in(c, rulebook.CASE, "case-218") == rulebook.current().snapshot_id
        assert rulebook.of_in(c, rulebook.PACKAGE_VERSION, str(version_id)) == rulebook.current().snapshot_id
