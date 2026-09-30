"""Jev-adapter (kérés-hash cache + ledger) és SQLite adattár - offline, hamis klienssel."""

from pathlib import Path

import pytest
from typesafe_sdk import Choice, Noul, SystemOneResponse

from jav import store
from jav.adapters.jev import JevAdapter, request_hash


class FakeClient:
    """Determinisztikus válasz; számolja a hívásokat, hogy a cache-találat mérhető legyen."""

    def __init__(self) -> None:
        self.calls = 0
        self.noul = 0.2  # a Noul-válasz; a teszt átállítja, hogy a cache-felülírás mérhető legyen

    def system_one(self, *, state, questions, model):
        self.calls += 1
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                first = next(iter(q.criteria))
                answers[qid] = {"type": "choice", "choice": first, "confidence": 0.9, "probabilities": {k: (0.9 if k == first else 0.1) for k in q.criteria}}
            else:
                answers[qid] = {"type": "noul", "noul": self.noul}
        return SystemOneResponse.model_validate({"model": model, "usage": {"input_tokens": 1000, "output_tokens": 10}, "answers": answers})


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    return tmp_path


def test_request_hash_is_canonical():
    q1 = {"b": Noul(instructions="x"), "a": Choice(instructions="y", criteria={"k": None})}
    q2 = {"a": Choice(instructions="y", criteria={"k": None}), "b": Noul(instructions="x")}
    assert request_hash("jev-latest", {"z": 1, "a": 2}, q1) == request_hash("jev-latest", {"a": 2, "z": 1}, q2)
    assert request_hash("jev-latest", {"a": 2}, q1) != request_hash("jev-latest", {"a": 3}, q1)
    assert request_hash("jev-latest", {"a": 2}, q1) != request_hash("jev-preview", {"a": 2}, q1)


def test_cache_hit_costs_nothing_and_is_ledgered(isolated: Path):
    client = FakeClient()
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.13.0")  # konkrét verzió: nincs alias-szonda
    qs = {"pick": Choice(instructions="which?", criteria={"a": None, "none": "n"})}

    r1 = jev.ask("t", {"lines": ["L01: a"]}, qs, run_id="run-1")
    r2 = jev.ask("t", {"lines": ["L01: a"]}, qs, run_id="run-2")
    r3 = jev.ask("t", {"lines": ["L01: a"]}, qs, run_id="run-3", use_cache=False)

    assert client.calls == 2  # r2 cache-ből
    assert (r1.cached, r2.cached, r3.cached) == (False, True, False)
    assert r1.call.cost_usd > 0 and r2.call.cost_usd == 0
    assert r2.response.choices["pick"].choice == "a"
    assert r1.cache_key == r2.cache_key == r3.cache_key

    rows = store.ledger_for_run("run-2")
    assert len(rows) == 1 and rows[0]["cached"] == 1 and rows[0]["provider"] == "jev"
    assert store.stats()["ledger"] == 3


def test_no_cache_write_context_keeps_reference_answer(isolated: Path):
    """Determinizmus-futás: `use_cache=False` a `no_cache_write()` alatt nem írja felül a referencia-választ."""
    client = FakeClient()
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.13.0")
    qs = {"flag": Noul(instructions="is it?")}
    state = {"lines": ["L01: a"]}

    ref = jev.ask("t", state, qs, run_id="ref")  # referencia: noul 0.2 a cache-ben
    client.noul = 0.7
    with jev.no_cache_write():
        live = jev.ask("t", state, qs, run_id="det-1", use_cache=False)
    again = jev.ask("t", state, qs, run_id="ref-2")  # cache-találat, a referencia marad

    assert (ref.cached, live.cached, again.cached) == (False, False, True)
    assert live.response.nouls["flag"].noul == 0.7
    assert again.response.nouls["flag"].noul == 0.2
    assert jev.write_cache is True  # a kontextus után visszaáll

    # a kontextuson kívül a `use_cache=False` futás továbbra is frissíti a cache-t (referencia-frissítés)
    client.noul = 0.9
    jev.ask("t", state, qs, run_id="refresh", use_cache=False)
    assert jev.ask("t", state, qs, run_id="ref-3").response.nouls["flag"].noul == 0.9


def test_store_documents_datapoints_review(isolated: Path):
    store.upsert_document(doc_id="d1", source_path="x.pdf", has_text=True, page_count=1, year=2022, doc_type="invoice_hu", run_id="r1")
    store.upsert_document(doc_id="d1", source_path="x.pdf", type_conf=0.9)  # additív frissítés
    store.insert_datapoints(
        run_id="r1", doc_id="d1", doc_type="invoice_hu", arm="S", datapoints={"gross_total": "1"},
        field_conf={"gross_total": 0.99}, validation=[], route="human", review_reasons=["x"], final_status="needs_review",
    )
    qid = store.review_enqueue(subject_kind="document", subject_id="d1", run_id="r1", reasons=["x"])
    s = store.stats()
    assert s["documents"] == 1 and s["datapoints"] == 1 and s["review_open"] == 1 and qid >= 1
    assert s["doc_types"] == [{"doc_type": "invoice_hu", "n": 1}]
    with store.connect() as c:
        row = c.execute("SELECT doc_type, type_conf, year FROM documents WHERE doc_id='d1'").fetchone()
        assert (row["doc_type"], row["type_conf"], row["year"]) == ("invoice_hu", 0.9, 2022)
