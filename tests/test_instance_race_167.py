"""167 (review R-7): a package deleted while a document is being added does not take the added document's copy.

The same content is kept once (`jav/source_instances.py`). Adding a document copies it first and records the item
afterwards; a package deleted in between released the shared copy (no item referred to it at that moment), so the new
item later stopped with "the copy kept when it was added is missing". The add now checks its copies inside the
transaction that records the items and makes a missing one again; an original that changed meanwhile is refused.

Synthetic PDFs, no paid calls.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from jav import app_settings, source_instances, store, work, work_readiness  # noqa: F401  (app_settings: its tables, read by readiness)
from tests.pdfgen import INVOICE_LINES, write_text_pdf


@pytest.fixture()
def env(tmp_path: Path):
    shared = tmp_path / "shared.pdf"
    write_text_pdf(shared, INVOICE_LINES)
    with store.use_store(tmp_path / "w.sqlite"):
        old = work.create_from_files([shared], name="Old package")
        target = work.create_workpackage(name="Target", source_kind="files", source_ref=None, owner=None)
        yield {"tmp": tmp_path, "shared": shared, "old": old, "target": target}


def _delete_meanwhile(monkeypatch, wp_id: str, then=None) -> None:
    """The deletion runs right after the add has made (or found) its copy, before the add records the item."""
    real = source_instances.freeze
    copies = []

    def freeze_then_delete(path, **kwargs):
        result = real(path, **kwargs)
        copies.append(result)
        if len(copies) == 1:  # only the first copy; the add's own second copy runs inside its transaction
            work.delete_workpackage(wp_id, actor="someone else")
            if then is not None:
                then(path)
        return result

    monkeypatch.setattr(source_instances, "freeze", freeze_then_delete)


def test_a_deletion_between_the_copy_and_the_record_does_not_leave_the_item_without_its_copy(env, monkeypatch):
    rel = env["old"]["items"][0]["instance"]
    _delete_meanwhile(monkeypatch, env["old"]["id"])
    wp = work.add_documents(env["target"]["id"], [env["shared"]], expected_revision=0)
    item = wp["items"][0]
    assert item["instance"] == rel
    assert source_instances.intact(source_instances.path_of(rel), item["sha256"])
    codes = [b["code"] for b in work_readiness.readiness(wp["id"], verify=True)["blockers"]]
    assert "instance_damaged" not in codes


def test_an_original_changed_before_the_copy_is_made_again_is_refused(env, monkeypatch):
    def change(path: Path) -> None:
        write_text_pdf(path, [line.replace("MINTA-2026-001", "MINTA-2026-009") for line in INVOICE_LINES])

    _delete_meanwhile(monkeypatch, env["old"]["id"], then=change)
    with pytest.raises(work.SourceChanged):
        work.add_documents(env["target"]["id"], [env["shared"]], expected_revision=0)
    assert work.get(env["target"]["id"])["items"] == []
    assert source_instances.files() == []  # neither the old copy nor a copy of the changed file is left behind


def test_an_add_without_interference_copies_once(env, monkeypatch):
    other = env["tmp"] / "other.pdf"
    write_text_pdf(other, INVOICE_LINES[:4])
    seen = []
    real = source_instances.freeze
    monkeypatch.setattr(source_instances, "freeze", lambda path, **kw: seen.append(path) or real(path, **kw))
    wp = work.add_documents(env["target"]["id"], [other], expected_revision=0)
    assert seen == [other.resolve()]
    assert wp["items"][0]["sha256"] == hashlib.sha256(other.read_bytes()).hexdigest()
