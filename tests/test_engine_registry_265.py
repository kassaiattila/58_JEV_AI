"""265 (plan L, L1): the engine and provider registries (`configs/engines.json`, `configs/providers.json`).

The engine is data: each engine names its judgement service, the providers it requires, its band suffix and its end
state when its answerer is unavailable; a provider names its key, the budget it spends from and whether an
installation may call it. These tests pin the registries' consistency, the reading of a processing setting (the old
`jev: on | off` too) and the availability, which only looks at the environment.
"""

from __future__ import annotations

import pytest

from jav.ai import engine
from jav.app import work_recipes
from jav.core import cfg, providers

KEYS = ("TypeSafeJAV_API_KEY", "TYPESAFE_API_KEY", "OPENAI_API_KEY", "AZURE_DI_ENDPOINT", "AZURE_DI_KEY",
        providers.ON_ENV, providers.OFF_ENV)


@pytest.fixture
def bare_env(monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# --- the registries agree with each other ---------------------------------------------------------------------------

def test_every_engine_names_described_judges_and_providers():
    registry = cfg.load("engines")
    described = set(providers.ids())
    assert registry["default"] in registry["engines"]
    for engine_id in engine.ids():
        e = engine.get(engine_id)
        assert e.judge is None or e.judge in engine.judges(), engine_id
        assert e.requires and set(e.requires) <= described, engine_id
    for judge in engine.judges():
        assert engine.judge_provider(judge) in described, judge


def test_engines_differ_in_their_bands_and_end_states():
    found = [engine.get(e) for e in engine.ids()]
    assert len({e.bands for e in found}) == len(found)
    assert len({e.unavailable_status for e in found}) == len(found)
    assert len({engine.judge_todo(j) for j in engine.judges()}) == len(engine.judges())


def test_every_provider_has_a_known_key_and_a_described_budget():
    for provider_id in providers.ids():
        p = providers.get(provider_id)
        assert p.key is None or p.key in providers._KEYS, provider_id
        assert p.budget in providers.ids(), provider_id


def test_decisions_spends_from_the_openai_budget():
    assert providers.budget_of("openai_decisions") == "openai"
    assert providers.sharing("openai") == ["openai", "openai_decisions"]
    assert providers.budget_of("mnb_rates") == "mnb_rates"  # a connector's name is its own budget
    assert providers.label("mnb_rates") == "mnb_rates"


# --- reading a processing setting -----------------------------------------------------------------------------------

@pytest.mark.parametrize(("params", "expected"), [
    ({"engine": "decisions"}, "decisions"),
    ({"engine": "gpt"}, "gpt"),
    ({"jev": "off"}, "gpt"),
    ({"jev": "on"}, "jev"),
    ({}, "jev"),
    (None, "jev"),
    ({"engine": "decisions", "jev": "off"}, "decisions"),  # a setting naming its engine is not read as the old switch
])
def test_a_setting_names_its_engine(params, expected):
    assert engine.of_params(params).id == expected


@pytest.mark.parametrize("params", [{"engine": "both"}, {"jev": "maybe"}])
def test_an_unknown_engine_is_refused(params):
    with pytest.raises(engine.UnknownEngine):
        engine.of_params(params)


def test_a_setting_saved_with_the_old_switch_names_its_engine():
    """A setting saved before the recipes named their engine is read, and saved again, under the engine's name."""
    for value, engine_id in (("on", "jev"), ("off", "gpt")):
        assert engine.of_params({"jev": value}).id == engine_id
        assert work_recipes.upgraded_params({"jev": value, "jev_cache": "live"}) == {"jev_cache": "live", "engine": engine_id}
    assert work_recipes.upgraded_params({"engine": "decisions"}) == {"engine": "decisions"}
    assert work_recipes.upgraded_params({"jev_cache": "live"}) == {"jev_cache": "live"}  # a recipe without the setting


def test_only_gpt_only_has_no_judge():
    assert [e for e in engine.ids() if not engine.get(e).judged] == ["gpt"]
    assert engine.get("jev").judge_provider == "jev"
    assert engine.get("decisions").judge_provider == "openai_decisions"
    assert engine.get("gpt").judge_provider is None


def test_band_keys_follow_the_engine():
    assert engine.get("jev").band_key("detect.doc_type") == "detect.doc_type"
    assert engine.get("gpt").band_key("detect.doc_type") == "detect.doc_type.gpt"
    assert engine.get("decisions").band_key("email.intent") == "email.intent.decisions"


# --- availability: the environment alone ----------------------------------------------------------------------------

def test_without_keys_nothing_is_available(bare_env):
    states = {c["engine"]: (c["available"], c["reason"], c["provider"]) for c in engine.choices()}
    assert states == {"jev": (False, "missing_key", "jev"),
                      "decisions": (False, "under_measurement", "openai_decisions"),
                      "gpt": (False, "missing_key", "openai")}


def test_a_key_makes_its_engines_available(bare_env):
    bare_env.setenv("TypeSafeJAV_API_KEY", "synthetic-offline-key")
    assert engine.availability("jev").available
    assert not engine.availability("gpt").available
    bare_env.setenv("OPENAI_API_KEY", "synthetic-offline-key")
    assert engine.availability("gpt").available
    assert engine.availability("decisions").reason == "under_measurement"  # off until the owner's decision


def test_an_installation_switches_a_provider(bare_env):
    bare_env.setenv(providers.ON_ENV, "openai_decisions")
    assert engine.availability("decisions") == providers.Availability(False, "missing_key", "openai_decisions")
    bare_env.setenv("OPENAI_API_KEY", "synthetic-offline-key")
    assert engine.availability("decisions").available
    bare_env.setenv("TYPESAFE_API_KEY", "synthetic-offline-key")
    bare_env.setenv(providers.OFF_ENV, "jev, azure_di")
    assert engine.availability("jev") == providers.Availability(False, "switched_off", "jev")
    assert not providers.availability("azure_di").available


def test_azure_needs_both_of_its_variables(bare_env):
    bare_env.setenv("AZURE_DI_ENDPOINT", "https://example.invalid")
    assert providers.availability("azure_di").reason == "missing_key"
    bare_env.setenv("AZURE_DI_KEY", "synthetic-offline-key")
    assert providers.availability("azure_di").available


# --- the installation's engine while nothing is saved (265, L4b; the owner's decision of 2026-11-01) ---------------

def test_an_installation_with_a_jev_key_takes_the_default(bare_env):
    bare_env.setenv("TypeSafeJAV_API_KEY", "synthetic-offline-key")
    bare_env.setenv("OPENAI_API_KEY", "synthetic-offline-key")
    assert engine.installation_default() == "jev"


def test_without_a_jev_key_an_installation_takes_gpt_only_not_decisions(bare_env):
    bare_env.setenv("OPENAI_API_KEY", "synthetic-offline-key")
    bare_env.setenv(providers.ON_ENV, "openai_decisions")  # Decisions can run here, and is still not the default
    assert engine.availability("decisions").available
    assert engine.installation_default() == "gpt"


def test_where_nothing_can_run_the_default_names_its_own_reason(bare_env):
    assert engine.installation_default() == engine.default_id()
    assert engine.availability(engine.default_id()).reason == providers.MISSING_KEY


def test_a_request_names_an_engine_of_the_registry():
    from pydantic import TypeAdapter, ValidationError

    names = TypeAdapter(engine.EngineId)
    assert [names.validate_python(e) for e in engine.ids()] == engine.ids()
    with pytest.raises(ValidationError):
        names.validate_python("both")
