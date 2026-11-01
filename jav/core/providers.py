"""The paid services the system calls, read from one registry (265, plan L; glossary: Provider registry).

Plain-language summary: JEV, OpenAI, OpenAI Decisions and Azure DI used to be listed by hand wherever the code needed
them (the call log's names, the budgets, the costs, the screens). Now `configs/providers.json` describes each one
once: which key it needs, which budget it spends from, its name on screen, and whether an installation may call it at
all. Whether a service is available here is answered from that description and the environment alone; nothing is
called to find out.

A provider's calls are booked under its own name in the call log, but they reserve from the budget of the provider
named by `budget` (OpenAI Decisions spends from the OpenAI budget, the owner's decision of 2026-11-01). An installation
switches a provider on or off with `JAV_PROVIDERS_ON` / `JAV_PROVIDERS_OFF` (comma-separated names); the file's
`enabled` is the default.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator

from jav.core import cfg
from jav.core.config import API_KEY_ENV_VARS, AZURE_DI_ENV_VARS, OPENAI_KEY_ENV_VAR

CONFIG = "providers"
ON_ENV = "JAV_PROVIDERS_ON"
OFF_ENV = "JAV_PROVIDERS_OFF"
SWITCHED_OFF = "switched_off"
MISSING_KEY = "missing_key"

# The environment variables of each kind of key: `any` of them or `all` of them must be set.
_KEYS: dict[str, tuple[str, tuple[str, ...]]] = {
    "typesafe": ("any", API_KEY_ENV_VARS),
    "openai": ("any", (OPENAI_KEY_ENV_VAR,)),
    "azure_di": ("all", AZURE_DI_ENV_VARS),
}


class UnknownProvider(KeyError):
    """No provider of the name is described in `configs/providers.json`."""


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    key: str | None
    budget: str
    enabled: bool
    off_note: str | None = None


@dataclass(frozen=True)
class Availability:
    """Whether a provider (or an engine, `jav.ai.engines`) can be called here; `reason` is a short code when it cannot
    (`switched_off`, `missing_key`), and `provider` names the provider the reason is about."""
    available: bool
    reason: str | None = None
    provider: str | None = None


def _described() -> dict[str, dict]:
    return dict(cfg.load(CONFIG)["providers"])


def ids() -> list[str]:
    """Every described provider, in the file's order."""
    return list(_described())


def get(provider_id: str) -> Provider:
    try:
        raw = _described()[provider_id]
    except KeyError:
        raise UnknownProvider(f"no provider is described as {provider_id!r} in configs/{CONFIG}.json") from None
    return Provider(id=provider_id, label=str(raw["label"]), key=raw.get("key"), budget=str(raw["budget"]),
                    enabled=bool(raw["enabled"]), off_note=raw.get("off_note"))


def check_id(provider_id: str) -> str:
    """The name itself when the registry describes such a provider (a contract field's check, `ProviderId`)."""
    if provider_id not in ids():
        raise ValueError(f"unknown provider {provider_id!r}; expected one of {ids()}")
    return provider_id


# A field holding a provider's name: any provider the registry describes (until 265 a hand-written list per contract).
ProviderId = Annotated[str, AfterValidator(check_id)]


def budgets() -> list[str]:
    """The budgets calls reserve from, in the file's order: every described provider that spends its own (OpenAI
    Decisions spends OpenAI's, so it is none)."""
    return [p for p in ids() if get(p).budget == p]


def check_budget(budget_id: str) -> str:
    """The name itself when calls reserve from such a budget (a budget field's check, `BudgetId`)."""
    if budget_id not in budgets():
        raise ValueError(f"unknown budget {budget_id!r}; expected one of {budgets()}")
    return budget_id


# A budget's key (a run's, a workflow step's, a case step's cap): a budget calls reserve from (until 265 a
# hand-written list per form).
BudgetId = Annotated[str, AfterValidator(check_budget)]


def label(provider_id: str) -> str:
    """The provider's name on screen; an undescribed name (a connector's, an old row's) is shown as it is."""
    try:
        return get(provider_id).label
    except UnknownProvider:
        return provider_id


def budget_of(provider_id: str) -> str:
    """The provider whose budget a call of `provider_id` reserves from; an undescribed name spends its own."""
    try:
        return get(provider_id).budget
    except UnknownProvider:
        return provider_id


def pooled(amounts: Mapping[str, Decimal]) -> dict[str, Decimal]:
    """Amounts per provider summed per budget they spend from (`budget_of`), in their order: a run's or a step's
    budget is kept so, as the call log reserves (OpenAI Decisions' amount in OpenAI's budget)."""
    out: dict[str, Decimal] = {}
    for provider_id, amount in amounts.items():
        budget = budget_of(provider_id)
        out[budget] = out.get(budget, Decimal(0)) + amount
    return out


def sharing(budget: str) -> list[str]:
    """Every provider whose calls reserve from `budget` (the budget's own provider among them, when described)."""
    found = [p for p in ids() if get(p).budget == budget]
    return found or [budget]


def _listed(variable: str) -> set[str]:
    return {name.strip() for name in os.environ.get(variable, "").split(",") if name.strip()}


def enabled(provider_id: str) -> bool:
    """Whether this installation may call the provider: the environment's switch, else the file's default."""
    if provider_id in _listed(OFF_ENV):
        return False
    if provider_id in _listed(ON_ENV):
        return True
    return get(provider_id).enabled


def has_key(provider_id: str) -> bool:
    """Whether the provider's key is in the environment (never its value)."""
    key = get(provider_id).key
    if key is None:
        return True
    mode, names = _KEYS[key]
    present = [bool((os.environ.get(name) or "").strip()) for name in names]
    return all(present) if mode == "all" else any(present)


def availability(provider_id: str) -> Availability:
    """Whether the provider can be called here: switched on, and its key given. Nothing is called to find out."""
    if not enabled(provider_id):
        return Availability(False, SWITCHED_OFF, provider_id)
    if not has_key(provider_id):
        return Availability(False, MISSING_KEY, provider_id)
    return Availability(True, provider=provider_id)


__all__ = ["Availability", "BudgetId", "MISSING_KEY", "Provider", "ProviderId", "SWITCHED_OFF", "UnknownProvider",
           "availability", "budget_of", "budgets", "check_budget", "check_id",
           "enabled", "get", "has_key", "ids", "label", "pooled", "sharing"]
