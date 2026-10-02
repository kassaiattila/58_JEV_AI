"""090: fixes of the 2026-10-02 backend and frontend audit (N05, N03). Synthetic PDFs and stand-in calls only; no paid
call. The audit's witnesses (`runs/20261002_full_audit/probes.py`) are turned round: they proved the faults, these
tests require the protected behaviour.

- N05: the backup starts from the source instances the saved store refers to, not from the files it happens to find.
  An instance that is neither in the store nor already verified in the backup is named as missing, the backup is not
  green, and no earlier backup is pruned; the store copy still goes to the second location, without pruning there.
  A restore made from the backup alone can open every referenced document.
- N03: only a call whose outcome is uncertain can be settled by hand, with a conditional write; an active call's
  reservation cannot be released, so its budget cannot be spent twice. A late answer never overwrites a manual
  settlement.
"""

from __future__ import annotations

import hashlib
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jav import api, backup, source_instances, store, work
from jav.runtime import calls
from tests.pdfgen import INVOICE_LINES, write_text_pdf

BASE = "http://127.0.0.1:8930"
HUMAN = {"X-Actor": "test.user"}


# --- N05: the backup checks the referenced source instances ------------------------------------------------------


@pytest.fixture()
def two_docs(tmp_path: Path):
    """A work package of two synthetic invoices, with its own store and source instances."""
    first, second = tmp_path / "in" / "first.pdf", tmp_path / "in" / "second.pdf"
    first.parent.mkdir()
    write_text_pdf(first, INVOICE_LINES)
    write_text_pdf(second, [line.replace("MINTA-2026-001", "MINTA-2026-002") for line in INVOICE_LINES])
    with store.use_store(tmp_path / "store" / "jav.sqlite"):
        wp = work.create_from_files([first, second], name="Synthetic backup")
        yield {"tmp": tmp_path, "items": wp["items"], "out": tmp_path / "backups", "nas": tmp_path / "nas"}


def _sources(manifest: dict) -> dict:
    return next(f for f in manifest["files"] if f["file"] == "sources")


def _hide(path: Path, tmp: Path) -> None:
    """Moves a synthetic instance out of the store (the evidence stays in the test folder)."""
    path.rename(tmp / f"hidden-{path.name}")


def test_a_referenced_instance_that_was_never_backed_up_fails_the_backup(two_docs):
    item = two_docs["items"][0]
    _hide(work.source_file(item), two_docs["tmp"])
    result = backup.backup(out_root=two_docs["out"], keep=1)
    entry = _sources(result)
    assert not result["ok"]
    assert entry["required"] == 2 and entry["missing"] == [item["instance"]] and entry["integrity"] != "ok"
    assert item["instance"] in result["error"]  # the status line names it (Settings › System)


def test_no_earlier_backup_is_pruned_while_a_referenced_instance_is_missing(two_docs):
    out = two_docs["out"]
    first = backup.backup(out_root=out, keep=1)
    assert first["ok"]
    (out / "sources" / two_docs["items"][0]["instance"]).unlink()  # the backup's copy is lost…
    _hide(work.source_file(two_docs["items"][0]), two_docs["tmp"])  # …and so is the store's own instance
    second = backup.backup(out_root=out, keep=1)
    assert not second["ok"] and second["removed"] == []
    assert (out / Path(first["dir"]).name).is_dir()


def test_the_store_copy_still_reaches_the_second_location_without_pruning(two_docs):
    out, nas = two_docs["out"], two_docs["nas"]
    assert backup.backup(out_root=out, keep=1, copy_to=nas)["ok"]
    (out / "sources" / two_docs["items"][0]["instance"]).unlink()
    _hide(work.source_file(two_docs["items"][0]), two_docs["tmp"])
    second = backup.backup(out_root=out, keep=1, copy_to=nas)
    assert not second["ok"]
    assert second["copy"]["ok"] and second["copy"]["removed"] == []
    assert len([p for p in nas.iterdir() if p.is_dir() and p.name != "sources"]) == 2


def test_an_instance_kept_by_an_earlier_backup_is_preserved_not_missing(two_docs):
    out = two_docs["out"]
    assert backup.backup(out_root=out, keep=2)["ok"]
    item = two_docs["items"][0]
    _hide(work.source_file(item), two_docs["tmp"])
    result = backup.backup(out_root=out, keep=2)
    entry = _sources(result)
    assert result["ok"] and entry["integrity"] == "ok"
    assert entry["preserved"] == [item["instance"]] and entry["missing"] == []


def test_a_missing_instance_folder_is_checked_against_the_backup(two_docs):
    out = two_docs["out"]
    shutil.rmtree(source_instances.root())  # no instance folder at all, and no earlier backup
    result = backup.backup(out_root=out, keep=2)
    assert not result["ok"]
    assert sorted(_sources(result)["missing"]) == sorted(i["instance"] for i in two_docs["items"])


def test_a_missing_instance_folder_with_an_earlier_backup_is_preserved(two_docs):
    out = two_docs["out"]
    assert backup.backup(out_root=out, keep=2)["ok"]
    shutil.rmtree(source_instances.root())
    result = backup.backup(out_root=out, keep=2)
    assert result["ok"]
    assert sorted(_sources(result)["preserved"]) == sorted(i["instance"] for i in two_docs["items"])


def test_a_damaged_instance_without_an_intact_copy_fails_the_backup(two_docs):
    item = two_docs["items"][0]
    work.source_file(item).write_bytes(b"%PDF damaged")
    result = backup.backup(out_root=two_docs["out"], keep=1)
    entry = _sources(result)
    assert not result["ok"]
    assert entry["damaged"] == [Path(item["instance"]).name] and entry["missing"] == [item["instance"]]


def test_an_unreferenced_instance_is_still_copied_but_not_required(two_docs):
    stray = source_instances.root() / "ab" / ("ab" + "0" * 62 + ".pdf")
    stray.parent.mkdir(exist_ok=True)
    stray.write_bytes(b"not referenced")  # its name is not its content hash: damaged, but nobody refers to it
    result = backup.backup(out_root=two_docs["out"], keep=1)
    assert result["ok"] and _sources(result)["required"] == 2 and _sources(result)["missing"] == []


def test_a_restore_from_the_backup_alone_opens_every_referenced_document(two_docs):
    result = backup.backup(out_root=two_docs["out"], keep=1)
    assert result["ok"]
    restored = two_docs["tmp"] / "restored"
    restored.mkdir()
    saved_store = Path(result["dir"]) / "jav.sqlite"
    shutil.copyfile(saved_store, restored / "jav.sqlite")
    shutil.copytree(two_docs["out"] / "sources", restored / "sources")
    with store.use_store(restored / "jav.sqlite"):
        items = work.get(work.list_workpackages()[0]["id"])["items"]
        assert len(items) == 2
        for item in items:
            data = work.source_file(item).read_bytes()
            assert data.startswith(b"%PDF") and hashlib.sha256(data).hexdigest() == item["sha256"]


# --- N03: only an uncertain call can be settled by hand ------------------------------------------------------------


def test_an_active_call_cannot_be_settled_and_its_budget_is_not_reused(tmp_path):
    db = tmp_path / "jav.sqlite"
    client = TestClient(api.create_app(store_path=db), base_url=BASE)
    with store.use_store(db):
        calls.set_budget("audit", "openai", Decimal("0.1"))
        seen = {}

        def in_flight():
            row = calls.journal("audit")[0]
            assert row["status"] == "reserved"
            seen["settle"] = client.post(f"/api/system/uncertain-calls/{row['id']}/resolve", headers=HUMAN,
                                         json={"cost_usd": "0", "note": "Synthetic settlement"})
            with pytest.raises(calls.BudgetExceeded):  # the active call's maximum is still committed
                calls.invoke(run_id="audit", step_id="second", provider="openai", model="fake", budget_scope="audit",
                             max_cost_usd=Decimal("0.1"), fn=lambda: calls.Outcome(response={}, cost_usd=Decimal("0.1")))
            return calls.Outcome(response={}, cost_usd=Decimal("0.1"))

        calls.invoke(run_id="audit", step_id="first", provider="openai", model="fake", budget_scope="audit",
                     max_cost_usd=Decimal("0.1"), fn=in_flight)
        assert seen["settle"].status_code == 409
        assert calls.journal("audit")[0]["status"] == "succeeded"
        assert calls.budget_usage("audit")["committed_usd"] == Decimal("0.1")


def test_an_active_call_cannot_be_settled_from_the_command_line_either(tmp_path):
    with store.use_store(tmp_path / "jav.sqlite"):
        calls._reserve(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.2"),
                       budget_scope=None, request_hash=None)  # still in progress: nobody marked it uncertain
        inv_id = calls.journal("r1")[0]["id"]
        with pytest.raises(calls.NotUncertain, match="still in progress"):
            calls.resolve_uncertain(inv_id, cost_usd=Decimal("0"), note="too early")
        assert calls.journal("r1")[0]["status"] == "reserved"


def test_an_uncertain_call_is_settled_once(tmp_path):
    with store.use_store(tmp_path / "jav.sqlite"):
        calls._reserve(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.2"),
                       budget_scope=None, request_hash=None)
        assert calls.recover_uncertain() == 1
        inv_id = calls.journal("r1")[0]["id"]
        calls.resolve_uncertain(inv_id, cost_usd=Decimal("0.07"), note="checked on the provider's console")
        with pytest.raises(calls.NotUncertain):
            calls.resolve_uncertain(inv_id, cost_usd=Decimal("0"), note="second settlement")
        assert calls.journal("r1")[0]["cost_usd"] == "0.07"


def test_a_late_answer_does_not_overwrite_a_manual_settlement(tmp_path):
    """A worker start marks every open reservation uncertain, also one a command-line measurement is still waiting
    on; if a person settles it in that window, the answer arriving afterwards must not rewrite the settlement."""
    with store.use_store(tmp_path / "jav.sqlite"):
        def answered_after_settlement():
            assert calls.recover_uncertain() == 1  # another process (the worker) starts meanwhile
            calls.resolve_uncertain(calls.journal("r1")[0]["id"], cost_usd=Decimal("0.05"), note="settled by hand")
            return calls.Outcome(response={"ok": True}, cost_usd=Decimal("0.02"))

        calls.invoke(run_id="r1", step_id="s1", provider="openai", model="m", max_cost_usd=Decimal("0.2"),
                     fn=answered_after_settlement)
        row = calls.journal("r1")[0]
        assert row["status"] == "failed" and row["cost_usd"] == "0.05" and "settled by hand" in row["note"]
