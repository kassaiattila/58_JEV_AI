"""Work package, recipe assignment, readiness and run (040 K1). No calls, synthetic files."""

from decimal import Decimal
from pathlib import Path

import pytest

from jav import store, work
from jav.runtime import calls, queue


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "w.sqlite"):
        yield tmp_path


def _folder(tmp_path: Path, n: int = 2) -> Path:
    d = tmp_path / "bejovo"
    d.mkdir()
    for i in range(n):
        (d / f"szamla_{i}.pdf").write_bytes(f"%PDF-1.4 minta {i}".encode())
    (d / "jegyzet.txt").write_text("nem irat", encoding="utf-8")
    return d


def _ready_wp(tmp_path: Path, n: int = 2) -> dict:
    wp = work.create_from_folder(_folder(tmp_path, n), name="Szeptemberi számlák")
    work.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "S", "doc_type": "invoice_hu"},
                       expected_revision=0, actor="teszt")
    return work.get(wp["id"])


def test_create_from_folder_takes_matching_files_with_hash(isolated):
    wp = work.create_from_folder(_folder(isolated), name="Szeptember")
    assert wp["name"] == "Szeptember" and wp["source_kind"] == "folder" and wp["revision"] == 1
    items = work.get(wp["id"])["items"]
    assert [Path(i["source_path"]).name for i in items] == ["szamla_0.pdf", "szamla_1.pdf"]
    assert all(len(i["sha256"]) == 64 and i["kind"] == "document" for i in items)


def test_revision_conflict_on_stale_edit(isolated):
    wp = work.create_from_folder(_folder(isolated), name="x")
    extra = isolated / "uj.pdf"
    extra.write_bytes(b"%PDF uj")
    work.add_document(wp["id"], extra, expected_revision=1)
    with pytest.raises(work.RevisionConflict):
        work.add_document(wp["id"], extra, expected_revision=1)  # changed meanwhile: rejection, not a silent overwrite


def test_assignment_validates_params_and_revision(isolated):
    wp = work.create_from_folder(_folder(isolated), name="x")
    with pytest.raises(ValueError):
        work.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "X"}, expected_revision=0, actor="t")
    with pytest.raises(ValueError):
        work.assign_recipe(wp["id"], "invoice-extraction", params={"doc_type": "nincs_ilyen"}, expected_revision=0, actor="t")
    a = work.assign_recipe(wp["id"], "invoice-extraction", params={}, expected_revision=0, actor="t", note="első")
    assert a["revision"] == 1 and a["params"] == {"arm": "auto", "doc_type": "invoice_hu", "jev_cache": "reuse", "azure_ocr": "on"}  # 053: the document type's recommended path; 075: Azure switch on
    with pytest.raises(work.RevisionConflict):
        work.assign_recipe(wp["id"], "invoice-extraction", params={}, expected_revision=0, actor="t")
    assert [h["note"] for h in work.assignment_history(wp["id"])] == ["első"]


def test_readiness_reports_blockers(isolated):
    wp = work.create_workpackage(name="üres", source_kind="manual", source_ref=None)
    r = work.readiness(wp["id"])
    assert not r["ready"] and {b["code"] for b in r["blockers"]} == {"no_items", "no_recipe"}


def test_readiness_detects_changed_and_missing_source(isolated):
    wp = _ready_wp(isolated)
    assert work.readiness(wp["id"])["ready"]
    src = Path(wp["items"][0]["source_path"])
    src.write_bytes(b"%PDF megvaltozott")
    Path(wp["items"][1]["source_path"]).unlink()
    codes = {b["code"] for b in work.readiness(wp["id"])["blockers"]}
    assert codes == {"source_changed", "source_missing"}


def test_readiness_budget_estimate(isolated):
    wp = _ready_wp(isolated, n=3)
    r = work.readiness(wp["id"])
    assert r["budget"] == {"jev": Decimal("0.15"), "azure_di": Decimal("0.06")}  # 3 items × 0.05 USD on the S path; 075: × 0.02 USD Azure


def test_budget_follows_the_actual_path(isolated):
    """065 decision: where the path does not call OpenAI, there is no OpenAI reservation. For a document of unknown type
    the worst case stays; for an already recognised document the type's recommended path counts."""
    wp = work.create_from_folder(_folder(isolated, 2), name="vegyes")
    rev = 0

    def assign(recipe_id: str, params: dict) -> dict:
        nonlocal rev
        work.assign_recipe(wp["id"], recipe_id, params=params, expected_revision=rev, actor="t")
        rev += 1
        return work.readiness(wp["id"])["budget"]

    assert assign("invoice-extraction", {"arm": "auto", "doc_type": "invoice_hu"}) == {"jev": Decimal("0.10"), "azure_di": Decimal("0.04")}  # S path
    assert "azure_di" not in assign("invoice-extraction", {"arm": "auto", "doc_type": "invoice_hu", "azure_ocr": "off"})  # 075: switch off
    assert assign("invoice-extraction", {"arm": "auto", "doc_type": "mohu_szamla"})["openai"] == Decimal("0.20")  # G path
    assert assign("document-processing", {"arm": "auto"})["openai"] == Decimal("0.20")  # the type is not known yet
    first, second = work.get(wp["id"])["items"]
    store.upsert_document(doc_id=first["sha256"], source_path=first["source_path"], detail_type="invoice_hu")
    store.upsert_document(doc_id=second["sha256"], source_path=second["source_path"], detail_type="mohu_szamla")
    budget = work.readiness(wp["id"])["budget"]
    assert budget == {"jev": Decimal("0.14"), "openai": Decimal("0.10"), "azure_di": Decimal("0.04")}  # only the utility invoice's path calls OpenAI
    # 066 Á07: a requested S path runs as G on a G-only type, so the G path's budget line is needed (previously it
    # reserved without OpenAI)
    assert assign("invoice-extraction", {"arm": "S", "doc_type": "certificate"})["openai"] == Decimal("0.20")


def test_start_run_is_idempotent_and_enqueues_one_job_per_item(isolated):
    wp = _ready_wp(isolated)
    r = work.readiness(wp["id"])
    first = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")
    again = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")
    assert not first["deduped"] and again["deduped"] and first["run_id"] == again["run_id"]
    assert queue.counts(run_id=first["run_id"]) == {"queued": 2}
    run = work.get_run(first["run_id"])
    assert run["status"] == "queued" and run["mode"] == "shadow" and len(run["input"]["items"]) == 2
    assert calls.budget_usage(first["run_id"])["providers"]["jev"]["limit_usd"] == Decimal("0.10")



def test_start_run_refuses_a_change_between_its_check_and_the_snapshot(isolated, monkeypatch):
    """066 Á19: the start checked the readiness snapshot but froze a later read. If a new document was added to the
    package meanwhile (concurrent edit), the run would have started with an input that nobody had checked."""
    wp = _ready_wp(isolated)
    r = work.readiness(wp["id"])
    extra = isolated / "kozben.pdf"
    extra.write_bytes(b"%PDF-1.4 kozben")
    real = work.readiness

    def readiness_then_concurrent_edit(wp_id, **kw):
        out = real(wp_id, **kw)
        work.add_document(wp_id, extra, expected_revision=work.get(wp_id)["revision"])
        return out

    monkeypatch.setattr(work, "readiness", readiness_then_concurrent_edit)
    with pytest.raises(work.RevisionConflict):
        work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")
    with store.connect() as c:
        assert c.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0

def test_start_run_refuses_stale_input_or_assignment(isolated):
    wp = _ready_wp(isolated)
    r = work.readiness(wp["id"])
    with pytest.raises(work.RevisionConflict):
        work.start_run(wp["id"], mode="shadow", expected_assignment_revision=0, input_hash=r["input_hash"], actor="t")
    with pytest.raises(work.RevisionConflict):
        work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash="régi", actor="t")
    Path(wp["items"][0]["source_path"]).write_bytes(b"%PDF mas")
    with pytest.raises(work.NotReady):
        work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")


def test_later_assignment_change_does_not_touch_started_run(isolated):
    wp = _ready_wp(isolated)
    r = work.readiness(wp["id"])
    run = work.start_run(wp["id"], mode="apply", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")
    work.assign_recipe(wp["id"], "invoice-extraction", params={"arm": "G"}, expected_revision=1, actor="t")
    assert work.get_run(run["run_id"])["params"] == {"arm": "S", "doc_type": "invoice_hu", "jev_cache": "reuse", "azure_ocr": "on"}


def test_run_status_rollup_and_approval_rules(isolated):
    wp = _ready_wp(isolated)
    r = work.readiness(wp["id"])
    run_id = work.start_run(wp["id"], mode="apply", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")["run_id"]
    items = work.get_run(run_id)["input"]["items"]
    with pytest.raises(work.NotReady):
        work.approve_run(run_id, actor="t")  # still running
    work.record_item_result(run_id, items[0]["item_id"], status="done", final_status="done", flow_run_id=work.flow_run_id(run_id, items[0]["item_id"]))
    work.record_item_result(run_id, items[1]["item_id"], status="done", final_status="needs_review", flow_run_id=work.flow_run_id(run_id, items[1]["item_id"]))
    for _ in range(2):
        queue.complete(queue.claim("w").id)
    store.review_enqueue(subject_kind="document", subject_id=items[1]["item_id"], run_id=work.flow_run_id(run_id, items[1]["item_id"]), reasons=["x:1"], producer="m2:S")
    assert work.refresh_run_status(run_id) == "needs_review"
    with pytest.raises(work.NotReady):
        work.approve_run(run_id, actor="t")  # no approval while a to-do is open
    store.review_resolve(store.review_open_reasons("document", items[1]["item_id"])[0]["id"], actor="t")
    assert work.refresh_run_status(run_id) == "done"
    work.approve_run(run_id, actor="ellenor")
    run = work.get_run(run_id)
    assert run["approval"] == "approved" and run["approved_by"] == "ellenor"


def test_shadow_run_cannot_be_approved(isolated):
    wp = _ready_wp(isolated)
    r = work.readiness(wp["id"])
    run_id = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")["run_id"]
    with pytest.raises(ValueError):
        work.approve_run(run_id, actor="t")


def test_folder_must_exist(isolated):
    with pytest.raises(ValueError):
        work.create_from_folder(isolated / "nincs", name="x")


def test_list_workpackages_counts(isolated):
    wp = _ready_wp(isolated)
    rows = work.list_workpackages()
    assert rows[0]["id"] == wp["id"] and rows[0]["items"] == 2 and rows[0]["recipe_id"] == "invoice-extraction"


def _stale_needs_review_run(tmp_path: Path) -> tuple[str, str]:
    """A live run with one open to-do on the second item (the run's status: to-dos pending)."""
    wp = _ready_wp(tmp_path)
    r = work.readiness(wp["id"])
    run_id = work.start_run(wp["id"], mode="apply", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")["run_id"]
    items = work.get_run(run_id)["input"]["items"]
    for it in items:
        work.record_item_result(run_id, it["item_id"], status="done", final_status="done", flow_run_id=work.flow_run_id(run_id, it["item_id"]))
        queue.complete(queue.claim("w").id)
    store.review_enqueue(subject_kind="document", subject_id=items[1]["item_id"], run_id=work.flow_run_id(run_id, items[1]["item_id"]),
                         reasons=["x:1"], producer="m2:S")
    assert work.refresh_run_status(run_id) == "needs_review"
    return run_id, items[1]["item_id"]


def test_resolving_last_reason_refreshes_run_status(isolated):
    # 058: the list badge must not stay "to-dos pending" once the last to-do has been closed
    run_id, item_id = _stale_needs_review_run(isolated)
    reason_id = store.review_open_reasons("document", item_id)[0]["id"]
    out = work.resolve_reason(reason_id, actor="ellenor", resolution=None, note=None)
    assert out["status"] == "resolved" and out["run_status"] == "done"
    assert work.get_run(run_id)["status"] == "done"
    with pytest.raises(work.RevisionConflict):
        work.resolve_reason(reason_id, actor="ellenor", resolution=None, note=None)  # reason already closed


def test_run_rows_show_done_for_stale_needs_review(isolated):
    # a stale stored "to-dos pending" status (to-dos closed earlier without a refresh) shows as "done" in the list
    run_id, item_id = _stale_needs_review_run(isolated)
    store.review_resolve(store.review_open_reasons("document", item_id)[0]["id"], actor="t")  # old path: no refresh
    row = next(r for r in work.run_rows() if r["run_id"] == run_id)
    assert row["open_reasons"] == 0 and row["status"] == "done"


def test_archive_hides_workpackage_and_restore_brings_it_back(isolated):
    wp = _ready_wp(isolated)
    work.archive_workpackage(wp["id"], actor="t")
    assert [w["id"] for w in work.list_workpackages()] == []
    archived = work.list_workpackages(include_archived=True)
    assert archived[0]["id"] == wp["id"] and archived[0]["status"] == "archived"
    assert work.get(wp["id"])["status"] == "archived"  # can still be opened directly
    work.restore_workpackage(wp["id"], actor="t")
    assert [w["id"] for w in work.list_workpackages()] == [wp["id"]]


def test_rename_workpackage(isolated):
    wp = _ready_wp(isolated)
    assert work.rename_workpackage(wp["id"], "  Októberi számlák  ", actor="t")["name"] == "Októberi számlák"
    with pytest.raises(ValueError):
        work.rename_workpackage(wp["id"], "   ", actor="t")
    with pytest.raises(KeyError):
        work.rename_workpackage("wp-000000000000", "x", actor="t")


def test_delete_only_workpackage_without_runs(isolated):
    wp = _ready_wp(isolated)
    r = work.readiness(wp["id"])
    work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")
    with pytest.raises(work.NotReady):
        work.delete_workpackage(wp["id"], actor="t")  # it has a run: it can only be hidden
    empty = work.create_workpackage(name="üres", source_kind="manual", source_ref=None)
    work.delete_workpackage(empty["id"], actor="t")
    with pytest.raises(KeyError):
        work.get(empty["id"])
    assert [w["id"] for w in work.list_workpackages(include_archived=True)] == [wp["id"]]


def test_readiness_reuses_fingerprint_until_size_or_mtime_changes(isolated, monkeypatch):
    # 058 (Q-lassú-nézet): opening a package does not rehash every file; starting always checks in full
    wp = _ready_wp(isolated)
    calls_ = []
    real = work.sha256_file
    monkeypatch.setattr(work, "sha256_file", lambda p: calls_.append(Path(p).name) or real(p))
    assert work.readiness(wp["id"])["ready"]
    first = len(calls_)
    assert work.readiness(wp["id"])["ready"] and len(calls_) == first  # unchanged file: no rehashing
    src = Path(wp["items"][0]["source_path"])
    src.write_bytes(b"%PDF-1.4 mas tartalom, mas meret")
    codes = {b["code"] for b in work.readiness(wp["id"])["blockers"]}
    assert codes == {"source_changed"} and calls_[-1] == src.name
    src.write_bytes(b"%PDF-1.4 minta 0")  # back to the original
    r = work.readiness(wp["id"])
    before = len(calls_)
    work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")
    assert len(calls_) - before == 2  # full check of every item at start


def test_status_refresh_never_overwrites_a_concurrent_cancel(isolated, monkeypatch):
    """066 Á32: the status refresh reads, computes, then writes; if the run was cancelled meanwhile, the refresh must
    not write it back to "done" (the cancellation would be lost)."""
    wp = _ready_wp(isolated)
    r = work.readiness(wp["id"])
    run_id = work.start_run(wp["id"], mode="shadow", expected_assignment_revision=1, input_hash=r["input_hash"], actor="t")["run_id"]
    for item in work.get_run(run_id)["input"]["items"]:
        work.record_item_result(run_id, item["item_id"], status="done", final_status="done",
                                flow_run_id=work.flow_run_id(run_id, item["item_id"]))
        queue.complete(queue.claim("w").id)
    real = work.open_reasons_for_run

    def cancel_meanwhile(rid):
        with store.connect() as c:
            c.execute("UPDATE runs SET status='cancelled' WHERE run_id=?", (rid,))
        return real(rid)

    monkeypatch.setattr(work, "open_reasons_for_run", cancel_meanwhile)
    assert work.refresh_run_status(run_id) == "cancelled"
    assert work.get_run(run_id)["status"] == "cancelled"
