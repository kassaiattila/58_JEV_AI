"""Native intake and mixed routing use frozen inputs without paid calls."""
from decimal import Decimal
from pathlib import Path

import pytest

from jav import app_settings, store, work
from jav.native_contracts import DOCUMENT_SUFFIXES
from jav.runtime import queue, worker


@pytest.fixture()
def isolated(tmp_path):
    with store.use_store(tmp_path / "native.sqlite"):
        yield tmp_path


def mixed_package(root: Path, *, params=None):
    folder = root / "incoming"
    folder.mkdir()
    for suffix in DOCUMENT_SUFFIXES:
        (folder / f"synthetic{suffix}").write_text(f"Synthetic {suffix}", encoding="utf-8")
    (folder / "excluded.bin").write_bytes(b"not a supported document")
    wp = work.create_from_folder(folder)
    work.assign_recipe(wp["id"], "multi-format-processing", params=params or {}, expected_revision=0, actor="reviewer")
    return work.get(wp["id"])


def test_mixed_intake_routing_plan_and_frozen_sources(isolated):
    wp = mixed_package(isolated)
    items = wp["items"]
    assert {Path(i["source_path"]).suffix for i in items} == set(DOCUMENT_SUFFIXES)
    assert app_settings.SUFFIXES == DOCUMENT_SUFFIXES
    recipe = work.recipe("multi-format-processing")
    ready = work.readiness(wp["id"])
    assert ready["ready"]
    assert ready["plan"]["native_documents"] == 4
    assert ready["plan"]["item_flows"] == {i["item_id"]: work.flow_for(recipe, i) for i in items}
    assert [work.flow_for(recipe, i) for i in items].count("native") == 4
    assert not ready["plan"]["azure"]
    for item in items:
        frozen = work.source_file(item).read_bytes()
        Path(item["source_path"]).write_bytes(b"changed after intake")
        assert work.source_file(item).read_bytes() == frozen
    assert work.readiness(wp["id"], verify=True)["ready"]


def test_native_s_is_rejected_before_queue_and_provider_reservation(isolated):
    wp = mixed_package(isolated, params={"arm": "S", "jev": "off"})
    ready = work.readiness(wp["id"])
    assert not ready["ready"]
    assert "native_s_unsupported" in {b["code"] for b in ready["blockers"]}
    with pytest.raises(work.NotReady):
        work.start_run(wp["id"], mode="apply", expected_assignment_revision=1,
                       input_hash=ready["input_hash"], actor="reviewer")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0


def test_native_budget_has_no_azure_and_jev_off_has_no_jev(isolated):
    from jav.native_processing import estimate_limits

    wp = mixed_package(isolated, params={"arm": "G", "jev": "off", "azure_ocr": "on"})
    ready = work.readiness(wp["id"])
    per = estimate_limits(wp["assignment"]["params"]).provider_limits_usd
    assert set(per) == {"openai"}
    assert "jev" not in ready["budget"]
    assert ready["budget"]["azure_di"] == Decimal("0.02")
    assert ready["budget"]["openai"] == 4 * per["openai"] + Decimal("0.22")


def test_old_recipe_rejects_native_and_explicit_pdf_filter_survives(isolated):
    wp = mixed_package(isolated)
    work.assign_recipe(wp["id"], "processing", params={}, expected_revision=1, actor="reviewer")
    assert not work.readiness(wp["id"])["ready"]
    pdfs = work.create_from_folder(isolated / "incoming", suffixes=(".pdf",))
    assert len(pdfs["items"]) == 1
    assert Path(pdfs["items"][0]["source_path"]).suffix == ".pdf"


def test_worker_passes_frozen_native_identity_without_pdf_stage(isolated, monkeypatch):
    source = isolated / "source.txt"
    source.write_text("Reference 00123", encoding="utf-8")
    wp = work.create_from_files([source], name="Native")
    work.assign_recipe(wp["id"], "multi-format-processing", params={"jev": "off"}, expected_revision=0, actor="reviewer")
    ready = work.readiness(wp["id"])
    rid = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1,
                         input_hash=ready["input_hash"], actor="reviewer")["run_id"]
    seen = []

    def stage(recipe, params, source_path, app_id, persister, **kwargs):
        seen.append((recipe, params, source_path, app_id, kwargs))
        return {"final_status": "done"}

    monkeypatch.setattr(worker, "_run_stage", stage)
    job = queue.claim("native-test")
    assert worker.process(job) == "done"
    assert len(seen) == 1 and seen[0][0]["flow"] == "native"
    assert seen[0][4]["run_id"] == rid
    assert seen[0][4]["recipe_hash"] == work.get_run(rid)["recipe_hash"]
    item = seen[0][4]["item"]
    assert item["sha256"] == work.sha256_file(Path(seen[0][4]["read_path"]))


def test_cli_approval_forwards_only_the_explicit_reviewed_version(monkeypatch, capsys):
    from jav import cli

    received = []

    def approve(run_id, *, actor, review_version):
        received.append((run_id, actor, review_version))
        return {"run_id": run_id, "approved_by": actor}

    monkeypatch.setattr(work, "approve_run", approve)
    assert cli.main(["run-approve", "run-synthetic", "--actor", "reviewer", "--review-version", "seen-version"]) == 0
    assert received == [("run-synthetic", "reviewer", "seen-version")]
    assert cli.main(["run-approve", "run-legacy", "--actor", "reviewer"]) == 0
    assert received[-1] == ("run-legacy", "reviewer", None)
    capsys.readouterr()
