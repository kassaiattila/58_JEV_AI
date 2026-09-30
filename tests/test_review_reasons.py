"""Okonkénti teendőkezelés (040 K1, F04): egy ok rendezése nem zár le és nem ír felül más okot."""

import json
from pathlib import Path

import pytest

from jav import store


@pytest.fixture()
def isolated(tmp_path: Path):
    with store.use_store(tmp_path / "t.sqlite"):
        yield tmp_path


def _item(subject_id: str) -> dict:
    with store.connect() as c:
        row = c.execute("SELECT * FROM review_queue WHERE subject_id=? ORDER BY id DESC", (subject_id,)).fetchone()
    return dict(row)


def test_prefix_close_keeps_unrelated_reason_open(isolated):
    """A 038-as F04 szonda: intent-ok lezárása nem zárhatja le a biztonsági okot."""
    store.review_enqueue(subject_kind="email", subject_id="mixed", run_id="one", reasons=["intent:low_conf", "security:unreviewed"])
    closed = store.review_close(subject_kind="email", subject_id="mixed", reason_prefix="intent:")
    item = _item("mixed")
    assert closed == 1
    assert item["status"] == "open"
    assert json.loads(item["reasons"]) == ["security:unreviewed"]
    assert [r["reason"] for r in store.review_open_reasons("email", "mixed")] == ["security:unreviewed"]


def test_item_closes_only_when_last_reason_closes(isolated):
    store.review_enqueue(subject_kind="email", subject_id="m", run_id="r1", reasons=["intent:low_conf"])
    store.review_close(subject_kind="email", subject_id="m", reason_prefix="intent:")
    item = _item("m")
    assert item["status"] == "superseded" and item["decided_at"]


def test_other_producer_does_not_overwrite_reasons(isolated):
    """A típusfelismerés és a számlakivonat ugyanarra az iratra ír: egyik sem törli a másik okát."""
    store.review_enqueue(subject_kind="document", subject_id="d", run_id="r1", reasons=["detect:low_conf:invoice_hu:0.55"],
                         producer="detect")
    store.review_enqueue(subject_kind="document", subject_id="d", run_id="r2", reasons=["S_G_disagree:gross_total"],
                         producer="m2")
    assert sorted(json.loads(_item("d")["reasons"])) == ["S_G_disagree:gross_total", "detect:low_conf:invoice_hu:0.55"]


def test_same_producer_rerun_supersedes_its_stale_reasons(isolated):
    store.review_enqueue(subject_kind="document", subject_id="d", run_id="r1", reasons=["a:1", "a:2"], producer="m2")
    store.review_enqueue(subject_kind="document", subject_id="d", run_id="r1", reasons=["x:keep"], producer="detect")
    store.review_enqueue(subject_kind="document", subject_id="d", run_id="r2", reasons=["a:2", "a:3"], producer="m2")
    assert sorted(json.loads(_item("d")["reasons"])) == ["a:2", "a:3", "x:keep"]
    with store.connect() as c:
        stale = c.execute("SELECT status FROM review_reasons WHERE reason='a:1'").fetchone()
    assert stale["status"] == "superseded"


def test_producer_close_leaves_other_producers(isolated):
    store.review_enqueue(subject_kind="email", subject_id="e", run_id="r1", reasons=["jev_unavailable:TypeSafeAPIConnectionError"],
                         producer="email_intent")
    store.review_enqueue(subject_kind="email", subject_id="e", run_id="r1", reasons=["security:unreviewed"], producer="security")
    assert store.review_close(subject_kind="email", subject_id="e", producer="email_intent") == 1
    assert json.loads(_item("e")["reasons"]) == ["security:unreviewed"]


def test_human_resolution_is_per_reason_and_attributed(isolated):
    store.review_enqueue(subject_kind="document", subject_id="d", run_id="r1", reasons=["a:1", "b:1"])
    first = store.review_open_reasons("document", "d")[0]
    store.review_resolve(first["id"], actor="ugyintezo", resolution={"field": "gross_total", "value": "100"}, note="javítva")
    left = store.review_open_reasons("document", "d")
    assert [r["reason"] for r in left] == ["b:1"] and _item("d")["status"] == "open"
    with store.connect() as c:
        row = c.execute("SELECT status, actor, resolution, note, closed_at FROM review_reasons WHERE id=?", (first["id"],)).fetchone()
    assert row["status"] == "resolved" and row["actor"] == "ugyintezo" and row["closed_at"]
    assert json.loads(row["resolution"]) == {"field": "gross_total", "value": "100"}
    with pytest.raises(ValueError):
        store.review_resolve(first["id"], actor="x")  # már lezárt ok nem zárható újra


def test_duplicate_reason_is_not_added_twice(isolated):
    store.review_enqueue(subject_kind="email", subject_id="e", run_id="r1", reasons=["a:1", "a:1"])
    store.review_enqueue(subject_kind="email", subject_id="e", run_id="r2", reasons=["a:1"])
    assert len(store.review_open_reasons("email", "e")) == 1


def test_legacy_open_rows_are_migrated_to_reasons(tmp_path):
    """Meglévő adattár: a régi, csak JSON-os nyitott tétel okai sorokká válnak."""
    import sqlite3
    db = tmp_path / "old.sqlite"
    with store.use_store(db):
        with store.connect():
            pass
    with sqlite3.connect(db) as c:
        c.execute("DROP TABLE review_reasons")
        c.execute("INSERT INTO review_queue(subject_kind, subject_id, run_id, reasons, status, created_at)"
                  " VALUES ('email','old','r0','[\"intent:low_conf\",\"security:x\"]','open','2026-09-20')")
    with store.use_store(db):
        assert [r["reason"] for r in store.review_open_reasons("email", "old")] == ["intent:low_conf", "security:x"]
        store.review_close(subject_kind="email", subject_id="old", reason_prefix="intent:")
        assert json.loads(_item("old")["reasons"]) == ["security:x"]


def test_reason_raised_again_by_a_new_run_belongs_to_the_new_run(tmp_path):
    """045: ha egy új futás ugyanazt az okot veti fel, amely egy korábbi futásból még nyitva van, az ok az új futásé lesz
    (különben az új futás tévesen teendő nélkülinek látszana és jóváhagyható lenne)."""
    from jav import store
    with store.use_store(tmp_path / "r.sqlite"):
        store.review_enqueue(subject_kind="document", subject_id="d", run_id="regi:1", reasons=["pick:low_conf:x:0.5"], producer="m2:S")
        store.review_enqueue(subject_kind="document", subject_id="d", run_id="uj:1", reasons=["pick:low_conf:x:0.5"], producer="m2:S")
        reasons = store.review_open_reasons("document", "d")
        assert [(r["reason"], r["run_id"]) for r in reasons] == [("pick:low_conf:x:0.5", "uj:1")]
