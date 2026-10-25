"""231 (plan stage C, C2a): connectors, the one way to ask an external service.

Each service is described once as data (`configs/connectors.json`); `connectors.ask` keeps to the description (its
timeout, answer limit, retries and rate limit) and writes every attempt into the call log under the connector's name.
A free lookup changes nothing, so an answer lost after sending is a plain failure, never an uncertain call a person
must settle; a priced one reserves its price from the running work's budget and is refused outside one. No test
reaches the network.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from jav.core import calls, cfg, connectors, store

MNB = connectors.of("mnb_rates")


def _described(**changes) -> dict:
    """The MNB description with `changes`, as a test connector `probe` beside the real ones."""
    raw = {"what": "A stand-in lookup", "kind": "lookup", "url": "http://example.invalid/ask", "headers": {"X-Probe": "1"},
           "sends": ["a code"], "price_usd": "0", "timeout_s": 5, "retries": 0, "retry_wait_s": 0, "max_per_minute": 30,
           "max_response_bytes": 100}
    return {"mnb_rates": dict(cfg.load("connectors")["connectors"]["mnb_rates"]), "probe": raw | changes}


@pytest.fixture
def db(tmp_path):
    with store.use_store(tmp_path / "connectors.sqlite"):
        yield


@pytest.fixture
def probe(monkeypatch):
    def describe(**changes):
        monkeypatch.setattr(connectors, "_described", lambda: _described(**changes))

    describe()
    return describe


class Service:
    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, url, body, headers, timeout):
        self.asked.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _calls() -> list[dict]:
    with store.connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM invocations ORDER BY id")]


# --- the descriptions -------------------------------------------------------------------------------------------------


def test_every_described_connector_fits_the_rules():
    described = connectors.catalogue()
    assert [c.name for c in described] == sorted(c.name for c in described) and described
    assert all(c.kind == "lookup" and c.sends for c in described)


def test_the_mnb_connector_keeps_the_earlier_settings():
    assert (MNB.url, MNB.timeout_s, MNB.max_response_bytes, MNB.retries) == ("http://www.mnb.hu/arfolyamok.asmx", 20.0,
                                                                              5_000_000, 0)
    assert MNB.headers["SOAPAction"] == '"http://www.mnb.hu/webservices/MNBArfolyamServiceSoap/GetExchangeRates"'
    assert MNB.free and MNB.sends == ("two dates", "currency codes")


@pytest.mark.parametrize("changes, why", [
    ({"kind": "handover"}, "its kind is one of lookup"),
    ({"url": "ftp://example.invalid"}, "http or https"),
    ({"sends": []}, "what leaves the machine"),
    ({"price_usd": "-1"}, "at least 0"),
    ({"retries": -1}, "retries is a whole number"),
    ({"max_per_minute": 0}, "max_per_minute"),
    ({"timeout_s": 0}, "timeout_s"),
])
def test_a_description_that_does_not_fit_is_refused_by_name(probe, changes, why):
    probe(**changes)
    with pytest.raises(connectors.ConnectorError, match=why):
        connectors.of("probe")


def test_an_undescribed_connector_is_a_named_error():
    with pytest.raises(connectors.ConnectorError, match="no connector nowhere"):
        connectors.of("nowhere")


# --- asking -------------------------------------------------------------------------------------------------------------


def test_a_question_goes_to_the_described_address_and_into_the_call_log(db, probe):
    service = Service(b"<answer/>")
    with connectors.use_transport(service):
        assert connectors.ask("probe", b"<q/>", purpose="check") == b"<answer/>"
    assert service.asked == [{"url": "http://example.invalid/ask", "body": b"<q/>", "headers": {"X-Probe": "1"},
                              "timeout": 5.0}]
    [row] = _calls()
    assert (row["run_id"], row["provider"], row["status"], row["cost_usd"], row["budget_scope"]) == (
        "connector:probe", "probe", "succeeded", "0", None)
    assert row["step_id"].startswith("check:") and row["note"] == calls.REPEATABLE_NOTE
    with store.connect() as c:
        saved = c.execute("SELECT payload FROM artifacts WHERE kind=? AND artifact_id=?",
                          (calls.RESPONSE_KIND, str(row["id"]))).fetchone()["payload"]
    assert "answer" not in saved and '"bytes": 9' in saved  # the answer's size and digest, not its content


def test_each_question_is_its_own_call(db, probe):
    with connectors.use_transport(Service(b"a", b"b")):
        assert [connectors.ask("probe", b"q", purpose="check") for _ in range(2)] == [b"a", b"b"]
    assert [r["status"] for r in _calls()] == ["succeeded", "succeeded"]


def test_an_unreached_service_is_a_named_failure_in_the_call_log(db, probe):
    with connectors.use_transport(Service(OSError("down"))), pytest.raises(connectors.ConnectorUnavailable) as exc:
        connectors.ask("probe", b"q", purpose="check")
    assert (exc.value.reason, exc.value.error) == ("unreachable", "OSError")
    [row] = _calls()
    assert row["status"] == "failed" and "OSError" in row["error"]


def test_a_lost_answer_of_a_free_lookup_is_a_plain_failure_not_uncertain(db, probe):
    with connectors.use_transport(Service(TimeoutError("read timed out"))), pytest.raises(connectors.ConnectorUnavailable):
        connectors.ask("probe", b"q", purpose="check")
    assert [r["status"] for r in _calls()] == ["failed"] and calls.uncertain_list() == []


def test_an_answer_over_the_limit_is_refused(db, probe):
    with connectors.use_transport(Service(b"x" * 101)), pytest.raises(connectors.ConnectorUnavailable) as exc:
        connectors.ask("probe", b"q", purpose="check")
    assert exc.value.reason == "too_large" and [r["status"] for r in _calls()] == ["failed"]


def test_an_unreached_service_is_asked_again_up_to_its_retries(db, probe):
    probe(retries=2)
    service = Service(OSError("down"), OSError("down"), b"ok")
    with connectors.use_transport(service):
        assert connectors.ask("probe", b"q", purpose="check") == b"ok"
    assert len(service.asked) == 3 and [r["status"] for r in _calls()] == ["failed", "failed", "succeeded"]


def test_an_answer_over_the_limit_is_not_asked_again(db, probe):
    probe(retries=2)
    service = Service(b"x" * 101)
    with connectors.use_transport(service), pytest.raises(connectors.ConnectorUnavailable):
        connectors.ask("probe", b"q", purpose="check")
    assert len(service.asked) == 1


def test_the_rate_limit_sends_nothing_more_within_the_minute(db, probe):
    probe(max_per_minute=2)
    service = Service(b"a")
    with connectors.use_transport(service):
        connectors.ask("probe", b"q", purpose="check")
        connectors.ask("probe", b"q", purpose="check")
        with pytest.raises(connectors.ConnectorUnavailable) as exc:
            connectors.ask("probe", b"q", purpose="check")
    assert exc.value.reason == "busy" and len(service.asked) == 2 and len(_calls()) == 2


def test_a_priced_lookup_is_refused_outside_a_budget(db, probe):
    probe(price_usd="0.05")
    service = Service(b"a")
    with connectors.use_transport(service), pytest.raises(calls.BudgetExceeded, match="only within a budget"):
        connectors.ask("probe", b"q", purpose="check")
    assert service.asked == [] and _calls() == []


def test_a_priced_lookup_reserves_from_the_budget_and_a_lost_answer_stays_uncertain(db, probe):
    probe(price_usd="0.05")
    with calls.outside_run("case:c1:check:1", {"probe": Decimal("0.10")}):
        with connectors.use_transport(Service(b"a")):
            connectors.ask("probe", b"q", purpose="check")
        with connectors.use_transport(Service(TimeoutError("read timed out"))), pytest.raises(connectors.ConnectorUnavailable):
            connectors.ask("probe", b"q", purpose="check")
        with connectors.use_transport(Service(b"a")), pytest.raises(calls.BudgetExceeded):
            connectors.ask("probe", b"q", purpose="check")  # 0.05 spent + 0.05 still committed by the uncertain one
    assert [(r["status"], r["budget_scope"]) for r in _calls()] == [("succeeded", "case:c1:check:1"),
                                                                    ("uncertain", "case:c1:check:1")]


def test_the_network_reading_stops_after_the_limit(monkeypatch):
    seen = {}

    class Answer:
        def read(self, n=-1):
            seen["read"] = n
            return b"x" * 10

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(request, timeout):
        seen.update(method=request.get_method(), timeout=timeout)
        return Answer()

    monkeypatch.setattr(connectors.urllib.request, "urlopen", urlopen)
    assert connectors._network(100)("http://example.invalid", b"q", {}, 3.0) == b"x" * 10
    assert seen == {"method": "POST", "timeout": 3.0, "read": 101}
    connectors._network(100)("http://example.invalid", None, {}, 3.0)
    assert seen["method"] == "GET"


def test_a_free_question_left_open_by_a_stopped_process_closes_as_failed(db):
    with store.connect() as c:
        for step, note in (("free", calls.REPEATABLE_NOTE), ("paid", None)):
            c.execute("INSERT INTO invocations(run_id, step_id, attempt, provider, status, max_cost_usd, note, created_at)"
                      " VALUES ('connector:probe', ?, 1, 'probe', 'reserved', '0', ?, '2026-10-25T08:00:00+00:00')",
                      (step, note))
    assert calls.recover_uncertain() == 1
    assert {r["step_id"]: r["status"] for r in _calls()} == {"free": "failed", "paid": "uncertain"}


def test_only_a_free_call_is_repeatable(db):
    with pytest.raises(ValueError, match="repeatable"):
        calls.invoke(run_id="r", step_id="s", provider="probe", model=None, max_cost_usd=Decimal("0.01"),
                     fn=lambda: calls.Outcome(response=None), repeatable=True)


def test_the_exchange_rates_are_asked_through_their_connector(db):
    from jav.domains.finance import fx
    from tests.test_fx_130 import WEEK, Service as RateService

    with fx.use_transport(RateService(WEEK)):
        assert fx.fetch(date(2026, 10, 1), date(2026, 10, 2), ["USD"]) == 2
    [row] = _calls()
    assert (row["provider"], row["run_id"], row["status"]) == ("mnb_rates", "connector:mnb_rates", "succeeded")
    assert row["step_id"].startswith("fx_fetch:")
