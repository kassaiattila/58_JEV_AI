"""265 (plan L, L3): the free pre-estimate translates every request for OpenAI Decisions, never sending it.

Each request the measurement's steps ask is translated (`jav/ai/decisions_wire.py`): whether the API's limits admit
it, how the shared state goes, and what every request would cost at Decisions' uncached input price. Offline: no
client is made, nothing is sent and nothing is cached.
"""

from decimal import Decimal

from typesafe_sdk import Choice, Noul

from jav.core import store
from jav.evals.jev_estimate import EstimatingAdapter, report, summary


def test_every_request_is_translated_and_priced_for_decisions(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    est = EstimatingAdapter("jev-1.14.0", cache_dir=tmp_path / "cache", decisions=True)
    est.step = "detect-golden"
    est.ask("detect", {"head_lines": ["Számla", "Végösszeg"]},
            {"doc_type": Choice(instructions="Which type?", criteria={"invoice": {"what": "an invoice"}, "unknown": None}),
             "issuer_is_hungarian": Noul(instructions="Is the issuer Hungarian?")})
    est.ask("detect", {"document": "x" * 300_000}, {"q": Noul(instructions="?")})  # over the JSON part's limit
    est.ask("detect", {"x": 1}, {"one": Choice(criteria={"only": None})})  # a choice of one: not admitted
    assert est._client is None
    fits, as_text, unfit = est.requests
    assert fits.decisions_state == "input_json" and fits.decisions_chars > 0 and fits.decisions_unfit is None
    assert as_text.decisions_state == "input_text"
    assert unfit.decisions_chars is None and "1 options" in unfit.decisions_unfit

    step = summary(est.requests)["steps"]["detect-golden"]
    assert (step["decisions_unfit"], step["decisions_as_text"]) == (1, 1)
    assert step["decisions_chars"] == fits.decisions_chars + as_text.decisions_chars
    assert Decimal(0) < step["decisions_expected_usd"] <= step["decisions_upper_usd"]
    assert "Decisions: not admitted" in report(summary(est.requests))


def test_without_the_switch_nothing_is_translated(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_PATH", tmp_path / "t.sqlite")
    est = EstimatingAdapter("jev-1.14.0", cache_dir=tmp_path / "cache")
    est.step = "s"
    est.ask("detect", {"x": 1}, {"q": Noul(instructions="?")})
    assert est.requests[0].decisions_chars is None
    result = summary(est.requests)
    assert "decisions_chars" not in result["total"] and "Decisions" not in report(result)


def test_run_on_its_own_it_loads_the_registrations(tmp_path, monkeypatch):
    """The steps' checks are registered by the application (229): `python -m jav.evals.jev_estimate` loads them as the
    command line does, or the first S path step stops with `RegistrationsMissing`."""
    import pytest

    from jav.app import registrations
    from jav.evals import jev_estimate

    loaded = []
    monkeypatch.setattr(registrations, "load_all", lambda: loaded.append(True))
    with pytest.raises(ValueError, match="unknown step"):
        jev_estimate.main(["no-such-step", "--out", str(tmp_path / "out")])
    assert loaded == [True]
