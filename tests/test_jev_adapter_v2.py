"""Jev keret-kör 1 / adapter (BACKLOG 1) - offline, hamis klienssel.

- az alias (`jev-latest`) konkrét modellverzióra oldódik egy apró szondával, a verzió a cache-kulcsban;
- a feloldás fájlban marad (`runs/cache/_model_versions.json`), TTL-lel, offline is használható;
- RetryPolicy a `configs/models.json`-ból;
- SDK-kivétel -> ledger-sor (`error` oszlop) + `JevUnavailableError`, a flow nem dől el (review-latch);
- `TYPESAFE_LOG_LEVEL=debug` védelem (PII a naplóban).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx2
import pytest
from typesafe_sdk import Choice, RetryPolicy, SystemOneResponse, TypeSafeAPIConnectionError, TypeSafeRateLimitError

from jav import config, store
from jav.adapters.jev import MODEL_VERSIONS_FILE, JevAdapter, JevUnavailableError, request_hash


class FakeClient:
    def __init__(self, model_name: str = "jev-9.9.9", fail: Exception | None = None) -> None:
        self.calls = 0
        self.model_name = model_name
        self.fail = fail
        self.seen_models: list[str] = []

    def system_one(self, *, state, questions, model):
        self.calls += 1
        self.seen_models.append(model)
        if self.fail is not None:
            raise self.fail
        answers = {}
        for qid, q in questions.items():
            if isinstance(q, Choice):
                first = next(iter(q.criteria))
                answers[qid] = {"type": "choice", "choice": first, "confidence": 0.9, "probabilities": {k: (0.9 if k == first else 0.1) for k in q.criteria}}
            else:
                answers[qid] = {"type": "noul", "noul": 0.2}
        return SystemOneResponse.model_validate({"model": self.model_name, "usage": {"input_tokens": 100, "output_tokens": 1}, "answers": answers})


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    return tmp_path


QS = {"pick": Choice(instructions="which?", criteria={"a": None, "none": "n"})}
STATE = {"lines": ["L01: a"]}


def test_alias_resolves_to_concrete_version_in_cache_key(isolated: Path):
    client = FakeClient("jev-9.9.9")
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-latest")
    r = jev.ask("t", STATE, QS, run_id="run-1")

    assert jev.resolved_model == "jev-9.9.9"
    assert r.cache_key == request_hash("jev-9.9.9", STATE, QS)  # a konkrét verzió a kulcsban, nem az alias
    assert client.calls == 2  # szonda + a valódi hívás
    assert client.seen_models == ["jev-latest", "jev-latest"]  # a kérésben az alias marad (azt kéri a felhasználó)
    assert r.call.model == "jev-9.9.9"

    versions = json.loads((isolated / "cache" / MODEL_VERSIONS_FILE).read_text(encoding="utf-8"))
    assert versions["jev-latest"]["model"] == "jev-9.9.9" and versions["jev-latest"]["resolved_at"]

    # a szonda is a ledgerben van (step=model_probe), költséggel
    rows = store.ledger_for_run("run-1")
    assert [r_["step"] for r_ in rows] == ["model_probe", "t"]

    # második adapter ugyanazzal a cache-mappával: a fájlból olvas, nem szondáz újra
    client2 = FakeClient("jev-9.9.9")
    jev2 = JevAdapter(client=client2, cache_dir=isolated / "cache", model="jev-latest")
    r2 = jev2.ask("t", STATE, QS, run_id="run-2")
    assert client2.calls == 0 and r2.cached and r2.cache_key == r.cache_key


def test_concrete_model_needs_no_probe(isolated: Path):
    client = FakeClient("jev-1.13.0")
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.13.0")
    jev.ask("t", STATE, QS, run_id="run-1")
    assert client.calls == 1 and jev.resolved_model == "jev-1.13.0"
    assert not (isolated / "cache" / MODEL_VERSIONS_FILE).exists()


def test_stale_resolution_is_refreshed_and_offline_falls_back(isolated: Path):
    cache = isolated / "cache"
    cache.mkdir()
    (cache / MODEL_VERSIONS_FILE).write_text(json.dumps({"jev-latest": {"model": "jev-1.0.0", "resolved_at": "2000-01-01T00:00:00+00:00"}}), encoding="utf-8")

    # lejárt TTL + elérhető API: friss szonda, a fájl frissül
    client = FakeClient("jev-2.0.0")
    jev = JevAdapter(client=client, cache_dir=cache, model="jev-latest")
    assert jev.resolved_model == "jev-2.0.0" and client.calls == 1
    assert json.loads((cache / MODEL_VERSIONS_FILE).read_text(encoding="utf-8"))["jev-latest"]["model"] == "jev-2.0.0"

    # lejárt TTL, de az API nem elérhető: a régi feloldás marad (cache-találatok offline is működnek)
    (cache / MODEL_VERSIONS_FILE).write_text(json.dumps({"jev-latest": {"model": "jev-1.0.0", "resolved_at": "2000-01-01T00:00:00+00:00"}}), encoding="utf-8")
    jev_off = JevAdapter(client=FakeClient(fail=TypeSafeAPIConnectionError("down")), cache_dir=cache, model="jev-latest")
    assert jev_off.resolved_model == "jev-1.0.0"

    # nincs fájl és nincs API: nem oldható fel -> JevUnavailableError
    (cache / MODEL_VERSIONS_FILE).unlink()
    jev_none = JevAdapter(client=FakeClient(fail=TypeSafeAPIConnectionError("down")), cache_dir=cache, model="jev-latest")
    with pytest.raises(JevUnavailableError) as ei:
        _ = jev_none.resolved_model
    assert ei.value.reason.startswith("TypeSafeAPIConnectionError")


def test_retry_policy_comes_from_models_json():
    raw = json.loads(config.MODELS_CONFIG.read_text(encoding="utf-8"))["jev"]
    assert raw["cache_version"] == 2  # a modellverzió a kulcsban: egyszeri érvénytelenítés a verzió-lépéssel együtt
    assert config.JEV_CACHE_VERSION == 2
    rp = config.build_retry_policy()
    assert isinstance(rp, RetryPolicy)
    assert rp.max_retries == raw["retry"]["max_retries"] and rp.backoff_max == raw["retry"]["backoff_max"]
    assert rp.timeout == raw["retry"]["timeout"] and rp.timeout > config.JEV_TIMEOUT_S  # a keret nagyobb, mint egy kérés időkorlátja
    assert 429 in rp.http_statuses and 503 in rp.http_statuses


def test_sdk_error_is_ledgered_and_raised_as_unavailable(isolated: Path):
    err = TypeSafeRateLimitError(429, {"detail": "slow down"}, httpx2.Headers({"retry-after-ms": "1500"}))
    client = FakeClient(fail=err)
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-1.13.0")
    with pytest.raises(JevUnavailableError) as ei:
        jev.ask("verify", STATE, QS, run_id="run-x", config_hash="abc")
    assert ei.value.reason == "TypeSafeRateLimitError:429"
    assert ei.value.retry_after_ms == 1500
    assert isinstance(ei.value.__cause__, TypeSafeRateLimitError)

    rows = store.ledger_for_run("run-x")
    assert len(rows) == 1
    row = rows[0]
    assert row["step"] == "verify" and row["cached"] == 0 and row["cost_usd"] == 0 and row["config_hash"] == "abc"
    assert row["error"] == "TypeSafeRateLimitError:429:retry_after_ms=1500"
    assert store.stats()["ledger_errors"] == 1


def test_unexpected_exception_is_not_swallowed(isolated: Path):
    jev = JevAdapter(client=FakeClient(fail=KeyError("bug")), cache_dir=isolated / "cache", model="jev-1.13.0")
    with pytest.raises(KeyError):  # programhiba nem "unavailable"
        jev.ask("t", STATE, QS, run_id="run-y")


def test_sdk_log_level_guard(monkeypatch: pytest.MonkeyPatch):
    logger = logging.getLogger("typesafe_sdk")
    monkeypatch.setenv("TYPESAFE_LOG_LEVEL", "debug")
    monkeypatch.delenv("JAV_ALLOW_SDK_DEBUG", raising=False)
    logger.setLevel(logging.DEBUG)
    assert config.guard_sdk_logging() is True
    assert logger.level == logging.WARNING  # a body PII-t tartalmaz: debug csak kifejezett engedéllyel

    monkeypatch.setenv("JAV_ALLOW_SDK_DEBUG", "1")
    logger.setLevel(logging.DEBUG)
    assert config.guard_sdk_logging() is False
    assert logger.level == logging.DEBUG

    monkeypatch.delenv("TYPESAFE_LOG_LEVEL")
    logger.setLevel(logging.NOTSET)
    assert config.guard_sdk_logging() is False


# --- a flow-k nem dőlnek el ------------------------------------------------------------------------


def _failing_adapter(tmp: Path) -> JevAdapter:
    return JevAdapter(client=FakeClient(fail=TypeSafeAPIConnectionError("down")), cache_dir=tmp / "cache", model="jev-1.13.0")


def test_email_flow_survives_jev_outage(isolated: Path, monkeypatch: pytest.MonkeyPatch):
    from jav import flow_email
    from jav.adapters import jev as jev_mod
    from jav.emails import EmailMessage

    monkeypatch.setattr(jev_mod, "get_adapter", lambda: _failing_adapter(isolated))
    msg = EmailMessage(message_id="m-1", subject="Számla", body="Mellékelten küldöm a számlát.")
    st = flow_email.run_email(message=msg, detect_attachments=False)

    assert st.final_status == "jev_unavailable" and st.result is None and st.uncertain
    assert st.next_flow == "human:jev_unavailable"
    assert any(r.startswith("jev_unavailable:TypeSafeAPIConnectionError") for r in st.review_reasons)
    s = store.stats()
    assert s["emails"] == 1 and s["review_open"] == 1
    with store.connect() as c:
        q = c.execute("SELECT reasons FROM review_queue").fetchone()
    assert "jev_unavailable" in q["reasons"]


def test_detect_step_survives_jev_outage(isolated: Path, monkeypatch: pytest.MonkeyPatch):
    from jav import flow_detect
    from jav.adapters import jev as jev_mod

    monkeypatch.setattr(jev_mod, "get_adapter", lambda: _failing_adapter(isolated))
    st = flow_detect.DetectState(source_path="x.pdf", run_id="r", text="SZÁMLA", lines=["SZÁMLA"], page_count=1, has_text_layer=True, doc_id="d1")
    st = flow_detect.detect(st)
    assert st.result is None and st.uncertain and st.review_reasons and st.review_reasons[0].startswith("jev_unavailable:")
    st = flow_detect.save(st)
    assert st.final_status == "jev_unavailable"
    assert store.stats()["review_open"] == 1


def test_invoice_steps_survive_jev_outage(isolated: Path, monkeypatch: pytest.MonkeyPatch):
    from jav import flow
    from jav.adapters import jev as jev_mod
    from jav.models import FlowState, InvoiceLLM

    monkeypatch.setattr(jev_mod, "get_adapter", lambda: _failing_adapter(isolated))
    s = flow.jev_select(FlowState(source_path="x.pdf", case_id="c", arm="S", candidates={"supplier_name": []}))
    assert s.picks == {} and s.needs_review and s.review_reasons[0].startswith("jev_unavailable:")
    g = flow.jev_verify(FlowState(source_path="x.pdf", case_id="c", arm="G", llm_output=InvoiceLLM(supplier_name="X").model_dump()))  # a kivonat szótár (típus-csomagok)
    assert g.verdicts is None and g.needs_review and g.review_reasons[0].startswith("jev_unavailable:")


def test_alias_switch_within_the_ttl_keys_the_answer_by_the_answering_version(isolated: Path):
    """066 Á17: a feloldás TTL-je alatt a szolgáltató az álnevet új verzióra állítja. A válasz ne a régi verzió kulcsa alá
    kerüljön (különben egy későbbi „ugyanaz a modell” gyorsítótár-találat más verzió válasza lenne), és a feloldás frissüljön."""
    client = FakeClient("jev-9.9.9")
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-latest")
    jev.ask("t", STATE, QS, run_id="r1")
    client.model_name = "jev-10.0.0"
    other = {"lines": ["L01: b"]}
    r = jev.ask("t", other, QS, run_id="r2")

    assert r.call.model == "jev-10.0.0"
    assert r.cache_key == request_hash("jev-10.0.0", other, QS)
    assert (isolated / "cache" / f"{r.cache_key}.json").exists()
    assert not (isolated / "cache" / f"{request_hash('jev-9.9.9', other, QS)}.json").exists()
    assert jev.resolved_model == "jev-10.0.0"
    versions = json.loads((isolated / "cache" / MODEL_VERSIONS_FILE).read_text(encoding="utf-8"))
    assert versions["jev-latest"]["model"] == "jev-10.0.0"
    row = store.ledger_for_run("r2")[-1]
    assert row["model"] == "jev-10.0.0" and row["cache_key"] == r.cache_key

    # egy új adapter a frissített feloldással a mentett választ találja, élő hívás nélkül
    client2 = FakeClient("jev-10.0.0")
    r2 = JevAdapter(client=client2, cache_dir=isolated / "cache", model="jev-latest").ask("t", other, QS, run_id="r3")
    assert r2.cached and client2.calls == 0


def test_a_damaged_cache_file_is_a_miss_and_is_rewritten_atomically(isolated: Path):
    """066 Á37: egy félbeszakadt írásból maradt, olvashatatlan gyorsítótár-fájl ne állítsa meg a folyamatot: kihagyjuk,
    élőben kérdezünk, és az új válasz ideiglenes fájlon át, cserével kerül a helyére."""
    client = FakeClient("jev-9.9.9")
    jev = JevAdapter(client=client, cache_dir=isolated / "cache", model="jev-9.9.9")
    key = request_hash("jev-9.9.9", STATE, QS)
    (isolated / "cache").mkdir(parents=True, exist_ok=True)
    (isolated / "cache" / f"{key}.json").write_text('{"model": "jev-9.9.9", "answ', encoding="utf-8")
    r = jev.ask("t", STATE, QS, run_id="r1")
    assert not r.cached and client.calls == 1
    again = jev.ask("t", STATE, QS, run_id="r1")
    assert again.cached and client.calls == 1
    assert not list((isolated / "cache").glob("*.tmp"))
