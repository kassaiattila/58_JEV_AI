"""066 Á32: a teendő-okok felvétele, lezárása és emberi rendezése olvas, dönt, majd ír; írási zár nélkül két párhuzamos
hívás (két felhasználó, feldolgozó + felület) ugyanarra az iratra két nyitott tételt hozhatott létre, vagy ugyanazt az
okot kétszer rendezhette. Most az olvasás már az írási zár alatt történik (`BEGIN IMMEDIATE`)."""

from __future__ import annotations

import pytest

from jav import store


@pytest.fixture()
def traced(tmp_path):
    with store.use_store(tmp_path / "t.sqlite"), store.session():
        with store.connect() as c:
            statements: list[str] = []
            c.set_trace_callback(statements.append)
        yield statements


def _lock_precedes_first_read(statements: list[str], table: str) -> bool:
    first_read = next(i for i, s in enumerate(statements) if s.lstrip().upper().startswith("SELECT") and table in s)
    return any(s.strip().upper() == "BEGIN IMMEDIATE" for s in statements[:first_read])


def test_enqueue_reads_under_the_write_lock(traced):
    store.review_enqueue(subject_kind="document", subject_id="d1", run_id="r1", reasons=["x:1"], producer="m2:S")
    assert _lock_precedes_first_read(traced, "review_queue")


def test_close_reads_under_the_write_lock(traced):
    store.review_enqueue(subject_kind="document", subject_id="d1", run_id="r1", reasons=["x:1"], producer="m2:S")
    traced.clear()
    assert store.review_close(subject_kind="document", subject_id="d1", producer="m2:S") == 1
    assert _lock_precedes_first_read(traced, "review_queue")


def test_resolve_reads_under_the_write_lock_and_refuses_a_second_resolution(traced):
    store.review_enqueue(subject_kind="document", subject_id="d1", run_id="r1", reasons=["x:1"], producer="m2:S")
    rid = store.review_open_reasons("document", "d1")[0]["id"]
    traced.clear()
    store.review_resolve(rid, actor="a")
    assert _lock_precedes_first_read(traced, "review_reasons")
    with pytest.raises(ValueError):
        store.review_resolve(rid, actor="b")
